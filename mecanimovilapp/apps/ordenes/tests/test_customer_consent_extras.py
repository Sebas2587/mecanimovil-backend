"""
Tests for customer consent on additional quotes (extras).
Ensures proper authorization flows via public token endpoints.
"""
from decimal import Decimal
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from datetime import date, time
from unittest.mock import patch

from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.ordenes.models import CotizacionCanal, CitaAgendaPersonal
from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
    crear_cotizacion_adicional_desde_catalogo
)

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    REST_FRAMEWORK={
        'DEFAULT_THROTTLE_CLASSES': [],
        'DEFAULT_THROTTLE_RATES': {}
    }
)
class CustomerConsentExtrasTestCase(TestCase):
    """Test customer authorization/rejection of additional quotes via public endpoints."""
    
    def setUp(self):
        """Set up test workshop and base quote."""
        self.user_taller = User.objects.create_user(
            username='taller_consent',
            email='consent@test.com',
            password='test123'
        )
        self.taller = Taller.objects.create(
            usuario=self.user_taller,
            nombre='Taller Consent Test',
            rut='99999999-9'
        )
        
        # Base quote (already accepted by customer)
        self.cot_base = CotizacionCanal.objects.create(
            taller=self.taller,
            creado_por=self.user_taller,
            estado='aceptada',
            mano_obra_clp=Decimal('50000'),
            total_clp=Decimal('50000'),
            url_publica='http://example.com/quote/base',
            token='base-token-12345'
        )
        
        # Cita for the base quote
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.cot_base,
            fecha_servicio=date.today(),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            creado_por=self.user_taller
        )
        
        self.client = APIClient()
    
    @patch('mecanimovilapp.apps.ordenes.views_cotizacion_publica.CotizacionPublicaThrottle.allow_request', return_value=True)
    def test_customer_accepts_additional_quote_via_public_endpoint(self, mock_throttle):
        """Customer accepts additional quote via public token URL (not workshop)."""
        # Workshop creates additional quote
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Filtro de aceite detectado en mal estado',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        cot_adicional.mano_obra_clp = Decimal('15000')
        cot_adicional.total_clp = Decimal('15000')
        cot_adicional.estado = 'enviada'  # Sent to customer
        cot_adicional.token = 'extra-token-67890'
        cot_adicional.url_publica = 'http://example.com/quote/extra'
        cot_adicional.save()
        
        # Customer accepts via public endpoint (no auth required, token-based)
        response = self.client.post(
            f'/api/ordenes/cotizaciones-publicas/{cot_adicional.token}/aceptar/',
            data={}
        )
        
        self.assertEqual(response.status_code, 200)
        cot_adicional.refresh_from_db()
        self.assertEqual(cot_adicional.estado, 'aceptada')
    
    @patch('mecanimovilapp.apps.ordenes.views_cotizacion_publica.CotizacionPublicaThrottle.allow_request', return_value=True)
    def test_customer_rejects_additional_quote_via_public_endpoint(self, mock_throttle):
        """Customer rejects additional quote via public token URL."""
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Batería reemplazo',
            servicios_catalogo=[],
            ejecucion_adicional='nueva_fecha'
        )
        cot_adicional.estado = 'enviada'
        cot_adicional.token = 'reject-token-11111'
        cot_adicional.url_publica = 'http://example.com/quote/reject'
        cot_adicional.save()
        
        # Customer rejects
        response = self.client.post(
            f'/api/ordenes/cotizaciones-publicas/{cot_adicional.token}/rechazar/',
            data={'motivo': 'Precio muy alto'}
        )
        
        self.assertEqual(response.status_code, 200)
        cot_adicional.refresh_from_db()
        self.assertEqual(cot_adicional.estado, 'rechazada')
    
    def test_base_order_completes_with_pending_extra(self):
        """Base order can complete while extra is still pending customer approval."""
        # Create pending extra
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Trabajo adicional pendiente',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        self.assertEqual(cot_adicional.estado, 'borrador')  # Not yet sent
        
        # Complete base quote
        self.cot_base.estado = 'completada'
        self.cot_base.save()
        
        # Base completes, extra remains pending
        self.assertEqual(self.cot_base.estado, 'completada')
        cot_adicional.refresh_from_db()
        self.assertEqual(cot_adicional.estado, 'borrador')
    
    def test_base_order_completes_with_rejected_extra(self):
        """Base order can complete even if extra was rejected by customer.
        
        Note: This test verifies the independence of base and extra quote states.
        In real workflow, order completion would happen via finalizar_servicio API
        after checklist completion. Here we verify state independence directly.
        """
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Rejected work',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        cot_adicional.estado = 'rechazada'
        cot_adicional.save()
        
        # Complete base (in real workflow via API after checklist complete)
        # Here testing state independence directly
        self.cot_base.estado = 'completada'
        self.cot_base.save()
        
        self.assertEqual(self.cot_base.estado, 'completada')
        cot_adicional.refresh_from_db()
        self.assertEqual(cot_adicional.estado, 'rechazada')
    
    @patch('mecanimovilapp.apps.ordenes.views_cotizacion_publica.CotizacionPublicaThrottle.allow_request', return_value=True)
    def test_public_token_endpoint_allows_any_bearer(self, mock_throttle):
        """Public token endpoint uses AllowAny - possession of token authorizes action.
        
        WARNING: Current design allows anyone with the token URL (including workshop)
        to accept/reject. No additional identity verification is performed beyond 
        possessing the unguessable token. Workshop that sees customer's WhatsApp 
        link can technically execute the action.
        
        This test documents the actual behavior - bearer token grants authorization.
        """
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Testing bearer token auth',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        cot_adicional.estado = 'enviada'
        cot_adicional.token = 'bearer-token-test-12345'
        cot_adicional.save()
        
        # Public endpoint allows anyone with token (AllowAny permission)
        # Even if workshop is authenticated, the public endpoint doesn't check
        self.client.force_authenticate(user=self.user_taller)
        
        response = self.client.post(
            f'/api/ordenes/cotizaciones-publicas/{cot_adicional.token}/aceptar/',
            data={}
        )
        
        # Token possession authorizes - this is current design
        # Not customer-identity-verified, just token-based
        self.assertEqual(response.status_code, 200)
        cot_adicional.refresh_from_db()
        self.assertEqual(cot_adicional.estado, 'aceptada')


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    REST_FRAMEWORK={
        'DEFAULT_THROTTLE_CLASSES': [],
        'DEFAULT_THROTTLE_RATES': {}
    }
)
class CrossTenantExtraPermissionsTestCase(TestCase):
    """Test cross-tenant isolation for additional quotes."""
    
    def setUp(self):
        """Set up two separate workshops."""
        # Taller A
        self.user_a = User.objects.create_user(
            username='taller_a_extra',
            email='extra_a@test.com',
            password='test123'
        )
        self.taller_a = Taller.objects.create(
            usuario=self.user_a,
            nombre='Taller A Extra',
            rut='11111111-1'
        )
        
        self.cot_a = CotizacionCanal.objects.create(
            taller=self.taller_a,
            creado_por=self.user_a,
            estado='aceptada',
            total_clp=Decimal('40000')
        )
        
        self.cita_a = CitaAgendaPersonal.objects.create(
            taller=self.taller_a,
            cotizacion_canal_origen=self.cot_a,
            fecha_servicio=date.today(),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            creado_por=self.user_a
        )
        
        # Taller B (different tenant)
        self.user_b = User.objects.create_user(
            username='taller_b_extra',
            email='extra_b@test.com',
            password='test123'
        )
        self.taller_b = Taller.objects.create(
            usuario=self.user_b,
            nombre='Taller B Extra',
            rut='22222222-2'
        )
        
        self.client = APIClient()
    
    def test_workshop_cannot_create_extra_for_another_workshop_appointment(self):
        """Workshop B cannot create additional quote for Workshop A's appointment."""
        # Taller B tries to create extra for Taller A's appointment
        with self.assertRaisesMessage(ValueError, 'La cotización original no pertenece a este taller'):
            # Should fail validation - base quote belongs to taller_a, not taller_b
            crear_cotizacion_adicional_desde_catalogo(
                cotizacion_original=self.cot_a,
                cita=self.cita_a,
                taller=self.taller_b,  # Wrong taller!
                creado_por=self.user_b,
                motivo_servicio_adicional='Cross-tenant attempt',
                servicios_catalogo=[],
                ejecucion_adicional='misma_visita'
            )
    
    def test_additional_quote_inherits_base_quote_taller(self):
        """Additional quote must belong to same taller as base quote."""
        cot_extra = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_a,
            cita=self.cita_a,
            taller=self.taller_a,
            creado_por=self.user_a,
            motivo_servicio_adicional='Valid extra',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        
        # Extra must have same taller as base
        self.assertEqual(cot_extra.taller_id, self.cot_a.taller_id)
        self.assertEqual(cot_extra.taller_id, self.taller_a.id)

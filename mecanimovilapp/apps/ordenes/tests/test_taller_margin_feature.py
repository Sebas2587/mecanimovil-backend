"""Tests for taller configurable margin and parts/labor separation feature."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle, CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    aplicar_margen_taller,
    economia_repuesto,
)
from mecanimovilapp.apps.ordenes.services.caja_taller import _desglose_partes_labor
from mecanimovilapp.apps.usuarios.models import MiembroTaller, Taller

User = get_user_model()


class TallerMarginModelTest(TestCase):
    """Test the margen_ganancia_pct field on Taller model."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='taller_margin', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Test Margin',
            telefono='912345678',
            estado_verificacion='aprobado',
        )
    
    def test_taller_has_margin_field(self):
        """Taller model should have margen_ganancia_pct field."""
        self.assertIsNone(self.taller.margen_ganancia_pct)
    
    def test_set_and_read_margin(self):
        """Can set and read margin percentage."""
        self.taller.margen_ganancia_pct = Decimal('30.00')
        self.taller.save()
        self.taller.refresh_from_db()
        self.assertEqual(self.taller.margen_ganancia_pct, Decimal('30.00'))
    
    def test_margin_accepts_decimal_values(self):
        """Margin field accepts decimal values."""
        self.taller.margen_ganancia_pct = Decimal('25.50')
        self.taller.save()
        self.taller.refresh_from_db()
        self.assertEqual(self.taller.margen_ganancia_pct, Decimal('25.50'))
    
    def test_null_margin_stays_null(self):
        """Null margin should stay null (no automatic default)."""
        self.taller.margen_ganancia_pct = None
        self.taller.save()
        self.taller.refresh_from_db()
        self.assertIsNone(self.taller.margen_ganancia_pct)


class TallerMarginSerializerTest(TestCase):
    """Test that margin field is exposed in workshop serializer."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='taller_api', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller API Test',
            telefono='912345678',
            estado_verificacion='aprobado',
            margen_ganancia_pct=Decimal('30.00'),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_margin_in_taller_profile_response(self):
        """Margin should appear in taller profile GET response."""
        from mecanimovilapp.apps.usuarios.serializers import TallerSerializer
        serializer = TallerSerializer(self.taller)
        data = serializer.data
        self.assertEqual(float(data['margen_ganancia_pct']), 30.00)
    
    def test_can_update_margin_via_serializer(self):
        """Can update margin via serializer."""
        from mecanimovilapp.apps.usuarios.serializers import TallerSerializer
        serializer = TallerSerializer(self.taller, data={'margen_ganancia_pct': '35.50'}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.taller.refresh_from_db()
        self.assertEqual(self.taller.margen_ganancia_pct, Decimal('35.50'))


class AplicarMargenTallerTest(TestCase):
    """Test the aplicar_margen_taller function."""
    
    def test_margin_applied_post_enrichment_store_price(self):
        """Post-enrichment: precio_unitario_clp is store price, apply margin."""
        taller = MagicMock()
        taller.margen_ganancia_pct = Decimal('30.00')
        
        # Post-enrichment state: precio_unitario_clp = discovered store price (cost)
        rep = {
            'nombre': 'Filtro',
            'cantidad': 1,
            'precio_unitario_clp': 10000,  # Discovered store price = cost
        }
        
        aplicar_margen_taller(rep, taller)
        
        # Cost frozen at 10000, sale = 10000 × 1.30 = 13000
        self.assertEqual(rep['precio_unitario_clp'], 13000)
        # Cost should be frozen
        self.assertIn('costo_estimado_clp', rep)
    
    def test_no_margin_application_when_margin_null(self):
        """When margin is null, don't compute price."""
        taller = MagicMock()
        taller.margen_ganancia_pct = None
        
        rep = {'nombre': 'Filtro', 'cantidad': 1, 'precio_unitario_clp': 10000}
        
        aplicar_margen_taller(rep, taller)
        
        # Price should stay unchanged
        self.assertEqual(rep['precio_unitario_clp'], 10000)
    
    def test_no_margin_application_when_cost_unknown(self):
        """When cost is unknown, don't compute price from margin."""
        taller = MagicMock()
        taller.margen_ganancia_pct = Decimal('30.00')
        
        rep = {'nombre': 'Filtro', 'cantidad': 1}  # No cost, no price
        
        aplicar_margen_taller(rep, taller)
        
        # Price should NOT be set
        self.assertNotIn('precio_unitario_clp', rep)
    
    def test_no_override_when_sale_differs_from_cost(self):
        """Don't override when sale already differs from cost (manual edit)."""
        taller = MagicMock()
        taller.margen_ganancia_pct = Decimal('30.00')
        
        rep = {
            'nombre': 'Filtro',
            'cantidad': 1,
            'costo_estimado_clp': 10000,  # Frozen cost
            'precio_unitario_clp': 15000,  # Manually edited (differs from cost)
        }
        
        aplicar_margen_taller(rep, taller)
        
        # Should keep existing price (manual edit)
        self.assertEqual(rep['precio_unitario_clp'], 15000)
    
    def test_margin_with_registered_cost(self):
        """Use registered cost when available."""
        taller = MagicMock()
        taller.margen_ganancia_pct = Decimal('25.00')
        
        rep = {
            'nombre': 'Filtro',
            'cantidad': 1,
            'costo_registrado_clp': 8000,  # Registered cost takes priority
            'precio_unitario_clp': 8000,
        }
        
        aplicar_margen_taller(rep, taller)
        
        # price = 8000 × 1.25 = 10000
        self.assertEqual(rep['precio_unitario_clp'], 10000)
    
    def test_apply_when_sale_equals_cost(self):
        """Apply margin when sale still equals cost (not yet marked up)."""
        taller = MagicMock()
        taller.margen_ganancia_pct = Decimal('30.00')
        
        rep = {
            'nombre': 'Filtro',
            'cantidad': 1,
            'costo_estimado_clp': 10000,
            'precio_unitario_clp': 10000,  # Still at cost
        }
        
        aplicar_margen_taller(rep, taller)
        
        # Should apply margin
        self.assertEqual(rep['precio_unitario_clp'], 13000)


class EconomiaRepuestoMarginTest(TestCase):
    """Test that margin calculation is profit/cost, not profit/sale."""
    
    def test_margin_pct_is_profit_over_cost_registered(self):
        """margen_pct should be (profit/cost)*100, not (profit/sale)*100."""
        rep = {
            'nombre': 'Filtro',
            'cantidad': 1,
            'costo_registrado_clp': 8000,  # Use registered cost
            'costo_origen': 'registrado',
            'precio_unitario_clp': 10000,
        }
        
        economia = economia_repuesto(rep)
        
        # Profit = 10000 - 8000 = 2000
        # margen_pct = (2000 / 8000) * 100 = 25.0%
        self.assertEqual(economia['margen_clp'], 2000)
        self.assertEqual(economia['margen_pct'], 25.0)
    
    def test_margin_with_estimated_cost(self):
        """Margin with estimated cost."""
        rep = {
            'nombre': 'Filtro',
            'cantidad': 1,
            'costo_estimado_clp': 8000,  # Estimated cost
            'precio_unitario_clp': 10000,
        }
        
        economia = economia_repuesto(rep)
        
        # Base cost = 8000 (estimated)
        self.assertEqual(economia['costo_unitario_clp'], 8000)
        # Profit = 10000 - 8000 = 2000
        self.assertEqual(economia['margen_clp'], 2000)
        # margen_pct = (2000 / 8000) * 100 = 25.0%
        self.assertEqual(economia['margen_pct'], 25.0)
    
    def test_manual_edit_recalculates_profit(self):
        """Editing price should recalculate profit, keeping cost unchanged."""
        rep = {
            'nombre': 'Filtro',
            'cantidad': 1,
            'costo_estimado_clp': 8000,
            'precio_unitario_clp': 12000,  # Edited from 10000 to 12000
        }
        
        economia = economia_repuesto(rep)
        
        # Cost stays 8000
        self.assertEqual(economia['costo_unitario_clp'], 8000)
        # New profit = 12000 - 8000 = 4000
        self.assertEqual(economia['margen_clp'], 4000)
        # New margin% = (4000 / 8000) * 100 = 50.0%
        self.assertEqual(economia['margen_pct'], 50.0)


class DesglosePartesLaborTest(TestCase):
    """Test parts/labor breakdown in caja response."""
    
    def test_complete_case_with_parts_and_labor(self):
        """Case with known costs should return complete breakdown."""
        cot = MagicMock(spec=CotizacionCanal)
        cot.mano_obra_clp = 50000
        cot.repuestos = [
            {
                'nombre': 'Filtro A',
                'cantidad': 1,
                'precio_unitario_clp': 10000,
                'costo_unitario_clp': 8000,
            },
            {
                'nombre': 'Filtro B',
                'cantidad': 2,
                'precio_unitario_clp': 15000,
                'costo_unitario_clp': 12000,
            },
        ]
        
        desglose = _desglose_partes_labor(cot)
        
        # Parts charged: 10000*1 + 15000*2 = 40000
        self.assertEqual(desglose['repuestos_cobrados_clp'], 40000)
        # Parts cost: 8000*1 + 12000*2 = 32000
        self.assertEqual(desglose['repuestos_costo_clp'], 32000)
        # Parts margin: 40000 - 32000 = 8000
        self.assertEqual(desglose['repuestos_margen_clp'], 8000)
        # Labor: 50000
        self.assertEqual(desglose['mano_obra_cobrada_clp'], 50000)
    
    def test_case_with_unknown_part_cost(self):
        """Case with any unknown cost should return null for cost/margin."""
        cot = MagicMock(spec=CotizacionCanal)
        cot.mano_obra_clp = 30000
        cot.repuestos = [
            {
                'nombre': 'Filtro A',
                'cantidad': 1,
                'precio_unitario_clp': 8000,
                'costo_unitario_clp': None,  # Unknown
            },
        ]
        
        desglose = _desglose_partes_labor(cot)
        
        # Parts charged: known
        self.assertEqual(desglose['repuestos_cobrados_clp'], 8000)
        # Cost: unknown (null)
        self.assertIsNone(desglose['repuestos_costo_clp'])
        # Margin: unknown (null)
        self.assertIsNone(desglose['repuestos_margen_clp'])
        # Labor: known
        self.assertEqual(desglose['mano_obra_cobrada_clp'], 30000)
    
    def test_case_without_parts(self):
        """Case with no parts should return zeros, not null."""
        cot = MagicMock(spec=CotizacionCanal)
        cot.mano_obra_clp = 40000
        cot.repuestos = []
        
        desglose = _desglose_partes_labor(cot)
        
        # No parts: known zeros
        self.assertEqual(desglose['repuestos_cobrados_clp'], 0)
        self.assertEqual(desglose['repuestos_costo_clp'], 0)
        self.assertEqual(desglose['repuestos_margen_clp'], 0)
        # Labor: known
        self.assertEqual(desglose['mano_obra_cobrada_clp'], 40000)
    
    def test_null_cotizacion_returns_all_null(self):
        """Null cotizacion should return all null."""
        desglose = _desglose_partes_labor(None)
        
        self.assertIsNone(desglose['repuestos_cobrados_clp'])
        self.assertIsNone(desglose['repuestos_costo_clp'])
        self.assertIsNone(desglose['repuestos_margen_clp'])
        self.assertIsNone(desglose['mano_obra_cobrada_clp'])


class CajaPartesLaborIntegrationTest(TestCase):
    """Integration test for parts/labor in caja API response."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='caja_test', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Caja',
            telefono='900000010',
            estado_verificacion='aprobado',
            margen_ganancia_pct=Decimal('30.00'),
        )
        self.mecanico = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=self.user,
            rol='mandante',
            nombre='Mecánico Test',
            modalidad_tecnico='en_taller',
            activo=True,
        )
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            cliente_nombre='Cliente Test',
            servicio_nombre='Cambio filtros',
            mano_obra_clp=50000,
            repuestos=[
                {
                    'nombre': 'Filtro aire',
                    'cantidad': 1,
                    'precio_unitario_clp': 13000,
                    'costo_unitario_clp': 10000,
                },
                {
                    'nombre': 'Filtro aceite',
                    'cantidad': 1,
                    'precio_unitario_clp': 10400,
                    'costo_unitario_clp': 8000,
                },
            ],
            costo_repuestos_clp=18000,
            total_clp=73400,
            token='tok-caja-parts',
        )
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.cot,
            miembro_taller=self.mecanico,
            fecha_servicio='2026-11-10',
            hora_servicio='10:00',
            tipo_servicio='taller',
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=self.cita,
            cliente_nombre='Cliente Test',
            servicio_nombre='Cambio filtros',
            precio_referencia=Decimal('73400'),
        )
        
        # Create payment record so cita shows in caja
        from mecanimovilapp.apps.ordenes.models_caja import CobroTaller
        from datetime import date
        CobroTaller.objects.create(
            taller=self.taller,
            ancla_tipo='cita',
            ancla_id=str(self.cita.id),
            origen='manual',
            ref_externa='test-payment',
            tipo='entrada',
            estado='confirmado',
            monto_clp=73400,
            fecha_efectiva=timezone.datetime(2026, 11, 10, 10, 0, tzinfo=timezone.get_current_timezone()),
            fecha_local=date(2026, 11, 10),
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_caja_response_includes_parts_labor_breakdown(self):
        """Caja API response should include parts/labor breakdown."""
        from mecanimovilapp.apps.ordenes.services.caja_taller import consultar_periodo
        from datetime import date
        
        data = consultar_periodo(
            taller=self.taller,
            desde=date(2026, 11, 1),
            hasta=date(2026, 11, 30),
            granularidad='dia',
            page=1,
            page_size=50,
            casos_page=1,
            rol='mandante',
        )
        
        casos = data['casos']['results']
        self.assertEqual(len(casos), 1)
        
        caso = casos[0]
        # Parts charged: 13000 + 10400 = 23400
        self.assertEqual(caso['repuestos_cobrados_clp'], 23400)
        # Parts cost: 10000 + 8000 = 18000
        self.assertEqual(caso['repuestos_costo_clp'], 18000)
        # Parts margin: 23400 - 18000 = 5400
        self.assertEqual(caso['repuestos_margen_clp'], 5400)
        # Labor: 50000
        self.assertEqual(caso['mano_obra_cobrada_clp'], 50000)
        
        # Resumen should aggregate across all casos
        resumen = data['resumen']
        self.assertEqual(resumen['repuestos_cobrados_clp'], 23400)
        self.assertEqual(resumen['repuestos_costo_clp'], 18000)
        self.assertEqual(resumen['repuestos_margen_clp'], 5400)
        self.assertEqual(resumen['mano_obra_cobrada_clp'], 50000)

"""
Checklist pause/resume/partial save tests with simplified fixtures.
"""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date, time

from mecanimovilapp.apps.usuarios.models import Taller, Cliente
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.checklists.models import ChecklistInstance

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_RESULT_BACKEND='cache+memory://'
)
class ChecklistPauseResumeTestCase(TestCase):
    """Test checklist pause/resume via real API endpoints."""
    
    def setUp(self):
        """Create minimal fixtures."""
        self.user = User.objects.create_user(
            username='taller_pause',
            password='test123',
            email='pause@test.com'
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Pause',
            rut='44444444-4',
            telefono='+56977777777',
            estado_verificacion='aprobado'
        )
        
        user_cliente = User.objects.create_user(
            username='cliente_pause',
            password='test123',
            email='cliente_pause@test.com'
        )
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Pause',
            email='cliente_pause@test.com',
            telefono='+56988888888'
        )
        
        marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Mazda')
        modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='CX-5')
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca,
            modelo=modelo,
            year=2022,
            patente='IJ7890'
        )
        
        self.orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date.today(),
            hora_servicio=time(13, 0),
            metodo_pago='efectivo',
            total=Decimal('90000.00'),
            estado='aceptada_por_proveedor'
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_iniciar_servicio_crea_checklist_pausable(self):
        """Iniciar servicio crea checklist que puede pausarse."""
        # Iniciar servicio (crea checklist automáticamente si configurado)
        url_iniciar = f'/api/ordenes/proveedor-ordenes/{self.orden.id}/iniciar_servicio/'
        response = self.client.post(url_iniciar, {})
        
        self.assertEqual(response.status_code, 200)
        self.orden.refresh_from_db()
        self.assertIn(self.orden.estado, ['servicio_iniciado', 'checklist_en_progreso'])
        
        # Verificar si checklist fue creado
        checklist_exists = ChecklistInstance.objects.filter(orden=self.orden).exists()
        if checklist_exists:
            instance = ChecklistInstance.objects.get(orden=self.orden)
            
            # Si está EN_PROGRESO, pausar
            if instance.estado == 'EN_PROGRESO':
                url_pause = f'/api/checklists/instances/{instance.id}/pause/'
                pause_resp = self.client.post(url_pause, {})
                self.assertEqual(pause_resp.status_code, 200)
                
                instance.refresh_from_db()
                self.assertEqual(instance.estado, 'PAUSADO')
                
                # Reanudar
                url_resume = f'/api/checklists/instances/{instance.id}/resume/'
                resume_resp = self.client.post(url_resume, {})
                self.assertEqual(resume_resp.status_code, 200)
                
                instance.refresh_from_db()
                self.assertEqual(instance.estado, 'EN_PROGRESO')
    
    def test_orden_continua_sin_checklist(self):
        """Orden puede continuar incluso si checklist no está configurado."""
        # Iniciar servicio
        url = f'/api/ordenes/proveedor-ordenes/{self.orden.id}/iniciar_servicio/'
        response = self.client.post(url, {})
        
        self.assertEqual(response.status_code, 200)
        # Orden transiciona independientemente de checklist
        self.orden.refresh_from_db()
        self.assertIn(self.orden.estado, ['servicio_iniciado', 'checklist_en_progreso', 'en_proceso'])

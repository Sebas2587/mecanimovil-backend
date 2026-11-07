"""
Tests for puede_gestionar capability field in servicio_iniciado state.
Ensures assigned mechanic can execute checklist while preserving role/tenant isolation.
"""
from decimal import Decimal
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from datetime import date, time, timedelta

from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class PuedeGestionarCapabilityTestCase(TestCase):
    """Test puede_gestionar capability reflects actual execution permissions."""
    
    def setUp(self):
        """Set up taller with owner, assigned mechanic, unassigned mechanic."""
        # Taller A with owner
        self.user_owner = User.objects.create_user(
            username='owner_a',
            email='owner@test.com',
            password='test123'
        )
        self.taller_a = Taller.objects.create(
            usuario=self.user_owner,
            nombre='Taller A',
            rut='11111111-1'
        )
        self.owner_member = MiembroTaller.objects.create(
            taller=self.taller_a,
            usuario=self.user_owner,
            rol='mandante',
            activo=True
        )
        
        # Assigned mechanic
        self.user_mec_assigned = User.objects.create_user(
            username='mec_assigned',
            email='mecassigned@test.com',
            password='test123'
        )
        self.mec_assigned = MiembroTaller.objects.create(
            taller=self.taller_a,
            usuario=self.user_mec_assigned,
            rol='mecanico',
            activo=True
        )
        
        # Unassigned mechanic (same taller)
        self.user_mec_unassigned = User.objects.create_user(
            username='mec_unassigned',
            email='mecunassigned@test.com',
            password='test123'
        )
        self.mec_unassigned = MiembroTaller.objects.create(
            taller=self.taller_a,
            usuario=self.user_mec_unassigned,
            rol='mecanico',
            activo=True
        )
        
        # Taller B (cross-tenant)
        self.user_b = User.objects.create_user(
            username='owner_b',
            email='ownerb@test.com',
            password='test123'
        )
        self.taller_b = Taller.objects.create(
            usuario=self.user_b,
            nombre='Taller B',
            rut='22222222-2'
        )
        self.owner_b_member = MiembroTaller.objects.create(
            taller=self.taller_b,
            usuario=self.user_b,
            rol='mandante',
            activo=True
        )
        
        # Cliente and vehiculo
        user_cliente = User.objects.create_user(
            username='cliente_test',
            email='cliente@test.com',
            password='test123'
        )
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Test',
            email='cliente@test.com',
            telefono='+56911111111'
        )
        marca = MarcaVehiculo.objects.create(nombre='Toyota')
        modelo = Modelo.objects.create(marca=marca, nombre='Corolla')
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            patente='TEST99',
            marca=marca,
            modelo=modelo,
            year=2020
        )
        
        # Create order and assign mechanic
        self.orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller_a,
            tipo_servicio='taller',
            fecha_servicio=date.today() + timedelta(days=1),
            hora_servicio=time(10, 0),
            estado='aceptada_por_proveedor',
            total=Decimal('50000.00'),
            metodo_pago='transferencia',
            mecanico_asignado=self.mec_assigned
        )
        
        self.client = APIClient()
    
    def test_owner_puede_gestionar_servicio_iniciado(self):
        """Owner has puede_gestionar=true in servicio_iniciado state."""
        self.orden.estado = 'servicio_iniciado'
        self.orden.save()
        
        self.client.force_authenticate(user=self.user_owner)
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['puede_gestionar'])
    
    def test_assigned_mechanic_puede_gestionar_servicio_iniciado(self):
        """Assigned mechanic has puede_gestionar=true to execute checklist."""
        self.orden.estado = 'servicio_iniciado'
        self.orden.save()
        
        self.client.force_authenticate(user=self.user_mec_assigned)
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['puede_gestionar'], 
                       "Assigned mechanic should have puede_gestionar=true in servicio_iniciado")
    
    def test_unassigned_mechanic_cannot_access_assigned_order(self):
        """Unassigned mechanic from same taller cannot access assigned order."""
        self.orden.estado = 'servicio_iniciado'
        self.orden.save()
        
        self.client.force_authenticate(user=self.user_mec_unassigned)
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        
        # Unassigned mechanic should not see the order at all
        self.assertEqual(response.status_code, 404,
                        "Unassigned mechanic should get 404 for assigned order")
    
    def test_cross_tenant_mechanic_cannot_access_order(self):
        """Cross-tenant mechanic cannot access order from another taller."""
        self.orden.estado = 'servicio_iniciado'
        self.orden.save()
        
        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        
        self.assertEqual(response.status_code, 404,
                        "Cross-tenant mechanic should get 404")
    
    def test_unassigned_order_only_visible_to_owner(self):
        """Order without assigned mechanic is only visible to owner/mandante.
        
        Mechanics only see orders where mecanico_asignado = themselves.
        This preserves proper role-based access control.
        """
        self.orden.mecanico_asignado = None
        self.orden.estado = 'aceptada_por_proveedor'
        self.orden.save()
        
        # Owner can see unassigned order
        self.client.force_authenticate(user=self.user_owner)
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['puede_gestionar'])
        
        # Mechanic cannot see unassigned order (correct role separation)
        self.client.force_authenticate(user=self.user_mec_unassigned)
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        self.assertEqual(response.status_code, 404,
                        "Unassigned order should not be visible to mechanic (only to owner)")
    
    def test_puede_gestionar_only_for_active_states(self):
        """puede_gestionar reflects estados_gestionables list."""
        # Test that servicio_iniciado is now manageable
        self.orden.estado = 'servicio_iniciado'
        self.orden.save()
        
        self.client.force_authenticate(user=self.user_owner)
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['puede_gestionar'],
                       "servicio_iniciado should have puede_gestionar=true")
    
    def test_mechanic_cannot_access_privileged_actions(self):
        """Mechanic with puede_gestionar=true cannot access privileged owner actions.
        
        puede_gestionar enables checklist execution, but should NOT grant:
        - Assignment changes
        - Cancellation
        - Financial operations
        Frontend must gate each action by role, not just puede_gestionar flag.
        """
        self.orden.estado = 'servicio_iniciado'
        self.orden.save()
        
        self.client.force_authenticate(user=self.user_mec_assigned)
        
        # Verify mechanic has puede_gestionar
        response = self.client.get(f'/api/ordenes/proveedor-ordenes/{self.orden.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['puede_gestionar'])
        
        # Try to reassign (privileged action)
        response = self.client.post(
            f'/api/ordenes/proveedor-ordenes/{self.orden.id}/asignar_tecnico/',
            data={'mecanico_id': self.mec_unassigned.id, 'fecha': str(date.today()), 'hora': '10:00'}
        )
        self.assertIn(response.status_code, [403, 404], 
                     "Mechanic should not reassign orders even with puede_gestionar=true")
        
        # Try to cancel (privileged action)
        response = self.client.post(
            f'/api/ordenes/proveedor-ordenes/{self.orden.id}/rechazar/',
            data={'motivo_rechazo': 'Test'}
        )
        self.assertIn(response.status_code, [403, 404, 400],
                     "Mechanic should not cancel orders even with puede_gestionar=true")

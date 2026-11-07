"""
Real concurrent assignment tests with actual threading and separate DB connections.
"""
import threading
import time
from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from decimal import Decimal
from datetime import date, time as dt_time

from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, AsignacionTecnicoLog
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo

User = get_user_model()


class RealConcurrentAssignmentTestCase(TransactionTestCase):
    """
    Test real concurrent requests with actual threads and separate DB connections.
    Must use TransactionTestCase for separate connection testing.
    """
    
    def setUp(self):
        """Create test fixtures."""
        # Taller
        user_taller = User.objects.create_user(
            username='taller_concurrent',
            password='test',
            email='concurrent@test.com'
        )
        self.taller = Taller.objects.create(
            usuario=user_taller,
            nombre='Taller Concurrent',
            rut='99999999-9',
            telefono='+56999999999',
            estado_verificacion='aprobado'
        )
        self.mandante = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_taller,
            nombre='Mandante',
            rol='mandante',
            activo=True,
            permisos={'servicios': True}
        )
        
        # Two mechanics
        user_mec1 = User.objects.create_user(username='mec1_conc', password='test', email='m1@test.com')
        self.mecanico1 = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_mec1,
            nombre='Mecánico 1',
            rol='mecanico',
            activo=True
        )
        
        user_mec2 = User.objects.create_user(username='mec2_conc', password='test', email='m2@test.com')
        self.mecanico2 = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_mec2,
            nombre='Mecánico 2',
            rol='mecanico',
            activo=True
        )
        
        # Cliente and vehicle
        user_cliente = User.objects.create_user(username='cli_conc', password='test', email='cli@test.com')
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Concurrent',
            email='cli@test.com',
            telefono='+56900000004'
        )
        
        marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Mazda')
        modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='3')
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca,
            modelo=modelo,
            year=2023,
            patente='CONC01'
        )
        
        # Test order
        self.orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            tipo_servicio='taller',
            fecha_servicio=date.today(),
            hora_servicio=dt_time(10, 0),
            metodo_pago='efectivo',
            total=Decimal('60000.00'),
            estado='aceptada_por_proveedor'
        )
        
        self.user_taller = user_taller
    
    def test_simultaneous_assignment_requests_serialized(self):
        """
        Two threads try to assign different mechanics to same order simultaneously.
        select_for_update() should serialize them - one succeeds, other sees already-assigned state.
        """
        results = {}
        errors = []
        
        def assign_mechanic(mechanic_id, thread_name):
            """Thread worker: try to assign mechanic."""
            try:
                client = APIClient()
                # Login to get token
                from rest_framework.authtoken.models import Token
                token, _ = Token.objects.get_or_create(user=self.user_taller)
                client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
                
                # Small delay to increase chance of simultaneous requests
                time.sleep(0.01)
                
                # Assign
                url = f'/api/ordenes/proveedor-ordenes/{self.orden.id}/asignar_tecnico/'
                response = client.post(url, {'mecanico_id': mechanic_id}, format='json')
                
                results[thread_name] = {
                    'status': response.status_code,
                    'success': response.status_code == 200,
                    'mechanic_id': mechanic_id
                }
            except Exception as e:
                errors.append(f"{thread_name}: {e}")
        
        # Launch two threads simultaneously
        thread1 = threading.Thread(target=assign_mechanic, args=(self.mecanico1.id, 'thread1'))
        thread2 = threading.Thread(target=assign_mechanic, args=(self.mecanico2.id, 'thread2'))
        
        thread1.start()
        thread2.start()
        
        thread1.join(timeout=5)
        thread2.join(timeout=5)
        
        # Verify no errors
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        
        # Verify both threads completed
        self.assertEqual(len(results), 2, "Both threads should complete")
        
        # Verify both got 200 (one assigns, other idempotent or second assignment)
        success_count = sum(1 for r in results.values() if r['success'])
        self.assertGreaterEqual(success_count, 1, "At least one assignment should succeed")
        
        # Verify final state: order has exactly one mechanic assigned
        self.orden.refresh_from_db()
        self.assertIsNotNone(self.orden.mecanico_asignado)
        self.assertIn(
            self.orden.mecanico_asignado.id,
            [self.mecanico1.id, self.mecanico2.id],
            "Assigned mechanic should be one of the two"
        )
        
        # Verify audit logs
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden).order_by('fecha_cambio')
        # Should have at least 1 log (first assignment)
        self.assertGreaterEqual(logs.count(), 1)
    
    def test_concurrent_reassignment_race(self):
        """
        Order starts with mechanic1. Two threads try to reassign to different mechanics.
        Lock should prevent inconsistent state.
        """
        # Initial assignment
        self.orden.mecanico_asignado = self.mecanico1
        self.orden.save()
        
        # Third mechanic for reassignment
        user_mec3 = User.objects.create_user(username='mec3_conc', password='test', email='m3@test.com')
        mecanico3 = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_mec3,
            nombre='Mecánico 3',
            rol='mecanico',
            activo=True
        )
        
        results = {}
        errors = []
        
        def reassign_mechanic(mechanic_id, thread_name):
            """Thread worker: try to reassign mechanic."""
            try:
                client = APIClient()
                from rest_framework.authtoken.models import Token
                token, _ = Token.objects.get_or_create(user=self.user_taller)
                client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
                
                time.sleep(0.01)
                
                url = f'/api/ordenes/proveedor-ordenes/{self.orden.id}/asignar_tecnico/'
                response = client.post(url, {'mecanico_id': mechanic_id}, format='json')
                
                results[thread_name] = {
                    'status': response.status_code,
                    'success': response.status_code == 200,
                    'mechanic_id': mechanic_id
                }
            except Exception as e:
                errors.append(f"{thread_name}: {e}")
        
        # Launch concurrent reassignments
        thread_a = threading.Thread(target=reassign_mechanic, args=(self.mecanico2.id, 'thread_a'))
        thread_b = threading.Thread(target=reassign_mechanic, args=(mecanico3.id, 'thread_b'))
        
        thread_a.start()
        thread_b.start()
        
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)
        
        # Verify
        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), 2)
        
        # Final state: order has one valid mechanic
        self.orden.refresh_from_db()
        self.assertIsNotNone(self.orden.mecanico_asignado)
        self.assertIn(
            self.orden.mecanico_asignado.id,
            [self.mecanico2.id, mecanico3.id],
            "Final mechanic should be one of the reassignments"
        )
        
        # Audit trail should show transitions
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden).order_by('fecha_cambio')
        # At least one reassignment log (mecanico1 -> mecanico2/3)
        self.assertGreaterEqual(logs.count(), 1)
        
        # First log should have mecanico1 as anterior
        first_log = logs.first()
        self.assertEqual(first_log.tecnico_anterior_id, self.mecanico1.id)

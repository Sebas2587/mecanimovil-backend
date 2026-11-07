"""
Tests for idempotency in critical state transitions.
"""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status as http_status
from django.contrib.auth import get_user_model
from decimal import Decimal
from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.checklists.models import ChecklistInstance
from datetime import date, time

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_RESULT_BACKEND='cache+memory://'
)
class IdempotenciaTestCase(TestCase):
    """Test idempotency of accept and start_service endpoints."""
    
    def setUp(self):
        """Create test fixtures."""
        # Taller owner (mandante)
        user_mandante = User.objects.create_user(
            username='mandante1',
            password='test',
            email='mandante@test.com'
        )
        self.taller = Taller.objects.create(
            usuario=user_mandante,
            nombre='Taller Test',
            rut='12345678-9',
            telefono='+56912345678',
            estado_verificacion='aprobado'
        )
        # Create MiembroTaller for mandante
        self.mandante = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_mandante,
            nombre='Mandante Test',
            rol='mandante',
            activo=True,
            permisos={'servicios': True}
        )
        
        # Cliente
        user_cliente = User.objects.create_user(
            username='cliente1',
            password='test',
            email='cliente@test.com'
        )
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Test',
            email='cliente@test.com',
            telefono='+56987654321'
        )
        
        # Vehículo
        marca_toyota, _ = MarcaVehiculo.objects.get_or_create(nombre='Toyota')
        modelo_corolla, _ = Modelo.objects.get_or_create(
            marca=marca_toyota,
            nombre='Corolla'
        )
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca_toyota,
            modelo=modelo_corolla,
            year=2020,
            patente='AB1234'
        )
        
        # APIClient with force_authenticate
        self.client = APIClient()
        self.client.force_authenticate(user=user_mandante)
    
    def test_aceptar_idempotente(self):
        """Aceptar orden múltiples veces debe retornar success sin errores."""
        orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date(2026, 11, 8),
            hora_servicio=time(10, 0),
            metodo_pago='efectivo',
            total=Decimal('50000.00'),
            estado='pendiente_aceptacion_proveedor'
        )
        
        url = f'/api/ordenes/proveedor-ordenes/{orden.id}/aceptar/'
        
        # Primera llamada
        response1 = self.client.post(url, {})
        self.assertEqual(response1.status_code, 200)
        data1 = response1.data
        self.assertTrue(data1['success'])
        self.assertIn('aceptada exitosamente', data1['message'].lower())
        
        # Segunda llamada (idempotencia)
        response2 = self.client.post(url, {})
        self.assertEqual(response2.status_code, 200)
        data2 = response2.data
        self.assertTrue(data2['success'])
        self.assertIn('ya estaba aceptada', data2['message'].lower())
        
        # Verificar estado en BD
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'aceptada_por_proveedor')
        
        # Tercera llamada también debe funcionar
        response3 = self.client.post(url, {}, format='json')
        self.assertEqual(response3.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response3.data['success'])
    
    def test_aceptar_concurrente_seguro(self):
        """Múltiples requests concurrentes a /aceptar/ no deben causar race conditions."""
        orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date(2026, 11, 8),
            hora_servicio=time(10, 0),
            metodo_pago='efectivo',
            total=Decimal('50000.00'),
            estado='pendiente_aceptacion_proveedor'
        )
        
        url = f'/api/ordenes/proveedor-ordenes/{orden.id}/aceptar/'
        
        # Simular 3 requests simultáneos (en tests síncronos, ejecutados secuencialmente)
        responses = []
        for i in range(3):
            resp = self.client.post(url, {}, format='json')
            responses.append(resp)
        
        # Todas deben retornar 200
        for resp in responses:
            self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
            self.assertTrue(resp.data['success'])
        
        # Verificar solo 1 transición ocurrió
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'aceptada_por_proveedor')
        self.assertIsNotNone(orden.fecha_respuesta_proveedor)
    
    def test_iniciar_servicio_idempotente(self):
        """Iniciar servicio múltiples veces no debe duplicar checklist."""
        orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date(2026, 11, 8),
            hora_servicio=time(10, 0),
            metodo_pago='efectivo',
            total=Decimal('50000.00'),
            estado='aceptada_por_proveedor'
        )
        
        url = f'/api/ordenes/proveedor-ordenes/{orden.id}/iniciar_servicio/'
        
        # Primera llamada
        response1 = self.client.post(url, {}, format='json')
        self.assertEqual(response1.status_code, http_status.HTTP_200_OK)
        data1 = response1.data
        self.assertTrue(data1['success'])
        self.assertIn('iniciado exitosamente', data1['message'].lower())
        
        # Verificar estado
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'servicio_iniciado')
        
        # Contar checklists creados
        checklist_count_1 = ChecklistInstance.objects.filter(orden=orden).count()
        
        # Segunda llamada (idempotencia)
        response2 = self.client.post(url, {}, format='json')
        self.assertEqual(response2.status_code, http_status.HTTP_200_OK)
        data2 = response2.data
        self.assertTrue(data2['success'])
        self.assertIn('ya estaba iniciado', data2['message'].lower())
        
        # No debe haber duplicado checklist
        checklist_count_2 = ChecklistInstance.objects.filter(orden=orden).count()
        self.assertEqual(checklist_count_1, checklist_count_2)
        
        # Tercera llamada también segura
        response3 = self.client.post(url, {}, format='json')
        self.assertEqual(response3.status_code, http_status.HTTP_200_OK)
        checklist_count_3 = ChecklistInstance.objects.filter(orden=orden).count()
        self.assertEqual(checklist_count_1, checklist_count_3)
    
    def test_aceptar_estado_invalido_rechaza(self):
        """Aceptar orden en estado inválido debe retornar 400."""
        orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date(2026, 11, 8),
            hora_servicio=time(10, 0),
            metodo_pago='efectivo',
            total=Decimal('50000.00'),
            estado='completado'  # Estado final, no puede aceptarse
        )
        
        url = f'/api/ordenes/proveedor-ordenes/{orden.id}/aceptar/'
        response = self.client.post(url, {}, format='json')
        
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework import status
import json

from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo, Marca, Modelo
from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
from mecanimovilapp.apps.personalizacion.models import (
    VehiculoActivo, PerfilVehiculo, RecomendacionPersonalizada, ConfiguracionPersonalizacion
)


class TestPersonalizacionAPIs(TestCase):
    """Tests para las APIs del sistema de personalización"""
    
    def setUp(self):
        """Configuración inicial para los tests de APIs"""
        self.client = APIClient()
        
        # Crear usuario y cliente de prueba
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.cliente = Cliente.objects.create(usuario=self.user)
        
        # Crear marca y modelo
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Corolla', marca=self.marca)
        
        # Crear vehículos
        self.vehiculo1 = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            patente='ABC123',
            año=2020,
            kilometraje=25000
        )
        
        self.vehiculo2 = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            patente='XYZ789',
            año=2019,
            kilometraje=45000
        )
        
        # Crear servicios de prueba
        self.servicio = Servicio.objects.create(
            nombre='Cambio de Aceite',
            descripcion='Cambio de aceite y filtro',
            precio_base=30000
        )
        
        # Crear configuraciones
        ConfiguracionPersonalizacion.objects.create(
            clave='umbral_score_minimo',
            valor='0.3',
            descripcion='Score mínimo para recomendaciones'
        )
        
    def test_vehiculo_activo_get_sin_autenticacion(self):
        """Test GET vehículo activo sin autenticación"""
        url = reverse('personalizacion:vehiculo-activo-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_vehiculo_activo_get_con_autenticacion_sin_vehiculo(self):
        """Test GET vehículo activo con autenticación pero sin vehículo activo"""
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:vehiculo-activo-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
    def test_vehiculo_activo_post_establecer(self):
        """Test POST para establecer vehículo activo"""
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:vehiculo-activo-list')
        
        data = {'vehiculo_id': self.vehiculo1.id}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verificar que se creó el vehículo activo
        vehiculo_activo = VehiculoActivo.objects.filter(cliente=self.cliente).first()
        self.assertIsNotNone(vehiculo_activo)
        self.assertEqual(vehiculo_activo.vehiculo, self.vehiculo1)
        
    def test_vehiculo_activo_get_con_vehiculo_establecido(self):
        """Test GET vehículo activo cuando ya está establecido"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:vehiculo-activo-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['vehiculo']['id'], self.vehiculo1.id)
        
    def test_vehiculo_activo_post_cambiar(self):
        """Test POST para cambiar vehículo activo"""
        # Establecer vehículo activo inicial
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:vehiculo-activo-list')
        
        # Cambiar a otro vehículo
        data = {'vehiculo_id': self.vehiculo2.id}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verificar que se cambió el vehículo activo
        vehiculo_activo = VehiculoActivo.objects.get(cliente=self.cliente)
        self.assertEqual(vehiculo_activo.vehiculo, self.vehiculo2)
        
    def test_vehiculo_activo_post_vehiculo_inexistente(self):
        """Test POST con vehículo inexistente"""
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:vehiculo-activo-list')
        
        data = {'vehiculo_id': 99999}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_vehiculo_activo_post_vehiculo_otro_cliente(self):
        """Test POST con vehículo de otro cliente"""
        # Crear otro cliente y vehículo
        otro_user = User.objects.create_user(
            username='otrouser',
            email='otro@example.com',
            password='testpass123'
        )
        otro_cliente = Cliente.objects.create(usuario=otro_user)
        otro_vehiculo = Vehiculo.objects.create(
            cliente=otro_cliente,
            marca=self.marca,
            modelo=self.modelo,
            patente='OTR123',
            año=2021,
            kilometraje=10000
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:vehiculo-activo-list')
        
        data = {'vehiculo_id': otro_vehiculo.id}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_recomendaciones_get_sin_autenticacion(self):
        """Test GET recomendaciones sin autenticación"""
        url = reverse('personalizacion:recomendacion-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_recomendaciones_get_sin_vehiculo_activo(self):
        """Test GET recomendaciones sin vehículo activo"""
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        
    def test_recomendaciones_get_con_vehiculo_activo(self):
        """Test GET recomendaciones con vehículo activo"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear recomendaciones
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Test de recomendación',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['tipo'], 'mantenimiento')
        
    def test_recomendaciones_get_filtro_por_tipo(self):
        """Test GET recomendaciones filtradas por tipo"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear recomendaciones de diferentes tipos
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Recomendación de mantenimiento',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='servicio_popular',
            servicio=self.servicio,
            score_relevancia=0.6,
            razon_recomendacion='Servicio popular',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        self.client.force_authenticate(user=self.user)
        
        # Test filtro por mantenimiento
        url = reverse('personalizacion:recomendacion-list') + '?tipo=mantenimiento'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['tipo'], 'mantenimiento')
        
        # Test filtro por servicio popular
        url = reverse('personalizacion:recomendacion-list') + '?tipo=servicio_popular'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['tipo'], 'servicio_popular')
        
    def test_recomendaciones_get_solo_activas(self):
        """Test GET recomendaciones solo devuelve las activas"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear recomendación activa
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Recomendación activa',
            fecha_expiracion=timezone.now() + timedelta(days=30),
            activa=True
        )
        
        # Crear recomendación inactiva
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.7,
            razon_recomendacion='Recomendación inactiva',
            fecha_expiracion=timezone.now() + timedelta(days=30),
            activa=False
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['razon_recomendacion'], 'Recomendación activa')
        
    def test_recomendaciones_get_no_expiradas(self):
        """Test GET recomendaciones no devuelve las expiradas"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear recomendación vigente
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Recomendación vigente',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        # Crear recomendación expirada
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.7,
            razon_recomendacion='Recomendación expirada',
            fecha_expiracion=timezone.now() - timedelta(days=1)
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['razon_recomendacion'], 'Recomendación vigente')
        
    def test_recomendaciones_ordenadas_por_score(self):
        """Test GET recomendaciones ordenadas por score de relevancia"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear recomendaciones con diferentes scores
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.6,
            razon_recomendacion='Score bajo',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.9,
            razon_recomendacion='Score alto',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        
        # Verificar orden descendente por score
        self.assertGreater(
            response.data[0]['score_relevancia'],
            response.data[1]['score_relevancia']
        )
        self.assertEqual(response.data[0]['razon_recomendacion'], 'Score alto')
        
    def test_regenerar_recomendaciones_sin_autenticacion(self):
        """Test POST regenerar recomendaciones sin autenticación"""
        url = reverse('personalizacion:recomendacion-regenerar')
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_regenerar_recomendaciones_sin_vehiculo_activo(self):
        """Test POST regenerar recomendaciones sin vehículo activo"""
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-regenerar')
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_regenerar_recomendaciones_con_vehiculo_activo(self):
        """Test POST regenerar recomendaciones con vehículo activo"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear perfil de vehículo
        PerfilVehiculo.objects.create(
            vehiculo=self.vehiculo1,
            gasto_promedio_mensual=50000,
            frecuencia_mantenimiento=90,
            servicios_frecuentes=['Cambio de Aceite']
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-regenerar')
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('mensaje', response.data)
        
    def test_marcar_vista_recomendacion(self):
        """Test POST marcar vista de recomendación"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear recomendación
        recomendacion = RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Test de vista',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-marcar-vista', args=[recomendacion.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verificar que se incrementó el contador
        recomendacion.refresh_from_db()
        self.assertEqual(recomendacion.veces_mostrada, 1)
        
    def test_marcar_click_recomendacion(self):
        """Test POST marcar click de recomendación"""
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo1)
        
        # Crear recomendación
        recomendacion = RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Test de click',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-marcar-click', args=[recomendacion.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verificar que se incrementó el contador
        recomendacion.refresh_from_db()
        self.assertEqual(recomendacion.veces_clickeada, 1)
        
    def test_marcar_vista_recomendacion_otro_cliente(self):
        """Test POST marcar vista de recomendación de otro cliente"""
        # Crear otro cliente y recomendación
        otro_user = User.objects.create_user(
            username='otrouser',
            email='otro@example.com',
            password='testpass123'
        )
        otro_cliente = Cliente.objects.create(usuario=otro_user)
        
        recomendacion = RecomendacionPersonalizada.objects.create(
            cliente=otro_cliente,
            vehiculo=self.vehiculo1,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Test de otro cliente',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        self.client.force_authenticate(user=self.user)
        url = reverse('personalizacion:recomendacion-marcar-vista', args=[recomendacion.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestPersonalizacionAPIsIntegracion(TestCase):
    """Tests de integración para las APIs de personalización"""
    
    def setUp(self):
        """Configuración para tests de integración de APIs"""
        self.client = APIClient()
        
        # Crear usuario y cliente
        self.user = User.objects.create_user(
            username='integrationuser',
            email='integration@example.com',
            password='testpass123'
        )
        self.cliente = Cliente.objects.create(usuario=self.user)
        
        # Crear datos de prueba
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Corolla', marca=self.marca)
        
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            patente='INT123',
            año=2020,
            kilometraje=30000
        )
        
        self.servicio = Servicio.objects.create(
            nombre='Cambio de Aceite',
            descripcion='Cambio de aceite y filtro',
            precio_base=30000
        )
        
        # Configuraciones
        ConfiguracionPersonalizacion.objects.create(
            clave='umbral_score_minimo',
            valor='0.3',
            descripcion='Score mínimo'
        )
        
    def test_flujo_completo_apis(self):
        """Test del flujo completo de APIs"""
        self.client.force_authenticate(user=self.user)
        
        # 1. Establecer vehículo activo
        url_vehiculo_activo = reverse('personalizacion:vehiculo-activo-list')
        data = {'vehiculo_id': self.vehiculo.id}
        response = self.client.post(url_vehiculo_activo, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # 2. Verificar que se puede obtener el vehículo activo
        response = self.client.get(url_vehiculo_activo)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['vehiculo']['id'], self.vehiculo.id)
        
        # 3. Crear recomendaciones manualmente para el test
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo='mantenimiento',
            servicio=self.servicio,
            score_relevancia=0.8,
            razon_recomendacion='Recomendación de integración',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        # 4. Obtener recomendaciones
        url_recomendaciones = reverse('personalizacion:recomendacion-list')
        response = self.client.get(url_recomendaciones)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        
        # 5. Marcar vista de recomendación
        recomendacion_id = response.data[0]['id']
        url_vista = reverse('personalizacion:recomendacion-marcar-vista', args=[recomendacion_id])
        response = self.client.post(url_vista)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 6. Marcar click de recomendación
        url_click = reverse('personalizacion:recomendacion-marcar-click', args=[recomendacion_id])
        response = self.client.post(url_click)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 7. Verificar que se actualizaron las métricas
        recomendacion = RecomendacionPersonalizada.objects.get(id=recomendacion_id)
        self.assertEqual(recomendacion.veces_mostrada, 1)
        self.assertEqual(recomendacion.veces_clickeada, 1)
        
    def test_performance_apis(self):
        """Test de performance de las APIs"""
        import time
        
        self.client.force_authenticate(user=self.user)
        
        # Establecer vehículo activo
        VehiculoActivo.objects.create(cliente=self.cliente, vehiculo=self.vehiculo)
        
        # Crear múltiples recomendaciones
        for i in range(50):
            RecomendacionPersonalizada.objects.create(
                cliente=self.cliente,
                vehiculo=self.vehiculo,
                tipo='mantenimiento',
                servicio=self.servicio,
                score_relevancia=0.5 + (i * 0.01),
                razon_recomendacion=f'Recomendación {i}',
                fecha_expiracion=timezone.now() + timedelta(days=30)
            )
        
        # Medir tiempo de respuesta
        url = reverse('personalizacion:recomendacion-list')
        start_time = time.time()
        response = self.client.get(url)
        end_time = time.time()
        
        tiempo_respuesta = end_time - start_time
        
        # Verificar que la respuesta es rápida (menos de 1 segundo)
        self.assertLess(tiempo_respuesta, 1.0, 
                       f"Tiempo de respuesta muy alto: {tiempo_respuesta:.2f}s")
        
        # Verificar que se devolvieron todas las recomendaciones
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 50)
        
    def test_concurrencia_vehiculo_activo(self):
        """Test de concurrencia para establecer vehículo activo"""
        self.client.force_authenticate(user=self.user)
        
        # Crear otro vehículo
        vehiculo2 = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            patente='CON123',
            año=2021,
            kilometraje=15000
        )
        
        url = reverse('personalizacion:vehiculo-activo-list')
        
        # Establecer primer vehículo
        data1 = {'vehiculo_id': self.vehiculo.id}
        response1 = self.client.post(url, data1, format='json')
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        
        # Cambiar a segundo vehículo
        data2 = {'vehiculo_id': vehiculo2.id}
        response2 = self.client.post(url, data2, format='json')
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        
        # Verificar que solo hay un vehículo activo
        vehiculos_activos = VehiculoActivo.objects.filter(cliente=self.cliente)
        self.assertEqual(vehiculos_activos.count(), 1)
        self.assertEqual(vehiculos_activos.first().vehiculo, vehiculo2) 
"""
Tests para el sistema de solicitudes públicas y ofertas
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework import status

from mecanimovilapp.apps.usuarios.models import Cliente, DireccionUsuario, Taller
from mecanimovilapp.apps.vehiculos.models import Vehiculo, Marca, Modelo
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.ordenes.models import (
    SolicitudServicioPublica,
    OfertaProveedor,
    DetalleServicioOferta,
    ChatSolicitud
)

User = get_user_model()


class SolicitudPublicaTestCase(TestCase):
    """Tests para SolicitudServicioPublica"""
    
    def setUp(self):
        """Configuración inicial para los tests"""
        # Crear usuario cliente
        self.cliente_user = User.objects.create_user(
            username='cliente_test',
            email='cliente@test.com',
            password='testpass123'
        )
        self.cliente = Cliente.objects.create(
            usuario=self.cliente_user,
            nombre='Cliente Test',
            email='cliente@test.com'
        )
        
        # Crear usuario proveedor
        self.proveedor_user = User.objects.create_user(
            username='proveedor_test',
            email='proveedor@test.com',
            password='testpass123'
        )
        
        # Crear marca y modelo
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(
            nombre='Corolla',
            marca=self.marca
        )
        
        # Crear vehículo
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2020,
            patente='ABC123'
        )
        
        # Crear servicio
        self.servicio = Servicio.objects.create(
            nombre='Cambio de aceite',
            descripcion='Cambio de aceite y filtro',
            precio_base=25000
        )
        self.servicio.marcas_compatibles.add(self.marca)
        
        # Crear dirección
        self.direccion = DireccionUsuario.objects.create(
            usuario=self.cliente_user,
            direccion='Av. Test 123',
            comuna='Santiago',
            region='Región Metropolitana',
            es_principal=True
        )
        
        # Cliente API
        self.client = APIClient()
        self.client.force_authenticate(user=self.cliente_user)
    
    def test_crear_solicitud_global(self):
        """Test: Crear una solicitud global"""
        fecha_expiracion = timezone.now() + timedelta(days=7)
        
        data = {
            'vehiculo': self.vehiculo.id,
            'descripcion_problema': 'Necesito cambio de aceite',
            'urgencia': 'normal',
            'tipo_solicitud': 'global',
            'direccion_usuario': self.direccion.id,
            'direccion_servicio_texto': 'Av. Test 123',
            'fecha_preferida': (timezone.now() + timedelta(days=3)).date().isoformat(),
            'fecha_expiracion': fecha_expiracion.isoformat(),
            'ubicacion_servicio': 'POINT(-70.6693 -33.4489)'
        }
        
        response = self.client.post('/api/ordenes/solicitudes-publicas/', data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['tipo_solicitud'], 'global')
        self.assertEqual(response.data['estado'], 'creada')
    
    def test_crear_solicitud_dirigida(self):
        """Test: Crear una solicitud dirigida"""
        fecha_expiracion = timezone.now() + timedelta(days=7)
        
        data = {
            'vehiculo': self.vehiculo.id,
            'descripcion_problema': 'Necesito cambio de aceite',
            'urgencia': 'normal',
            'tipo_solicitud': 'dirigida',
            'proveedores_dirigidos': [self.proveedor_user.id],
            'direccion_usuario': self.direccion.id,
            'direccion_servicio_texto': 'Av. Test 123',
            'fecha_preferida': (timezone.now() + timedelta(days=3)).date().isoformat(),
            'fecha_expiracion': fecha_expiracion.isoformat(),
            'ubicacion_servicio': 'POINT(-70.6693 -33.4489)'
        }
        
        response = self.client.post('/api/ordenes/solicitudes-publicas/', data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['tipo_solicitud'], 'dirigida')
    
    def test_agregar_servicios(self):
        """Test: Agregar servicios a una solicitud"""
        solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='Test',
            fecha_preferida=timezone.now().date() + timedelta(days=3),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Test'
        )
        
        response = self.client.post(
            f'/api/ordenes/solicitudes-publicas/{solicitud.id}/agregar_servicios/',
            {'servicios': [self.servicio.id]}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['estado'], 'seleccionando_servicios')
        self.assertEqual(solicitud.servicios_solicitados.count(), 1)
    
    def test_publicar_solicitud(self):
        """Test: Publicar una solicitud"""
        solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='Test',
            fecha_preferida=timezone.now().date() + timedelta(days=3),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Test',
            estado='seleccionando_servicios'
        )
        solicitud.servicios_solicitados.add(self.servicio)
        
        response = self.client.post(
            f'/api/ordenes/solicitudes-publicas/{solicitud.id}/publicar/'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['estado'], 'publicada')
        self.assertIsNotNone(response.data['fecha_publicacion'])

    def test_verificar_servicio_activo_bloqueado(self):
        """Mismo vehículo + servicio en solicitud activa bloquea nueva verificación."""
        solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='Aceite en curso',
            fecha_preferida=timezone.now().date() + timedelta(days=3),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Test',
            estado='publicada',
        )
        solicitud.servicios_solicitados.add(self.servicio)

        response = self.client.get(
            '/api/ordenes/solicitudes-publicas/verificar-servicio-activo/',
            {'vehiculo_id': self.vehiculo.id, 'servicio_ids': str(self.servicio.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['bloqueado'])
        self.assertEqual(str(solicitud.id), response.data['solicitud_id'])

    def test_crear_solicitud_duplicada_rechazada(self):
        """POST con mismo vehículo y servicio activo devuelve 400."""
        solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='Ya pedí aceite',
            fecha_preferida=timezone.now().date() + timedelta(days=3),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Test',
            estado='con_ofertas',
        )
        solicitud.servicios_solicitados.add(self.servicio)

        fecha_expiracion = timezone.now() + timedelta(days=7)
        data = {
            'vehiculo': self.vehiculo.id,
            'descripcion_problema': 'Otro pedido de aceite',
            'urgencia': 'normal',
            'tipo_solicitud': 'global',
            'servicios_solicitados': [self.servicio.id],
            'direccion_usuario': self.direccion.id,
            'direccion_servicio_texto': 'Av. Test 123',
            'fecha_preferida': (timezone.now() + timedelta(days=4)).date().isoformat(),
            'fecha_expiracion': fecha_expiracion.isoformat(),
            'ubicacion_servicio': 'POINT(-70.6693 -33.4489)',
        }
        response = self.client.post('/api/ordenes/solicitudes-publicas/', data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('servicios_solicitados', response.data)


class OfertaProveedorTestCase(TestCase):
    """Tests para OfertaProveedor"""
    
    def setUp(self):
        """Configuración inicial"""
        # Reutilizar setup de SolicitudPublicaTestCase
        self.cliente_user = User.objects.create_user(
            username='cliente_test',
            email='cliente@test.com',
            password='testpass123'
        )
        self.cliente = Cliente.objects.create(
            usuario=self.cliente_user,
            nombre='Cliente Test',
            email='cliente@test.com'
        )
        
        self.proveedor_user = User.objects.create_user(
            username='proveedor_test',
            email='proveedor@test.com',
            password='testpass123'
        )
        
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Corolla', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2020,
            patente='ABC123'
        )
        
        self.servicio = Servicio.objects.create(
            nombre='Cambio de aceite',
            descripcion='Cambio de aceite y filtro',
            precio_base=25000
        )
        
        self.solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='Test',
            fecha_preferida=timezone.now().date() + timedelta(days=3),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Test',
            estado='publicada',
            fecha_publicacion=timezone.now()
        )
        self.solicitud.servicios_solicitados.add(self.servicio)
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.proveedor_user)
    
    def test_crear_oferta(self):
        """Test: Crear una oferta"""
        data = {
            'solicitud': self.solicitud.id,
            'proveedor': self.proveedor_user.id,
            'tipo_proveedor': 'taller',
            'precio_total_ofrecido': 30000,
            'incluye_repuestos': True,
            'tiempo_estimado_total': '02:00:00',
            'descripcion_oferta': 'Oferta de prueba',
            'fecha_disponible': (timezone.now() + timedelta(days=3)).date().isoformat(),
            'detalles_servicios': [
                {
                    'servicio': self.servicio.id,
                    'precio_servicio': 30000,
                    'tiempo_estimado': '02:00:00'
                }
            ]
        }
        
        response = self.client.post('/api/ordenes/ofertas/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['estado'], 'enviada')
        self.assertEqual(OfertaProveedor.objects.count(), 1)


class ChatSolicitudTestCase(TestCase):
    """Tests para ChatSolicitud"""
    
    def setUp(self):
        """Configuración inicial"""
        self.cliente_user = User.objects.create_user(
            username='cliente_test',
            email='cliente@test.com',
            password='testpass123'
        )
        self.cliente = Cliente.objects.create(
            usuario=self.cliente_user,
            nombre='Cliente Test',
            email='cliente@test.com'
        )
        
        self.proveedor_user = User.objects.create_user(
            username='proveedor_test',
            email='proveedor@test.com',
            password='testpass123'
        )
        
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Corolla', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2020,
            patente='ABC123'
        )
        
        self.solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='Test',
            fecha_preferida=timezone.now().date() + timedelta(days=3),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Test',
            estado='publicada'
        )
        
        self.oferta = OfertaProveedor.objects.create(
            solicitud=self.solicitud,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=30000,
            estado='enviada'
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.cliente_user)
    
    def test_enviar_mensaje_cliente(self):
        """Test: Cliente envía mensaje"""
        data = {
            'oferta': self.oferta.id,
            'mensaje': 'Hola, ¿está disponible?',
            'es_proveedor': False
        }
        
        response = self.client.post('/api/ordenes/chat-solicitudes/', data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['mensaje'], 'Hola, ¿está disponible?')
        self.assertFalse(response.data['es_proveedor'])
        self.assertEqual(ChatSolicitud.objects.count(), 1)


class MisSolicitudesAislamientoTestCase(TestCase):
    """Regresión: Mis solicitudes no expone solicitudes de otros clientes."""

    def setUp(self):
        self.marca = Marca.objects.create(nombre='Nissan')
        self.modelo = Modelo.objects.create(nombre='Sentra', marca=self.marca)

        self.user_a = User.objects.create_user(
            username='cliente_a', email='a@test.com', password='testpass123'
        )
        self.cliente_a = Cliente.objects.create(
            usuario=self.user_a, nombre='A', email='a@test.com'
        )
        self.vehiculo_a = Vehiculo.objects.create(
            cliente=self.cliente_a,
            marca=self.marca,
            modelo=self.modelo,
            year=2019,
            patente='AAA111',
        )

        self.user_b = User.objects.create_user(
            username='cliente_b', email='b@test.com', password='testpass123'
        )
        self.cliente_b = Cliente.objects.create(
            usuario=self.user_b, nombre='B', email='b@test.com'
        )

        self.solicitud_a = SolicitudServicioPublica.objects.create(
            cliente=self.cliente_a,
            vehiculo=self.vehiculo_a,
            descripcion_problema='Solicitud de A',
            fecha_preferida=timezone.now().date() + timedelta(days=2),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Dir A',
            estado='publicada',
        )

        self.proveedor_user = User.objects.create_user(
            username='solo_proveedor', email='p@test.com', password='testpass123'
        )
        Taller.objects.create(
            nombre='Taller P',
            usuario=self.proveedor_user,
            estado_verificacion='aprobado',
            telefono='9',
        )
        self.vehiculo_global = Vehiculo.objects.create(
            cliente=self.cliente_a,
            marca=self.marca,
            modelo=self.modelo,
            year=2018,
            patente='BBB222',
        )
        self.solicitud_global = SolicitudServicioPublica.objects.create(
            cliente=self.cliente_a,
            vehiculo=self.vehiculo_global,
            descripcion_problema='Global marketplace',
            fecha_preferida=timezone.now().date() + timedelta(days=2),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Dir G',
            estado='publicada',
            tipo_solicitud='global',
        )
        self.taller = Taller.objects.get(usuario=self.proveedor_user)
        self.taller.marcas_atendidas.add(self.marca)

    def _ids_from_response(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            data = data['results']
        if isinstance(data, dict) and data.get('type') == 'FeatureCollection':
            items = data.get('features') or []
        elif isinstance(data, list):
            items = data
        else:
            items = data or []
        ids = []
        for item in items:
            if isinstance(item, dict):
                ids.append(str(item.get('id') or item.get('properties', {}).get('id')))
        return ids

    def test_cliente_b_no_ve_solicitudes_de_cliente_a_en_mis_solicitudes(self):
        client = APIClient()
        client.force_authenticate(user=self.user_b)
        response = client.get('/api/ordenes/solicitudes-publicas/mis-solicitudes/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._ids_from_response(response)
        self.assertNotIn(str(self.solicitud_a.id), ids)
        self.assertNotIn(str(self.solicitud_global.id), ids)

    def test_cliente_b_no_ve_solicitudes_ajenas_en_list(self):
        client = APIClient()
        client.force_authenticate(user=self.user_b)
        response = client.get('/api/ordenes/solicitudes-publicas/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._ids_from_response(response)
        self.assertNotIn(str(self.solicitud_a.id), ids)

    def test_proveedor_sin_cliente_list_vacio(self):
        client = APIClient()
        client.force_authenticate(user=self.proveedor_user)
        response = client.get('/api/ordenes/solicitudes-publicas/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._ids_from_response(response)
        self.assertEqual(len(ids), 0)

    def test_cliente_a_ve_solo_sus_solicitudes(self):
        client = APIClient()
        client.force_authenticate(user=self.user_a)
        response = client.get('/api/ordenes/solicitudes-publicas/mis-solicitudes/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._ids_from_response(response)
        self.assertIn(str(self.solicitud_a.id), ids)
        self.assertIn(str(self.solicitud_global.id), ids)


class ProveedorDetalleSolicitudRechazadaTestCase(MisSolicitudesAislamientoTestCase):
    """Proveedor debe poder abrir detalle de solicitudes rechazadas / historial."""

    def test_proveedor_ve_detalle_con_oferta_rechazada(self):
        from datetime import time as dt_time, timedelta
        from decimal import Decimal

        fd = timezone.now().date() + timedelta(days=3)
        OfertaProveedor.objects.create(
            solicitud=self.solicitud_global,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('45000'),
            incluye_repuestos=False,
            tiempo_estimado_total=timedelta(hours=1),
            descripcion_oferta='Oferta rechazada',
            fecha_disponible=fd,
            hora_disponible=dt_time(10, 0),
            estado='rechazada',
        )

        client = APIClient()
        client.force_authenticate(user=self.proveedor_user)
        response = client.get(
            f'/api/ordenes/solicitudes-publicas/{self.solicitud_global.id}/',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_proveedor_ve_detalle_tras_rechazar_sin_oferta(self):
        from mecanimovilapp.apps.ordenes.models import RechazoSolicitud

        RechazoSolicitud.objects.create(
            solicitud=self.solicitud_global,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            motivo='ocupado',
        )

        client = APIClient()
        client.force_authenticate(user=self.proveedor_user)
        response = client.get(
            f'/api/ordenes/solicitudes-publicas/{self.solicitud_global.id}/',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


"""Tests reserva de adjudicación por créditos."""
import uuid
from datetime import time as dt_time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import (
    DetalleServicioOferta,
    OfertaProveedor,
    SolicitudServicioPublica,
)
from mecanimovilapp.apps.ordenes.services import adjudicacion_publica
from mecanimovilapp.apps.ordenes.serializers import SolicitudServicioPublicaSerializer
from mecanimovilapp.apps.ordenes.views import procesar_solicitudes_expiradas
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.suscripciones.models import ConsumoCredito, CreditoProveedor
from mecanimovilapp.apps.usuarios.models import Cliente, DireccionUsuario, Taller
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()


class PrivacidadReservaCreditosTest(TestCase):
    """Serializer: sin BD pesada en helpers de privacidad."""

    def test_proveedor_no_ve_pii_en_esperando_creditos(self):
        from unittest.mock import MagicMock

        ser = SolicitudServicioPublicaSerializer()
        prov = MagicMock()
        prov.id = 10
        sel = MagicMock()
        sel.proveedor = prov
        sel.estado = 'pendiente_creditos'
        sol = MagicMock()
        sol.oferta_seleccionada = sel
        sol.estado = 'esperando_creditos_proveedor'
        self.assertFalse(ser._proveedor_puede_ver_datos_cliente(prov, sol))

    def test_proveedor_ve_pii_tras_adjudicada(self):
        from unittest.mock import MagicMock

        ser = SolicitudServicioPublicaSerializer()
        prov = MagicMock()
        sel = MagicMock()
        sel.proveedor = prov
        sel.estado = 'aceptada'
        sol = MagicMock()
        sol.oferta_seleccionada = sel
        sol.estado = 'adjudicada'
        self.assertTrue(ser._proveedor_puede_ver_datos_cliente(prov, sol))


class AplicarReservaCreditosTest(TestCase):
    """Reserva atómica: estados, oferta seleccionada, competencia cerrada."""

    def setUp(self):
        suf = uuid.uuid4().hex[:10]
        self.cliente_user = User.objects.create_user(
            username=f'c_{suf}',
            email=f'c_{suf}@t.com',
            password='x',
            first_name='C',
            last_name='L',
        )
        self.proveedor_user = User.objects.create_user(
            username=f'p_{suf}',
            email=f'p_{suf}@t.com',
            password='x',
            first_name='P',
            last_name='R',
        )
        self.proveedor2_user = User.objects.create_user(
            username=f'p2o_{suf}',
            email=f'p2o_{suf}@t.com',
            password='x',
            first_name='P',
            last_name='2',
        )
        self.cliente = Cliente.objects.create(
            usuario=self.cliente_user,
            nombre='C',
            apellido='L',
            email=self.cliente_user.email,
        )
        self.taller = Taller.objects.create(
            nombre='Taller T',
            usuario=self.proveedor_user,
            estado_verificacion='aprobado',
            telefono='1',
        )
        Taller.objects.create(
            nombre='Taller Otra',
            usuario=self.proveedor2_user,
            estado_verificacion='aprobado',
            telefono='2',
        )
        self.marca = Marca.objects.create(nombre=f'M{suf}')
        self.modelo = Modelo.objects.create(nombre='Mod', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2020,
            patente='AB12',
        )
        self.servicio = Servicio.objects.create(
            nombre=f'Svc{suf}',
            descripcion='d',
            precio_referencia=Decimal('10000'),
        )
        self.direccion = DireccionUsuario.objects.create(
            usuario=self.cliente_user,
            direccion='Dir',
            comuna='Santiago',
            region='RM',
            es_principal=True,
        )
        fd = (timezone.now() + timedelta(days=5)).date()
        self.solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='x',
            fecha_preferida=timezone.now().date() + timedelta(days=2),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Dir',
            direccion_usuario=self.direccion,
            estado='con_ofertas',
            fecha_publicacion=timezone.now(),
        )
        self.solicitud.servicios_solicitados.add(self.servicio)

        self.oferta_main = OfertaProveedor.objects.create(
            solicitud=self.solicitud,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('30000'),
            incluye_repuestos=False,
            tiempo_estimado_total=timedelta(hours=2),
            descripcion_oferta='d',
            fecha_disponible=fd,
            hora_disponible=dt_time(10, 0),
            estado='en_chat',
        )
        DetalleServicioOferta.objects.create(
            oferta=self.oferta_main,
            servicio=self.servicio,
            precio_servicio=Decimal('30000'),
            tiempo_estimado=timedelta(hours=2),
        )
        self.oferta_otra = OfertaProveedor.objects.create(
            solicitud=self.solicitud,
            proveedor=self.proveedor2_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('28000'),
            incluye_repuestos=False,
            tiempo_estimado_total=timedelta(hours=2),
            descripcion_oferta='o',
            fecha_disponible=fd,
            hora_disponible=dt_time(11, 0),
            estado='en_chat',
        )
        DetalleServicioOferta.objects.create(
            oferta=self.oferta_otra,
            servicio=self.servicio,
            precio_servicio=Decimal('28000'),
            tiempo_estimado=timedelta(hours=2),
        )

    @patch('mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay')
    def test_reserva_marca_estados_y_rechaza_otras(self, _push):
        res = adjudicacion_publica.aplicar_reserva_por_falta_creditos(
            self.solicitud.id,
            self.oferta_main.id,
            2,
        )
        self.assertIn('fecha_limite_confirmacion_creditos', res)
        self.solicitud.refresh_from_db()
        self.oferta_main.refresh_from_db()
        self.oferta_otra.refresh_from_db()
        self.assertEqual(self.solicitud.estado, 'esperando_creditos_proveedor')
        self.assertEqual(self.oferta_main.estado, 'pendiente_creditos')
        self.assertEqual(self.solicitud.oferta_seleccionada_id, self.oferta_main.id)
        self.assertEqual(self.oferta_otra.estado, 'rechazada')


class ProcesarExpiracionReservaTest(TestCase):
    """PASO 0 en procesar_solicitudes_expiradas."""

    def setUp(self):
        suf = uuid.uuid4().hex[:10]
        self.cliente_user = User.objects.create_user(
            username=f'c2_{suf}',
            email=f'c2_{suf}@t.com',
            password='x',
            first_name='C',
            last_name='L',
        )
        self.proveedor_user = User.objects.create_user(
            username=f'p2_{suf}',
            email=f'p2_{suf}@t.com',
            password='x',
            first_name='P',
            last_name='R',
        )
        self.cliente = Cliente.objects.create(
            usuario=self.cliente_user,
            nombre='C',
            apellido='L',
            email=self.cliente_user.email,
        )
        Taller.objects.create(
            nombre='T2',
            usuario=self.proveedor_user,
            estado_verificacion='aprobado',
            telefono='1',
        )
        self.marca = Marca.objects.create(nombre=f'M2{suf}')
        self.modelo = Modelo.objects.create(nombre='M2', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2019,
            patente='CD34',
        )
        self.servicio = Servicio.objects.create(
            nombre=f'S2{suf}',
            descripcion='d',
            precio_referencia=Decimal('5000'),
        )
        self.direccion = DireccionUsuario.objects.create(
            usuario=self.cliente_user,
            direccion='D',
            comuna='Santiago',
            region='RM',
            es_principal=True,
        )
        fd = (timezone.now() + timedelta(days=3)).date()
        self.solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='x',
            fecha_preferida=timezone.now().date() + timedelta(days=1),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='D',
            direccion_usuario=self.direccion,
            estado='esperando_creditos_proveedor',
            fecha_publicacion=timezone.now(),
            fecha_limite_confirmacion_creditos=timezone.now() - timedelta(hours=1),
        )
        self.solicitud.servicios_solicitados.add(self.servicio)
        self.oferta = OfertaProveedor.objects.create(
            solicitud=self.solicitud,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('20000'),
            incluye_repuestos=False,
            tiempo_estimado_total=timedelta(hours=1),
            descripcion_oferta='d',
            fecha_disponible=fd,
            hora_disponible=dt_time(9, 0),
            estado='pendiente_creditos',
        )
        self.solicitud.oferta_seleccionada = self.oferta
        self.solicitud.save(update_fields=['oferta_seleccionada'])
        DetalleServicioOferta.objects.create(
            oferta=self.oferta,
            servicio=self.servicio,
            precio_servicio=Decimal('20000'),
            tiempo_estimado=timedelta(hours=1),
        )

    def test_expira_reserva_sin_ofertas_abiertas(self):
        n = procesar_solicitudes_expiradas()
        self.assertGreaterEqual(n, 1)
        self.solicitud.refresh_from_db()
        self.oferta.refresh_from_db()
        self.assertIn(self.solicitud.estado, ('expirada', 'con_ofertas'))
        self.assertIsNone(self.solicitud.oferta_seleccionada_id)
        self.assertEqual(self.oferta.estado, 'expirada')


class CompletarAdjudicacionIdempotenciaTest(TestCase):
    """Si ya existe ConsumoCredito, completar_adjudicacion_si_listo no vuelve a ejecutar."""

    def setUp(self):
        suf = uuid.uuid4().hex[:10]
        self.cliente_user = User.objects.create_user(
            username=f'c3_{suf}',
            email=f'c3_{suf}@t.com',
            password='x',
            first_name='C',
            last_name='L',
        )
        self.proveedor_user = User.objects.create_user(
            username=f'p3_{suf}',
            email=f'p3_{suf}@t.com',
            password='x',
            first_name='P',
            last_name='R',
        )
        self.cliente = Cliente.objects.create(
            usuario=self.cliente_user,
            nombre='C',
            apellido='L',
            email=self.cliente_user.email,
        )
        Taller.objects.create(
            nombre='T3',
            usuario=self.proveedor_user,
            estado_verificacion='aprobado',
            telefono='1',
        )
        self.marca = Marca.objects.create(nombre=f'M3{suf}')
        self.modelo = Modelo.objects.create(nombre='M3', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2018,
            patente='EF56',
        )
        self.servicio = Servicio.objects.create(
            nombre=f'S3{suf}',
            descripcion='d',
            precio_referencia=Decimal('8000'),
        )
        self.direccion = DireccionUsuario.objects.create(
            usuario=self.cliente_user,
            direccion='D',
            comuna='Santiago',
            region='RM',
            es_principal=True,
        )
        fd = (timezone.now() + timedelta(days=2)).date()
        self.solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='x',
            fecha_preferida=timezone.now().date() + timedelta(days=1),
            fecha_expiracion=timezone.now() + timedelta(days=5),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='D',
            direccion_usuario=self.direccion,
            estado='esperando_creditos_proveedor',
            fecha_publicacion=timezone.now(),
            fecha_limite_confirmacion_creditos=timezone.now() + timedelta(days=1),
        )
        self.solicitud.servicios_solicitados.add(self.servicio)
        self.oferta = OfertaProveedor.objects.create(
            solicitud=self.solicitud,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('15000'),
            incluye_repuestos=False,
            tiempo_estimado_total=timedelta(hours=1),
            descripcion_oferta='d',
            fecha_disponible=fd,
            hora_disponible=dt_time(8, 0),
            estado='pendiente_creditos',
        )
        self.solicitud.oferta_seleccionada = self.oferta
        self.solicitud.save(update_fields=['oferta_seleccionada'])
        DetalleServicioOferta.objects.create(
            oferta=self.oferta,
            servicio=self.servicio,
            precio_servicio=Decimal('15000'),
            tiempo_estimado=timedelta(hours=1),
        )
        CreditoProveedor.objects.create(proveedor=self.proveedor_user, saldo_creditos=10)
        ConsumoCredito.objects.create(
            proveedor=self.proveedor_user,
            oferta=self.oferta,
            servicio=self.servicio,
            creditos_consumidos=2,
            precio_credito=Decimal('1000.00'),
        )

    def test_completar_retorna_ok_si_ya_hay_consumo(self):
        r1 = adjudicacion_publica.completar_adjudicacion_si_listo(self.oferta.id)
        r2 = adjudicacion_publica.completar_adjudicacion_si_listo(self.oferta.id)
        self.assertEqual(r1.get('reason'), 'already_has_consumo')
        self.assertEqual(r2.get('reason'), 'already_has_consumo')


class SeleccionarOfertaReservaAPITest(TestCase):
    """Cliente elige oferta con proveedor sin saldo → 200 y estado_resultado."""

    def setUp(self):
        suf = uuid.uuid4().hex[:10]
        self.cliente_user = User.objects.create_user(
            username=f'c4_{suf}',
            email=f'c4_{suf}@t.com',
            password='pass12345',
            first_name='C',
            last_name='L',
        )
        self.proveedor_user = User.objects.create_user(
            username=f'p4_{suf}',
            email=f'p4_{suf}@t.com',
            password='pass12345',
            first_name='P',
            last_name='R',
        )
        self.cliente = Cliente.objects.create(
            usuario=self.cliente_user,
            nombre='C',
            apellido='L',
            email=self.cliente_user.email,
        )
        Taller.objects.create(
            nombre='T4',
            usuario=self.proveedor_user,
            estado_verificacion='aprobado',
            telefono='1',
        )
        self.marca = Marca.objects.create(nombre=f'M4{suf}')
        self.modelo = Modelo.objects.create(nombre='M4', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2017,
            patente='GH78',
        )
        self.servicio = Servicio.objects.create(
            nombre=f'S4{suf}',
            descripcion='d',
            precio_referencia=Decimal('12000'),
        )
        self.direccion = DireccionUsuario.objects.create(
            usuario=self.cliente_user,
            direccion='D',
            comuna='Santiago',
            region='RM',
            es_principal=True,
        )
        fd = (timezone.now() + timedelta(days=4)).date()
        self.solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='x',
            fecha_preferida=timezone.now().date() + timedelta(days=1),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='D',
            direccion_usuario=self.direccion,
            estado='con_ofertas',
            fecha_publicacion=timezone.now(),
        )
        self.solicitud.servicios_solicitados.add(self.servicio)
        self.oferta = OfertaProveedor.objects.create(
            solicitud=self.solicitud,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('22000'),
            incluye_repuestos=False,
            tiempo_estimado_total=timedelta(hours=2),
            descripcion_oferta='d',
            fecha_disponible=fd,
            hora_disponible=dt_time(10, 30),
            estado='en_chat',
        )
        DetalleServicioOferta.objects.create(
            oferta=self.oferta,
            servicio=self.servicio,
            precio_servicio=Decimal('22000'),
            tiempo_estimado=timedelta(hours=2),
        )
        CreditoProveedor.objects.get_or_create(
            proveedor=self.proveedor_user,
            defaults={'saldo_creditos': 0},
        )
        cp = CreditoProveedor.objects.get(proveedor=self.proveedor_user)
        cp.saldo_creditos = 0
        cp.save(update_fields=['saldo_creditos'])

        self.api = APIClient()
        self.api.force_authenticate(user=self.cliente_user)

    @patch('mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay')
    def test_seleccionar_sin_creditos_devuelve_reserva_200(self, _push):
        url = f'/api/ordenes/solicitudes-publicas/{self.solicitud.id}/seleccionar_oferta/'
        resp = self.api.post(url, {'oferta_id': str(self.oferta.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get('estado_resultado'), 'esperando_creditos_proveedor')
        self.assertGreater(resp.data.get('creditos_necesarios', 0), 0)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, 'esperando_creditos_proveedor')

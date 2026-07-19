"""Adjudicación catálogo con múltiples OfertaServicio por servicio (multimarca / tipo motor)."""
import uuid
from datetime import time as dt_time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import DetalleServicioOferta, OfertaProveedor, SolicitudServicioPublica
from mecanimovilapp.apps.ordenes.services import adjudicacion_publica
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_confirmacion import (
    ConfirmacionCatalogoError,
    adjudicar_oferta_catalogo_confirmada,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.suscripciones.models import CreditoProveedor
from mecanimovilapp.apps.usuarios.models import Cliente, DireccionUsuario, MecanicoDomicilio
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

User = get_user_model()


class ResolverOfertaServicioCatalogoMultimarcaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        suf = uuid.uuid4().hex[:8]
        cls.marca = MarcaVehiculo.objects.create(nombre=f'MultimarcaAdj{suf}')
        cls.modelo = Modelo.objects.create(nombre='ModAdj', marca=cls.marca)
        cls.servicio = Servicio.objects.create(
            nombre=f'Cambio liquido frenos {suf}',
            descripcion='d',
            precio_referencia=Decimal('50000'),
        )

        cls.proveedor_user = User.objects.create_user(
            username=f'prov_adj_{suf}@test.com',
            email=f'prov_adj_{suf}@test.com',
            password='testpass123',
        )
        cls.mecanico = MecanicoDomicilio.objects.create(
            usuario=cls.proveedor_user,
            nombre='Mecanico Adj',
            telefono='56900000000',
            verificado=True,
            activo=True,
        )

        cls.oferta_gasolina = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='mecanico',
            mecanico=cls.mecanico,
            tipo_motor='GASOLINA',
            disponible=True,
            precio_sin_repuestos=Decimal('40000'),
            precio_con_repuestos=Decimal('50000'),
            precio_publicado_cliente=Decimal('50000'),
            costo_mano_de_obra_sin_iva=Decimal('30000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )
        cls.oferta_diesel = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='mecanico',
            mecanico=cls.mecanico,
            tipo_motor='DIESEL',
            disponible=True,
            precio_sin_repuestos=Decimal('45000'),
            precio_con_repuestos=Decimal('55000'),
            precio_publicado_cliente=Decimal('55000'),
            costo_mano_de_obra_sin_iva=Decimal('32000'),
            costo_repuestos_sin_iva=Decimal('11000'),
        )

        cls.cliente_user = User.objects.create_user(
            username=f'cli_adj_{suf}@test.com',
            email=f'cli_adj_{suf}@test.com',
            password='testpass123',
        )
        cls.cliente = Cliente.objects.create(
            usuario=cls.cliente_user,
            nombre='Cliente',
            apellido='Adj',
            email=cls.cliente_user.email,
        )
        cls.vehiculo = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca,
            modelo=cls.modelo,
            year=2020,
            patente=f'ADJ{suf[:4]}',
            tipo_motor='DIESEL',
        )
        cls.direccion = DireccionUsuario.objects.create(
            usuario=cls.cliente_user,
            direccion='Dir test',
            comuna='Santiago',
            region='RM',
            es_principal=True,
        )

    def _crear_oferta_catalogo(self, oferta_servicio: OfertaServicio) -> OfertaProveedor:
        fd = (timezone.now() + timedelta(days=3)).date()
        solicitud = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            descripcion_problema='Frenos',
            fecha_preferida=timezone.now().date() + timedelta(days=1),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio=Point(-70.6693, -33.4489, srid=4326),
            direccion_servicio_texto='Dir test',
            direccion_usuario=self.direccion,
            estado='pendiente_confirmacion',
            fecha_publicacion=timezone.now(),
        )
        solicitud.servicios_solicitados.add(self.servicio)
        oferta = OfertaProveedor.objects.create(
            solicitud=solicitud,
            proveedor=self.proveedor_user,
            tipo_proveedor='mecanico',
            origen='catalogo',
            oferta_servicio=oferta_servicio,
            metadata_ia={
                'oferta_servicio_id': oferta_servicio.id,
                'oferta_servicio_ids': [oferta_servicio.id],
            },
            precio_total_ofrecido=Decimal('55000'),
            incluye_repuestos=True,
            costo_mano_obra=Decimal('32000'),
            costo_repuestos=Decimal('11000'),
            tiempo_estimado_total=timedelta(hours=2),
            descripcion_oferta='Catálogo',
            fecha_disponible=fd,
            hora_disponible=dt_time(10, 0),
            estado='pendiente_confirmacion',
        )
        detalle = DetalleServicioOferta.objects.create(
            oferta=oferta,
            servicio=self.servicio,
            precio_servicio=Decimal('55000'),
            tiempo_estimado=timedelta(hours=2),
        )
        return oferta, solicitud, detalle

    def test_resolver_usa_metadata_catalogo_con_duplicados(self):
        oferta, solicitud, detalle = self._crear_oferta_catalogo(self.oferta_diesel)
        resolved = adjudicacion_publica.resolver_oferta_servicio_para_detalle(
            oferta=oferta,
            detalle=detalle,
            tipo_proveedor='mecanico',
            taller=None,
            mecanico=self.mecanico,
            solicitud=solicitud,
        )
        self.assertEqual(resolved.id, self.oferta_diesel.id)

    @patch('mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay')
    @patch('mecanimovilapp.apps.suscripciones.creditos_services.consumir_creditos_adjudicacion')
    def test_confirmar_catalogo_adjudica_con_multiples_ofertas_servicio(self, _consumir, _push):
        CreditoProveedor.objects.create(proveedor=self.proveedor_user, saldo_creditos=50)
        oferta, solicitud, detalle = self._crear_oferta_catalogo(self.oferta_diesel)

        carrito_id = adjudicacion_publica.ejecutar_finalizacion_adjudicacion(
            solicitud,
            oferta,
            None,
            self.mecanico,
            [detalle],
        )

        self.assertIsNotNone(carrito_id)
        solicitud.refresh_from_db()
        oferta.refresh_from_db()
        self.assertEqual(solicitud.estado, 'adjudicada')
        self.assertEqual(oferta.estado, 'aceptada')

    def test_confirmar_catalogo_sin_creditos_hard_gate_no_muta_estados(self):
        """Sin saldo: error 402-equivalente, estados siguen pendiente_confirmacion."""
        CreditoProveedor.objects.create(proveedor=self.proveedor_user, saldo_creditos=0)
        oferta, solicitud, _detalle = self._crear_oferta_catalogo(self.oferta_diesel)

        with self.assertRaises(ConfirmacionCatalogoError) as ctx:
            adjudicar_oferta_catalogo_confirmada(oferta)

        err = ctx.exception
        self.assertEqual(err.code, 'creditos_insuficientes')
        self.assertEqual(err.status_code, 402)
        self.assertTrue(err.extra.get('puede_rechazar'))
        self.assertGreater(err.extra.get('creditos_necesarios', 0), 0)

        solicitud.refresh_from_db()
        oferta.refresh_from_db()
        self.assertEqual(solicitud.estado, 'pendiente_confirmacion')
        self.assertEqual(oferta.estado, 'pendiente_confirmacion')
        self.assertIsNone(solicitud.oferta_seleccionada_id)
        self.assertIsNone(solicitud.fecha_limite_confirmacion_creditos)

    def test_liberar_reserva_creditos_catalogo_cancela(self):
        CreditoProveedor.objects.create(proveedor=self.proveedor_user, saldo_creditos=0)
        oferta, solicitud, _detalle = self._crear_oferta_catalogo(self.oferta_diesel)
        oferta.estado = 'pendiente_creditos'
        oferta.save(update_fields=['estado'])
        solicitud.estado = 'esperando_creditos_proveedor'
        solicitud.oferta_seleccionada = oferta
        solicitud.fecha_limite_confirmacion_creditos = timezone.now() + timedelta(hours=24)
        solicitud.save(
            update_fields=[
                'estado',
                'oferta_seleccionada',
                'fecha_limite_confirmacion_creditos',
                'fecha_actualizacion',
            ]
        )

        with patch('mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay'):
            result = adjudicacion_publica.liberar_reserva_creditos_proveedor(
                oferta.id,
                self.proveedor_user.id,
                motivo='sin saldo',
            )

        self.assertTrue(result['ok'])
        self.assertEqual(result['estado_solicitud'], 'cancelada')
        solicitud.refresh_from_db()
        oferta.refresh_from_db()
        self.assertEqual(solicitud.estado, 'cancelada')
        self.assertEqual(oferta.estado, 'rechazada')
        self.assertIsNone(solicitud.oferta_seleccionada_id)

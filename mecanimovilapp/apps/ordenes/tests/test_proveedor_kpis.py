"""Tests: KPIs de rendimiento del taller (proveedor)."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import (
    OfertaProveedor,
    RechazoSolicitud,
    SolicitudServicio,
    SolicitudServicioPublica,
)
from mecanimovilapp.apps.ordenes.services.kpi_constants import (
    PENALIZACION_RECHAZOS_RECIENTES_UMBRAL,
    SLA_ACEPTACION_ORDEN_MINUTOS,
)
from mecanimovilapp.apps.ordenes.services.kpi_scoring import (
    RechazoEvento,
    aplicar_multiplicador_rechazos_recientes,
    compute_score_aceptacion_ordenes,
    score_confiabilidad_from_eventos,
    score_tiempo_aceptacion_minutos,
)
from mecanimovilapp.apps.ordenes.services.proveedor_kpis import compute_proveedor_kpis_resumen
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.usuarios.models import Cliente, DireccionUsuario, Taller
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()


class KpiScoringUnitTests(TestCase):
    def test_aceptacion_menos_24h_puntua_alto(self):
        self.assertEqual(score_tiempo_aceptacion_minutos(60), 96)
        self.assertEqual(score_tiempo_aceptacion_minutos(SLA_ACEPTACION_ORDEN_MINUTOS), 0)

    def test_confiabilidad_baja_con_rechazo_reciente(self):
        ahora = timezone.now()
        score, _ = score_confiabilidad_from_eventos([
            RechazoEvento(fecha=ahora - timedelta(hours=1), severidad=1.0),
        ])
        self.assertLess(score, 100)

    def test_multiplicador_tres_rechazos_7d(self):
        base = 80
        score, mult = aplicar_multiplicador_rechazos_recientes(
            base,
            PENALIZACION_RECHAZOS_RECIENTES_UMBRAL,
        )
        self.assertEqual(mult, 0.85)
        self.assertEqual(score, 68)


class ProveedorKpisIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.proveedor_user = User.objects.create_user(
            username='prov_kpi@test.com',
            email='prov_kpi@test.com',
            password='x',
        )
        cls.taller = Taller.objects.create(
            usuario=cls.proveedor_user,
            nombre='Taller KPI',
            verificado=True,
            activo=True,
        )

        cliente_user = User.objects.create_user(
            username='cli_kpi@test.com',
            email='cli_kpi@test.com',
            password='x',
        )
        cls.cliente = Cliente.objects.create(
            usuario=cliente_user,
            nombre='Cliente',
            email='cli_kpi@test.com',
        )
        marca = Marca.objects.create(nombre='Toy KPI')
        modelo = Modelo.objects.create(nombre='Cor KPI', marca=marca)
        cls.vehiculo = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=marca,
            modelo=modelo,
            year=2020,
            patente='KPI100',
        )
        cls.servicio = Servicio.objects.create(
            nombre='Cambio aceite KPI',
            descripcion='d',
            precio_referencia=Decimal('15000'),
        )
        cls.direccion = DireccionUsuario.objects.create(
            usuario=cliente_user,
            direccion='Dir',
            comuna='Santiago',
            region='RM',
            es_principal=True,
        )
        cls.sol_publica = SolicitudServicioPublica.objects.create(
            cliente=cls.cliente,
            vehiculo=cls.vehiculo,
            descripcion_problema='test',
            fecha_preferida=timezone.now().date(),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6693 -33.4489)',
            direccion_servicio_texto='Dir',
            direccion_usuario=cls.direccion,
            estado='con_ofertas',
            fecha_publicacion=timezone.now() - timedelta(days=2),
        )
        cls.sol_publica.servicios_solicitados.add(cls.servicio)
        cls.oferta = OfertaProveedor.objects.create(
            solicitud=cls.sol_publica,
            proveedor=cls.proveedor_user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('30000'),
            incluye_repuestos=False,
            tiempo_estimado_total=timedelta(hours=2),
            descripcion_oferta='oferta',
            fecha_disponible=timezone.now().date() + timedelta(days=3),
            hora_disponible=time(10, 0),
            estado='aceptada',
            fecha_envio=timezone.now() - timedelta(days=1),
        )

    def _crear_orden_respondida(self, *, horas_respuesta: float, estado: str) -> SolicitudServicio:
        inicio = timezone.now() - timedelta(hours=horas_respuesta + 1)
        respuesta = timezone.now() - timedelta(hours=1)
        return SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            oferta_proveedor=self.oferta,
            tipo_servicio='taller',
            fecha_servicio=timezone.localdate(),
            hora_servicio=time(10, 0),
            metodo_pago='transferencia',
            total=Decimal('30000'),
            estado=estado,
            fecha_hora_solicitud=inicio,
            fecha_pendiente_aceptacion_proveedor=inicio,
            fecha_respuesta_proveedor=respuesta,
        )

    def test_aceptacion_rapida_mejor_que_lenta(self):
        self._crear_orden_respondida(horas_respuesta=0.5, estado='aceptada_por_proveedor')

        kpis_rapido = compute_proveedor_kpis_resumen(self.proveedor_user, dias=30)
        self.assertIsNotNone(kpis_rapido['score_aceptacion_ordenes'])
        self.assertGreater(kpis_rapido['score_aceptacion_ordenes'], 90)

        SolicitudServicio.objects.all().delete()
        inicio = timezone.now() - timedelta(hours=30)
        respuesta = timezone.now() - timedelta(hours=2)
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            oferta_proveedor=self.oferta,
            tipo_servicio='taller',
            fecha_servicio=timezone.localdate(),
            hora_servicio=time(10, 0),
            metodo_pago='transferencia',
            total=Decimal('30000'),
            estado='aceptada_por_proveedor',
            fecha_hora_solicitud=inicio,
            fecha_pendiente_aceptacion_proveedor=inicio,
            fecha_respuesta_proveedor=respuesta,
        )
        kpis_lento = compute_proveedor_kpis_resumen(self.proveedor_user, dias=30)
        self.assertLess(
            kpis_lento['score_aceptacion_ordenes'],
            kpis_rapido['score_aceptacion_ordenes'],
        )

    def test_rechazo_orden_baja_confiabilidad(self):
        self._crear_orden_respondida(horas_respuesta=1, estado='rechazada_por_proveedor')
        kpis = compute_proveedor_kpis_resumen(self.proveedor_user, dias=30)
        self.assertLess(kpis['score_confiabilidad'], 100)
        self.assertEqual(kpis['score_aceptacion_ordenes'], 0)

    def test_multiplicador_tres_rechazos_recientes(self):
        ahora = timezone.now()
        for _ in range(PENALIZACION_RECHAZOS_RECIENTES_UMBRAL):
            self._crear_orden_respondida(horas_respuesta=1, estado='rechazada_por_proveedor')

        kpis = compute_proveedor_kpis_resumen(self.proveedor_user, dias=30)
        self.assertGreaterEqual(kpis['rechazos_ultimos_7_dias'], PENALIZACION_RECHAZOS_RECIENTES_UMBRAL)
        self.assertEqual(kpis['multiplicador_penalizacion'], 0.85)
        self.assertLess(kpis['score_rendimiento'], kpis['score_rendimiento_base'])

    def test_compute_score_aceptacion_ordenes_rechazo_cuenta_cero(self):
        orden = self._crear_orden_respondida(horas_respuesta=1, estado='rechazada_por_proveedor')
        qs = SolicitudServicio.objects.filter(pk=orden.pk)
        score, _, n = compute_score_aceptacion_ordenes(qs)
        self.assertEqual(score, 0)
        self.assertEqual(n, 1)

    def test_rechazo_solicitud_publica_penaliza_confiabilidad(self):
        RechazoSolicitud.objects.create(
            solicitud=self.sol_publica,
            proveedor=self.proveedor_user,
            tipo_proveedor='taller',
            motivo='ocupado',
        )
        kpis = compute_proveedor_kpis_resumen(self.proveedor_user, dias=30)
        self.assertGreater(kpis['rechazos_periodo'], 0)
        self.assertLess(kpis['score_confiabilidad'], 100)

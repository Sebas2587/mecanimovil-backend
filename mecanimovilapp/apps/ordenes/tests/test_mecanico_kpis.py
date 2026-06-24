"""Tests: KPIs de rendimiento por mecánico del taller."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.ordenes.services.mecanico_kpis import compute_mecanico_kpis
from mecanimovilapp.apps.usuarios.models import Cliente, MiembroTaller, Taller
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()


class MecanicoKpisMetricasTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoy = timezone.localdate()

        cliente_user = User.objects.create_user(
            username='cliente_kpi@test.com',
            email='cliente_kpi@test.com',
            password='x',
        )
        cls.cliente = Cliente.objects.create(
            usuario=cliente_user,
            nombre='Cliente KPI',
            email='cliente_kpi@test.com',
        )

        marca = Marca.objects.create(nombre='Kia KPI')
        modelo = Modelo.objects.create(nombre='Rio KPI', marca=marca)
        cls.vehiculo = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=marca,
            modelo=modelo,
            year=2021,
            patente='KPI001',
        )

        taller_user = User.objects.create_user(
            username='taller_kpi@test.com',
            email='taller_kpi@test.com',
            password='x',
        )
        cls.taller = Taller.objects.create(
            usuario=taller_user,
            nombre='Taller KPI Test',
            verificado=True,
            activo=True,
        )
        cls.mecanico = MiembroTaller.objects.create(
            taller=cls.taller,
            rol='mecanico',
            nombre='Donal Jose',
            modalidad_tecnico='ambas',
            activo=True,
        )

    def _crear_orden(self, *, estado: str, total: Decimal = Decimal('50000')) -> SolicitudServicio:
        return SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            tipo_servicio='taller',
            mecanico_asignado=self.mecanico,
            fecha_servicio=self.hoy,
            hora_servicio=time(10, 0),
            metodo_pago='transferencia',
            total=total,
            estado=estado,
        )

    def test_completada_sin_checklist_cuenta_en_totales_no_en_con_checklist(self):
        self._crear_orden(estado='completado')

        kpis = compute_mecanico_kpis(self.mecanico, dias=30)

        self.assertEqual(kpis['servicios_completados_totales'], 1)
        self.assertEqual(kpis['servicios_completados'], 1)
        self.assertEqual(kpis['servicios_completados_con_checklist'], 0)
        self.assertEqual(kpis['ordenes_mecanimovil'], 1)

    def test_rechazada_incrementa_servicios_rechazados(self):
        self._crear_orden(estado='rechazada_por_proveedor')

        kpis = compute_mecanico_kpis(self.mecanico, dias=30)

        self.assertEqual(kpis['servicios_rechazados'], 1)
        self.assertEqual(kpis['servicios_completados_totales'], 0)

    def test_facturacion_incluye_completadas_sin_checklist(self):
        self._crear_orden(estado='completado', total=Decimal('75000'))

        kpis = compute_mecanico_kpis(self.mecanico, dias=30)

        self.assertEqual(kpis['facturacion_periodo'], 75000)
        self.assertEqual(kpis['servicios_completados_con_checklist'], 0)

    def _crear_orden_mkt(self, **kwargs) -> SolicitudServicio:
        defaults = {
            'cliente': self.cliente,
            'vehiculo': self.vehiculo,
            'taller': self.taller,
            'tipo_servicio': 'taller',
            'mecanico_asignado': self.mecanico,
            'fecha_servicio': self.hoy,
            'hora_servicio': time(10, 0),
            'metodo_pago': 'transferencia',
            'total': Decimal('50000'),
        }
        defaults.update(kwargs)
        return SolicitudServicio.objects.create(**defaults)

    def test_rechazo_baja_score_confiabilidad(self):
        inicio = timezone.now() - timedelta(hours=2)
        self._crear_orden_mkt(
            estado='rechazada_por_proveedor',
            oferta_proveedor=None,
            fecha_pendiente_aceptacion_proveedor=inicio,
            fecha_respuesta_proveedor=timezone.now() - timedelta(hours=1),
        )

        kpis = compute_mecanico_kpis(self.mecanico, dias=30)

        self.assertLess(kpis['score_confiabilidad'], 100)
        self.assertGreater(kpis['rechazos_periodo'], 0)

    def test_resena_en_orden_asignada_entra_al_score(self):
        from mecanimovilapp.apps.usuarios.models import Resena

        orden = self._crear_orden_mkt(estado='completado')
        Resena.objects.create(
            cliente=self.cliente,
            taller=self.taller,
            solicitud=orden,
            calificacion=5,
            comentario='Excelente',
        )

        kpis = compute_mecanico_kpis(self.mecanico, dias=30)

        self.assertEqual(kpis['calificacion_cliente_promedio'], 5.0)
        self.assertEqual(kpis['score_calificacion_cliente'], 100)

    def test_orden_por_fecha_solicitud_cuenta_aunque_servicio_futuro(self):
        """Ventana incluye actividad por fecha_hora_solicitud, no solo fecha_servicio."""
        from datetime import timedelta

        orden = self._crear_orden_mkt(
            estado='aceptada_por_proveedor',
            fecha_servicio=self.hoy + timedelta(days=45),
        )
        orden.fecha_hora_solicitud = timezone.now()
        orden.save(update_fields=['fecha_hora_solicitud'])

        kpis = compute_mecanico_kpis(self.mecanico, dias=30)

        self.assertEqual(kpis['total_asignados'], 1)
        self.assertEqual(kpis['servicios_en_proceso'], 1)

    def test_agenda_personal_no_modifica_score_calidad(self):
        from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle

        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            miembro_taller=self.mecanico,
            estado='cerrada',
            fecha_servicio=self.hoy,
            hora_servicio=time(9, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            creado_por=self.taller.usuario,
            cerrada_en=timezone.now(),
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Cliente particular',
            servicio_nombre='Servicio externo',
        )

        kpis = compute_mecanico_kpis(self.mecanico, dias=30)

        self.assertEqual(kpis['ordenes_personales'], 1)
        self.assertEqual(kpis['servicios_completados_totales'], 0)
        self.assertIsNone(kpis['score_rendimiento_global'])

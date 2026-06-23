"""Tests: KPIs de rendimiento por mecánico del taller."""
from datetime import time
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

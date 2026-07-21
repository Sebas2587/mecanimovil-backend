"""Tests: ganancias del taller (Mecanimovil + agenda personal)."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CitaAgendaPersonalDetalle,
    SolicitudServicio,
)
from mecanimovilapp.apps.ordenes.services.ganancias_taller import (
    compute_ganancias_taller_resumen,
    compute_ganancias_taller_serie,
)
from mecanimovilapp.apps.usuarios.models import Cliente, MiembroTaller, Taller
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()


class GananciasTallerResumenTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoy = timezone.localdate()

        taller_user = User.objects.create_user(
            username='taller_gan@test.com',
            email='taller_gan@test.com',
            password='x',
        )
        cls.taller_user = taller_user
        cls.taller = Taller.objects.create(
            usuario=taller_user,
            nombre='Taller Ganancias',
            verificado=True,
            activo=True,
        )
        cls.mecanico = MiembroTaller.objects.create(
            taller=cls.taller,
            rol='mecanico',
            nombre='Mecánico',
            modalidad_tecnico='ambas',
            activo=True,
        )

        cliente_user = User.objects.create_user(
            username='cli_gan@test.com',
            email='cli_gan@test.com',
            password='x',
        )
        cls.cliente = Cliente.objects.create(
            usuario=cliente_user,
            nombre='Cliente',
            email='cli_gan@test.com',
        )
        marca = Marca.objects.create(nombre='Toy Gan')
        modelo = Modelo.objects.create(nombre='Yaris Gan', marca=marca)
        cls.vehiculo = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=marca,
            modelo=modelo,
            year=2020,
            patente='GAN001',
        )

    def test_suma_mecanimovil_y_agenda_personal_mes_actual(self):
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            mecanico_asignado=self.mecanico,
            tipo_servicio='taller',
            fecha_servicio=self.hoy,
            hora_servicio=time(10, 0),
            metodo_pago='transferencia',
            total=Decimal('80000'),
            estado='completado',
            fecha_hora_solicitud=timezone.now(),
        )

        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            miembro_taller=self.mecanico,
            estado='cerrada',
            fecha_servicio=self.hoy,
            hora_servicio=time(14, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            creado_por=self.taller_user,
            cerrada_en=timezone.now(),
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Particular',
            servicio_nombre='Frenos',
            precio_referencia=Decimal('45000'),
        )

        resumen = compute_ganancias_taller_resumen(self.taller_user)

        self.assertEqual(resumen['ganancias_mecanimovil'], 80000)
        self.assertEqual(resumen['ganancias_agenda_personal'], 45000)
        self.assertEqual(resumen['ganancias_total'], 125000)
        self.assertEqual(resumen['ordenes_mecanimovil'], 1)
        self.assertEqual(resumen['ordenes_agenda_personal'], 1)

    def test_orden_futura_con_solicitud_hoy_cuenta_en_mes(self):
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            tipo_servicio='taller',
            fecha_servicio=self.hoy + timedelta(days=20),
            hora_servicio=time(11, 0),
            metodo_pago='transferencia',
            total=Decimal('60000'),
            estado='completado',
            fecha_hora_solicitud=timezone.now(),
        )

        resumen = compute_ganancias_taller_resumen(self.taller_user)

        self.assertEqual(resumen['ganancias_mecanimovil'], 60000)

    def test_serie_ordenes_cuenta_por_fecha_solicitud_si_servicio_futuro(self):
        """Serie y totales deben coincidir cuando la orden entra por fecha_hora_solicitud."""
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            mecanico_asignado=self.mecanico,
            tipo_servicio='taller',
            fecha_servicio=self.hoy + timedelta(days=45),
            hora_servicio=time(11, 0),
            metodo_pago='transferencia',
            total=Decimal('60000'),
            estado='completado',
            fecha_hora_solicitud=timezone.now(),
        )

        serie = compute_ganancias_taller_serie(
            self.taller_user,
            granularidad='dia',
            metrica='ordenes',
            dias=30,
        )

        self.assertEqual(serie['totales_periodo']['ordenes_mecanimovil'], 1)
        suma_puntos = sum(p['mecanimovil'] for p in serie['puntos'])
        self.assertEqual(suma_puntos, 1)
        hoy_punto = next(p for p in serie['puntos'] if p['clave'] == self.hoy.isoformat())
        self.assertEqual(hoy_punto['mecanimovil'], 1)

    def test_serie_diaria_separa_canales(self):
        ayer = self.hoy - timedelta(days=1)
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            mecanico_asignado=self.mecanico,
            tipo_servicio='taller',
            fecha_servicio=ayer,
            hora_servicio=time(9, 0),
            metodo_pago='transferencia',
            total=Decimal('50000'),
            estado='completado',
            fecha_hora_solicitud=timezone.now(),
        )
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            mecanico_asignado=self.mecanico,
            tipo_servicio='taller',
            fecha_servicio=self.hoy,
            hora_servicio=time(10, 0),
            metodo_pago='transferencia',
            total=Decimal('30000'),
            estado='completado',
            fecha_hora_solicitud=timezone.now(),
        )
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            miembro_taller=self.mecanico,
            estado='cerrada',
            fecha_servicio=self.hoy,
            hora_servicio=time(14, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            creado_por=self.taller_user,
            cerrada_en=timezone.now(),
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Particular',
            servicio_nombre='Aceite',
            precio_referencia=Decimal('20000'),
        )

        serie = compute_ganancias_taller_serie(self.taller_user, granularidad='dia')
        puntos_hoy = [p for p in serie['puntos'] if p['clave'] == self.hoy.isoformat()]
        self.assertEqual(len(puntos_hoy), 1)
        self.assertEqual(puntos_hoy[0]['mecanimovil'], 30000)
        self.assertEqual(puntos_hoy[0]['agenda_personal'], 20000)
        self.assertEqual(serie['pico_mayor']['total'], max(p['total'] for p in serie['puntos']))

    def test_serie_filtra_por_mecanico(self):
        otro = MiembroTaller.objects.create(
            taller=self.taller,
            rol='mecanico',
            nombre='Otro',
            modalidad_tecnico='ambas',
            activo=True,
        )
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            mecanico_asignado=otro,
            tipo_servicio='taller',
            fecha_servicio=self.hoy,
            hora_servicio=time(11, 0),
            metodo_pago='transferencia',
            total=Decimal('99000'),
            estado='completado',
            fecha_hora_solicitud=timezone.now(),
        )
        SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            taller=self.taller,
            mecanico_asignado=self.mecanico,
            tipo_servicio='taller',
            fecha_servicio=self.hoy,
            hora_servicio=time(12, 0),
            metodo_pago='transferencia',
            total=Decimal('10000'),
            estado='completado',
            fecha_hora_solicitud=timezone.now(),
        )

        serie = compute_ganancias_taller_serie(
            self.taller_user,
            granularidad='dia',
            mecanico_id=self.mecanico.id,
        )
        hoy = next(p for p in serie['puntos'] if p['clave'] == self.hoy.isoformat())
        self.assertEqual(hoy['mecanimovil'], 10000)

    def test_serie_serializer_acepta_etiquetas_vacias(self):
        from mecanimovilapp.apps.ordenes.serializers import GananciasTallerSerieSerializer

        serie = compute_ganancias_taller_serie(self.taller_user, granularidad='dia')
        self.assertTrue(any(p['etiqueta'] == '' for p in serie['puntos']))

        serializer = GananciasTallerSerieSerializer(data=serie)
        self.assertTrue(serializer.is_valid(), serializer.errors)

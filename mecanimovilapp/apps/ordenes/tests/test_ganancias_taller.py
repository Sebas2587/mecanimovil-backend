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
from mecanimovilapp.apps.ordenes.services.ganancias_taller import compute_ganancias_taller_resumen
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

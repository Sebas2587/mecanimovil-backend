"""
Tests: citas agenda personal y bloqueo de disponibilidad.
"""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle
from mecanimovilapp.apps.usuarios.models import HorarioProveedor, Taller
from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import intervalos_ocupados_dia

User = get_user_model()


class CitaAgendaPersonalModelTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='prov_cita', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Test Cita',
            telefono='900000000',
            estado_verificacion='aprobado',
        )
        HorarioProveedor.objects.create(
            taller=self.taller,
            dia_semana=0,
            activo=True,
            hora_inicio=time(8, 0),
            hora_fin=time(18, 0),
            duracion_slot=60,
        )

    def _crear_cita(self, estado='activa', hora=time(10, 0)):
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            fecha_servicio=date(2030, 6, 17),
            hora_servicio=hora,
            duracion_minutos=60,
            tipo_servicio='taller',
            estado=estado,
            creado_por=self.user,
            cerrada_en=timezone.now() if estado == 'cerrada' else None,
            cancelada_en=timezone.now() if estado == 'cancelada' else None,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Juan Pérez',
            cliente_telefono='+56912345678',
            vehiculo_marca='Toyota',
            vehiculo_modelo='Corolla',
            vehiculo_patente='AA1234',
            servicio_nombre='Cambio aceite',
        )
        return cita

    def test_activa_bloquea_intervalos(self):
        self._crear_cita(estado='activa', hora=time(10, 0))
        intervalos = intervalos_ocupados_dia(
            taller=self.taller,
            fecha=date(2030, 6, 17),
        )
        self.assertTrue(len(intervalos) >= 1)

    def test_cerrada_no_bloquea(self):
        self._crear_cita(estado='cerrada', hora=time(10, 0))
        intervalos = intervalos_ocupados_dia(
            taller=self.taller,
            fecha=date(2030, 6, 17),
        )
        self.assertEqual(intervalos, [])

    def test_delete_solo_cancelada(self):
        activa = self._crear_cita(estado='activa')
        with self.assertRaises(Exception):
            activa.delete()

        cancelada = self._crear_cita(estado='cancelada', hora=time(11, 0))
        pk = cancelada.pk
        cancelada.delete()
        self.assertFalse(CitaAgendaPersonal.objects.filter(pk=pk).exists())


class CitaAgendaPersonalAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='prov_api', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller API',
            telefono='900000001',
            estado_verificacion='aprobado',
        )
        # 2030-06-17 is Tuesday -> weekday 1
        HorarioProveedor.objects.create(
            taller=self.taller,
            dia_semana=1,
            activo=True,
            hora_inicio=time(8, 0),
            hora_fin=time(18, 0),
        )
        self.client.force_authenticate(user=self.user)

    def test_crear_cerrar_cancelar_eliminar(self):
        payload = {
            'fecha_servicio': '2030-06-18',
            'hora_servicio': '10:00:00',
            'tipo_servicio': 'taller',
            'detalle': {
                'cliente_nombre': 'María López',
                'cliente_telefono': '+56987654321',
                'vehiculo_marca': 'Nissan',
                'vehiculo_modelo': 'Versa',
                'vehiculo_patente': 'BB5678',
                'servicio_nombre': 'Frenos',
            },
        }
        res = self.client.post('/api/ordenes/citas-agenda-personal/', payload, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        cita_id = res.data['id']

        res_cerrar = self.client.post(f'/api/ordenes/citas-agenda-personal/{cita_id}/cerrar/')
        self.assertEqual(res_cerrar.status_code, 200)
        self.assertEqual(res_cerrar.data['estado'], 'cerrada')

        res2 = self.client.post('/api/ordenes/citas-agenda-personal/', payload, format='json')
        cita2_id = res2.data['id']
        res_cancel = self.client.post(f'/api/ordenes/citas-agenda-personal/{cita2_id}/cancelar/')
        self.assertEqual(res_cancel.status_code, 200)

        res_del_ok = self.client.delete(f'/api/ordenes/citas-agenda-personal/{cita2_id}/')
        self.assertEqual(res_del_ok.status_code, 204)

        res_del_fail = self.client.delete(f'/api/ordenes/citas-agenda-personal/{cita_id}/')
        self.assertEqual(res_del_fail.status_code, 409)

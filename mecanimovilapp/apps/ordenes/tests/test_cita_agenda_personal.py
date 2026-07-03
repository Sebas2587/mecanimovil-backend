"""
Tests: citas agenda personal y bloqueo de disponibilidad.
"""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle
from mecanimovilapp.apps.usuarios.models import HorarioProveedor, MiembroTaller, Taller
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


class CitaAgendaPersonalMecanicoEquipoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        owner = User.objects.create_user(username='owner_cita', password='test123')
        self.taller = Taller.objects.create(
            usuario=owner,
            nombre='Taller Equipo',
            telefono='900000002',
            estado_verificacion='aprobado',
        )

        self.mecanico_a = MiembroTaller.objects.create(
            taller=self.taller,
            rol='mecanico',
            nombre='Mecánico A',
            activo=True,
        )
        self.mecanico_b = MiembroTaller.objects.create(
            taller=self.taller,
            rol='mecanico',
            nombre='Mecánico B',
            activo=True,
        )

        self.user_mecanico = User.objects.create_user(username='mec_cita', password='test123')
        self.mecanico_a.usuario = self.user_mecanico
        self.mecanico_a.save(update_fields=['usuario'])

    def _crear_cita(self, miembro: MiembroTaller, hora=time(10, 0)):
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            miembro_taller=miembro,
            fecha_servicio=date(2030, 6, 17),
            hora_servicio=hora,
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            creado_por=self.taller.usuario,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Cliente Test',
            cliente_telefono='+56911111111',
            vehiculo_marca='Toyota',
            vehiculo_modelo='Yaris',
            servicio_nombre='Diagnóstico',
        )
        return cita

    def test_mecanico_equipo_solo_ve_sus_citas_asignadas(self):
        cita_propia = self._crear_cita(self.mecanico_a, hora=time(10, 0))
        self._crear_cita(self.mecanico_b, hora=time(11, 0))

        self.client.force_authenticate(user=self.user_mecanico)
        res = self.client.get('/api/ordenes/citas-agenda-personal/?estado=activa')
        self.assertEqual(res.status_code, 200, res.content)

        ids = [item['id'] for item in res.data]
        self.assertEqual(ids, [cita_propia.id])

    def test_mecanico_equipo_no_puede_ver_cita_de_otro(self):
        cita_otro = self._crear_cita(self.mecanico_b)

        self.client.force_authenticate(user=self.user_mecanico)
        res = self.client.get(f'/api/ordenes/citas-agenda-personal/{cita_otro.id}/')
        self.assertEqual(res.status_code, 404, res.content)

    def test_mecanico_equipo_no_puede_editar_ni_eliminar_cita(self):
        cita = self._crear_cita(self.mecanico_a)
        cita.cancelar()
        cita.save(update_fields=['estado', 'cancelada_en', 'fecha_actualizacion'])

        self.client.force_authenticate(user=self.user_mecanico)
        res_patch = self.client.patch(
            f'/api/ordenes/citas-agenda-personal/{cita.id}/',
            {'detalle': {'cliente_nombre': 'Otro nombre'}},
            format='json',
        )
        self.assertEqual(res_patch.status_code, 403, res_patch.content)

        res_del = self.client.delete(f'/api/ordenes/citas-agenda-personal/{cita.id}/')
        self.assertEqual(res_del.status_code, 403, res_del.content)

    def test_mecanico_equipo_puede_consultar_asistente_ia_cita(self):
        cita = self._crear_cita(self.mecanico_a)
        self.client.force_authenticate(user=self.user_mecanico)
        res = self.client.get(f'/api/ordenes/citas-agenda-personal/{cita.id}/asistente-ia/')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(res.data['disponible'])
        self.assertIsNone(res.data['contenido'])

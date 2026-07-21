"""Tests: cierre de cita personal cuando el checklist ya está COMPLETADO."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.checklists.models import ChecklistInstance, ChecklistTemplate
from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle
from mecanimovilapp.apps.ordenes.services.cita_cierre_sync import (
    asegurar_cierre_cita_si_checklist_completo,
)
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class CitaCierreSyncTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sync_cita', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Sync',
            telefono='900000099',
            estado_verificacion='aprobado',
        )
        self.servicio = Servicio.objects.create(nombre='Diagnóstico sync test')
        self.template = ChecklistTemplate.objects.create(
            nombre='Tpl sync',
            servicio=self.servicio,
        )
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            fecha_servicio=date(2030, 7, 20),
            hora_servicio=time(15, 45),
            duracion_minutos=60,
            tipo_servicio='domicilio',
            estado='activa',
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=self.cita,
            cliente_nombre='Radamel falcao',
            cliente_telefono='+56911111111',
            vehiculo_marca='FIAT',
            vehiculo_modelo='BRAVO',
            vehiculo_patente='ZZ9999',
            servicio_nombre='Diagnóstico mecánico Diesel',
        )

    def _checklist(self, **kwargs):
        defaults = {
            'cita_personal': self.cita,
            'checklist_template': self.template,
            'estado': 'COMPLETADO',
            'firma_tecnico': 'firma-tecnico-b64',
            'firma_supervisor': 'firma-supervisor-b64',
            'firma_cliente': 'firma-cliente-b64',
            'progreso_porcentaje': 100,
        }
        defaults.update(kwargs)
        return ChecklistInstance.objects.create(**defaults)

    def test_cierra_cita_activa_con_checklist_completo_y_firmas(self):
        self._checklist()
        closed = asegurar_cierre_cita_si_checklist_completo(self.cita)
        self.assertTrue(closed)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, 'cerrada')
        self.assertIsNotNone(self.cita.cerrada_en)

    def test_no_cierra_sin_firma_cliente_en_taller(self):
        self._checklist(firma_cliente=None)
        closed = asegurar_cierre_cita_si_checklist_completo(self.cita)
        self.assertFalse(closed)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, 'activa')

    def test_idempotente_si_ya_cerrada(self):
        self._checklist()
        self.assertTrue(asegurar_cierre_cita_si_checklist_completo(self.cita))
        self.assertFalse(asegurar_cierre_cita_si_checklist_completo(self.cita))

    def test_endpoint_cerradas_repara_desfase(self):
        from rest_framework.test import APIClient

        self._checklist()
        client = APIClient()
        client.force_authenticate(user=self.user)
        res = client.get('/api/ordenes/citas-agenda-personal/cerradas/')
        self.assertEqual(res.status_code, 200, res.content)
        ids = {row['id'] for row in res.data}
        self.assertIn(self.cita.id, ids)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, 'cerrada')

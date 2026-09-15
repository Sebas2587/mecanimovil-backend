"""Aviso al cliente cuando el taller confirma día y hora."""
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from mecanimovilapp.apps.ordenes.services.aviso_cita_cliente import (
    avisar_cliente_cita_agendada,
    formatear_slot_cita_cliente,
    texto_cita_agendada_cliente,
)


def _cita(*, conversation=None):
    return SimpleNamespace(
        pk=3,
        id=3,
        conversation_origen=conversation,
        cotizacion_canal_origen=None,
        detalle=SimpleNamespace(servicio_nombre='Kit de embrague'),
        taller=SimpleNamespace(nombre='Taller Aviso Cita'),
        fecha_servicio=date(2030, 9, 16),
        hora_servicio=time(10, 30),
    )


class AvisoClienteCitaAgendadaTests(SimpleTestCase):
    def test_formatea_fecha_hora_y_taller(self):
        cita = _cita()
        slot = formatear_slot_cita_cliente(cita)
        self.assertIn('10:30', slot)
        texto = texto_cita_agendada_cliente(cita)
        self.assertIn('Kit de embrague', texto)
        self.assertIn('Taller Aviso Cita', texto)
        self.assertIn('10:30', texto)

    def test_sin_conversacion_no_falla(self):
        cita = _cita(conversation=None)
        qs = MagicMock()
        qs.select_related.return_value.filter.return_value.first.return_value = cita
        with patch(
            'mecanimovilapp.apps.ordenes.models.CitaAgendaPersonal.objects',
            qs,
        ):
            res = avisar_cliente_cita_agendada(cita, user=SimpleNamespace(id=1))
        self.assertFalse(res['enviado'])
        self.assertEqual(res['via'], 'sin_canal')

    def _entregar(self, *, conversation, ventana_abierta: bool, delay_mock):
        user = SimpleNamespace(id=1, first_name='Ana', last_name='Taller', username='ana')
        cita = _cita(conversation=conversation)
        qs = MagicMock()
        qs.select_related.return_value.filter.return_value.first.return_value = cita
        created = MagicMock()
        created.channel_metadata = {}
        created.sender = user
        created.content = 'aviso'
        created.id = 11
        created.timestamp = timezone.now()
        created.sender_id = user.id
        with patch(
            'mecanimovilapp.apps.ordenes.models.CitaAgendaPersonal.objects',
            qs,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.aviso_cita_cliente.Message.objects.create',
            return_value=created,
        ), patch(
            'mecanimovilapp.apps.omnichannel.services.outbound_guard.customer_care_window_open',
            return_value=ventana_abierta,
        ), patch(
            'mecanimovilapp.apps.omnichannel.services.outbound_guard.connection_activa',
            return_value=object(),
        ), patch(
            'mecanimovilapp.apps.omnichannel.services.broadcast.broadcast_to_participants',
        ), patch(
            'mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay',
            delay_mock,
        ):
            return avisar_cliente_cita_agendada(cita, user=user), created

    def test_aviso_en_sesion_abierta(self):
        conversation = MagicMock()
        conversation.source_channel = 'WHATSAPP'
        conversation.id = 9
        conversation.external_contact = None
        conversation.participants.all.return_value = []
        delay = MagicMock()
        res, _created = self._entregar(
            conversation=conversation,
            ventana_abierta=True,
            delay_mock=delay,
        )
        self.assertTrue(res['enviado'])
        self.assertEqual(res['via'], 'sesion_meta')
        delay.assert_called_once()

    @override_settings(
        WHATSAPP_TEMPLATES_ENABLED=True,
        WHATSAPP_TEMPLATE_CITA='cita_recordatorio',
    )
    def test_aviso_usa_plantilla_si_ventana_cerrada(self):
        conversation = MagicMock()
        conversation.source_channel = 'WHATSAPP'
        conversation.id = 9
        conversation.external_contact = None
        conversation.participants.all.return_value = []
        delay = MagicMock()
        res, created = self._entregar(
            conversation=conversation,
            ventana_abierta=False,
            delay_mock=delay,
        )
        self.assertTrue(res['enviado'])
        self.assertEqual(res['via'], 'whatsapp_template')
        delay.assert_called_once()
        self.assertTrue((created.channel_metadata or {}).get('whatsapp_template'))

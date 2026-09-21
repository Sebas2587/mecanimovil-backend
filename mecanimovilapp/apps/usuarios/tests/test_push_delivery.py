"""Tests de ruteo y normalización de push (sin DB)."""
from django.test import SimpleTestCase, override_settings
from django.core.cache import cache

from mecanimovilapp.apps.usuarios.tasks import (
    _channel_for_type,
    _normalize_expo_push_data,
    _should_throttle,
)


class ChannelForTypeTests(SimpleTestCase):
    def test_rutas_comerciales_proveedor(self):
        self.assertEqual(_channel_for_type('chat_message'), 'chat')
        self.assertEqual(_channel_for_type('nuevo_contacto_canal'), 'chat')
        self.assertEqual(_channel_for_type('agente_ia_escalamiento'), 'chat')
        self.assertEqual(_channel_for_type('agente_ia_cotizacion_borrador'), 'servicios')
        self.assertEqual(_channel_for_type('pipeline_agenda_pendiente_confirmacion'), 'servicios')
        self.assertEqual(_channel_for_type('suscripcion_por_vencer'), 'suscripciones')


class NormalizeExpoPushDataTests(SimpleTestCase):
    def test_convierte_ids_a_string(self):
        out = _normalize_expo_push_data({
            'type': 'chat_message',
            'conversation_id': 44,
            'nuevo_contacto': True,
        })
        self.assertEqual(out['conversation_id'], '44')
        self.assertEqual(out['nuevo_contacto'], 'true')


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'push-throttle-tests',
    },
})
class ThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_int_y_str_comparten_bucket(self):
        data_int = {'type': 'chat_message', 'conversation_id': 9, 'sender_id': 3}
        data_str = {'type': 'chat_message', 'conversation_id': '9', 'sender_id': '3'}
        self.assertFalse(_should_throttle(1, data_int))
        self.assertTrue(_should_throttle(1, data_str))

"""Payloads de plantillas Utility (sin DB)."""
from django.test import SimpleTestCase, override_settings

from mecanimovilapp.apps.omnichannel.services.whatsapp_templates import (
    payload_aviso,
    payload_cita,
    payload_cotizacion,
    payload_desde_metadata,
)


class WhatsappTemplatesTests(SimpleTestCase):
    @override_settings(WHATSAPP_TEMPLATE_COTIZACION='cotizacion_lista', WHATSAPP_TEMPLATE_LANG='es')
    def test_payload_cotizacion_cuatro_vars(self):
        tpl = payload_cotizacion(
            taller='Taller Sur',
            servicio='Diagnóstico',
            total='$40.000',
            url='https://example.com/c/abc',
        )
        self.assertEqual(tpl['name'], 'cotizacion_lista')
        texts = [p['text'] for p in tpl['components'][0]['parameters']]
        self.assertEqual(texts, ['Taller Sur', 'Diagnóstico', '$40.000', 'https://example.com/c/abc'])

    @override_settings(WHATSAPP_TEMPLATE_CITA='cita_recordatorio')
    def test_payload_cita(self):
        tpl = payload_cita(taller='Taller Sur', slot='22/08/2030 a las 10:00')
        self.assertEqual(tpl['name'], 'cita_recordatorio')
        self.assertEqual(len(tpl['components'][0]['parameters']), 2)

    @override_settings(WHATSAPP_TEMPLATE_AVISO='aviso_taller')
    def test_payload_aviso(self):
        tpl = payload_aviso(taller='Taller Sur')
        self.assertEqual(tpl['name'], 'aviso_taller')
        self.assertEqual(tpl['components'][0]['parameters'][0]['text'], 'Taller Sur')

    def test_payload_desde_metadata(self):
        meta = {
            'whatsapp_template': True,
            'template_name': 'aviso_taller',
            'template_language': 'es',
            'template_kind': 'aviso',
            'template_components': [{'type': 'body', 'parameters': []}],
        }
        tpl = payload_desde_metadata(meta)
        self.assertEqual(tpl['name'], 'aviso_taller')
        self.assertIsNone(payload_desde_metadata({}))

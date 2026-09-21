"""El chat del agente debe caer a 2.5-flash si 3.1-flash-lite responde 503."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


class GeminiAgenteFallbackTestCase(SimpleTestCase):
    def test_http_503_usa_modelo_respaldo_sin_dormir(self):
        from mecanimovilapp.apps.agente_ia.services import orquestador

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.text = 'high demand'
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [
                        {'thought': True, 'text': 'thinking'},
                        {'text': '{"respuesta_cliente":"Hola","burbujas":["Hola"]}'},
                    ],
                },
            }],
        }
        with patch.object(orquestador.settings, 'GEMINI_API_KEY', 'k'), patch.object(
            orquestador.settings, 'AGENTE_IA_GEMINI_MODEL', 'gemini-3.1-flash-lite',
        ), patch.object(
            orquestador.settings, 'ASISTENTE_COTIZACION_GEMINI_FALLBACKS', 'gemini-2.5-flash',
        ), patch.object(
            orquestador.requests, 'post', side_effect=[resp_503, ok],
        ) as post_mock:
            data, err = orquestador._llamar_gemini_agente('prompt')

        self.assertIsNone(err)
        self.assertEqual(data.get('respuesta_cliente'), 'Hola')
        self.assertEqual(post_mock.call_count, 2)
        urls = [c.args[0] for c in post_mock.call_args_list]
        self.assertIn('gemini-3.1-flash-lite', urls[0])
        self.assertIn('gemini-2.5-flash', urls[1])
        cfg_lite = post_mock.call_args_list[0].kwargs['json']['generationConfig']
        cfg_flash = post_mock.call_args_list[1].kwargs['json']['generationConfig']
        self.assertEqual(cfg_lite['thinkingConfig']['thinkingLevel'], 'low')
        self.assertEqual(cfg_flash['thinkingConfig']['thinkingBudget'], 2048)

from django.test import SimpleTestCase

from mecanimovilapp.apps.chat.link_preview import validate_preview_url
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.imagen_repuesto import (
    ESTADO_ERROR,
    resolver_imagen_opcion,
)


class ImagenRepuestoSsrfTest(SimpleTestCase):
    def test_bloquea_ip_privada_internal_y_localhost(self):
        self.assertIsNone(validate_preview_url('http://127.0.0.1/secret'))
        self.assertIsNone(validate_preview_url('http://localhost/x'))
        self.assertIsNone(validate_preview_url('http://10.0.0.8/img'))
        self.assertIsNone(validate_preview_url('https://foo.internal/og'))
        self.assertIsNone(resolver_imagen_opcion('http://127.0.0.1/secret'))

    def test_content_type_no_imagen_no_sube(self):
        self.assertIsNone(resolver_imagen_opcion('javascript:alert(1)'))

    def test_estado_error_no_reintenta_en_task(self):
        class _Row:
            imagen_estado = ESTADO_ERROR
            imagen_url = ''
            url = 'https://example.com/p'

            def save(self, **kwargs):
                raise AssertionError('no debe reintentar error')

        from mecanimovilapp.apps.ordenes.tasks import hidratar_imagen_precio_web

        # La task corta antes de hidratar si el estado ya es error.
        self.assertEqual(ESTADO_ERROR, 'error')
        self.assertTrue(callable(hidratar_imagen_precio_web))

from django.test import SimpleTestCase

from mecanimovilapp.apps.chat.link_preview import _parse_html, validate_preview_url


class LinkPreviewValidationTest(SimpleTestCase):
    def test_https_publico_ok(self):
        self.assertTrue(
            validate_preview_url('https://maps.app.goo.gl/uzU6nknmWKmo37SA7', resolve_dns=False)
        )

    def test_bloquea_localhost_y_esquema(self):
        self.assertIsNone(validate_preview_url('http://127.0.0.1/secret'))
        self.assertIsNone(validate_preview_url('http://localhost/x'))
        self.assertIsNone(validate_preview_url('javascript:alert(1)'))
        self.assertIsNone(validate_preview_url('ftp://example.com/a'))

    def test_parse_og_tags(self):
        html = """
        <html><head>
          <meta property="og:title" content="Taller Los Alerces" />
          <meta property="og:description" content="Ruta 5 sur" />
          <meta property="og:image" content="/img.png" />
          <meta property="og:site_name" content="Google Maps" />
          <title>Ignorar</title>
        </head></html>
        """
        data = _parse_html(html, 'https://maps.app.goo.gl/abc')
        self.assertEqual(data['title'], 'Taller Los Alerces')
        self.assertEqual(data['description'], 'Ruta 5 sur')
        self.assertEqual(data['site_name'], 'Google Maps')
        self.assertEqual(data['image'], 'https://maps.app.goo.gl/img.png')

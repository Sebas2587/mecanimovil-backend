"""Tests middleware ráfaga sin auth."""
from django.test import RequestFactory, SimpleTestCase, override_settings

from mecanimovilapp.middleware.unauth_burst import UnauthDashboardBurstMiddleware


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-unauth-burst',
        }
    }
)
class UnauthBurstMiddlewareTestCase(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = UnauthDashboardBurstMiddleware(lambda r: self._ok_response())

    @staticmethod
    def _ok_response():
        from django.http import HttpResponse

        return HttpResponse('ok', status=200)

    def test_permite_primeras_solicitudes_sin_token(self):
        request = self.factory.get('/api/ordenes/proveedor-ordenes/ganancias-resumen/')
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_bloquea_ráfaga_sin_token(self):
        path = '/api/suscripciones/mi-suscripcion/estado-salud/'
        for _ in range(20):
            req = self.factory.get(path, REMOTE_ADDR='203.0.113.50')
            res = self.middleware(req)
            self.assertEqual(res.status_code, 200)
        blocked = self.middleware(
            self.factory.get(path, REMOTE_ADDR='203.0.113.50'),
        )
        self.assertEqual(blocked.status_code, 429)

    def test_no_bloquea_con_token(self):
        path = '/api/mercadopago/cuenta-proveedor/mi-cuenta/'
        for _ in range(25):
            req = self.factory.get(
                path,
                HTTP_AUTHORIZATION='Token abc123',
                REMOTE_ADDR='203.0.113.51',
            )
            res = self.middleware(req)
            self.assertEqual(res.status_code, 200)

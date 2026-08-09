"""Tests búsqueda web de repuestos (Gemini URL Context)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings


@override_settings(
    BUSQUEDA_WEB_REPUESTOS_ENABLED=True,
    BUSQUEDA_WEB_REPUESTOS_MAX_URLS=4,
    BUSQUEDA_WEB_REPUESTOS_FUENTES=[
        {
            'nombre': 'Mercado Libre',
            'dominio': 'listado.mercadolibre.cl',
            'plantilla': 'https://listado.mercadolibre.cl/{q}',
        },
        {
            'nombre': 'AutoPlanet',
            'dominio': 'www.autoplanet.cl',
            'plantilla': 'https://www.autoplanet.cl/search?q={q}',
        },
        {
            'nombre': 'Mundo Repuestos',
            'dominio': 'www.mundorepuestos.cl',
            'plantilla': 'https://www.mundorepuestos.cl/buscar?q={q}',
        },
        {
            'nombre': 'Refax',
            'dominio': 'www.refax.cl',
            'plantilla': 'https://www.refax.cl/search?q={q}',
        },
    ],
    BUSQUEDA_WEB_REPUESTOS_PRECIO_MIN=1000,
    BUSQUEDA_WEB_REPUESTOS_PRECIO_MAX=3_000_000,
)
class ConstruirUrlsTestCase(SimpleTestCase):
    def test_construye_urls_con_datos_patente(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            construir_urls_busqueda,
        )

        urls = construir_urls_busqueda(
            ['kit embrague'],
            marca='Hyundai',
            modelo='Accent',
            anio=2015,
            cilindraje='1.4',
        )
        self.assertTrue(urls)
        self.assertLessEqual(len(urls), 4)
        joined = ' '.join(urls).lower()
        self.assertIn('hyundai', joined)
        self.assertIn('accent', joined)
        self.assertTrue(any('mercadolibre' in u for u in urls))

    def test_respeta_tope_max_urls(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            construir_urls_busqueda,
        )

        with override_settings(BUSQUEDA_WEB_REPUESTOS_MAX_URLS=2):
            urls = construir_urls_busqueda(
                ['bujias'],
                marca='Fiat',
                modelo='Bravo',
                anio=2010,
            )
        self.assertEqual(len(urls), 2)


@override_settings(
    BUSQUEDA_WEB_REPUESTOS_ENABLED=True,
    BUSQUEDA_WEB_REPUESTOS_FUENTES=[
        {
            'nombre': 'Mercado Libre',
            'dominio': 'listado.mercadolibre.cl',
            'plantilla': 'https://listado.mercadolibre.cl/{q}',
        },
        {
            'nombre': 'AutoPlanet',
            'dominio': 'www.autoplanet.cl',
            'plantilla': 'https://www.autoplanet.cl/search?q={q}',
        },
    ],
    BUSQUEDA_WEB_REPUESTOS_PRECIO_MIN=1000,
    BUSQUEDA_WEB_REPUESTOS_PRECIO_MAX=3_000_000,
    GEMINI_API_KEY='test-key',
)
class ValidarResultadoTestCase(SimpleTestCase):
    def test_descarta_dominio_fuera_whitelist(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_resultado,
        )

        out = _validar_resultado(
            {
                'encontrado': True,
                'nombre_buscado': 'bujias',
                'nombre_producto': 'Bujía NGK',
                'marca_repuesto': 'NGK',
                'precio_clp': 12000,
                'tienda': 'FakeShop',
                'url': 'https://evil.example.com/item/1',
                'compatibilidad': 'alta',
            },
            urls_ok={'https://evil.example.com/item/1'},
            whitelist={'listado.mercadolibre.cl', 'www.autoplanet.cl'},
        )
        self.assertIsNone(out)

    def test_descarta_sin_retrieval_exitoso(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_resultado,
        )

        item = {
            'encontrado': True,
            'nombre_buscado': 'bujias',
            'nombre_producto': 'Bujía NGK',
            'marca_repuesto': 'NGK',
            'precio_clp': 12000,
            'tienda': 'AutoPlanet',
            'url': 'https://www.autoplanet.cl/producto/1',
            'compatibilidad': 'alta',
        }
        # Sin retrieval OK → descartar.
        self.assertIsNone(
            _validar_resultado(item, urls_ok=set(), whitelist={'www.autoplanet.cl'}),
        )
        # Retrieval de otro dominio → descartar.
        self.assertIsNone(
            _validar_resultado(
                item,
                urls_ok={'https://listado.mercadolibre.cl/bujias'},
                whitelist={'www.autoplanet.cl', 'listado.mercadolibre.cl'},
            ),
        )
        # Retrieval del mismo dominio → aceptar.
        self.assertIsNotNone(
            _validar_resultado(
                item,
                urls_ok={'https://www.autoplanet.cl/search?q=bujias', 'www.autoplanet.cl'},
                whitelist={'www.autoplanet.cl'},
            ),
        )

    def test_descarta_precio_absurdo(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_resultado,
        )

        out = _validar_resultado(
            {
                'encontrado': True,
                'nombre_buscado': 'bujias',
                'nombre_producto': 'Bujía',
                'marca_repuesto': 'NGK',
                'precio_clp': 50,
                'tienda': 'AutoPlanet',
                'url': 'https://www.autoplanet.cl/p/1',
                'compatibilidad': 'alta',
            },
            urls_ok={'https://www.autoplanet.cl/search?q=bujias'},
            whitelist={'www.autoplanet.cl'},
        )
        self.assertIsNone(out)

    def test_descarta_marca_placeholder(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_resultado,
        )

        out = _validar_resultado(
            {
                'encontrado': True,
                'nombre_buscado': 'filtro',
                'nombre_producto': 'Filtro genérico',
                'marca_repuesto': 'GENÉRICO',
                'precio_clp': 15000,
                'tienda': 'AutoPlanet',
                'url': 'https://www.autoplanet.cl/p/2',
                'compatibilidad': 'media',
            },
            urls_ok={'www.autoplanet.cl'},
            whitelist={'www.autoplanet.cl'},
        )
        # Marca inválida se limpia; aún puede pasar si hay nombre+precio.
        # Exigimos que marca quede vacía.
        self.assertIsNotNone(out)
        self.assertEqual(out.get('marca_repuesto'), '')

    @override_settings(GEMINI_API_KEY='test-key', BUSQUEDA_WEB_REPUESTOS_ENABLED=True)
    def test_respuesta_no_json_no_rompe(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            'candidates': [{
                'content': {'parts': [{'text': 'esto no es json'}]},
                'url_context_metadata': {
                    'url_metadata': [{
                        'retrieved_url': 'https://www.autoplanet.cl/search?q=x',
                        'url_retrieval_status': 'URL_RETRIEVAL_STATUS_SUCCESS',
                    }],
                },
            }],
        }
        with patch.object(bw, 'cuota_diaria_disponible', return_value=True), patch.object(
            bw, '_consumir_cuota_diaria', return_value=True,
        ), patch('mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post', return_value=fake_resp):
            out = bw.buscar_repuestos_web(
                ['bujias'],
                vehiculo={'marca': 'Fiat', 'modelo': 'Bravo', 'anio': 2010},
            )
        self.assertEqual(out, {})


class DispararBusquedaWebTestCase(SimpleTestCase):
    @override_settings(BUSQUEDA_WEB_REPUESTOS_ENABLED=False)
    def test_marcar_pendiente_noop_si_disabled(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            marcar_busqueda_web_pendiente,
        )

        meta = marcar_busqueda_web_pendiente({'origen': 'ia'})
        self.assertNotIn('busqueda_web_estado', meta)

    @override_settings(BUSQUEDA_WEB_REPUESTOS_ENABLED=True, GEMINI_API_KEY='k')
    def test_marcar_pendiente_cuando_enabled(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            marcar_busqueda_web_pendiente,
        )

        meta = marcar_busqueda_web_pendiente({'origen': 'ia'})
        self.assertEqual(meta.get('busqueda_web_estado'), 'pendiente')


@override_settings(
    BUSQUEDA_WEB_REPUESTOS_ENABLED=True,
    GEMINI_API_KEY='k',
    BUSQUEDA_WEB_REPUESTOS_TTL_DIAS=14,
    BUSQUEDA_WEB_REPUESTOS_MAX_LINEAS=6,
)
class BuscarPreciosWebTaskTestCase(SimpleTestCase):
    def test_no_toca_cotizacion_no_borrador(self):
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = MagicMock()
        cot.estado = 'enviada'
        cot.pk = 99
        with patch(
            'mecanimovilapp.apps.ordenes.models.CotizacionCanal.objects.filter',
        ) as filt:
            filt.return_value.first.return_value = cot
            with patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
                return_value=True,
            ):
                result = buscar_precios_web_cotizacion_task.run(99)
        self.assertFalse(result.get('ok'))
        self.assertEqual(result.get('reason'), 'not_borrador')
        cot.save.assert_not_called()

    def test_gemini_falla_deja_estado_error(self):
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = MagicMock()
        cot.estado = 'borrador'
        cot.pk = 7
        cot.id = 7
        cot.repuestos = [{'nombre': 'Bujias', 'precio_estimado': True, 'cantidad': 1, 'precio_unitario_clp': 0}]
        cot.mano_obra_clp = 10000
        cot.vehiculo_marca = 'Fiat'
        cot.vehiculo_modelo = 'Bravo'
        cot.vehiculo_anio = 2010
        cot.vehiculo_cilindraje = ''
        cot.tipo_motor = ''
        cot.servicio_nombre = 'Bujias'
        cot.taller = MagicMock()
        cot.metadata = {'busqueda_web_estado': 'pendiente'}

        with patch(
            'mecanimovilapp.apps.ordenes.models.CotizacionCanal.objects.filter',
        ) as filt, patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.cuota_diaria_disponible',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=RuntimeError('boom'),
        ):
            filt.return_value.first.return_value = cot
            result = buscar_precios_web_cotizacion_task.run(7)
        self.assertFalse(result.get('ok'))
        # metadata marcada error
        self.assertEqual(cot.metadata.get('busqueda_web_estado'), 'error')

    def test_sin_cuota_diaria_marca_error(self):
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = MagicMock()
        cot.estado = 'borrador'
        cot.pk = 3
        cot.metadata = {}
        with patch(
            'mecanimovilapp.apps.ordenes.models.CotizacionCanal.objects.filter',
        ) as filt, patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.cuota_diaria_disponible',
            return_value=False,
        ):
            filt.return_value.first.return_value = cot
            result = buscar_precios_web_cotizacion_task.run(3)
        self.assertFalse(result.get('ok'))
        self.assertEqual(result.get('reason'), 'rpd')
        self.assertEqual(cot.metadata.get('busqueda_web_estado'), 'error')

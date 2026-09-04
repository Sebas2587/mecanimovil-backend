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
        # Un listado no dice de qué tienda es el precio: solo tiendas con producto.
        self.assertFalse(any('mercadolibre' in u for u in urls))
        self.assertTrue(any('autoplanet' in u for u in urls))

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

    def test_una_query_por_repuesto_no_mezcla_nombres(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            construir_urls_busqueda,
        )

        with override_settings(BUSQUEDA_WEB_REPUESTOS_MAX_URLS=3):
            urls = construir_urls_busqueda(
                [
                    'Termostato de refrigerante',
                    'Sensor de temperatura de refrigerante',
                    'Refrigerante orgánico',
                ],
                marca='Suzuki',
                modelo='CELERIO HB 1.0',
                anio=2017,
            )
        self.assertEqual(len(urls), 3)
        joined = ' '.join(urls).lower()
        # Una query por pieza, no un mashup de las tres.
        self.assertTrue(any('termostato' in u.lower() for u in urls))
        self.assertTrue(any('sensor' in u.lower() for u in urls))
        self.assertNotIn('termostato-de-refrigerante-sensor-de-temperatura', joined)
        self.assertNotIn('2017', joined)

    def test_no_consulta_listados_de_marketplace(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            construir_urls_busqueda,
        )

        # Solo ML configurado: sin tienda atribuible no hay nada que consultar.
        with override_settings(BUSQUEDA_WEB_REPUESTOS_FUENTES=[{
            'nombre': 'Mercado Libre',
            'dominio': 'listado.mercadolibre.cl',
            'plantilla': 'https://listado.mercadolibre.cl/{q}',
        }]):
            self.assertEqual(construir_urls_busqueda(['pastillas de freno'], marca='Fiat'), [])


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

    def test_descarta_sin_retrieval_ni_dominio_solicitado(self):
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
        # Sin retrieval OK y sin dominios solicitados → descartar.
        self.assertIsNone(
            _validar_resultado(item, urls_ok=set(), whitelist={'www.autoplanet.cl'}),
        )
        # Retrieval de otro dominio y dominio solicitado distinto → descartar.
        self.assertIsNone(
            _validar_resultado(
                item,
                urls_ok={'https://listado.mercadolibre.cl/bujias'},
                whitelist={'www.autoplanet.cl', 'listado.mercadolibre.cl'},
                dominios_solicitados={'listado.mercadolibre.cl'},
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
        # Sin metadata de retrieval, pero dominio coincidente con URL pedida → aceptar.
        out = _validar_resultado(
            item,
            urls_ok=set(),
            whitelist={'www.autoplanet.cl'},
            dominios_solicitados={'www.autoplanet.cl', 'autoplanet.cl'},
        )
        self.assertIsNotNone(out)
        self.assertEqual(out.get('marca_repuesto'), 'NGK')
        self.assertEqual(out.get('tienda'), 'AutoPlanet')

    def test_precio_absurdo_conserva_marca_tienda(self):
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
        # Precio fuera de rango no bloquea marca/tienda (precio_clp queda 0).
        self.assertIsNotNone(out)
        self.assertEqual(out.get('marca_repuesto'), 'NGK')
        self.assertEqual(out.get('tienda'), 'AutoPlanet')
        self.assertEqual(out.get('precio_clp'), 0)

    def test_acepta_subdominio_mercadolibre(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_resultado,
        )

        out = _validar_resultado(
            {
                'encontrado': True,
                'nombre_buscado': 'termostato',
                'nombre_producto': 'Termostato Gates Suzuki',
                'marca_repuesto': 'Gates',
                'precio_clp': 18990,
                'tienda': 'Mercado Libre',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'compatibilidad': 'alta',
            },
            urls_ok={'https://listado.mercadolibre.cl/termostato-suzuki', 'listado.mercadolibre.cl'},
            whitelist={'listado.mercadolibre.cl', 'www.autoplanet.cl'},
            dominios_solicitados={'listado.mercadolibre.cl', 'mercadolibre.cl'},
        )
        self.assertIsNotNone(out)
        self.assertEqual(out.get('marca_repuesto'), 'Gates')
        self.assertIn('mercadolibre', (out.get('dominio') or ''))

    def test_descarta_listado_sin_vendedor(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _motivo_descarte,
            _validar_resultado,
        )

        # Un listado agrega decenas de vendedores: el precio no tiene tienda.
        item = {
            'encontrado': True,
            'nombre_buscado': 'termostato',
            'nombre_producto': 'Termostato Gates Suzuki',
            'marca_repuesto': 'Gates',
            'precio_clp': 18990,
            'tienda': 'Mercado Libre',
            'url': 'https://listado.mercadolibre.cl/termostato-suzuki',
            'compatibilidad': 'alta',
        }
        kwargs = {
            'urls_ok': {'https://listado.mercadolibre.cl/termostato-suzuki'},
            'whitelist': {'listado.mercadolibre.cl', 'www.autoplanet.cl'},
            'dominios_solicitados': {'listado.mercadolibre.cl'},
        }
        self.assertIsNone(_validar_resultado(item, **kwargs))
        self.assertIn('listado_sin_vendedor', _motivo_descarte(item, **kwargs) or '')
        # La publicación del mismo marketplace sí tiene vendedor: se acepta.
        self.assertIsNotNone(
            _validar_resultado(
                {**item, 'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato'},
                **kwargs,
            ),
        )

    def test_solo_acepta_tiendas_chilenas(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _es_tienda_chilena,
        )

        wl = {'www.autoplanet.cl'}
        self.assertTrue(_es_tienda_chilena('https://gmak.cl/products/pastillas', wl))
        self.assertTrue(_es_tienda_chilena('https://www.autoplanet.cl/producto/x', wl))
        # Misma tienda configurada con otro TLD.
        with override_settings(BUSQUEDA_WEB_REPUESTOS_FUENTES=[{
            'nombre': 'Mundo Repuestos',
            'dominio': 'www.mundorepuestos.cl',
            'plantilla': 'https://www.mundorepuestos.cl/buscar?q={q}',
        }]):
            self.assertTrue(_es_tienda_chilena('https://mundorepuestos.com/producto/x', wl))
        # Un precio en euros o pesos colombianos no orienta al taller.
        self.assertFalse(_es_tienda_chilena('https://www.autodoc.es/repuestos/x', wl))
        self.assertFalse(_es_tienda_chilena('https://brakepak.com.co/tienda/x', wl))
        self.assertFalse(_es_tienda_chilena('https://tienda.imfrisa.com.ec/frenos/x', wl))

    def test_descarta_paginas_sin_ficha(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _es_pagina_sin_ficha,
        )

        self.assertTrue(_es_pagina_sin_ficha('https://www.repuestosboston.cl/blog/consumo-accent'))
        self.assertTrue(_es_pagina_sin_ficha('https://www.mercadolibre.cl/pagina/zapatafrenos'))
        self.assertFalse(_es_pagina_sin_ficha('https://gmak.cl/products/pastillas-fiat-uno'))

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


class CacheSkipGeminiTestCase(SimpleTestCase):
    def test_nombres_sin_cache_separa_faltantes(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import (
            busqueda_web_repuestos as bw,
        )

        # _clave_fuzzy elimina ruido "kit" → clave "embrague".
        with patch.object(
            bw,
            'hits_cache_vigentes_para_nombres',
            return_value={
                'embrague': {
                    'nombre_producto': 'Kit embrague Sachs',
                    'marca_repuesto': 'Sachs',
                    'precio_clp': 150000,
                    'tienda': 'AutoPlanet',
                    'confianza': 0.8,
                },
            },
        ):
            faltantes, hits = bw.nombres_sin_cache_vigente(
                ['Kit embrague', 'Volante bimasa'],
                marca_vehiculo='Hyundai',
                modelo_vehiculo='Accent',
            )
        self.assertIn('Volante bimasa', faltantes)
        self.assertNotIn('Kit embrague', faltantes)
        self.assertIn('embrague', hits)

    def test_task_cache_completo_no_llama_gemini(self):
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = MagicMock()
        cot.estado = 'borrador'
        cot.pk = 11
        cot.id = 11
        cot.repuestos = [{
            'nombre': 'Kit embrague',
            'precio_estimado': True,
            'cantidad': 1,
            'precio_unitario_clp': 0,
        }]
        cot.mano_obra_clp = 20000
        cot.vehiculo_marca = 'Hyundai'
        cot.vehiculo_modelo = 'Accent'
        cot.vehiculo_anio = 2015
        cot.vehiculo_cilindraje = ''
        cot.tipo_motor = ''
        cot.servicio_nombre = 'Embrague'
        cot.taller = MagicMock()
        cot.metadata = {'busqueda_web_estado': 'pendiente'}

        cache_hit = {
            'kit embrague': {
                'nombre_buscado': 'Kit embrague',
                'nombre_producto': 'Kit embrague Sachs',
                'marca_repuesto': 'Sachs',
                'precio_clp': 150000,
                'tienda': 'AutoPlanet',
                'dominio': 'www.autoplanet.cl',
                'url': 'https://www.autoplanet.cl/p/1',
                'compatibilidad': 'alta',
                'confianza': 0.8,
                'desde_cache': True,
            },
        }

        with patch(
            'mecanimovilapp.apps.ordenes.models.CotizacionCanal.objects.filter',
        ) as filt, patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.nombres_sin_cache_vigente',
            return_value=([], cache_hit),
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
        ) as buscar, patch(
            'mecanimovilapp.apps.ordenes.models.PrecioRepuestoWeb.objects.update_or_create',
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos.enriquecer_repuestos_cotizacion',
            side_effect=lambda reps, **kw: [{
                **reps[0],
                'fuente_marketplace': 'web',
                'marca_repuesto': 'Sachs',
                'proveedor_nombre': 'AutoPlanet',
                'precio_unitario_clp': 150000,
                'precio_estimado': True,
                'precio_referencia_mercado': True,
            }],
        ):
            filt.return_value.first.return_value = cot
            result = buscar_precios_web_cotizacion_task.run(11)
        buscar.assert_not_called()
        self.assertTrue(result.get('ok'))


class AprendizajeCotizacionTestCase(SimpleTestCase):
    def test_bloque_historial_vacio_sin_taller(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aprendizaje_cotizacion import (
            construir_bloque_historial_prompt,
        )

        self.assertEqual(
            construir_bloque_historial_prompt(
                taller=None,
                servicio_nombre='Embrague',
                marca='Hyundai',
                modelo='Accent',
            ),
            '',
        )

    def test_servicios_similares(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aprendizaje_cotizacion import (
            _servicios_similares,
        )

        self.assertTrue(_servicios_similares('Cambio de embrague', 'Embrague completo'))
        self.assertFalse(_servicios_similares('Cambio de aceite', 'Alineación'))


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
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.nombres_sin_cache_vigente',
            return_value=(['Bujias'], {}),
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
        cot.id = 3
        cot.repuestos = [{
            'nombre': 'Bujias',
            'precio_estimado': True,
            'cantidad': 1,
            'precio_unitario_clp': 0,
        }]
        cot.mano_obra_clp = 10000
        cot.vehiculo_marca = 'Fiat'
        cot.vehiculo_modelo = 'Bravo'
        cot.vehiculo_anio = 2010
        cot.vehiculo_cilindraje = ''
        cot.tipo_motor = ''
        cot.servicio_nombre = 'Bujias'
        cot.taller = MagicMock()
        cot.metadata = {}
        with patch(
            'mecanimovilapp.apps.ordenes.models.CotizacionCanal.objects.filter',
        ) as filt, patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.nombres_sin_cache_vigente',
            return_value=(['Bujias'], {}),
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.cuota_diaria_disponible',
            return_value=False,
        ):
            filt.return_value.first.return_value = cot
            result = buscar_precios_web_cotizacion_task.run(3)
        self.assertFalse(result.get('ok'))
        self.assertEqual(result.get('reason'), 'rpd')
        self.assertEqual(cot.metadata.get('busqueda_web_estado'), 'error')


@override_settings(
    BUSQUEDA_WEB_REPUESTOS_ENABLED=True,
    GEMINI_API_KEY='test-key',
    TAVILY_API_KEY='tvly-test',
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
)
class BuscarRepuestosWebTavilyTestCase(SimpleTestCase):
    def _fake_tavily_resp(self, results):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'results': results}
        return resp

    def _fake_gemini_resp(self, resultados):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': __import__('json').dumps({'resultados': resultados})}]}}],
        }
        return resp

    def test_usa_tavily_como_fuente_primaria_y_no_llama_url_context(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([
            {
                'title': 'Termostato Gates Fiat Bravo 1.4 T-Jet',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'content': 'Termostato Gates para Fiat Bravo T-Jet. Precio $ 18.990. Envío a todo Chile.',
            },
        ])
        gemini_resp = self._fake_gemini_resp([
            {
                'nombre_buscado': 'Termostato de refrigerante',
                'encontrado': True,
                'nombre_producto': 'Termostato Gates Fiat Bravo 1.4 T-Jet',
                'marca_repuesto': 'Gates',
                'precio_clp': 18990,
                'tienda': 'Mercado Libre',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'compatibilidad': 'alta',
            },
        ])

        extract_resp = MagicMock()
        extract_resp.status_code = 200
        extract_resp.json.return_value = {'results': []}  # sin ficha; se usa el snippet.

        calls = {'tavily_search': 0, 'tavily_extract': 0, 'gemini': 0}

        def fake_post(url, **kwargs):
            if url.endswith('/extract'):
                calls['tavily_extract'] += 1
                return extract_resp
            if 'tavily.com' in url:
                calls['tavily_search'] += 1
                self.assertEqual(kwargs['headers']['Authorization'], 'Bearer tvly-test')
                return tavily_resp
            calls['gemini'] += 1
            # El path Tavily NO debe pedir la tool url_context (evita alucinaciones).
            self.assertNotIn('tools', kwargs.get('json', {}))
            return gemini_resp

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            out = bw.buscar_repuestos_web(
                ['Termostato de refrigerante'],
                vehiculo={'marca': 'Fiat', 'modelo': 'Bravo Sport TJet', 'anio': 2010},
                servicio_nombre='Cambio de termostato',
            )

        self.assertEqual(calls['tavily_search'], 1)
        self.assertEqual(calls['tavily_extract'], 1)
        self.assertEqual(calls['gemini'], 1)
        self.assertEqual(len(out), 1)
        hit = next(iter(out.values()))
        self.assertEqual(hit['marca_repuesto'], 'Gates')
        self.assertEqual(hit['tienda'], 'Mercado Libre')
        self.assertEqual(hit['precio_clp'], 18990)
        self.assertEqual(hit['url'], 'https://articulo.mercadolibre.cl/MLC-123-termostato')

    def test_descarta_url_alucinada_que_tavily_no_devolvio(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([
            {
                'title': 'Pastillas de freno genéricas',
                'url': 'https://www.autoplanet.cl/producto/real-1',
                'content': 'Pastillas de freno.',
            },
        ])
        # Gemini inventa una URL que no estaba en los candidatos reales.
        gemini_resp = self._fake_gemini_resp([
            {
                'nombre_buscado': 'Pastillas de freno',
                'encontrado': True,
                'nombre_producto': 'Pastillas Bosch',
                'marca_repuesto': 'Bosch',
                'precio_clp': 20000,
                'tienda': 'AutoPlanet',
                'url': 'https://www.autoplanet.cl/producto/inventada-2',
                'compatibilidad': 'alta',
            },
        ])

        def fake_post(url, **kwargs):
            return tavily_resp if 'tavily.com' in url else gemini_resp

        # Se llama directo a la función Tavily (no al dispatcher) para aislar
        # el chequeo anti-alucinación del fallback a url_context.
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            out = bw._buscar_repuestos_web_tavily(
                ['Pastillas de freno'],
                marca='Fiat',
                modelo='Bravo',
                anio=2010,
                cilindraje='',
                tipo_motor='',
                servicio_nombre='',
                timeout=20,
            )
        self.assertEqual(out, {})

    def test_fallback_a_url_context_si_tavily_sin_candidatos(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([])  # Sin resultados → debe caer a url_context.
        gemini_url_context_resp = MagicMock()
        gemini_url_context_resp.status_code = 200
        gemini_url_context_resp.json.return_value = {
            'candidates': [{
                'content': {'parts': [{'text': __import__('json').dumps({'resultados': []})}]},
                'urlContextMetadata': {'urlMetadata': []},
            }],
        }

        calls = {'tavily': 0, 'gemini_with_tools': 0}

        def fake_post(url, **kwargs):
            if 'tavily.com' in url:
                calls['tavily'] += 1
                return tavily_resp
            if 'tools' in kwargs.get('json', {}):
                calls['gemini_with_tools'] += 1
            return gemini_url_context_resp

        with patch.object(bw, 'cuota_diaria_disponible', return_value=True), patch.object(
            bw, '_consumir_cuota_diaria', return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            bw.buscar_repuestos_web(
                ['Pastillas de freno'],
                vehiculo={'marca': 'Fiat', 'modelo': 'Bravo', 'anio': 2010},
            )

        self.assertEqual(calls['tavily'], 1)
        self.assertEqual(calls['gemini_with_tools'], 1)

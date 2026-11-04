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
        self.assertTrue(_es_pagina_sin_ficha('https://www.autoplanet.cl/busqueda/kit-embrague-kia-morning'))
        self.assertTrue(_es_pagina_sin_ficha(
            'https://www.repuestosboston.cl/repuestos-boston/embrague/kit-de-embragues.html'
            '?marca_vehiculo=Kia&modelo_vehiculo=Morning',
        ))
        self.assertTrue(_es_pagina_sin_ficha(
            'https://www.tiktok.com/@x/video/7575996897500990727',
        ))
        self.assertFalse(_es_pagina_sin_ficha('https://gmak.cl/products/pastillas-fiat-uno'))
        self.assertFalse(_es_pagina_sin_ficha(
            'https://www.todoembragues.cl/kit-embrague-para-kia-morning-1-1-g4hg',
        ))

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
            return_value=(MagicMock(), False),
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
        self.assertFalse(_servicios_similares('Cambio de embrague', 'Cambio de amortiguadores'))
        self.assertFalse(
            _servicios_similares(
                'Cambio de embrague',
                'Servicio cambio kit de embrague, cambio de amortiguadores delanteros y diagnóstico eléctrico',
            )
        )


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

        meta = marcar_busqueda_web_pendiente(
            {'origen': 'ia'},
            repuestos=[{'nombre': 'Filtro de aceite', 'precio_unitario_clp': 0}],
        )
        self.assertEqual(meta.get('busqueda_web_estado'), 'pendiente')
        self.assertTrue(meta.get('busqueda_web_en'))
        progreso = meta.get('busqueda_web_progreso') or {}
        self.assertEqual(progreso.get('paso'), 'casas')
        self.assertEqual(progreso['lineas'][0]['nombre'], 'Filtro de aceite')
        self.assertIn('Catálogo del taller', progreso.get('fuentes') or [])

    @override_settings(BUSQUEDA_WEB_REPUESTOS_ENABLED=True, GEMINI_API_KEY='k')
    def test_progreso_omite_lineas_ya_cotizadas(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            marcar_busqueda_web_pendiente,
        )

        meta = marcar_busqueda_web_pendiente(
            {'origen': 'ia'},
            repuestos=[
                {
                    'id': '1',
                    'nombre': 'Radiador de refrigeración',
                    'precio_unitario_clp': 93000,
                    'fuente_marketplace': 'web',
                    'proveedor_nombre': 'Casa Chile',
                },
                {
                    'id': '2',
                    'nombre': 'Aceite motor',
                    'precio_unitario_clp': 0,
                },
            ],
        )
        nombres = [l['nombre'] for l in (meta.get('busqueda_web_progreso') or {}).get('lineas') or []]
        self.assertEqual(nombres, ['Aceite motor'])

    @override_settings(BUSQUEDA_WEB_REPUESTOS_ENABLED=True, GEMINI_API_KEY='k')
    def test_en_curso_si_marcado_recien(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            busqueda_web_en_curso,
            marcar_busqueda_web_pendiente,
        )

        meta = marcar_busqueda_web_pendiente({'origen': 'ia'})
        self.assertTrue(busqueda_web_en_curso(meta))
        self.assertFalse(busqueda_web_en_curso({'busqueda_web_estado': 'ok'}))


@override_settings(
    BUSQUEDA_WEB_REPUESTOS_ENABLED=True,
    GEMINI_API_KEY='k',
    BUSQUEDA_WEB_REPUESTOS_TTL_DIAS=14,
    BUSQUEDA_WEB_REPUESTOS_MAX_LINEAS=6,
)
class BuscarPreciosWebTaskTestCase(SimpleTestCase):
    def test_no_toca_cotizacion_cancelada(self):
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = MagicMock()
        cot.estado = 'cancelada'
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
        self.assertEqual(result.get('reason'), 'estado')
        cot.save.assert_not_called()

    def test_cancelada_no_consulta_tiendas(self):
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = MagicMock()
        cot.estado = 'borrador'
        cot.pk = 42
        cot.metadata = {'busqueda_web_estado': 'pendiente'}
        cot.repuestos = [{'nombre': 'Bujías', 'precio_unitario_clp': 0, 'cantidad': 1}]
        with patch(
            'mecanimovilapp.apps.ordenes.models.CotizacionCanal.objects.filter',
        ) as filt, patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web.busqueda_fue_cancelada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
        ) as buscar:
            filt.return_value.first.return_value = cot
            result = buscar_precios_web_cotizacion_task.run(42)
        self.assertFalse(result.get('ok'))
        self.assertEqual(result.get('reason'), 'cancelada')
        buscar.assert_not_called()
        cot.save.assert_not_called()

    def test_cancelar_mata_el_worker(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            cancelar_busqueda_web_cotizacion,
        )

        cot = MagicMock()
        cot.id = 15
        cot.metadata = {
            'busqueda_web_estado': 'pendiente',
            'busqueda_web_task_id': 'abc-123',
        }
        with patch('django.core.cache.cache.set') as cache_set, patch(
            'mecanimovilapp.celery.app',
        ) as celery_app:
            cancelar_busqueda_web_cotizacion(cot)
        self.assertEqual(cot.metadata['busqueda_web_estado'], 'cancelada')
        self.assertIn('cancelada', (cot.metadata.get('busqueda_web_progreso') or {}).get('detalle', '').lower())
        cache_set.assert_called()
        celery_app.control.revoke.assert_called_once_with(
            'abc-123',
            terminate=True,
            signal='SIGTERM',
        )
        cot.save.assert_called()

    def test_si_busca_en_cotizacion_aceptada(self):
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = MagicMock()
        cot.estado = 'aceptada'
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
            return_value=False,
        ):
            filt.return_value.first.return_value = cot
            result = buscar_precios_web_cotizacion_task.run(3)
        self.assertFalse(result.get('ok'))
        self.assertEqual(result.get('reason'), 'rpd')
        self.assertEqual(cot.metadata.get('busqueda_web_estado'), 'error')

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
        # Una llamada corta para razonar el pedido. La ficha sale del snippet, no de otra vuelta a Gemini.
        self.assertEqual(calls['gemini'], 1)
        self.assertEqual(len(out), 1)
        hit = next(iter(out.values()))
        self.assertEqual(hit['marca_repuesto'], 'Gates')
        self.assertEqual(hit['tienda'], 'Mercado Libre')
        self.assertEqual(hit['precio_clp'], 18990)
        self.assertEqual(hit['url'], 'https://articulo.mercadolibre.cl/MLC-123-termostato')

    def test_no_guarda_el_hit_cuando_no_hay_monto_en_ninguna_parte(self):
        """Una fila con precio 0 envenena el cache: mejor no dejar rastro."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([
            {
                'title': 'Termostato Fiat Bravo',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'content': 'Termostato para Fiat Bravo. Consultar disponibilidad.',
            },
        ])
        gemini_resp = self._fake_gemini_resp([
            {
                'nombre_buscado': 'Termostato de refrigerante',
                'encontrado': True,
                'nombre_producto': 'Termostato Fiat Bravo',
                'marca_repuesto': 'Gates',
                'precio_clp': 0,
                'tienda': 'Mercado Libre',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'compatibilidad': 'alta',
            },
        ])

        extract_resp = MagicMock()
        extract_resp.status_code = 200
        extract_resp.json.return_value = {'results': []}

        def fake_post(url, **kwargs):
            if url.endswith('/extract'):
                return extract_resp
            return tavily_resp if 'tavily.com' in url else gemini_resp

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ), patch.object(bw, '_leer_html_fichas', return_value={}):
            out = bw._buscar_repuestos_web_tavily(
                ['Termostato de refrigerante'],
                marca='Fiat',
                modelo='Bravo Sport TJet',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='',
                servicio_nombre='',
                timeout=20,
            )

        self.assertEqual(out, {})

    def test_recupera_el_precio_aunque_el_modelo_reescriba_el_nombre(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([
            {
                'title': 'Termostato Gates Fiat Bravo',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'content': 'Termostato Gates Fiat Bravo $ 18.990',
            },
        ])
        # El modelo devuelve el nombre con otra redacción y sin monto.
        gemini_resp = self._fake_gemini_resp([
            {
                'nombre_buscado': 'termostato  de   refrigerante',
                'encontrado': True,
                'nombre_producto': 'Termostato Gates Fiat Bravo',
                'marca_repuesto': 'Gates',
                'precio_clp': None,
                'tienda': 'Mercado Libre',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'compatibilidad': 'alta',
            },
        ])

        extract_resp = MagicMock()
        extract_resp.status_code = 200
        extract_resp.json.return_value = {'results': []}

        def fake_post(url, **kwargs):
            if url.endswith('/extract'):
                return extract_resp
            return tavily_resp if 'tavily.com' in url else gemini_resp

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            out = bw._buscar_repuestos_web_tavily(
                ['Termostato de refrigerante'],
                marca='Fiat',
                modelo='Bravo Sport TJet',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='',
                servicio_nombre='',
                timeout=20,
            )

        self.assertEqual(len(out), 1)
        self.assertEqual(next(iter(out.values()))['precio_clp'], 18990)

    def test_rescata_del_snippet_la_linea_que_el_modelo_omitio(self):
        """Con 2 repuestos y 1 solo en la respuesta, la otra línea no queda en $0."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([
            {
                'title': 'Termostato Gates Fiat Bravo 1.4 T-Jet',
                'url': 'https://articulo.mercadolibre.cl/MLC-123-termostato',
                'content': 'Termostato Gates Fiat Bravo T-Jet $ 18.990',
            },
            {
                'title': 'Disco de freno delantero Fiat Bravo',
                'url': 'https://articulo.mercadolibre.cl/MLC-456-disco',
                'content': 'Disco ventilado 284mm Fiat Bravo $ 32.500',
            },
        ])
        # El modelo solo reporta el termostato y omite los discos.
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
        extract_resp.json.return_value = {'results': []}

        def fake_post(url, **kwargs):
            if url.endswith('/extract'):
                return extract_resp
            return tavily_resp if 'tavily.com' in url else gemini_resp

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            out = bw._buscar_repuestos_web_tavily(
                ['Termostato de refrigerante', 'Disco de freno delantero'],
                marca='Fiat',
                modelo='Bravo Sport TJet',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='bencinero',
                servicio_nombre='cambio de termostato y discos de frenos',
                timeout=20,
            )

        self.assertEqual(len(out), 2)
        disco = out[bw._clave_fuzzy('Disco de freno delantero')]
        self.assertGreater(disco['precio_clp'], 0)
        self.assertEqual(disco['dominio'], 'articulo.mercadolibre.cl')
        # Rescate sin verificación del modelo: no se declara compatibilidad alta.
        self.assertIn(disco['compatibilidad'], ('media', 'baja'))

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
        ), patch.object(bw, '_leer_html_fichas', return_value={}):
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

    def test_nombra_la_casa_especialista_de_la_marca_en_la_busqueda(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([
            {
                'title': 'Pastillas Fiat Bravo Sport 1.4 T-Jet',
                'url': 'https://indra.cl/producto/pastillas-bravo-tjet',
                'content': 'Pastillas delanteras Fiat Bravo Sport T-Jet $ 24.990',
            },
        ])
        queries: list[str] = []

        def fake_post(url, **kwargs):
            if url.endswith('/extract'):
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {'results': []}
                return resp
            if 'tavily.com' in url:
                queries.append(kwargs['json']['query'])
                return tavily_resp
            return self._fake_gemini_resp([])

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            out = bw.buscar_repuestos_web(
                ['Pastillas de freno delanteras'],
                vehiculo={'marca': 'Fiat', 'modelo': 'BRAVO SPORT TJET', 'cilindraje': '1.4'},
            )

        self.assertEqual(
            queries,
            [
                'pastillas freno delanteras fiat bravo 1.4',
                'pastillas freno fiat bravo',
                'pastillas freno fiat linea t-jet',
            ],
        )
        self.assertNotIn('indra', ' '.join(queries).lower())
        self.assertNotIn('sport', ' '.join(queries).lower())
        self.assertNotIn('stilo', ' '.join(queries).lower())
        hit = out[bw._clave_fuzzy('Pastillas de freno delanteras')]
        self.assertEqual(hit['precio_clp'], 24990)
        self.assertIn('Bravo', hit['nombre_producto'])

    def test_retail_generalista_solo_si_no_hay_casa_de_repuestos(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        retail = {
            'title': 'Pastillas de freno',
            'url': 'https://www.sodimac.cl/sodimac-cl/articulo/123/Pastillas',
            'content': 'Pastillas de freno $ 10.000',
        }
        casa = {
            'title': 'Pastillas Fiat Bravo 1.4',
            'url': 'https://frenosvergara.shop/products/pastillas-bravo',
            'content': 'Pastillas Fiat Bravo 1.4 $ 24.990',
        }
        self.assertEqual(
            [c['url'] for c in bw._ordenar_candidatos([retail, casa])],
            [casa['url']],
        )
        # Sin alternativa, el retail sirve: mejor una referencia que ninguna.
        self.assertEqual([c['url'] for c in bw._ordenar_candidatos([retail])], [retail['url']])

    def test_calce_con_el_vehiculo_manda_sobre_la_ficha_generica(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tokens = bw._tokens_vehiculo('Fiat', 'BRAVO SPORT TJET', 2010, '1.4')
        exacta = {
            'url': 'https://tiendaa.cl/p/1',
            'title': 'Discos Delanteros Fiat Bravo 1.4 T-Jet 2004-2014',
            'content': '$ 99.600',
        }
        generica = {'url': 'https://tiendab.cl/p/2', 'title': 'Discos de freno', 'content': '$ 40.000'}
        otro_auto = {
            'url': 'https://tiendac.cl/p/3',
            'title': 'Discos Suzuki Grand Vitara 2.0',
            'content': '$ 21.400',
        }
        # "TJET" calza con "T-Jet" y "1.4" con "1 4"; el monto de otro auto no cuenta.
        self.assertEqual(bw._calce_vehiculo(exacta, tokens), 4)
        self.assertEqual(bw._calce_vehiculo(generica, tokens), 0)
        self.assertEqual(bw._calce_vehiculo(otro_auto, tokens), 0)
        self.assertEqual(
            [c['url'] for c in bw._ordenar_candidatos(
                [generica, otro_auto, exacta], tokens_vehiculo=tokens,
            )][0],
            exacta['url'],
        )

    def test_escalera_de_consultas_no_pierde_el_modelo_numerico(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        # El 208 es el nombre del modelo; la cilindrada y el año no.
        self.assertEqual(bw._modelo_busqueda_completo('208 ALLURE'), '208 Allure')
        self.assertEqual(bw._modelo_busqueda_completo('RIO 5 EX'), 'Rio 5 Ex')
        self.assertEqual(bw._modelo_busqueda_completo('CELERIO HB 1.0'), 'Celerio Hb')
        self.assertEqual(bw._modelo_busqueda_completo('TUCSON GL 2018'), 'Tucson Gl')

        consultas = bw._escalera_consultas(
            'Pastillas', marca='Kia', modelo='RIO 5 EX', cilindraje='1.4', casas=[],
        )
        # Específica primero, modelo a secas y al final solo la pieza.
        self.assertEqual(consultas[0], 'Pastillas Kia Rio 5 Ex 1.4')
        self.assertEqual(consultas[1], 'Pastillas Kia RIO')
        self.assertIn('pastillas', [bw._norm(q) for q in consultas])
        self.assertEqual(
            bw._escalera_consultas('Pastillas', marca='Kia', modelo='RIO', cilindraje='', casas=[])[0],
            'Pastillas Kia Rio',
        )

    def test_gemini_503_usa_modelo_respaldo(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        saturado = MagicMock()
        saturado.status_code = 503
        saturado.text = 'high demand'
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {'candidates': []}
        urls = []

        def fake_post(url, **kwargs):
            urls.append(url)
            return saturado if 'flash-lite' in url else ok

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ), patch.object(
            bw, 'modelos_gemini_cotizacion', return_value=['gemini-3.1-flash-lite', 'gemini-2.5-flash'],
        ):
            body = bw._gemini_generar('prompt', timeout=5, use_url_context=False)

        self.assertEqual(body, {'candidates': []})
        self.assertEqual(len(urls), 2)
        self.assertIn('gemini-3.1-flash-lite', urls[0])
        self.assertIn('gemini-2.5-flash', urls[1])

    def test_descarta_home_de_la_tienda(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        # La portada no tiene ficha ni precio de la pieza.
        self.assertTrue(bw._es_pagina_sin_ficha('https://indra.cl'))
        self.assertTrue(bw._es_pagina_sin_ficha('https://indra.cl/'))
        self.assertFalse(bw._es_pagina_sin_ficha('https://indra.cl/producto/pastillas-bravo'))

    def test_fallback_a_url_context_si_tavily_sin_candidatos(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        tavily_resp = self._fake_tavily_resp([])  # Sin resultados: no se llama url_context.
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
                # Marca sin casa especialista configurada: una sola búsqueda.
                vehiculo={'marca': 'Toyota', 'modelo': 'Yaris', 'anio': 2010},
            )

        self.assertGreaterEqual(calls['tavily'], 1)
        # Tavily ya buscó en Chile: url_context no recupera el kit y suma minutos.
        self.assertEqual(calls['gemini_with_tools'], 0)

    def test_tavily_no_recorre_toda_la_escalera_del_kit(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls = {'n': 0}

        def fake_buscar(query, **kwargs):
            calls['n'] += 1
            return []

        escalera = bw._escalera_consultas(
            'Kit de embrague',
            marca='Kia',
            modelo='Morning',
            cilindraje='',
            casas=[],
        )
        self.assertGreater(len(escalera), bw._MAX_CONSULTAS_TAVILY_POR_LINEA)

        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None):
            bw._buscar_repuestos_web_tavily(
                ['Kit de embrague'],
                marca='Kia',
                modelo='Morning',
                anio=2011,
                cilindraje='',
                tipo_motor='',
                servicio_nombre='Cambio de kit de embrague',
                timeout=5,
            )

        self.assertEqual(calls['n'], bw._MAX_CONSULTAS_TAVILY_POR_LINEA)

    def test_tavily_corta_cuando_hay_dos_fichas_de_kit_sin_precio(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls = {'n': 0}

        def fake_buscar(query, **kwargs):
            calls['n'] += 1
            return [
                {
                    'title': 'KIT EMBRAGUE KIA MORNING 2012-2016',
                    'url': 'https://articulo.mercadolibre.cl/MLC-111-kit',
                    'content': 'Consultar precio',
                    'score': 0.9,
                },
                {
                    'title': 'KIT EMBRAGUE 3 PIEZAS KIA MORNING',
                    'url': 'https://www.refax.cl/producto/kit-morning',
                    'content': 'Stock disponible',
                    'score': 0.8,
                },
            ]

        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', return_value={}), patch.object(
            bw, '_gemini_generar', return_value=None,
        ):
            bw._buscar_repuestos_web_tavily(
                ['Kit de embrague'],
                marca='Kia',
                modelo='Morning',
                anio=2011,
                cilindraje='',
                tipo_motor='',
                servicio_nombre='Cambio de kit de embrague',
                timeout=5,
            )

        self.assertEqual(calls['n'], 1)


class PrecioDesdeTextoTestCase(SimpleTestCase):
    """El monto del snippet alimenta la cotización: no puede ser de otra moneda."""

    def test_acepta_pesos_con_signo_o_prefijo_clp(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        self.assertEqual(bw._precio_desde_texto('Termostato $ 18.990 envío gratis'), 18990)
        self.assertEqual(bw._precio_desde_texto('Disco ventilado 284mm $32.500'), 32500)
        self.assertEqual(bw._precio_desde_texto('CLP 34.990'), 34990)
        self.assertEqual(bw._precio_desde_texto('CLP$ 34.990'), 34990)

    def test_usa_precio_etiquetado_no_el_de_un_relacionado(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        snippet = (
            'KIT EMBRAGUE 5 PIEZAS CHEVROLET LUV 3.2 $447.000 Ver compatibilidad '
            'PRENSA EMBRAGUE HYUNDAI GRAN I10 1.2 2017-2019 Precio: $23.170'
        )
        self.assertEqual(
            bw._precio_desde_texto(snippet, 'Prensa embrague Hyundai Grand i10'),
            23170,
        )

    def test_kit_no_acepta_precio_de_prensa_ni_outlier(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        kit = 'Kit de embrague (disco, prensa y rodamiento de empuje)'
        self.assertFalse(bw._precio_plausible_para_linea(kit, 23170))
        self.assertFalse(bw._precio_plausible_para_linea(kit, 447000))
        self.assertTrue(bw._precio_plausible_para_linea(kit, 89900))
        self.assertFalse(bw._precio_plausible_para_linea('Aceite de caja de cambios', 300000))
        self.assertFalse(bw._precio_plausible_para_linea('Rodamiento de volante', 300000))
        self.assertTrue(bw._precio_plausible_para_linea('Rodamiento de volante', 12990))
        self.assertTrue(bw._precio_plausible_para_linea('Piola de embrague', 18990))
        self.assertFalse(
            bw._ficha_cubre_pieza(
                'Rodamiento de volante',
                'Volante bimasa Suzuki Celerio',
            )
        )
        self.assertFalse(
            bw._ficha_cubre_pieza(
                'Aceite de caja de cambios',
                'Kit de embrague Suzuki Celerio',
            )
        )
        self.assertFalse(
            bw._ficha_cubre_pieza(
                'Kit de embrague',
                'piola embrague suzuki celerio',
            )
        )
        self.assertTrue(
            bw._ficha_cubre_pieza(
                'Piola de embrague',
                'piola embrague suzuki celerio',
            )
        )
        self.assertTrue(
            bw._ficha_cubre_pieza(
                'Kit de embrague',
                'Kit embrague Suzuki Celerio 2016',
            )
        )
        self.assertFalse(
            bw._ficha_cubre_pieza(
                'Rodamiento de volante',
                'Rodamiento Suzuki',
            )
        )
        self.assertTrue(
            bw._ficha_cubre_pieza(
                'Rodamiento de volante',
                'Rodamiento piloto Suzuki Celerio',
            )
        )
        self.assertFalse(
            bw._candidato_sirve_linea(
                'Rodamiento de volante',
                {
                    'title': 'Rodamiento Suzuki',
                    'content': 'Envío gratis Precio $300.000',
                    'url': 'https://www.mundorepuestos.cl/rodamiento-suzuki',
                },
                anio=2016,
                modelo='CELERIO',
            )
        )
        self.assertTrue(
            bw._candidato_sirve_linea(
                'Kit de embrague',
                {
                    'title': 'Kit embrague Suzuki Celerio 2014-2018',
                    'content': 'Precio $89.900',
                    'url': 'https://www.repuestodo.cl/kit-embrague-celerio',
                },
                anio=2016,
                modelo='CELERIO',
            )
        )
        self.assertEqual(
            bw._precio_desde_texto('Precio: $89.900 En Stock', kit),
            89900,
        )
        self.assertEqual(
            bw._precio_desde_texto(
                'KIT EMBRAGUE 5 PIEZAS LUV $447.000 Precio: $23.170',
                kit,
            ),
            0,
        )

    def test_ignora_cuotas_y_toma_el_precio_de_lista(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        self.assertEqual(
            bw._precio_desde_texto(
                'Kit De Embrague Hyundai I10 Grand 1.2 $107.500 6 cuotas de $17.917 sin interés',
                'Kit de embrague',
            ),
            107500,
        )

    def test_ignora_montos_en_moneda_extranjera(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        self.assertEqual(bw._precio_desde_texto('US$ 45.00 shipping worldwide'), 0)
        self.assertEqual(bw._precio_desde_texto('USD 45.00'), 0)
        self.assertEqual(bw._precio_desde_texto('R$ 4.500'), 0)
        self.assertEqual(bw._precio_desde_texto('€ 45.00'), 0)

    def test_sin_monto_devuelve_cero(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        self.assertEqual(bw._precio_desde_texto('Consultar disponibilidad'), 0)
        self.assertEqual(bw._precio_desde_texto(''), 0)


class AtributosFichaTavilyTestCase(SimpleTestCase):
    def test_hits_desde_candidatos_marca_calidad_y_origen(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        out = bw._hits_desde_candidatos(
            {
                'Termostato': [{
                    'title': 'Termostato Gates Fiat Bravo',
                    'url': 'https://articulo.mercadolibre.cl/MLC-1-termostato',
                    'content': (
                        'Tipo: ALTERNATIVO. Gates. '
                        'Importado directamente de China. Precio $ 18.990'
                    ),
                }],
            },
            ['fiat', 'bravo'],
            marca_vehiculo='Fiat',
        )
        self.assertEqual(len(out), 1)
        hit = next(iter(out.values()))
        self.assertEqual(hit['marca_repuesto'], 'Gates')
        self.assertEqual(hit['calidad'], 'alternativo')
        self.assertEqual(hit['pais_origen'], 'China')
        self.assertEqual(hit['precio_clp'], 18990)

    def test_kit_embrague_no_toma_ficha_de_prensa(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        linea = 'Kit de embrague (disco, prensa y rodamiento de empuje)'
        titulo = 'PRENSA EMBRAGUE HYUNDAI GRAN I10 1.2 2017-2019'
        self.assertFalse(bw._ficha_cubre_pieza(linea, titulo))
        self.assertFalse(bw._ficha_cubre_anio(titulo, 2016))
        self.assertTrue(bw._ficha_cubre_anio(titulo, 2018))
        self.assertTrue(bw._ficha_cubre_pieza(
            linea,
            'KIT EMBRAGUE HYUNDAI GRAND I10 1.2 2014-2017',
        ))

        out = bw._hits_desde_candidatos(
            {
                linea: [{
                    'title': titulo,
                    'url': 'https://www.ciper.cl/prensa-embrague-hyundai-gran-i10-12-2017-2019-861864-2/p',
                    'content': 'PRENSA EMBRAGUE HYUNDAI GRAN I10 1.2 2017-2019 $447.000',
                }],
            },
            ['hyundai', 'grand', 'i10'],
            marca_vehiculo='Hyundai',
            anio=2016,
        )
        self.assertEqual(out, {})

    def test_kit_morning_acepta_ficha_con_anio_contiguo(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        linea = 'Kit de embrague'
        cand = {
            'title': 'KIT EMBRAGUE KIA MORNING 2012-2016',
            'content': 'Precio $89.900',
            'url': 'https://articulo.mercadolibre.cl/MLC-1-kit-morning',
        }
        self.assertTrue(bw._candidato_sirve_linea(linea, cand, anio=2011))
        self.assertFalse(bw._candidato_sirve_linea(linea, cand, anio=2008))
        prensa = {
            'title': 'PRENSA EMBRAGUE KIA MORNING 2012-2016',
            'content': 'Precio $23.170',
            'url': 'https://www.ciper.cl/prensa-morning/p',
        }
        self.assertFalse(bw._candidato_sirve_linea(linea, prensa, anio=2011))
        conjunto = {
            'title': 'DISCO PRENSA Y RODAMIENTO DE EMPUJE KIA MORNING 1.1 2012-2016',
            'content': 'Precio $82.900',
            'url': 'https://www.todoembragues.cl/disco-prensa-rodamiento-morning-11',
        }
        self.assertTrue(bw._candidato_sirve_linea(linea, conjunto, anio=2014, cilindraje='1.1'))
        self.assertFalse(bw._ficha_cubre_pieza('Disco de embrague', conjunto['title']))

    def test_kit_1_2_no_sirve_para_morning_1_1(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        linea = 'Kit de embrague'
        kit_12 = {
            'title': 'Kit de Embrague SECO Kia Morning 1.2 (3 piezas)',
            'content': 'Precio $89.900',
            'url': 'https://www.autoplanet.cl/producto/kit_de_embrague_seco_kia_morning_12_3_piezas/456966',
        }
        kit_11 = {
            'title': 'Kit Embrague Para Kia Morning 1.1 G4hg',
            'content': 'Prensa Disco Rodamiento $82.900 CLP',
            'url': 'https://www.todoembragues.cl/kit-embrague-para-kia-morning-1-1-g4hg',
        }
        self.assertFalse(bw._candidato_sirve_linea(linea, kit_12, anio=2008, cilindraje='1.1'))
        self.assertTrue(bw._candidato_sirve_linea(linea, kit_11, anio=2008, cilindraje='1.1'))

    def test_precio_todoembragues_toma_el_de_la_ficha(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        texto = (
            'Kit Embrague Para Kia Morning 1.1 G4hg\n'
            '$82.900 CLP\n'
            'Kit Embrague Para Kia Morning 1.0 G3la Kappa C\n'
            '$61.800 CLP'
        )
        self.assertEqual(
            bw._precio_desde_texto(texto, 'Kit de embrague'),
            82900,
        )

    def test_kit_ciper_tres_piezas_llena_la_linea(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        linea = 'Kit de embrague (disco, prensa y rodamiento de empuje)'
        out = bw._hits_desde_candidatos(
            {
                linea: [{
                    'title': 'KIT EMBRAGUE 3 PIEZAS HYUNDAI GRAN I10 1.2 2014-2018',
                    'url': 'https://www.ciper.cl/kit-embrague-3-piezas-hyundai-gran-i10-12-2014-2018-866844/p',
                    'content': (
                        'KIT EMBRAGUE 5 PIEZAS CHEVROLET LUV $447.000 '
                        'Precio: $89.900 En Stock GRAN I10 2016'
                    ),
                }],
            },
            ['hyundai', 'grand', 'i10'],
            marca_vehiculo='Hyundai',
            anio=2016,
        )
        self.assertEqual(len(out), 1)
        hit = next(iter(out.values()))
        self.assertEqual(hit['precio_clp'], 89900)
        self.assertIn('kit-embrague-3-piezas', hit['url'])

    def test_no_usa_la_marca_del_auto_como_marca_de_pieza(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        attrs = bw._atributos_desde_texto(
            'Marca: Fiat. Termostato para Bravo. $ 18.990',
            marca_vehiculo='Fiat',
        )
        self.assertEqual(attrs['marca_repuesto'], '')

    @override_settings(TAVILY_API_KEY='tvly-test')
    def test_extract_pide_chunks_de_marca_calidad_y_origen(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        seen = {}

        def fake_post(url, **kwargs):
            seen.update(kwargs.get('json') or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {'results': []}
            return resp

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            bw._tavily_extraer(['https://articulo.mercadolibre.cl/MLC-1'])

        self.assertIn('marca', seen.get('query', '').lower())
        self.assertIn('origen', seen.get('query', '').lower())
        self.assertEqual(seen.get('chunks_per_source'), 6)

    @override_settings(TAVILY_API_KEY='tvly-test')
    def test_extract_reintenta_sin_query_si_tavily_400(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        payloads = []

        def fake_post(url, **kwargs):
            payloads.append(kwargs.get('json') or {})
            resp = MagicMock()
            if len(payloads) == 1:
                resp.status_code = 400
                resp.text = '{"error":"query not supported"}'
                return resp
            resp.status_code = 200
            resp.json.return_value = {
                'results': [{
                    'url': 'https://articulo.mercadolibre.cl/MLC-1',
                    'raw_content': 'Pastillas Bosch Precio $ 45990',
                }],
            }
            return resp

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.post',
            side_effect=fake_post,
        ):
            out = bw._tavily_extraer(['https://articulo.mercadolibre.cl/MLC-1'])

        self.assertEqual(len(payloads), 2)
        self.assertIn('query', payloads[0])
        self.assertNotIn('query', payloads[1])
        self.assertIn('https://articulo.mercadolibre.cl/MLC-1', out)


class CoberturaPreciosComunesTests(SimpleTestCase):
    def test_escalera_termina_en_el_nombre_corto_sin_auto(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        qs = bw._escalera_consultas(
            'Filtro de aceite',
            marca='Ssangyong',
            modelo='Rexton',
            cilindraje='',
            casas=[],
        )
        normas = [bw._norm(q) for q in qs]
        self.assertIn('filtro aceite', normas)

    def test_escalera_kit_busca_como_google(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        qs = bw._escalera_consultas(
            'Kit de embrague',
            marca='Hyundai',
            modelo='Grand i10',
            cilindraje='1.2',
            casas=[],
        )
        self.assertTrue(qs)
        self.assertNotIn('3 piezas', qs[0].lower())
        self.assertIn('hyundai', qs[0].lower())
        self.assertIn('1.2', qs[0])

    def test_escalera_kit_morning_incluye_motor(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        qs = bw._escalera_consultas(
            'Kit de embrague',
            marca='Kia',
            modelo='Morning',
            cilindraje='1.1',
            casas=[],
            tipo_motor='G4HG',
        )
        self.assertIn('morning', qs[0].lower())
        self.assertIn('1.1', qs[0])
        self.assertIn('g4hg', qs[0].lower())
        self.assertNotIn('3 piezas', qs[0].lower())

    def test_match_nucleo_de_pieza_comun(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _match_score,
            min_score_web_para,
        )

        self.assertGreaterEqual(
            _match_score('filtro aceite motor rexton', 'filtro aceite mann'),
            70,
        )
        self.assertLessEqual(min_score_web_para('Filtro de aceite Ssangyong'), 40)

    @override_settings(TAVILY_API_KEY='tvly-test', GEMINI_API_KEY='k')
    def test_si_gemini_falla_conserva_el_precio_del_snippet(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        def fake_cands(query, _whitelist):
            q = query.lower()
            if 'filtro' in q:
                return [{
                    'title': 'Filtro aceite',
                    'url': 'https://www.autoplanet.cl/p/filtro',
                    'content': 'Filtro de aceite para motor. Stock en Chile.',
                }]
            return [{
                'title': 'Termostato Gates',
                'url': 'https://www.autoplanet.cl/p/termostato',
                'content': 'Termostato Gates. Precio $ 18.990. Envío Chile.',
            }]

        with patch.object(bw, '_candidatos_validos', side_effect=fake_cands), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', return_value={}), patch.object(
            bw, '_gemini_generar', return_value=None,
        ):
            out = bw._buscar_repuestos_web_tavily(
                ['Termostato', 'Filtro de aceite'],
                marca='Fiat',
                modelo='Bravo',
                anio=2010,
                cilindraje='',
                tipo_motor='',
                servicio_nombre='Mantención',
                timeout=10,
            )

        self.assertIn(bw._clave_fuzzy('Termostato'), out)
        self.assertEqual(out[bw._clave_fuzzy('Termostato')]['precio_clp'], 18990)


class RazonarYCortarBusquedaTests(SimpleTestCase):
    def test_plan_embrague_separa_kit_de_piola(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.razonar_pedido import (
            planificar,
        )

        plan = planificar(
            'servicio para cambio de kit de embrague, cambio piola de embrague',
            {'marca': 'SUZUKI', 'modelo': 'CELERIO', 'anio': 2016, 'cilindraje': '998'},
            usar_llm=False,
        )
        nombres = [p['nombre'] for p in plan['piezas']]
        self.assertIn('Kit de embrague', nombres)
        self.assertIn('Piola de embrague', nombres)
        self.assertIn('Rodamiento de volante', nombres)
        kit = next(p for p in plan['piezas'] if p['nombre'] == 'Kit de embrague')
        self.assertIn('kit', kit['consulta'])
        self.assertNotIn('piola', kit['consulta'])
        piloto = next(p for p in plan['piezas'] if 'volante' in p['nombre'])
        self.assertTrue(piloto['escasa'])
        self.assertIn('piloto', piloto['consulta'])
        self.assertIn('CELERIO', plan['razonamiento'])

    def test_ficha_ajena_corta_la_busqueda(self):
        from unittest.mock import patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.razonar_pedido import (
            planificar,
        )

        calls = {'n': 0}

        def fake_validos(query, _whitelist):
            calls['n'] += 1
            return [{
                'title': 'piola embrague suzuki celerio',
                'url': 'https://www.repuestodo.cl/piola-celerio',
                'content': 'Precio: $12.800',
            }]

        plan = planificar(
            'cambio de kit de embrague',
            {'marca': 'Suzuki', 'modelo': 'Celerio', 'anio': 2016},
            usar_llm=False,
        )
        avisos: dict = {}
        with patch.object(bw, '_candidatos_validos', side_effect=fake_validos), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None):
            out = bw._buscar_repuestos_web_tavily(
                ['Kit de embrague'],
                marca='Suzuki',
                modelo='Celerio',
                anio=2016,
                cilindraje='998',
                tipo_motor='GASOLINA',
                servicio_nombre='cambio de kit de embrague',
                timeout=5,
                avisos=avisos,
                plan=plan,
            )
        self.assertEqual(calls['n'], 1)
        self.assertEqual(out, {})
        self.assertEqual(avisos['Kit de embrague']['motivo'], 'sin_ficha')
        self.assertIn('piola', avisos['Kit de embrague']['detalle'].lower())


class CoberturaPiezasComunesTests(SimpleTestCase):
    """Cotización 184: pastillas y aceite 5W40 quedaron sin tienda.

    La escalera gastaba las 3 consultas en 'cerámica' / 'TISS' / 'Sport T-Jet'.
    La casa publica 'Pastilla freno delantera Fiat Bravo' y 'Aceite 5W40 4L'.
    """

    def test_escalera_de_pastillas_no_lleva_ceramica_ni_la_version(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        qs = bw._escalera_consultas(
            'Pastillas de freno cerámica delanteras',
            marca='Fiat',
            modelo='BRAVO SPORT TJET',
            cilindraje='1.4',
            casas=[{'alias': 'indra repuestos', 'nombre': 'Indra'},
                   {'alias': 'Frenos Vergara', 'nombre': 'Frenos Vergara'}],
        )
        self.assertEqual(qs[0], 'pastillas freno delanteras fiat bravo 1.4')
        self.assertEqual(qs[1], 'pastillas freno fiat bravo')
        self.assertEqual(qs[2], 'pastillas freno fiat linea t-jet')
        self.assertNotIn('stilo', ' '.join(qs).lower())
        for q in qs:
            self.assertNotIn('ceramica', bw._norm(q))
            self.assertNotIn('sport', q.lower())
            self.assertNotIn('tjet', q.lower())
            self.assertNotIn('2010', q)
            self.assertNotIn('indra', q.lower())
            self.assertNotIn('vergar', q.lower())

    def test_escalera_de_aceite_guarda_la_viscosidad_y_suelta_la_marca(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        qs = bw._escalera_consultas(
            'Aceite de motor TISS 5W40 sintético',
            marca='Fiat',
            modelo='BRAVO SPORT TJET',
            cilindraje='1.4',
            casas=[{'alias': 'Frenos Vergara', 'nombre': 'Frenos Vergara'}],
        )
        self.assertEqual(qs[0], 'aceite 5w40 sintetico 4 litros')
        self.assertEqual(qs[1], 'aceite motor 5w40 1 litro')
        for q in qs:
            self.assertNotIn('fiat', q.lower())
            self.assertNotIn('bravo', q.lower())
            self.assertNotIn('tiss', q.lower())
            self.assertNotIn('sport', q.lower())
            self.assertNotIn('vergar', q.lower())

        corta = bw._escalera_consultas(
            'Aceite 5W-40 sintético',
            marca='Fiat',
            modelo='Bravo',
            cilindraje='',
            casas=[],
        )
        self.assertEqual(corta[0], 'aceite 5w40 sintetico 4 litros')
        self.assertEqual(corta[1], 'aceite motor 5w40 1 litro')

    def test_titulos_de_tienda_si_son_la_pieza(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _titulo_nombra_pieza,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _producto_es_la_pieza,
        )

        pastillas = 'Pastillas de freno cerámica delanteras'
        aceite = 'Aceite 5W40 sintético'
        self.assertTrue(_titulo_nombra_pieza(pastillas, 'Pastilla freno delantera Fiat Bravo'))
        self.assertTrue(_producto_es_la_pieza(
            pastillas, 'Pastilla freno delantera Fiat Bravo', fuente='web',
        ))
        self.assertTrue(_titulo_nombra_pieza(aceite, 'Aceite 5W40 4L'))
        self.assertTrue(_producto_es_la_pieza(aceite, 'Aceite 5W40 4L', fuente='web'))
        self.assertFalse(_titulo_nombra_pieza(
            pastillas, 'Repuestos Fiat Bravo | Mundo Repuestos Chile',
        ))
        self.assertFalse(_producto_es_la_pieza(
            aceite, 'Enfriador aceite Fiat Bravo 1.4', fuente='web',
        ))
        self.assertFalse(_producto_es_la_pieza(
            'Filtro de aceite', 'Aceite 5W40 4L', fuente='web',
        ))
        self.assertTrue(_titulo_nombra_pieza(
            'Aceite de motor', 'Aceite Motor Shell Helix HX8 5W40 4L',
        ))
        self.assertTrue(_producto_es_la_pieza(
            'Aceite de motor', 'Aceite Motor Shell Helix HX8 5W40 4L', fuente='web',
        ))
        self.assertTrue(_titulo_nombra_pieza(
            'Pastillas de freno delanteras',
            'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
        ))
        self.assertTrue(bw._candidato_sirve_linea(
            'Pastillas de freno delanteras',
            {
                'title': 'Pastillas de Freno Delanteras compatibles Fiat Bravo, Stilo y Grande Punto',
                'content': 'Juego delantero para varios Fiat. Precio $ 24.990',
                'url': 'https://www.mundorepuestos.cl/pastillas-bravo-stilo-punto',
            },
            anio=2010,
            cilindraje='1.4',
            modelo='BRAVO SPORT TJET',
        ))

    def test_bidon_de_4_litros_se_cotiza_por_litro(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            precio_unitario_desde_envase,
        )

        unit, nota = precio_unitario_desde_envase(
            'Aceite 5W40 sintético', 39960, 'Aceite 5W40 4L',
        )
        self.assertEqual(unit, 9990)
        self.assertIn('4 L', nota)
        self.assertIn('39.960', nota)
        self.assertIn('9.990', nota)
        self.assertIn('litro', nota)

        igual, sin_nota = precio_unitario_desde_envase(
            'Aceite 5W40 sintético', 12990, 'Aceite 5W40 1L',
        )
        self.assertEqual(igual, 12990)
        self.assertEqual(sin_nota, '')

        pastilla, nota_pastilla = precio_unitario_desde_envase(
            'Pastillas de freno cerámica delanteras', 24990, 'Pastilla freno delantera Fiat Bravo',
        )
        self.assertEqual(pastilla, 24990)
        self.assertEqual(nota_pastilla, '')

        litros, nota_lts = precio_unitario_desde_envase(
            'Aceite de motor', 40000, 'Aceite motor 5W40 4 litros',
        )
        self.assertEqual(litros, 10000)
        self.assertIn('litro', nota_lts)

        cinco, nota_cinco = precio_unitario_desde_envase(
            'Aceite de motor', 49950, 'Aceite Motor 5W40 5L',
        )
        self.assertEqual(cinco, 9990)
        self.assertIn('5 L', nota_cinco)

        uno, sin_nota_uno = precio_unitario_desde_envase(
            'Aceite de motor', 12990, 'Aceite Motor Shell Helix 5W40 1L',
        )
        self.assertEqual(uno, 12990)
        self.assertEqual(sin_nota_uno, '')

    def test_plan_largo_no_pisa_la_consulta_corta_y_acepta_la_ficha(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls: list[str] = []

        def fake_validos(query, _whitelist):
            calls.append(query)
            q = bw._norm(query)
            if 'ceramica' in q or 'sport' in q or 'tjet' in q:
                return [{
                    'title': 'Repuestos Fiat Bravo | Mundo Repuestos Chile',
                    'url': 'https://www.mundorepuestos.cl/repuestos-fiat-bravo',
                    'content': 'Catálogo. Precio $ 15.990',
                }]
            return [{
                'title': 'Pastilla freno delantera Fiat Bravo',
                'url': 'https://www.mundorepuestos.cl/pastilla-freno-delantera-fiat-bravo',
                'content': 'Pastilla de freno delantera. Precio $ 24.990',
            }]

        plan = {
            'piezas': [{
                'nombre': 'Pastillas de freno cerámica delanteras',
                'consulta': 'Pastillas de freno cerámica delanteras Fiat Bravo Sport Tjet 1.4',
                'escasa': False,
            }],
        }
        with patch.object(bw, '_candidatos_validos', side_effect=fake_validos), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None):
            out = bw._buscar_repuestos_web_tavily(
                ['Pastillas de freno cerámica delanteras'],
                marca='Fiat',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='',
                servicio_nombre='Mantención',
                timeout=5,
                plan=plan,
            )

        self.assertTrue(calls)
        self.assertNotIn('ceramica', bw._norm(calls[0]))
        self.assertNotIn('sport', bw._norm(calls[0]))
        self.assertIn('pastilla', bw._norm(calls[0]))
        self.assertIn('bravo', bw._norm(calls[0]))
        hit = out[bw._clave_fuzzy('Pastillas de freno cerámica delanteras')]
        self.assertEqual(hit['precio_clp'], 24990)
        self.assertIn('Pastilla', hit['nombre_producto'])
        self.assertNotIn('Mundo Repuestos Chile', hit['nombre_producto'])

    def test_listado_generico_no_corta_la_busqueda_y_el_aviso_dice_por_que(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls: list[str] = []

        def fake_validos(query, _whitelist):
            calls.append(query)
            return [{
                'title': 'Repuestos Fiat Bravo | Mundo Repuestos Chile',
                'url': f'https://www.mundorepuestos.cl/listado-{len(calls)}',
                'content': 'Repuestos para Fiat Bravo. Precio $ 15.990',
            }]

        avisos: dict = {}
        with patch.object(bw, '_candidatos_validos', side_effect=fake_validos), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None):
            out = bw._buscar_repuestos_web_tavily(
                ['Pastillas de freno cerámica delanteras'],
                marca='Fiat',
                modelo='Bravo',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='',
                servicio_nombre='Mantención',
                timeout=5,
                avisos=avisos,
            )

        self.assertEqual(out, {})
        self.assertEqual(len(calls), 2)
        detalle = avisos['Pastillas de freno cerámica delanteras']['detalle']
        self.assertIn('Se buscó', detalle)
        self.assertIn('pastillas freno delanteras fiat bravo 1.4', detalle)
        self.assertIn('pastillas freno fiat bravo', detalle)
        self.assertIn('Repuestos Fiat Bravo', detalle)
        self.assertIn('no es esa pieza', detalle)
        self.assertNotIn('No se encontraron proveedores con este repuesto en stock', detalle)

    def test_log_de_tavily_lista_consultas_y_el_rechazo(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        def fake_validos(query, _whitelist):
            return [{
                'title': 'Enfriador aceite Fiat Bravo 1.4',
                'url': 'https://euroespecialista.cl/enfriador-aceite-fiat-bravo',
                'content': 'Enfriador de aceite. Precio $ 31.490',
            }]

        with patch.object(bw, '_candidatos_validos', side_effect=fake_validos), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            bw._buscar_repuestos_web_tavily(
                ['Aceite 5W40 sintético'],
                marca='Fiat',
                modelo='Bravo',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='',
                servicio_nombre='Mantención',
                timeout=5,
            )

        texto = '\n'.join(logs.output)
        self.assertIn('busqueda_web_repuestos[tavily]', texto)
        self.assertIn('queries=', texto)
        self.assertIn('5w', texto.lower())
        self.assertIn('Enfriador', texto)
        self.assertTrue(
            'otra pieza' in texto or 'no es esa pieza' in texto,
            texto,
        )
        self.assertRegex(texto, r'n=\d+/\d+')
        self.assertIn('candidatos=', texto)

    def test_aceite_5w40_acepta_la_ficha_del_bidon(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls: list[str] = []

        def fake_validos(query, _whitelist):
            calls.append(query)
            return [{
                'title': 'Aceite Motor Shell Helix HX8 5W40 4L',
                'url': 'https://www.todoautochile.cl/aceite-shell-helix-5w40-4l',
                'content': 'Aceite sintético 5W40 envase 4 litros. Precio $ 39.960',
            }]

        with patch.object(bw, '_candidatos_validos', side_effect=fake_validos), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None):
            out = bw._buscar_repuestos_web_tavily(
                ['Aceite de motor TISS 5W40 sintético'],
                marca='Fiat',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='',
                servicio_nombre='Mantención',
                timeout=5,
            )

        self.assertEqual(calls[0], 'aceite 5w40 sintetico 4 litros')
        self.assertNotIn('fiat', calls[0])
        hit = out[bw._clave_fuzzy('Aceite de motor TISS 5W40 sintético')]
        self.assertEqual(hit['precio_clp'], 39960)
        self.assertEqual(hit['nombre_producto'], 'Aceite Motor Shell Helix HX8 5W40 4L')
        por_litro, nota = bw.precio_unitario_desde_envase(
            'Aceite de motor TISS 5W40 sintético',
            hit['precio_clp'],
            hit['nombre_producto'],
        )
        self.assertEqual(por_litro, 9990)
        self.assertIn('litro', nota)

    def test_cotizacion_7_busca_aceite_por_spec_y_pastillas_sin_trim(self):
        """Cotización 7: el plan largo y 'Frenos Vergara' no son las consultas.

        El aceite se busca por viscosidad y envase. Las pastillas, por modelo
        sin trim ni año. Una ficha que lista varios autos compatibles entra.
        """
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls: list[str] = []

        def fake_buscar(query, **kwargs):
            calls.append(query)
            q = bw._norm(query)
            if 'pastilla' in q and 'delantera' in q:
                return [{
                    'title': 'Repuestos Fiat Bravo | Mundo Repuestos Chile',
                    'url': 'https://www.mundorepuestos.cl/repuestos-fiat-bravo',
                    'content': 'Catálogo. Precio $ 15.990',
                    'score': 0.4,
                }]
            if 'pastilla' in q:
                return [{
                    'title': 'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
                    'url': 'https://www.todoautochile.cl/pastillas-fiat-bravo-14',
                    'content': (
                        'Compatibles con Fiat Bravo, Stilo y Grande Punto. Precio $ 24.990'
                    ),
                    'score': 0.9,
                }]
            if '4 litros' in q:
                return [
                    {
                        'title': 'Bomba de aceite Fiat Bravo 1.4',
                        'url': 'https://euroespecialista.cl/bomba-aceite-fiat-bravo',
                        'content': 'Bomba de aceite. Precio $ 62.991',
                        'score': 0.8,
                    },
                    {
                        'title': 'Aceite Motor Shell Helix HX8 5W40 4L',
                        'url': 'https://www.todoautochile.cl/shell-helix-hx8-5w40-4l',
                        'content': 'Aceite de motor sintético 5W40, bidón de 4 litros. Precio $ 39.960',
                        'score': 0.9,
                    },
                ]
            return [{
                'title': 'Aceite Motor Shell Helix 5W40 1L',
                'url': 'https://www.todoautochile.cl/shell-helix-5w40-1l',
                'content': 'Botella 1 litro. Precio $ 12.990',
                'score': 0.7,
            }]

        plan = {
            'piezas': [
                {
                    'nombre': 'Pastillas de freno delanteras',
                    'consulta': 'Pastillas de freno delanteras FIAT BRAVO SPORT TJET 2010 1.4',
                    'escasa': True,
                },
                {
                    'nombre': 'Aceite de motor',
                    'consulta': 'Aceite de motor FIAT Bravo Sport Tjet 1.4 Frenos Vergara',
                    'escasa': False,
                },
            ],
        }
        with patch.object(
            bw, '_especialistas_de_marca',
            return_value=[{
                'alias': 'Frenos Vergara',
                'nombre': 'Frenos Vergara',
                'dominio': 'frenosvergara.cl',
                'marcas': ['fiat'],
            }],
        ), patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                ['Pastillas de freno delanteras', 'Aceite de motor'],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='TJET',
                servicio_nombre='Cambio de pastillas de freno delanteras',
                timeout=5,
                plan=plan,
                especificaciones={'Aceite de motor': '5W40 sintético'},
            )

        self.assertIn('pastillas freno delanteras fiat bravo 1.4', calls)
        self.assertIn('pastillas freno fiat bravo', calls)
        self.assertIn('aceite 5w40 sintetico 4 litros', calls)
        for q in calls:
            self.assertNotIn('2010', q)
            self.assertNotIn('SPORT', q)
            self.assertNotIn('Tjet', q)
            self.assertNotIn('Vergara', q)
            self.assertNotIn('TISS', q)
        texto = '\n'.join(logs.output)
        self.assertIn('resultados=', texto)
        self.assertRegex(texto, r'resultados=[1-9]')
        pastillas = out[bw._clave_fuzzy('Pastillas de freno delanteras')]
        self.assertEqual(pastillas['precio_clp'], 24990)
        self.assertIn('Fiat Bravo', pastillas['nombre_producto'])
        self.assertIn('T-Jet', pastillas['nombre_producto'])
        aceite = out[bw._clave_fuzzy('Aceite de motor')]
        self.assertEqual(aceite['nombre_producto'], 'Aceite Motor Shell Helix HX8 5W40 4L')
        self.assertNotIn('Bomba', aceite['nombre_producto'])
        por_litro, _nota = bw.precio_unitario_desde_envase(
            'Aceite de motor', aceite['precio_clp'], aceite['nombre_producto'],
        )
        self.assertEqual(por_litro, 9990)

    def test_nota_lista_los_titulos_rechazados(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        def fake_buscar(query, **kwargs):
            return [
                {
                    'title': 'Enfriador aceite Fiat Bravo 1.4',
                    'url': 'https://euroespecialista.cl/enfriador-aceite',
                    'content': 'Enfriador de aceite. Precio $ 31.490',
                    'score': 0.9,
                },
                {
                    'title': 'Bomba de aceite Fiat Bravo 1.4',
                    'url': 'https://euroespecialista.cl/bomba-aceite',
                    'content': 'Bomba de aceite. Precio $ 62.991',
                    'score': 0.8,
                },
            ]

        avisos: dict = {}
        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                ['Aceite de motor'],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='',
                servicio_nombre='Cambio de aceite',
                timeout=5,
                avisos=avisos,
                especificaciones={'Aceite de motor': '5W40 sintético'},
            )

        self.assertEqual(out, {})
        detalle = avisos['Aceite de motor']['detalle']
        self.assertIn('aceite 5w40 sintetico 4 litros', detalle)
        self.assertIn('aceite motor 5w40 1 litro', detalle)
        self.assertIn('Enfriador aceite Fiat Bravo 1.4', detalle)
        self.assertIn('Bomba de aceite Fiat Bravo 1.4', detalle)
        self.assertNotIn('Frenos Vergara', detalle)
        self.assertNotIn('2010', detalle)
        self.assertIn('resultados=', '\n'.join(logs.output))

    def test_pastillas_recorren_la_escalera_aunque_la_primera_tenga_precio(self):
        """Cotización 8: un snippet con precio no puede comerse las otras consultas."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls: list[str] = []

        def fake_buscar(query, **kwargs):
            calls.append(query)
            q = query.lower()
            if q == 'pastillas freno delanteras fiat bravo 1.4':
                return [{
                    'title': 'Pastillas de freno',
                    'url': 'https://www.sodimac.cl/sodimac-cl/articulo/123/pastillas',
                    'content': 'Pastillas de freno genéricas. Precio $ 18.990',
                    'score': 0.5,
                }]
            if q == 'pastillas freno fiat bravo':
                return [{
                    'title': 'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
                    'url': 'https://frenosvergara.shop/products/pastillas-fiat-bravo',
                    'content': 'Juego delantero Fiat Bravo. Precio $ 28.990',
                    'score': 0.9,
                }]
            if 'linea' in q:
                return [{
                    'title': 'Pastillas de Freno Delanteras Fiat Bravo, Linea y Punto 1.4 T-Jet',
                    'url': 'https://www.mundorepuestos.cl/producto/pastillas-bravo-linea-punto',
                    'content': 'Compatibles Fiat Bravo T-Jet, Linea T-Jet y Punto T-Jet. Precio $ 32.990',
                    'score': 0.8,
                }]
            return []

        plan = {
            'piezas': [{
                'nombre': 'Pastillas de freno delanteras',
                'consulta': 'Pastillas de freno delanteras FIAT BRAVO SPORT TJET 2010 1.4',
                'escasa': True,
            }],
        }
        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_gemini_generar', return_value=None), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                ['Pastillas de freno delanteras'],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='TJET',
                servicio_nombre='Cambio de pastillas de freno delanteras',
                timeout=5,
                plan=plan,
            )

        self.assertEqual(calls, [
            'pastillas freno delanteras fiat bravo 1.4',
            'pastillas freno fiat bravo',
            'pastillas freno fiat linea t-jet',
        ])
        self.assertNotIn('stilo', ' '.join(calls))
        texto = '\n'.join(logs.output)
        self.assertIn('resultados=1', texto)
        self.assertIn('fichas=1', texto)
        hit = out[bw._clave_fuzzy('Pastillas de freno delanteras')]
        self.assertIn('frenosvergara.shop', hit['url'])
        self.assertEqual(hit['precio_clp'], 28990)
        self.assertIn('Bravo', hit['nombre_producto'])
        self.assertNotIn('sodimac', hit['url'])

    def test_fichas_chilenas_de_pastillas_no_las_bota_el_filtro(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        wl = bw._dominios_whitelist()
        tiendas = [
            'https://frenosvergara.shop/products/pastillas-fiat-bravo',
            'https://www.mundorepuestos.cl/producto/pastillas-freno-delanteras-fiat-bravo',
            'https://articulo.mercadolibre.cl/MLC-123456789-pastillas-freno-fiat-bravo',
        ]
        for url in tiendas:
            self.assertTrue(bw._es_tienda_chilena(url, wl, ''), url)
            self.assertFalse(bw._es_pagina_sin_ficha(url), url)
            self.assertFalse(bw._es_listado_sin_vendedor(url), url)
        self.assertTrue(bw._es_listado_sin_vendedor(
            'https://listado.mercadolibre.cl/pastillas-fiat-bravo',
        ))
        self.assertTrue(bw._candidato_sirve_linea(
            'Pastillas de freno delanteras',
            {
                'title': 'Pastillas de Freno Delanteras Fiat Bravo, Linea y Punto 1.4 T-Jet',
                'content': 'Compatibles con Fiat Bravo T-Jet y Fiat Linea T-Jet.',
                'url': 'https://www.mundorepuestos.cl/producto/pastillas-bravo-linea',
            },
            anio=2010,
            cilindraje='1.4',
            modelo='BRAVO SPORT TJET',
        ))
        self.assertEqual(
            bw._consultas_pastillas(
                'Pastillas de freno delanteras',
                marca='Fiat',
                modelo='Bravo',
                cilindraje='1.4',
            ),
            [
                'pastillas freno delanteras fiat bravo 1.4',
                'pastillas freno fiat bravo',
            ],
        )

    def test_el_modelo_no_cruza_pastillas_aceite_y_filtro_por_nombre_o_indice(self):
        """Cotización 9: 8 fichas de pastillas y el JSON de Gemini las pierde.

        El modelo devuelve el aceite en el primer ítem con el nombre de las
        pastillas, las pastillas con el nombre ya renombrado del aceite, y el
        filtro al final. La URL de cada ficha es la que manda, no el índice.
        Los snippets no traen precio: si el cruce se descarta, no hay rescate.
        """
        import json

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        pad_url = 'https://frenosvergara.shop/products/pastillas-fiat-bravo'
        oil_url = 'https://www.mundorepuestos.cl/producto/aceite-liqui-moly-5w40-4l'
        filter_url = 'https://www.todoautochile.cl/filtro-aceite-bravo'

        def fake_buscar(query, **kwargs):
            q = query.lower()
            if 'pastilla' in q:
                return [{
                    'title': 'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
                    'url': pad_url,
                    'content': 'Juego delantero Fiat Bravo. Consultar stock en tienda.',
                    'score': 0.9,
                }]
            if 'filtro' in q:
                return [{
                    'title': 'Filtro de aceite Mann Fiat Bravo',
                    'url': filter_url,
                    'content': 'Filtro de aceite para Fiat Bravo. Consultar stock.',
                    'score': 0.8,
                }]
            if 'aceite' in q:
                return [{
                    'title': 'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
                    'url': oil_url,
                    'content': 'Lubricante sintético. Consultar stock.',
                    'score': 0.9,
                }]
            return []

        gemini = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({'resultados': [
                            {
                                'nombre_buscado': 'Pastillas de freno delanteras',
                                'encontrado': True,
                                'nombre_producto': 'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
                                'precio_clp': 39960,
                                'tienda': 'Mundo Repuestos',
                                'url': oil_url,
                                'compatibilidad': 'alta',
                            },
                            {
                                'nombre_buscado': 'Aceite de motor Liqui Moly',
                                'encontrado': True,
                                'nombre_producto': 'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
                                'precio_clp': 28990,
                                'tienda': 'Frenos Vergara',
                                'url': pad_url,
                                'compatibilidad': 'alta',
                            },
                            {
                                'nombre_buscado': 'Pastillas de freno delanteras',
                                'encontrado': True,
                                'nombre_producto': 'Filtro de aceite Mann Fiat Bravo',
                                'precio_clp': 10990,
                                'tienda': 'Todoautochile',
                                'url': filter_url,
                                'compatibilidad': 'media',
                            },
                        ]}),
                    }],
                },
            }],
        }
        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', return_value={}), patch.object(
            bw, '_gemini_generar', return_value=gemini,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                [
                    'Pastillas de freno delanteras',
                    'Filtro de aceite',
                    'Aceite de motor',
                ],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='TJET',
                servicio_nombre='Cambio de pastillas, filtro y aceite',
                timeout=5,
                plan={'piezas': []},
            )

        texto = '\n'.join(logs.output)
        pads = out[bw._clave_fuzzy('Pastillas de freno delanteras')]
        aceite = out[bw._clave_fuzzy('Aceite de motor')]
        filtro = out[bw._clave_fuzzy('Filtro de aceite')]
        self.assertEqual(pads['url'], pad_url)
        self.assertIn('Pastillas', pads['nombre_producto'])
        self.assertNotIn('Liqui', pads['nombre_producto'])
        self.assertEqual(pads['precio_clp'], 28990)
        self.assertEqual(aceite['url'], oil_url)
        self.assertIn('Liqui Moly', aceite['nombre_producto'])
        self.assertEqual(aceite['precio_clp'], 39960)
        self.assertEqual(aceite['nombre_buscado'], 'Aceite de motor')
        self.assertEqual(filtro['url'], filter_url)
        self.assertIn('Filtro', filtro['nombre_producto'])
        self.assertIn('elegido linea=Pastillas de freno delanteras', texto)
        self.assertIn(pad_url, texto)
        self.assertIn('reasignado', texto)


class PrecioDesdeHtmlTestCase(SimpleTestCase):
    """28990.00 es 28990. _to_int_clp juntaría los decimales y daría 2.899.000."""

    def test_shopify_jsonld_y_og_no_toman_el_relacionado_ni_los_centavos(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _to_int_clp,
        )

        self.assertEqual(_to_int_clp('28990.00'), 2899000)
        self.assertEqual(bw._parse_monto_clp('28990.00'), 28990)
        self.assertEqual(bw._parse_monto_clp('28.990'), 28990)
        html = """
        <html><head>
          <link href="https://cdn.shopify.com/s/files/theme.css">
          <meta content="28990.00" property="og:price:amount">
          <script type="application/ld+json">
          {"@context":"https://schema.org","@graph":[{
            "@type":"Product",
            "name":"Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet",
            "offers":{"@type":"Offer","price":"28990.00","priceCurrency":"CLP"}
          }]}
          </script>
        </head><body>
          <script type="application/json">{"variants":[{"price":2899000}]}</script>
          <p>Relacionados $ 99.990</p>
        </body></html>
        """
        self.assertEqual(
            bw._precio_desde_html(
                html,
                'Pastillas de freno delanteras',
                url='https://frenosvergara.shop/products/pastillas-fiat-bravo',
            ),
            28990,
        )

    def test_shopify_solo_centavos_del_variant(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        html = """
        <html><head><link href="https://cdn.shopify.com/s/files/theme.css"></head>
        <body>
          <script type="application/json">
            {"title":"Pastillas de Freno Delanteras Fiat Bravo","variants":[{"price":2899000,"compare_at_price":3599000}]}
          </script>
          <p>También $ 99.990</p>
        </body></html>
        """
        self.assertEqual(
            bw._precio_desde_html(html, 'Pastillas de freno delanteras', url='https://frenosvergara.shop/products/x'),
            28990,
        )

    def test_mercadolibre_jsonld(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        html = """
        <html><head>
          <script type="application/ld+json">
            {"@type":"Product","name":"Pastillas Frasle PD/92 Fiat Bravo",
             "offers":{"@type":"Offer","price":32990,"priceCurrency":"CLP"}}
          </script>
        </head><body>
          <span class="andes-money-amount__fraction">32.990</span>
          <span class="andes-money-amount__fraction">1.990</span>
        </body></html>
        """
        self.assertEqual(
            bw._precio_desde_html(
                html,
                'Pastillas de freno delanteras',
                url='https://articulo.mercadolibre.cl/MLC-998877-pastillas-bravo',
            ),
            32990,
        )

    def test_woocommerce_toma_el_primer_monto_de_la_ficha(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        html = """
        <div class="summary">
          <p class="price"><span class="woocommerce-Price-amount amount"><bdi>
            <span class="woocommerce-Price-currencySymbol">$</span>24.990
          </bdi></span></p>
        </div>
        <ul class="products"><span class="woocommerce-Price-amount amount"><bdi>$9.990</bdi></span></ul>
        """
        self.assertEqual(
            bw._precio_desde_html(html, 'Pastillas de freno delanteras', url='https://www.mundorepuestos.cl/producto/pastillas'),
            24990,
        )

    def test_jsonld_en_dolares_no_es_precio(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        html = """
        <script type="application/ld+json">
          {"@type":"Product","offers":{"price":"45.00","priceCurrency":"USD"}}
        </script>
        """
        self.assertEqual(bw._precio_desde_html(html, 'Pastillas de freno delanteras'), 0)


class FichaSinPrecioEnSnippetTests(SimpleTestCase):
    def test_pastillas_sin_precio_leen_la_ficha_y_dejan_el_aceite_fuera(self):
        """Cotización 10: 8 candidatos, snippets sin monto, y se saltaba la página."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        urls = [
            'https://frenosvergara.shop/products/pastillas-fiat-bravo',
            'https://frenosvergara.shop/products/pastillas-bravo-2',
            'https://frenosvergara.shop/products/pastillas-bravo-3',
            'https://frenosvergara.shop/products/pastillas-bravo-4',
            'https://frenosvergara.shop/products/pastillas-fuera-de-banda',
            'https://frenosvergara.shop/products/pastillas-bravo-6',
            'https://frenosvergara.shop/products/pastillas-bravo-7',
            'https://www.mundorepuestos.cl/producto/aceite-liqui-moly-5w40-4l',
        ]
        # Mismo calce de auto y la misma casa: el orden de entrada es el cupo.
        titulos = [
            'Pastillas de freno delanteras Fiat Bravo 1.4 T-Jet',
            'Pastillas de freno delanteras Fiat Bravo 1.4 T-Jet dos',
            'Pastillas de freno delanteras Fiat Bravo 1.4 T-Jet tres',
            'Pastillas de freno delanteras Fiat Bravo 1.4 T-Jet cuatro',
            'Pastillas de freno delanteras Fiat Bravo 1.4 T-Jet cinco',
            'Pastillas de freno delanteras Fiat Bravo 1.4 T-Jet seis',
            'Pastillas de freno delanteras Fiat Bravo 1.4 T-Jet siete',
            'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
        ]
        ficha = """
        <html><head>
          <link href="https://cdn.shopify.com/s/files/theme.css">
          <meta property="og:price:amount" content="28990.00">
          <script type="application/ld+json">
            {"@type":"Product","name":"Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet",
             "offers":{"@type":"Offer","price":"28990.00","priceCurrency":"CLP"}}
          </script>
        </head><body>
          <script type="application/json">{"variants":[{"price":2899000}]}</script>
          Relacionados $ 99.990
        </body></html>
        """
        fuera = '<html><head><meta property="og:price:amount" content="900000"></head></html>'
        vacia = '<html><body>Consultar stock en tienda</body></html>'
        paginas = {urls[0]: ficha, urls[1]: vacia, urls[2]: vacia, urls[4]: fuera}
        pedidos: list[str] = []

        def fake_buscar(query, **kwargs):
            if 'pastilla' not in query.lower():
                return []
            return [
                {'title': titulos[i], 'url': urls[i], 'content': 'Consultar stock en tienda.', 'score': 0.8}
                for i in range(8)
            ]

        def fake_html(lista):
            pedidos.extend(lista)
            return {url: paginas[url] for url in lista if url in paginas}

        gemini = MagicMock()
        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', side_effect=fake_html), patch.object(
            bw, '_gemini_generar', gemini,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                ['Pastillas de freno delanteras'],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='TJET',
                servicio_nombre='Cambio de pastillas',
                timeout=5,
                plan={'piezas': []},
            )

        hit = out[bw._clave_fuzzy('Pastillas de freno delanteras')]
        self.assertEqual(hit['url'], urls[0])
        self.assertEqual(hit['precio_clp'], 28990)
        self.assertIn('Pastillas', hit['nombre_producto'])
        self.assertNotIn('Liqui', hit['nombre_producto'])
        gemini.assert_not_called()
        self.assertIn(urls[0], pedidos)
        self.assertIn(urls[3], pedidos)
        self.assertNotIn(urls[5], pedidos)
        self.assertNotIn(urls[7], pedidos)
        texto = '\n'.join(logs.output)
        motivos = {
            urls[0]: 'elegido',
            urls[1]: 'sin_precio',
            urls[2]: 'sin_precio',
            urls[3]: 'ficha_no_leida',
            urls[4]: 'precio_fuera_de_banda',
            urls[5]: 'fuera_del_cupo',
            urls[6]: 'fuera_del_cupo',
            urls[7]: 'titulo_no_es_la_pieza',
        }
        for url, titulo, motivo in zip(urls, titulos, (motivos[u] for u in urls)):
            self.assertIn(titulo, texto)
            self.assertIn(
                f'url={url} motivo={motivo}',
                texto,
            )


class CalidadFichaQuote11Tests(SimpleTestCase):
    """Cotización 11: listado Fiat genérico, marca cortada, casa 'Repuestos' y el tachado."""

    def test_precio_actual_no_el_tachado_y_el_litro_sale_del_bidon(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        html = """
        <html><head>
          <title>Aceite Para Motor Liqui Moly Sintético 5w-40 4L | Sergio Escobar Repuestos</title>
          <script type="application/ld+json">
            {"@type":"Product","name":"Aceite Para Motor Liqui Moly Sintético 5w-40 4L",
             "offers":{"@type":"Offer","price":"58500","priceCurrency":"CLP"}}
          </script>
        </head><body>
          <h1>Aceite Para Motor Liqui Moly Sintético 5w-40 4L</h1>
          <p class="price">
            <del><span class="woocommerce-Price-amount amount"><bdi>$58.500</bdi></span></del>
            <ins><span class="woocommerce-Price-amount amount"><bdi>$52.650</bdi></span></ins>
          </p>
          <p>El precio original era: $58.500. El precio actual es: $52.650.</p>
          <p>Marca: Liqui Moly</p>
          <table><tr><td>Marca</td><td>Liqui Moly</td></tr></table>
        </body></html>
        """
        url = (
            'https://repuestos.sergioescobar.cl/tienda/lubricantes/'
            'aceite-para-motor-liqui-moly-sintetico-5w-40-para-auto-camioneta-x-4l/'
        )
        self.assertEqual(bw._precio_desde_html(html, 'Aceite de motor', url=url), 52650)
        unit, nota = bw.precio_unitario_desde_envase(
            'Aceite de motor',
            52650,
            'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
        )
        self.assertEqual(unit, 13162)
        self.assertIn('52.650', nota)
        self.assertIn('13.162', nota)
        self.assertIn('4 L', nota)
        self.assertEqual(bw._tienda_de_ficha(url, ''), 'Repuestos Sergio Escobar')
        self.assertNotEqual(bw._tienda_por_dominio('repuestos.sergioescobar.cl'), 'Repuestos')
        self.assertEqual(
            bw._tienda_por_dominio('mundorepuestos.com'),
            'Mundo Repuestos',
        )

    def test_marca_liqui_moly_completa_y_stp_no_se_pega(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _marca_desde_etiqueta,
            _nombre_con_marca,
        )

        texto = 'Marca: Liqui Moly. Origen: Alemania. Marca | Liqui Moly'
        self.assertEqual(_marca_desde_etiqueta(texto), 'Liqui Moly')
        self.assertEqual(
            _nombre_con_marca('Aceite de motor', 'Liqui', texto),
            'Aceite de motor Liqui Moly',
        )
        self.assertEqual(
            _nombre_con_marca('Aceite de motor', 'Liqui'),
            'Aceite de motor',
        )
        self.assertEqual(
            _nombre_con_marca('Pastillas de freno delanteras', 'Stp', 'Marca: Stp'),
            'Pastillas de freno delanteras',
        )
        self.assertEqual(_marca_desde_etiqueta('Marca: Stp Origen: China'), '')
        self.assertEqual(_nombre_con_marca('Discos de freno delanteros', 'Repstock'), 'Discos de freno delanteros Repstock')

    def test_pastilla_sin_bravo_y_barata_no_se_cotiza(self):
        from unittest.mock import patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        mala = 'https://mundorepuestos.com/producto/9972779244826220072009/juego-pastillas-freno-fiat'
        buena = 'https://frenosvergara.shop/products/pastillas-fiat-bravo-t-jet'
        html_mala = """
        <html><head><title>Juego Pastillas Freno Fiat | Envío gratis - Mundo Repuestos Chile</title></head>
        <body>
          <h1>Juego Pastillas Freno Fiat</h1>
          <p class="price"><span class="woocommerce-Price-amount amount"><bdi>$11.920</bdi></span></p>
          <p>Marca: Stp</p>
          <p>Modelos de autos compatibles: Fiat IDEA ADVENTUR 1.8, Fiorino, Strada, Ram 700.</p>
        </body></html>
        """
        html_buena = """
        <html><head>
          <title>Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet</title>
          <meta property="og:price:amount" content="32990">
        </head><body><h1>Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet</h1></body></html>
        """

        def fake_buscar(query, **kwargs):
            if 'pastilla' not in query.lower():
                return []
            return [
                {
                    'title': 'Juego Pastillas Freno Fiat | Envío gratis - Mundo Repuestos Chile',
                    'url': mala,
                    'content': 'Consultar stock en tienda.',
                    'score': 0.9,
                },
                {
                    'title': 'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
                    'url': buena,
                    'content': 'Consultar stock en tienda.',
                    'score': 0.8,
                },
            ]

        def fake_html(urls):
            return {mala: html_mala, buena: html_buena}

        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', side_effect=fake_html), patch.object(
            bw, '_gemini_generar', return_value=None,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                ['Pastillas de freno delanteras'],
                marca='FIAT',
                modelo='Bravo',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='T-Jet',
                servicio_nombre='Pastillas',
                timeout=5,
                plan={'piezas': []},
                bandas_min={'Pastillas de freno delanteras': 28000},
            )

        hit = out[bw._clave_fuzzy('Pastillas de freno delanteras')]
        self.assertEqual(hit['url'], buena)
        self.assertEqual(hit['precio_clp'], 32990)
        self.assertNotIn('Stp', hit.get('marca_repuesto') or '')
        texto = '\n'.join(logs.output)
        self.assertIn('motivo=modelo_incompatible', texto)
        self.assertIn(mala, texto)
        self.assertIn('precio=11920', texto)
        self.assertIn('banda_min=28000', texto)

    def test_solo_el_listado_idea_no_deja_hit_y_linea_tjet_si(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        idea = {
            'title': 'Juego Pastillas Freno Fiat | Envío gratis - Mundo Repuestos Chile',
            'url': 'https://mundorepuestos.com/producto/1/juego-pastillas-fiat-idea',
            'content': 'Precio: $11920',
            'cuerpo': 'Marca: Stp. Compatible con Fiat Idea, Fiorino y Strada.',
            'ficha_leida': True,
            'precio_snippet': 11920,
        }
        self.assertFalse(bw._candidato_sirve_linea(
            'Pastillas de freno delanteras',
            idea,
            modelo='Bravo',
            tipo_motor='T-Jet',
            banda_min=28000,
        ))
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                idea,
                nombre='Pastillas de freno delanteras',
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=28000,
            ),
            'modelo_incompatible',
        )
        stilo = {
            'title': 'Pastillas freno Fiat Stilo 1.4',
            'url': 'https://frenosvergara.shop/products/stilo',
            'content': 'Fiat Stilo. Precio: $24990',
            'ficha_leida': True,
            'precio_snippet': 24990,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                stilo,
                nombre='Pastillas de freno delanteras',
                modelo='Bravo',
                tipo_motor='T-Jet',
            ),
            'modelo_incompatible',
        )
        linea = {
            'title': 'Pastillas freno Fiat Linea 1.4 T-Jet',
            'url': 'https://frenosvergara.shop/products/linea-t-jet',
            'content': 'Compatible Linea T-Jet y Punto T-Jet. Precio: $32990',
            'ficha_leida': True,
            'precio_snippet': 32990,
        }
        self.assertTrue(bw._candidato_sirve_linea(
            'Pastillas de freno delanteras',
            linea,
            modelo='Bravo',
            tipo_motor='T-Jet',
            banda_min=28000,
        ))
        exacta_barata = {
            'title': 'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
            'url': 'https://frenosvergara.shop/products/bravo',
            'content': 'Precio: $11920',
            'ficha_leida': True,
            'precio_snippet': 11920,
        }
        self.assertTrue(bw._candidato_sirve_linea(
            'Pastillas de freno delanteras',
            exacta_barata,
            modelo='Bravo',
            tipo_motor='T-Jet',
            banda_min=28000,
        ))
        generica = {
            'title': 'Juego Pastillas Freno Fiat',
            'url': 'https://mundorepuestos.com/producto/2/juego-pastillas-fiat',
            'content': 'Precio: $11920',
            'cuerpo': 'Pastillas de freno para Fiat. Envío gratis.',
            'ficha_leida': True,
            'precio_snippet': 11920,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                generica,
                nombre='Pastillas de freno delanteras',
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=28000,
            ),
            'precio_bajo_banda',
        )
        self.assertTrue(bw._es_pagina_sin_ficha(
            'https://www.mundorepuestos.cl/categoria/pastillas-freno-fiat',
        ))


class Quote13PadCandidatesTests(SimpleTestCase):
    """Cotización 13: el slug linea-t-jet no salva el listado, y Bravo entra al cupo."""

    _LINEA = 'Pastillas de freno delanteras'
    _URL_LISTADO = (
        'https://mundorepuestos.com/producto/9971766272027220102014/'
        'juego-pastillas-freno-delanteras-semimetalica-fiat-linea-active-1400-'
        'sohc-t-jet-198-a4-000-italia'
    )
    _TITULO_LISTADO = 'Juego Pastillas Freno Fiat | Envío gratis - Mundo Repuestos Chile'

    def test_11_920_es_11920_y_el_slug_linea_no_salva_el_listado(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        self.assertEqual(bw._parse_monto_clp('11.920'), 11920)
        self.assertEqual(bw._parse_monto_clp('11920.00'), 11920)
        html = """
        <html><head>
          <title>Juego Pastillas Freno Fiat | Envío gratis - Mundo Repuestos Chile</title>
          <script type="application/ld+json">
            {"@type":"Product","name":"Juego Pastillas Freno Fiat",
             "offers":{"@type":"Offer","price":"1192.00","priceCurrency":"CLP"}}
          </script>
        </head><body>
          <h1>Juego Pastillas Freno Fiat</h1>
          <p>Precio: $11.920</p>
        </body></html>
        """
        self.assertEqual(bw._precio_desde_html(html, self._LINEA, url=self._URL_LISTADO), 11920)
        listado = {
            'title': self._TITULO_LISTADO,
            'url': self._URL_LISTADO,
            'content': 'Precio: $11.920',
            'ficha_leida': True,
            'precio_snippet': 11920,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                listado,
                nombre=self._LINEA,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=28000,
            ),
            'listado',
        )
        self.assertFalse(bw._candidato_sirve_linea(
            self._LINEA,
            listado,
            modelo='Bravo',
            tipo_motor='T-Jet',
            banda_min=28000,
        ))
        linea_barata = {
            'title': 'Pastillas freno Fiat Linea 1.4 T-Jet',
            'url': 'https://frenosvergara.shop/products/linea-t-jet-barata',
            'content': 'Compatible Linea T-Jet. Precio: $15000',
            'ficha_leida': True,
            'precio_snippet': 15000,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                linea_barata,
                nombre=self._LINEA,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=28000,
            ),
            'precio_bajo_banda',
        )
        lider = {
            'title': 'Pastillas De Freno Delantera Fiat Bravo 1.4 08/15',
            'url': 'https://www.lider.cl/pastillas-freno-fiat-bravo-14',
            'content': 'Precio: $21.390',
            'precio_snippet': 21390,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                lider,
                nombre=self._LINEA,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=28000,
            ),
            '',
        )
        sodimac = {
            'title': 'Pastillas de freno Delantera Fiat Bravo 1.4 08/15',
            'url': 'https://www.sodimac.cl/sodimac-cl/articulo/123/pastillas-bravo',
            'content': 'Precio: $10.000',
            'precio_snippet': 10000,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                sodimac,
                nombre=self._LINEA,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=28000,
            ),
            'precio_bajo_banda',
        )

    def test_bravo_se_lee_antes_que_el_listado_y_si_no_hay_precio_no_hay_tienda(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        urls = {
            'listado': self._URL_LISTADO,
            'sodimac': 'https://www.sodimac.cl/sodimac-cl/articulo/123/pastillas-bravo-14',
            'lider': 'https://www.lider.cl/pastillas-freno-delantera-fiat-bravo-14',
            'gmak': 'https://www.gmak.cl/pastillas-freno-fiat-bravo-14-t-jet',
            'sol': 'https://www.repuestosdelsol.cl/pastillas-freno-fiat-bravo-14-2007',
            'ml': 'https://articulo.mercadolibre.cl/MLC-123-pastillas-freno-fiat-linea-t-jet',
            'imaparts': 'https://www.imaparts.cl/pastillas-freno-fiat-bravo-14',
        }
        titulos = {
            'listado': self._TITULO_LISTADO,
            'sodimac': 'Pastillas de freno Delantera Fiat Bravo 1.4 08/15',
            'lider': 'Pastillas De Freno Delantera Fiat Bravo 1.4 08/15',
            'gmak': 'Pastillas de freno Delantera Fiat Bravo 1.4 T-Jet',
            'sol': 'Pastillas de freno Fiat Bravo 1.4 2007',
            'ml': 'Pastillas de Freno Delanteras Fiat Linea 1.4 T-Jet',
            'imaparts': 'Pastillas de freno Fiat Bravo 1.4',
        }
        contenidos = {
            'listado': 'Juego pastillas Fiat. Precio: $11.920',
            'sodimac': 'Fiat Bravo 1.4. Precio: $10.000',
            'lider': 'Fiat Bravo 1.4 08/15. Precio: $21.390',
            'gmak': 'Consultar stock en tienda.',
            'sol': 'Consultar stock en tienda.',
            'ml': 'Consultar stock en tienda.',
            'imaparts': 'Consultar stock en tienda.',
        }
        html_gmak = """
        <html><head>
          <title>Pastillas de freno Delantera Fiat Bravo 1.4 T-Jet</title>
          <meta property="og:price:amount" content="32990">
        </head><body><h1>Pastillas de freno Delantera Fiat Bravo 1.4 T-Jet</h1></body></html>
        """
        html_listado = """
        <html><head>
          <script type="application/ld+json">
            {"@type":"Product","name":"Juego Pastillas Freno Fiat",
             "offers":{"price":"1192.00","priceCurrency":"CLP"}}
          </script>
        </head><body><p>Precio: $11.920</p></body></html>
        """
        pedidos: list[str] = []

        def fake_buscar(query, **kwargs):
            if 'pastilla' not in query.lower():
                return []
            return [
                {'title': titulos[k], 'url': urls[k], 'content': contenidos[k], 'score': 0.8}
                for k in (
                    'listado', 'sodimac', 'lider', 'gmak', 'sol', 'ml', 'imaparts',
                )
            ]

        def fake_html(lista):
            pedidos.extend(lista)
            return {
                url: html_gmak if url == urls['gmak'] else html_listado
                for url in lista
            }

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._tavily_buscar_uno',
            side_effect=fake_buscar,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._tavily_extraer',
            return_value={},
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._leer_html_fichas',
            side_effect=fake_html,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._gemini_generar',
            return_value=None,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                [self._LINEA],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='T-Jet',
                servicio_nombre='Pastillas',
                timeout=5,
                plan={'piezas': []},
                bandas_min={self._LINEA: 28000},
            )

        hit = out[bw._clave_fuzzy(self._LINEA)]
        self.assertEqual(hit['url'], urls['gmak'])
        self.assertEqual(hit['precio_clp'], 32990)
        self.assertNotEqual(hit['precio_clp'], 1192)
        self.assertNotIn('mundorepuestos', hit['url'])
        self.assertIn(urls['gmak'], pedidos)
        self.assertIn(urls['sol'], pedidos)
        self.assertIn(urls['ml'], pedidos)
        self.assertNotIn(urls['listado'], pedidos)
        texto = '\n'.join(logs.output)
        self.assertIn(f"url={urls['listado']} motivo=listado", texto)
        self.assertIn(f"url={urls['sodimac']} motivo=precio_bajo_banda", texto)
        self.assertNotIn(f"url={urls['lider']} motivo=fuera_del_cupo", texto)
        self.assertNotIn(f"url={urls['gmak']} motivo=fuera_del_cupo", texto)
        self.assertIn('banda_min=28000', texto)

        def fake_buscar_sin_bravo(query, **kwargs):
            if 'pastilla' not in query.lower():
                return []
            return [
                {'title': titulos['listado'], 'url': urls['listado'], 'content': contenidos['listado'], 'score': 0.9},
                {'title': titulos['sodimac'], 'url': urls['sodimac'], 'content': contenidos['sodimac'], 'score': 0.5},
            ]

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._tavily_buscar_uno',
            side_effect=fake_buscar_sin_bravo,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._tavily_extraer',
            return_value={},
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._leer_html_fichas',
            return_value={urls['listado']: html_listado},
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._gemini_generar',
            return_value=None,
        ):
            vacio = bw._buscar_repuestos_web_tavily(
                [self._LINEA],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='T-Jet',
                servicio_nombre='Pastillas',
                timeout=5,
                plan={'piezas': []},
                bandas_min={self._LINEA: 28000},
            )
        self.assertEqual(vacio, {})


class Quote16BujiasYFiltroAireTests(SimpleTestCase):
    """Cotización 16: las compuertas y la escalera corta valen para toda pieza."""

    _BUJIA = 'Bujías NGK Iridium'
    _FILTRO = 'Filtro de aire'
    _ML = 'https://articulo.mercadolibre.cl/MLC-999888777-filtro-aire-fiat-bravo-14-turbo'
    _BUJIA_URL = 'https://www.mundorepuestos.cl/producto/bujia-ngk-iridium-fiat-bravo-14'

    def test_filtro_a_cinco_veces_la_banda_no_se_cotiza_y_la_bujia_usa_la_escalera_corta(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        calls: list[str] = []

        def fake_buscar(query, **kwargs):
            calls.append(query)
            q = query.lower()
            if q.startswith('bujias'):
                return [{
                    'title': 'Bujía NGK Iridium Fiat Bravo 1.4 T-Jet',
                    'url': self._BUJIA_URL,
                    'content': 'Bujía NGK para Fiat Bravo 1.4 T-Jet. Precio $ 12.990',
                    'score': 0.9,
                }]
            if q.startswith('filtro aire'):
                return [{
                    'title': 'Filtro Aire Fiat Bravo 1.4 Turbo',
                    'url': self._ML,
                    'content': 'Filtro de aire Fiat Bravo 1.4 Turbo. Precio $ 81.900',
                    'score': 0.8,
                }]
            return []

        plan = {
            'piezas': [
                {
                    'nombre': self._BUJIA,
                    'consulta': 'Bujías NGK Iridium Fiat Bravo 1.4 T-Jet 2010',
                    'escasa': True,
                },
                {
                    'nombre': self._FILTRO,
                    'consulta': 'Filtro de aire Fiat Bravo 1.4 Turbo 2010',
                    'escasa': True,
                },
            ],
        }
        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', return_value={}), patch.object(
            bw, '_gemini_generar', return_value=None,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                [self._BUJIA, self._FILTRO],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='T-Jet',
                servicio_nombre='Cambio de bujías y filtro de aire',
                timeout=5,
                plan=plan,
                bandas_min={self._BUJIA: 8000, self._FILTRO: 8000},
                bandas_max={self._BUJIA: 18000, self._FILTRO: 15000},
            )

        self.assertEqual(calls, [
            'bujias fiat bravo 1.4',
            'bujias fiat bravo',
            'bujias fiat linea t-jet',
            'filtro aire fiat bravo 1.4',
            'filtro aire fiat bravo',
            'filtro aire fiat linea t-jet',
        ])
        self.assertNotIn('iridium', ' '.join(calls))
        self.assertNotIn('2010', ' '.join(calls))
        self.assertNotIn('ngk', ' '.join(calls))
        hit = out[bw._clave_fuzzy(self._BUJIA)]
        self.assertEqual(hit['url'], self._BUJIA_URL)
        self.assertEqual(hit['precio_clp'], 12990)
        self.assertNotIn(bw._clave_fuzzy(self._FILTRO), out)
        texto = '\n'.join(logs.output)
        self.assertIn(f'url={self._ML} motivo=precio_alto_banda', texto)

    def test_una_sola_tienda_no_respalda_el_techo_y_dos_si(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        uno = {
            'title': 'Filtro Aire Fiat Bravo 1.4 Turbo',
            'url': self._ML,
            'content': 'Precio $ 81.900',
            'ficha_leida': True,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                uno,
                nombre=self._FILTRO,
                modelo='BRAVO SPORT TJET',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=15000,
            ),
            'precio_alto_banda',
        )
        otro = {
            'title': 'Filtro de aire Fiat Bravo 1.4 Turbo',
            'url': 'https://www.mundorepuestos.cl/producto/filtro-aire-bravo-14',
            'content': 'Precio $ 84.900',
            'ficha_leida': True,
        }
        bw._marcar_respaldo_alto([uno, otro], self._FILTRO, 15000)
        self.assertTrue(uno.get('respaldo_alto'))
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                uno,
                nombre=self._FILTRO,
                modelo='BRAVO SPORT TJET',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=15000,
            ),
            '',
        )

    def test_cruce_linea_dentro_de_banda_sirve_y_por_encima_no(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        dentro = {
            'title': 'Filtro de aire Fiat Linea 1.4 T-Jet',
            'url': 'https://www.todoautochile.cl/producto/filtro-aire-linea-tjet',
            'content': 'Filtro de aire Fiat Linea T-Jet. Precio $ 12.000',
            'ficha_leida': True,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                dentro,
                nombre=self._FILTRO,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=15000,
            ),
            '',
        )
        arriba = dict(dentro)
        arriba['content'] = 'Filtro de aire Fiat Linea T-Jet. Precio $ 20.000'
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                arriba,
                nombre=self._FILTRO,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=15000,
            ),
            'precio_alto_banda',
        )
        barato = {
            'title': 'Filtro de aire universal',
            'url': 'https://www.todoautochile.cl/producto/filtro-aire-universal',
            'content': 'Precio $ 3.000',
            'ficha_leida': True,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                barato,
                nombre=self._FILTRO,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=15000,
            ),
            'precio_bajo_banda',
        )
        listado = {
            'title': 'Filtro de aire | Envío gratis',
            'url': 'https://www.mundorepuestos.cl/producto/filtro-aire',
            'content': 'Precio $ 12.000',
            'ficha_leida': True,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                listado,
                nombre=self._FILTRO,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=15000,
            ),
            'listado',
        )

    def test_juego_de_4_se_mide_por_bujia_y_se_parte_si_la_linea_pide_cuatro(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        juego = {
            'title': 'Juego de 4 bujías NGK Fiat Bravo 1.4',
            'url': 'https://www.mundorepuestos.cl/producto/juego-4-bujias-ngk-bravo',
            'content': 'Juego de 4 bujías NGK Fiat Bravo 1.4. Precio $ 40.000',
            'ficha_leida': True,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                juego,
                nombre=self._BUJIA,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=12000,
            ),
            '',
        )
        suelta = dict(juego)
        suelta['title'] = 'Bujía NGK Fiat Bravo 1.4'
        suelta['content'] = 'Bujía NGK Fiat Bravo 1.4. Precio $ 40.000'
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                suelta,
                nombre=self._BUJIA,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=12000,
            ),
            'precio_alto_banda',
        )
        unit, nota = bw.precio_unitario_desde_pack(
            self._BUJIA, 32000, 'Juego de 4 bujías NGK', 4,
        )
        self.assertEqual(unit, 8000)
        self.assertIn('juego de 4', nota)
        barato, nota_barato = bw.precio_unitario_desde_pack(
            self._BUJIA, 8000, 'Juego de 4 bujías NGK', 4,
        )
        self.assertEqual(barato, 2000)
        self.assertIn('juego de 4', nota_barato)
        uno, sin_nota_uno = bw.precio_unitario_desde_pack(
            self._BUJIA, 32000, 'Juego de 4 bujías NGK', 1,
        )
        self.assertEqual(uno, 32000)
        self.assertEqual(sin_nota_uno, '')


class Quote17AnioYPackTests(SimpleTestCase):
    """Cotización 17: el Bravo 1995-2001 no es el Bravo 2010 T-Jet."""

    _BUJIA = 'Bujías'
    _FILTRO = 'Filtro de aire'
    _TITULO_BUJIA = 'Bujía Champion Fiat Bravo 1.4 1995-2001 x4'
    _TITULO_FILTRO = 'FILTRO AIRE FIAT BRAVO 1996/2000'
    _URL_BUJIA = 'https://www.entretuercas.cl/producto/bujia-champion-fiat-bravo-14-1995-2001'
    _URL_FILTRO = 'https://todoautochile.cl/producto/filtro-aire-fiat-bravo-1996-2000/'

    def test_formatos_de_anio_y_un_rango_que_no_incluye_el_auto_se_rechaza(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        self.assertTrue(bw._ficha_cubre_anio('Fiat Bravo 1.4 08/15', 2010))
        self.assertTrue(bw._ficha_cubre_anio('FILTRO ACEITE FIAT BRAVO 1.4 2008-2014', 2010))
        self.assertTrue(bw._ficha_cubre_anio('FILTRO ACEITE FIAT BRAVO 1.4 2008/2014', 2010))
        self.assertFalse(bw._ficha_cubre_anio(self._TITULO_FILTRO, 2010))
        self.assertFalse(bw._ficha_cubre_anio('Bujía Fiat Bravo 95-01', 2010))
        self.assertFalse(bw._ficha_cubre_anio(self._TITULO_BUJIA, 2010))
        self.assertEqual(
            bw.unidades_pack(self._TITULO_BUJIA), 4,
        )
        self.assertEqual(bw.unidades_pack('Bujías NGK x 4'), 4)
        self.assertEqual(bw.unidades_pack('kit 4 bujías'), 4)
        self.assertEqual(bw.unidades_pack('Bujías 4 unidades'), 4)
        self.assertEqual(bw.unidades_pack('Juego de 4 bujías'), 4)
        self.assertEqual(bw.unidades_pack('Fiat Bravo 1.4'), 0)
        unit, nota = bw.precio_unitario_desde_pack(self._BUJIA, 9641, self._TITULO_BUJIA, 4)
        self.assertEqual(unit, 2410)
        self.assertIn('juego de 4', nota)
        self.assertIn('2.410', nota)

    def test_bujia_1995_y_filtro_1996_no_cotizan_el_bravo_2010(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        bujia = {
            'title': self._TITULO_BUJIA,
            'url': self._URL_BUJIA,
            'content': f'{self._TITULO_BUJIA}. Precio $ 9.641',
            'ficha_leida': True,
        }
        filtro = {
            'title': self._TITULO_FILTRO,
            'url': self._URL_FILTRO,
            'content': f'{self._TITULO_FILTRO}. Precio $ 7.990',
            'ficha_leida': True,
        }
        for cand, nombre in ((bujia, self._BUJIA), (filtro, self._FILTRO)):
            self.assertEqual(
                bw._motivo_calidad_pastilla(
                    cand,
                    nombre=nombre,
                    modelo='BRAVO SPORT TJET',
                    tipo_motor='T-Jet',
                    banda_min=8000,
                    banda_max=18000,
                    anio=2010,
                ),
                'anio_incompatible',
                nombre,
            )
        # El mismo set, con años del Bravo II, igual cae: $9.641 / 4 = $2.410.
        vigente = {
            'title': 'Bujía Champion Fiat Bravo 1.4 2008-2014 x4',
            'url': self._URL_BUJIA,
            'content': 'Bujía Champion Fiat Bravo 1.4 2008-2014 x4. Precio $ 9.641',
            'ficha_leida': True,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                vigente,
                nombre=self._BUJIA,
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=18000,
                anio=2010,
            ),
            'precio_bajo_banda',
        )
        # 08/15 sigue siendo el Bravo de 2010. No es un rechazo de año.
        lider = {
            'title': 'Pastillas De Freno Delantera Fiat Bravo 1.4 08/15',
            'url': 'https://www.lider.cl/producto/pastillas-bravo-14',
            'content': 'Pastillas De Freno Delantera Fiat Bravo 1.4 08/15. Precio $ 21.390',
            'ficha_leida': True,
        }
        self.assertNotEqual(
            bw._motivo_calidad_pastilla(
                lider,
                nombre='Pastillas de freno delanteras',
                modelo='BRAVO SPORT TJET',
                tipo_motor='T-Jet',
                banda_min=28000,
                banda_max=55000,
                anio=2010,
            ),
            'anio_incompatible',
        )

    def test_busqueda_de_la_cotizacion_17_deja_las_lineas_sin_tienda(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        def fake_buscar(query, **kwargs):
            q = query.lower()
            if q.startswith('bujias'):
                return [{
                    'title': self._TITULO_BUJIA,
                    'url': self._URL_BUJIA,
                    'content': f'{self._TITULO_BUJIA}. Precio $ 9.641',
                    'score': 0.9,
                }]
            if q.startswith('filtro aire'):
                return [{
                    'title': self._TITULO_FILTRO,
                    'url': self._URL_FILTRO,
                    'content': f'{self._TITULO_FILTRO}. Precio $ 7.990',
                    'score': 0.8,
                }]
            return []

        avisos: dict = {}
        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', return_value={}), patch.object(
            bw, '_gemini_generar', return_value=None,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                [self._BUJIA, self._FILTRO],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='T-Jet',
                servicio_nombre='Cambio de bujías y filtro de aire',
                timeout=5,
                plan={'piezas': []},
                bandas_min={self._BUJIA: 8000, self._FILTRO: 8000},
                bandas_max={self._BUJIA: 18000, self._FILTRO: 15000},
                avisos=avisos,
            )

        self.assertEqual(out, {})
        texto = '\n'.join(logs.output)
        self.assertIn(f'url={self._URL_BUJIA} motivo=anio_incompatible', texto)
        self.assertIn(f'url={self._URL_FILTRO} motivo=anio_incompatible', texto)
        nota_bujia = avisos[self._BUJIA]['detalle']
        nota_filtro = avisos[self._FILTRO]['detalle']
        self.assertIn('2010', nota_bujia)
        self.assertIn('1995-2001', nota_bujia)
        self.assertIn('2010', nota_filtro)
        self.assertIn('1996/2000', nota_filtro)


class Quote19HolguraMotorTests(SimpleTestCase):
    """Cotización 19: 2011-2014 del mismo Bravo Sport 1.4 T-Jet cabe en 2010.

    Un año de borde solo si el título nombra el modelo y el motor. Otra
    generación (1995-2001) u otro motor (1.6, 8v) se sigue botando, y el
    monto sigue sujeto a la banda.
    """

    _BUJIA = 'Bujías'
    _FILTRO = 'Filtro de aire'
    _TITULO = 'Bujía Original Fiat Bravo Sport 1.4t 2011-2014'
    _URL = 'https://www.repuestosbravo.cl/producto/bujia-original-bravo-sport-14t-2011-2014'

    def _motivo(self, cand, nombre, *, banda_min=8000, banda_max=18000):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        return bw._motivo_calidad_pastilla(
            cand,
            nombre=nombre,
            modelo='BRAVO SPORT TJET',
            tipo_motor='T-Jet',
            banda_min=banda_min,
            banda_max=banda_max,
            anio=2010,
            cilindraje='1.4',
        )

    def test_un_anio_de_borde_si_el_titulo_nombra_modelo_y_motor(self):
        en_banda = {
            'title': self._TITULO,
            'url': self._URL,
            'content': f'{self._TITULO}. Precio $ 12.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(en_banda, self._BUJIA), '')
        # Sport o T-Jet alcanzan; no hace falta que estén las tres marcas.
        por_sport = {
            'title': 'Bujía Fiat Bravo Sport 2011-2014',
            'url': self._URL,
            'content': 'Precio $ 12.990',
            'ficha_leida': True,
        }
        por_tjet = {
            'title': 'Bujía Fiat Bravo T-Jet 2011-2014',
            'url': self._URL,
            'content': 'Precio $ 12.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(por_sport, self._BUJIA), '')
        self.assertEqual(self._motivo(por_tjet, self._BUJIA), '')
        # El filtro usa la misma regla.
        filtro = {
            'title': 'Filtro de aire Fiat Bravo Sport 1.4t 2011-2014',
            'url': 'https://www.repuestosbravo.cl/producto/filtro-aire-bravo-sport-14t',
            'content': 'Precio $ 9.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(filtro, self._FILTRO, banda_max=15000), '')
        # Sin motor en el título no hay borde: 2011-2014 deja afuera el 2010.
        sin_motor = {
            'title': 'Bujía Fiat Bravo 2011-2014',
            'url': self._URL,
            'content': 'Precio $ 12.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(sin_motor, self._BUJIA), 'anio_incompatible')
        # Dos años de diferencia siguen afuera.
        dos = {
            'title': 'Bujía Fiat Bravo Sport 1.4t 2012-2014',
            'url': self._URL,
            'content': 'Precio $ 12.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(dos, self._BUJIA), 'anio_incompatible')

    def test_otra_generacion_u_otro_motor_se_rechazan_y_la_banda_sigue(self):
        viejo = {
            'title': 'Bujía Champion Fiat Bravo 1.4 1995-2001 x4',
            'url': 'https://www.entretuercas.cl/producto/bujia-champion-bravo-1995',
            'content': 'Precio $ 9.641',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(viejo, self._BUJIA), 'anio_incompatible')
        uno_seis = {
            'title': 'Bujía Fiat Bravo 1.6 2008-2014',
            'url': 'https://www.repuestosbravo.cl/producto/bujia-bravo-16',
            'content': 'Precio $ 12.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(uno_seis, self._BUJIA), 'motor_incompatible')
        ocho = {
            'title': 'Bujía Fiat Bravo 8v 2008-2014',
            'url': 'https://www.repuestosbravo.cl/producto/bujia-bravo-8v',
            'content': 'Precio $ 12.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(ocho, self._BUJIA), 'motor_incompatible')
        # El borde no salta la banda: por encima de 2,5× el máximo sigue alto.
        caro = {
            'title': self._TITULO,
            'url': self._URL,
            'content': f'{self._TITULO}. Precio $ 49.990',
            'ficha_leida': True,
        }
        self.assertEqual(self._motivo(caro, self._BUJIA), 'precio_alto_banda')

    def test_busqueda_cotiza_el_2011_y_bota_1995_y_el_1_6(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        url_16 = 'https://www.repuestosbravo.cl/producto/bujia-bravo-16-2008'
        url_95 = 'https://www.entretuercas.cl/producto/bujia-champion-bravo-1995'
        html = """
        <html><head>
          <meta property="og:price:amount" content="12990">
        </head><body><h1>Bujía Original Fiat Bravo Sport 1.4t 2011-2014</h1></body></html>
        """

        def fake_buscar(query, **kwargs):
            q = query.lower()
            if q.startswith('bujias'):
                return [
                    {
                        'title': self._TITULO,
                        'url': self._URL,
                        'content': self._TITULO,
                        'score': 0.7,
                    },
                    {
                        'title': 'Bujía Champion Fiat Bravo 1.4 1995-2001 x4',
                        'url': url_95,
                        'content': 'Bujía Champion Fiat Bravo 1.4 1995-2001 x4. Precio $ 9.641',
                        'score': 0.9,
                    },
                    {
                        'title': 'Bujía Fiat Bravo 1.6 2008-2014',
                        'url': url_16,
                        'content': 'Bujía Fiat Bravo 1.6 2008-2014. Precio $ 12.990',
                        'score': 0.8,
                    },
                ]
            return []

        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', return_value={self._URL: html}), patch.object(
            bw, '_gemini_generar', return_value=None,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                [self._BUJIA],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1.4',
                tipo_motor='T-Jet',
                servicio_nombre='Cambio de bujías y filtro de aire',
                timeout=5,
                plan={'piezas': []},
                bandas_min={self._BUJIA: 8000},
                bandas_max={self._BUJIA: 18000},
            )

        hit = out[bw._clave_fuzzy(self._BUJIA)]
        self.assertEqual(hit['url'], self._URL)
        texto = '\n'.join(logs.output)
        self.assertIn(f'url={url_95} motivo=anio_incompatible', texto)
        self.assertIn(f'url={url_16} motivo=motor_incompatible', texto)
        self.assertNotIn(f'url={self._URL} motivo=anio_incompatible', texto)


class Quote21EscaleraHolguraTests(SimpleTestCase):
    """Cotización 21: la escalera de Tavily aplica el año de borde.

    El log de producción rechazó 'Bujía Original Fiat Bravo Sport 1.4t
    2011-2014' en `rechazos=` para un BRAVO SPORT TJET 2010. 1368 cc es el
    1.4 T-Jet. La banda $32.000 con cantidad 4 es el juego, no cada bujía.
    """

    _BUJIA = 'Bujías'
    _TITULO = 'Bujía Original Fiat Bravo Sport 1.4t 2011-2014'
    _URL = (
        'https://www.mercadolibre.cl/bujia-original-fiat-bravo-sport-14t-20112014'
        '/up/MLCU67593706'
    )

    def test_1368_cc_es_el_1_4_y_el_1_4t_calza_el_tjet(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        self.assertEqual(bw._cilindraje_litros('1368'), '1.4')
        self.assertEqual(bw._cilindraje_litros('1.368 cc'), '1.4')
        self.assertEqual(bw._cilindraje_litros('1.4L'), '1.4')
        cand = {
            'title': self._TITULO,
            'url': self._URL,
            'content': f'{self._TITULO}. Precio $ 9.990',
            'ficha_leida': True,
        }
        for modelo, tipo, cil in (
            ('BRAVO SPORT TJET', 'T-Jet', '1.4'),
            ('BRAVO SPORT TJET', '', '1368'),
            ('Bravo', 'T-Jet', ''),
            ('Bravo', '', '1368'),
        ):
            self.assertEqual(
                bw._motivo_calidad_pastilla(
                    cand,
                    nombre=self._BUJIA,
                    modelo=modelo,
                    tipo_motor=tipo,
                    banda_min=32000,
                    banda_max=40000,
                    anio=2010,
                    cilindraje=cil,
                ),
                '',
                f'{modelo} {tipo} {cil}',
            )
        self.assertEqual(
            bw._monto_banda_por_unidad(self._BUJIA, 32000, 4),
            8000,
        )
        self.assertEqual(
            bw._monto_banda_por_unidad(self._BUJIA, 40000, 4),
            10000,
        )
        self.assertEqual(bw._monto_banda_por_unidad(self._BUJIA, 8000, 4), 8000)

    def _buscar(self, html_side_effect):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        def fake_buscar(query, **kwargs):
            if query.lower().startswith('bujias'):
                return [{
                    'title': self._TITULO,
                    'url': self._URL,
                    'content': self._TITULO,
                    'score': 0.9,
                }]
            return []

        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', side_effect=html_side_effect), patch.object(
            bw, '_gemini_generar', return_value=None,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                [self._BUJIA],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1368',
                tipo_motor='GASOLINA',
                servicio_nombre='Cambio de bujías y filtro de aire',
                timeout=5,
                plan={'piezas': []},
                bandas_min={self._BUJIA: 32000},
                bandas_max={self._BUJIA: 40000},
                cantidades={self._BUJIA: 4},
            )
        return out, '\n'.join(logs.output)

    def test_la_escalera_no_marca_anio_incompatible_y_la_banda_es_por_bujia(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        html = """
        <html><head>
          <meta property="og:price:amount" content="9990">
        </head><body><h1>Bujía Original Fiat Bravo Sport 1.4t 2011-2014</h1>
        <p>Valor unitario</p></body></html>
        """

        def fake_html(urls):
            bw._FICHAS_BLOQUEADAS.clear()
            return {self._URL: html}

        out, texto = self._buscar(fake_html)
        self.assertNotIn(f'{self._TITULO}: anio_incompatible', texto)
        self.assertNotIn(f'url={self._URL} motivo=anio_incompatible', texto)
        self.assertIn('banda_min=8000', texto)
        hit = out[bw._clave_fuzzy(self._BUJIA)]
        self.assertEqual(hit['url'], self._URL)
        self.assertEqual(hit['precio_clp'], 9990)

    def test_muro_de_mercadolibre_deja_la_bujia_sin_precio(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        def fake_html(urls):
            bw._FICHAS_BLOQUEADAS = set(urls)
            return {}

        out, texto = self._buscar(fake_html)
        self.assertEqual(out, {})
        self.assertNotIn(f'{self._TITULO}: anio_incompatible', texto)
        self.assertIn('banda_min=8000', texto)

        class _Prev:
            def __init__(self, url):
                self.url = url
                self.headers = {'Location': 'https://www.mercadolibre.cl/gz/account-verification?go=1'}

        class _Resp:
            status_code = 200
            url = 'https://www.mercadolibre.cl/gz/account-verification?go=1'
            text = '<html><span class="andes-money-amount__fraction">12345</span></html>'
            history = [_Prev(self._URL)]

        self.assertTrue(bw._respuesta_sin_ficha(_Resp()))
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.requests.get',
            return_value=_Resp(),
        ):
            htmls = bw._leer_html_fichas([self._URL])
        self.assertEqual(htmls, {})
        self.assertIn(self._URL, bw._FICHAS_BLOQUEADAS)

        class _Deny:
            status_code = 403
            url = self._URL
            text = 'forbidden'
            history = []

        self.assertTrue(bw._respuesta_sin_ficha(_Deny()))


class Quote22MismaCompuertaTests(SimpleTestCase):
    """Un Linea 1.4 2013-2017 no es el Bravo T-Jet 2010, en ningún paso.

    La selección, la caché y el apply leen el mismo motivo. Si no hay ficha,
    la nota dice qué se buscó y por qué se botó el título.
    """

    _BUJIA = 'Bujías'
    _TITULO = 'SET 4 BUJIAS FIAT LINEA 1.4 2013 2017 - TodoAuto Spa'
    _URL = 'https://www.todoauto.cl/set-4-bujias-fiat-linea-14-2013-2017'
    _LINEA_SIN_ANIO = 'SET 4 BUJIAS FIAT LINEA 1.4'

    def _cand(self, titulo: str, *, leida: bool = False) -> dict:
        cand = {
            'title': titulo,
            'url': self._URL,
            'content': f'{titulo}. Precio $ 18.990',
        }
        if leida:
            cand['ficha_leida'] = True
            cand['precio_snippet'] = 18990
        return cand

    def _motivo(self, cand: dict) -> str:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw

        return bw._motivo_calidad_pastilla(
            cand,
            nombre=self._BUJIA,
            modelo='BRAVO SPORT TJET',
            tipo_motor='GASOLINA',
            banda_min=7000,
            banda_max=25000,
            anio=2010,
            cilindraje='1368',
        )

    def test_2013_2017_es_un_rango_y_linea_sin_tjet_no_es_el_bravo(self):
        from types import SimpleNamespace

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw
        from mecanimovilapp.apps.ordenes.tasks import _motivo_hit

        self.assertEqual(
            bw._rangos_anio(self._TITULO),
            [(2013, 2017)],
        )
        self.assertTrue(bw._anio_fuera_de_rango(self._cand(self._TITULO), 2010))
        # El guion sigue siendo un rango. Un año suelto no.
        self.assertEqual(bw._rangos_anio('Bujía Fiat Bravo 2011-2014'), [(2011, 2014)])
        self.assertEqual(bw._rangos_anio('Bujía Fiat Bravo 2010'), [])

        seleccion = self._motivo(self._cand(self._TITULO))
        cache = self._motivo(bw._candidato_desde_cache(
            SimpleNamespace(nombre_producto=self._TITULO, url=self._URL),
            18990,
        ))
        cot = SimpleNamespace(
            vehiculo_modelo='BRAVO SPORT TJET',
            vehiculo_anio=2010,
            vehiculo_cilindraje='1368',
            tipo_motor='GASOLINA',
            tipo_motor_label='',
        )
        apply = _motivo_hit(
            {
                'nombre_producto': self._TITULO,
                'url': self._URL,
                'precio_clp': 18990,
            },
            {
                'nombre': self._BUJIA,
                'cantidad': 4,
                'precio_min_clp': 7000,
                'precio_max_clp': 25000,
            },
            cot,
        )
        self.assertEqual(seleccion, 'anio_incompatible')
        self.assertEqual(cache, seleccion)
        self.assertEqual(apply, seleccion)

        sin_anio = self._motivo(self._cand(self._LINEA_SIN_ANIO))
        sin_anio_leida = self._motivo(self._cand(self._LINEA_SIN_ANIO, leida=True))
        self.assertEqual(sin_anio, 'modelo_incompatible')
        self.assertEqual(sin_anio_leida, sin_anio)

        # El cruce sigue siendo el Linea T-Jet, no el 1.4 atmosférico.
        tjet = {
            'title': 'Pastillas freno Fiat Linea 1.4 T-Jet',
            'url': 'https://frenosvergara.shop/products/linea-t-jet',
            'content': 'Precio: $32990',
            'precio_snippet': 32990,
        }
        self.assertEqual(
            bw._motivo_calidad_pastilla(
                tjet,
                nombre='Pastillas de freno delanteras',
                modelo='BRAVO SPORT TJET',
                tipo_motor='T-Jet',
                banda_min=28000,
                anio=2010,
                cilindraje='1.4',
            ),
            '',
        )

    def test_la_escalera_no_elige_el_linea_y_la_nota_dice_por_que(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import busqueda_web_repuestos as bw
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            nota_de_busqueda,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
            _aplicar_seleccion_casa_repuestos,
        )

        def fake_buscar(query, **kwargs):
            if 'bujia' in query.lower():
                return [{
                    'title': self._TITULO,
                    'url': self._URL,
                    'content': f'{self._TITULO}. Precio $ 18.990',
                    'score': 0.9,
                }]
            return []

        avisos: dict = {}
        with patch.object(bw, '_tavily_buscar_uno', side_effect=fake_buscar), patch.object(
            bw, '_tavily_extraer', return_value={},
        ), patch.object(bw, '_leer_html_fichas', return_value={}), patch.object(
            bw, '_gemini_generar', return_value=None,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            out = bw._buscar_repuestos_web_tavily(
                [self._BUJIA],
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                cilindraje='1368',
                tipo_motor='GASOLINA',
                servicio_nombre='Cambio de bujías y filtro de aire',
                timeout=5,
                plan={'piezas': []},
                bandas_min={self._BUJIA: 7000},
                bandas_max={self._BUJIA: 25000},
                cantidades={self._BUJIA: 4},
                avisos=avisos,
            )

        self.assertEqual(out, {})
        texto = '\n'.join(logs.output)
        self.assertIn(f'{self._TITULO}: anio_incompatible', texto)
        self.assertNotIn('elegido linea=Bujías', texto)
        detalle = avisos[self._BUJIA]['detalle']
        self.assertIn('Se buscó', detalle)
        self.assertIn('bujias', detalle.lower())
        self.assertIn('LINEA 1.4 2013 2017', detalle)
        self.assertIn('otros años', detalle)
        self.assertIn('otro modelo', detalle)
        self.assertNotIn(
            'No se encontraron proveedores con este repuesto en stock',
            detalle,
        )
        self.assertEqual(nota_de_busqueda(detalle), detalle)

        linea = _aplicar_seleccion_casa_repuestos([{
            'id': 'rep-0',
            'nombre': self._BUJIA,
            'cantidad': 4,
            'precio_unitario_clp': 0,
            'motivo_seleccion': detalle,
        }])[0]
        self.assertEqual(linea['motivo_seleccion'], detalle)
        self.assertNotEqual(
            linea['motivo_seleccion'],
            'No se encontraron proveedores con este repuesto en stock para el vehículo',
        )

        tardia = bw._aviso_sin_ficha(
            self._BUJIA,
            [self._cand(self._TITULO)],
            'BRAVO SPORT TJET',
            False,
            anio=2010,
            tipo_motor='GASOLINA',
            cilindraje='1368',
        )['detalle']
        self.assertTrue(nota_de_busqueda(tardia))
        conservada = _aplicar_seleccion_casa_repuestos([{
            'id': 'rep-0',
            'nombre': self._BUJIA,
            'cantidad': 4,
            'precio_unitario_clp': 0,
            'motivo_seleccion': tardia,
        }])[0]
        self.assertEqual(conservada['motivo_seleccion'], tardia)

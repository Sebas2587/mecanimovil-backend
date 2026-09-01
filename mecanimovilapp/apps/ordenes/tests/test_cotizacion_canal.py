"""Tests cotización canal IA."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.contexto import armar_contexto_cotizacion
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
    calcular_descuento_aplicado,
    descuento_visible_clp,
    etiqueta_descuento,
    normalizar_cotizacion_ia,
    normalizar_repuesto,
    recalcular_totales,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
    _parse_button_id,
    formatear_resumen_cotizacion,
)


class NormalizarCotizacionTestCase(SimpleTestCase):
    def test_normaliza_repuesto_desde_ia(self):
        rep = normalizar_repuesto(
            {'repuesto': 'Filtro aceite', 'precio_estimado_clp': '$15.000 - $25.000 CLP', 'cantidad': 1},
            0,
        )
        self.assertEqual(rep['nombre'], 'Filtro aceite')
        self.assertGreater(rep['precio_unitario_clp'], 0)

    def test_normaliza_repuesto_marketplace_y_marca(self):
        rep = normalizar_repuesto(
            {
                'nombre': 'Pastillas freno',
                'fuente_repuesto': 'mercadolibre',
                'marca_repuesto': 'Bosch',
                'tienda_ml': 'Autopartes Sur',
                'precio_unitario_clp': 45000,
            },
            0,
        )
        self.assertEqual(rep['nombre'], 'Pastillas freno')
        self.assertEqual(rep['fuente_marketplace'], 'mercadolibre')
        self.assertEqual(rep['marca_repuesto'], 'Bosch')
        self.assertEqual(rep['tienda_ml'], 'Autopartes Sur')
        self.assertTrue(rep['precio_iva_incluido'])

    def test_enriquecer_infiere_marca_desde_nombre(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        from unittest.mock import patch

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_catalogo_maestro',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ):
            out = enriquecer_repuestos_cotizacion(
                [{
                    'id': 'rep-0',
                    'nombre': 'Volante bimasa Vimasa',
                    'cantidad': 1,
                    'precio_unitario_clp': 180000,
                }],
                marca_vehiculo='Fiat',
                modelo_vehiculo='Bravo',
                usar_ml=False,
            )
        self.assertEqual(out[0].get('marca_repuesto'), 'Vimasa')
        self.assertIsNone(out[0].get('tienda_ml'))
        # La marca inferida por nombre SIEMPRE se etiqueta como 'estimado',
        # nunca como si viniera de un dato real (catálogo/historial/ML).
        self.assertEqual(out[0].get('fuente_marketplace'), 'estimado')

    def test_enriquecer_catalogo_corrige_marca_adivinada_por_ia(self):
        """La IA ya no debería mandar marca, pero si llega un residuo sin fuente
        real, el catálogo del taller debe poder corregirlo (marca y fuente viajan
        siempre juntas)."""
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        cat = [{
            'nombre': 'Pastillas freno',
            'marca_repuesto': 'Mann',
            'precio_unitario_clp': 30000,
            'fuente_marketplace': 'catalogo',
            'proveedor_nombre': 'Catálogo del taller',
            'tienda_ml': '',
            'confianza': 0.9,
            'clave': 'pastillas freno',
        }]
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=cat,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_catalogo_maestro',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ):
            out = enriquecer_repuestos_cotizacion(
                [{
                    'id': 'rep-0',
                    'nombre': 'Pastillas freno',
                    'cantidad': 1,
                    # Simula un residuo de marca sin fuente real (p. ej. de IA legacy).
                    'marca_repuesto': 'Bosch',
                    'precio_unitario_clp': 0,
                }],
                taller=MagicMock(),
                usar_ml=False,
            )
        self.assertEqual(out[0].get('marca_repuesto'), 'Mann')
        self.assertEqual(out[0].get('fuente_marketplace'), 'catalogo')
        self.assertEqual(out[0].get('proveedor_nombre'), 'Catálogo del taller')

    def test_enriquecer_ml_mock_llena_tienda(self):
        from unittest.mock import patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        fake = {
            'marca_repuesto': 'Bosch',
            'tienda_ml': 'AutopartesSurCL',
            'proveedor_nombre': 'AutopartesSurCL',
            'fuente_marketplace': 'mercadolibre',
            'precio_unitario_clp': 42000,
            'confianza': 0.75,
            'clave': 'pastillas freno',
        }
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._buscar_ml_repuesto',
            return_value=fake,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_catalogo_maestro',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ):
            out = enriquecer_repuestos_cotizacion(
                [{'id': 'rep-0', 'nombre': 'Pastillas freno', 'cantidad': 1, 'precio_unitario_clp': 45000}],
                usar_ml=True,
            )
        self.assertEqual(out[0].get('marca_repuesto'), 'Bosch')
        self.assertEqual(out[0].get('tienda_ml'), 'AutopartesSurCL')
        self.assertEqual(out[0].get('proveedor_nombre'), 'AutopartesSurCL')
        self.assertEqual(out[0].get('fuente_marketplace'), 'mercadolibre')
        # ML no pisa precio IA si ya hay precio
        self.assertEqual(out[0].get('precio_unitario_clp'), 45000)

    def test_enriquecer_catalogo_disponible_sin_fielderror(self):
        """Regresión: OfertaServicio usa disponible, no activo."""
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        cat = [{
            'nombre': 'Filtro de aceite',
            'marca_repuesto': 'Mann',
            'precio_unitario_clp': 12000,
            'fuente_marketplace': 'catalogo',
            'proveedor_nombre': 'Catálogo del taller',
            'tienda_ml': '',
            'confianza': 0.9,
            'clave': 'filtro aceite',
        }]
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=cat,
        ) as mock_cat, patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ):
            out = enriquecer_repuestos_cotizacion(
                [{'id': 'rep-0', 'nombre': 'Filtro aceite', 'cantidad': 1, 'precio_unitario_clp': 0}],
                taller=MagicMock(),
                usar_ml=False,
            )
        mock_cat.assert_called()
        self.assertEqual(out[0].get('marca_repuesto'), 'Mann')
        self.assertEqual(out[0].get('precio_unitario_clp'), 12000)
        self.assertEqual(out[0].get('fuente_marketplace'), 'catalogo')
        self.assertEqual(out[0].get('proveedor_nombre'), 'Catálogo del taller')
        self.assertFalse(out[0].get('precio_estimado'))

    def test_no_usa_catalogo_maestro_mecanimovil_sin_ofertas_taller(self):
        """Regresión: sin servicios del taller no debe aparecer Catálogo Mecanimovil/GENÉRICO."""
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _candidatos_catalogo_maestro,
            enriquecer_repuestos_cotizacion,
        )

        self.assertEqual(_candidatos_catalogo_maestro('Hyundai'), [])

        # Aunque el stub viejo devolviera hits del maestro, el pipeline ya no los mezcla.
        fake_maestro = [{
            'nombre': 'Pastillas freno',
            'marca_repuesto': 'GENÉRICO',
            'precio_unitario_clp': 42000,
            'fuente_marketplace': 'catalogo',
            'proveedor_nombre': 'Catálogo Mecanimovil',
            'confianza': 0.85,
            'clave': 'pastillas freno',
        }]
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_catalogo_maestro',
            return_value=fake_maestro,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ):
            out = enriquecer_repuestos_cotizacion(
                [{
                    'id': 'rep-0',
                    'nombre': 'Pastillas freno delanteras',
                    'cantidad': 1,
                    'precio_unitario_clp': 42000,
                }],
                taller=MagicMock(),
                marca_vehiculo='Hyundai',
                modelo_vehiculo='Elantra',
                usar_ml=False,
            )
        self.assertNotEqual(out[0].get('fuente_marketplace'), 'catalogo')
        self.assertNotEqual(out[0].get('proveedor_nombre'), 'Catálogo Mecanimovil')
        self.assertNotIn('marca_repuesto', out[0])
        self.assertTrue(out[0].get('precio_estimado'))

    def test_fusion_catalogo_taller_reemplaza_estimacion_ia(self):
        """Si hay OfertaServicio para marca/modelo, alimenta la cotización."""
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
            fusionar_contenido_con_catalogo_taller,
        )

        contenido = {
            'servicio_nombre': 'Cambio de bujías',
            'mano_obra_clp': 99999,
            'repuestos': [{
                'nombre': 'Bujía inventada',
                'cantidad': 1,
                'precio_unitario_clp': 1000,
                'precio_estimado': True,
            }],
            'advertencias': ['Precios de repuestos estimados: revisa'],
        }
        oferta = MagicMock()
        oferta.id = 7
        oferta.servicio.nombre = 'Cambio de bujías'

        with patch(
            'mecanimovilapp.apps.ordenes.services.catalogo_pricing.buscar_oferta_exacta',
            return_value=oferta,
        ), patch(
            'mecanimovilapp.apps.agente_ia.services.cotizacion_borrador._desglose_oferta_catalogo',
            return_value=(25000, [{
                'id': 'cat-1',
                'nombre': 'Bujía iridium',
                'cantidad': 4,
                'precio_unitario_clp': 8000,
                'marca_repuesto': 'NGK',
                'fuente_marketplace': 'catalogo',
                'proveedor_nombre': 'Catálogo del taller',
                'precio_estimado': False,
                'precio_iva_incluido': True,
            }]),
        ):
            out = fusionar_contenido_con_catalogo_taller(
                contenido,
                taller=MagicMock(),
                servicio_nombre='Cambio de bujías',
                marca='Chevrolet',
                modelo='Sail',
            )
        self.assertTrue(out.get('precio_desde_catalogo'))
        self.assertFalse(out.get('valores_estimativos'))
        self.assertEqual(out.get('mano_obra_clp'), 25000)
        self.assertEqual(out['repuestos'][0].get('marca_repuesto'), 'NGK')
        self.assertEqual(out['repuestos'][0].get('proveedor_nombre'), 'Catálogo del taller')
        self.assertEqual(out['repuestos'][0].get('fuente_marketplace'), 'catalogo')
        self.assertFalse(out['repuestos'][0].get('precio_estimado'))

    def test_candidatos_ofertas_filtra_otro_modelo(self):
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import enriquecer_repuestos as mod

        marca = MagicMock()
        marca.nombre = 'Chevrolet'
        modelo_sail = MagicMock()
        modelo_sail.nombre = 'Sail'
        modelo_spark = MagicMock()
        modelo_spark.nombre = 'Spark'

        oferta_sail = MagicMock()
        oferta_sail.marca_vehiculo_seleccionada_id = 1
        oferta_sail.marca_vehiculo_seleccionada = marca
        oferta_sail.modelo_vehiculo_seleccionado_id = 10
        oferta_sail.modelo_vehiculo_seleccionado = modelo_sail
        oferta_sail.repuestos_seleccionados = [{
            'id': 1,
            'nombre': 'Bujía Sail',
            'marca_repuesto': 'NGK',
            'precio': 5000,
        }]

        oferta_spark = MagicMock()
        oferta_spark.marca_vehiculo_seleccionada_id = 1
        oferta_spark.marca_vehiculo_seleccionada = marca
        oferta_spark.modelo_vehiculo_seleccionado_id = 11
        oferta_spark.modelo_vehiculo_seleccionado = modelo_spark
        oferta_spark.repuestos_seleccionados = [{
            'id': 2,
            'nombre': 'Bujía Spark',
            'marca_repuesto': 'Bosch',
            'precio': 6000,
        }]

        only_qs = [oferta_sail, oferta_spark]
        chain = MagicMock()
        chain.select_related.return_value.only.return_value.__getitem__ = MagicMock(
            return_value=only_qs,
        )
        # Iterate the slice result
        sliced = MagicMock()
        sliced.__iter__ = MagicMock(return_value=iter(only_qs))
        chain.select_related.return_value.only.return_value.__getitem__ = MagicMock(
            return_value=sliced,
        )
        # Simpler: make only() return a list-like that supports [:200]
        class FakeQS(list):
            def __getitem__(self, item):
                if isinstance(item, slice):
                    return list(self)[item]
                return list.__getitem__(self, item)

        fake = FakeQS([oferta_sail, oferta_spark])
        chain.select_related.return_value.only.return_value = fake
        filter_mock = MagicMock(return_value=chain)
        oferta_cls = MagicMock()
        oferta_cls.objects.filter = filter_mock

        with patch(
            'mecanimovilapp.apps.servicios.models.OfertaServicio',
            oferta_cls,
        ), patch(
            'mecanimovilapp.apps.servicios.models.Repuesto',
            MagicMock(),
        ):
            out = mod._candidatos_ofertas_taller(
                MagicMock(),
                'Chevrolet',
                modelo_vehiculo='Sail',
            )
        nombres = {c.get('nombre') for c in out}
        self.assertIn('Bujía Sail', nombres)
        self.assertNotIn('Bujía Spark', nombres)

    def test_strips_marca_generico_legacy(self):
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ):
            out = enriquecer_repuestos_cotizacion(
                [{
                    'id': 'rep-0',
                    'nombre': 'Filtro de aire',
                    'cantidad': 1,
                    'precio_unitario_clp': 15000,
                    'marca_repuesto': 'GENÉRICO',
                    'fuente_marketplace': 'catalogo',
                    'proveedor_nombre': 'Catálogo Mecanimovil',
                }],
                taller=MagicMock(),
                usar_ml=False,
            )
        self.assertNotIn('marca_repuesto', out[0])
        self.assertNotEqual(out[0].get('proveedor_nombre'), 'Catálogo Mecanimovil')
        self.assertNotEqual(out[0].get('fuente_marketplace'), 'catalogo')
        self.assertTrue(out[0].get('precio_estimado'))

    def test_enriquecer_historial_mediana_precio_y_marca(self):
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        hist = [{
            'nombre': 'Pastillas freno delanteras',
            'marca_repuesto': 'Textar',
            'precio_unitario_clp': 55000,
            'fuente_marketplace': 'historial',
            'proveedor_nombre': 'Historial del taller',
            'tienda_ml': '',
            'confianza': 0.7,
            'clave': 'pastillas freno delanteras',
        }]
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_catalogo_maestro',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=hist,
        ):
            out = enriquecer_repuestos_cotizacion(
                [{
                    'id': 'rep-0',
                    'nombre': 'Pastillas freno delanteras',
                    'cantidad': 1,
                    'precio_unitario_clp': 40000,
                }],
                taller=MagicMock(),
                usar_ml=False,
            )
        self.assertEqual(out[0].get('marca_repuesto'), 'Textar')
        self.assertEqual(out[0].get('precio_unitario_clp'), 55000)
        self.assertEqual(out[0].get('fuente_marketplace'), 'historial')

    def test_candidatos_ofertas_usa_disponible_no_activo(self):
        """Asegura el filtro ORM correcto (FieldError si se usa activo)."""
        from unittest.mock import MagicMock, patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import enriquecer_repuestos as mod

        chain = MagicMock()
        # filter().select_related().only()[:120] → iterable vacío
        chain.select_related.return_value.only.return_value.__getitem__ = MagicMock(
            return_value=[],
        )
        chain.select_related.return_value.only.return_value.__iter__ = MagicMock(
            return_value=iter([]),
        )
        # Slicing on MagicMock often returns another MagicMock; force empty list
        sliced = []
        only_qs = MagicMock()
        only_qs.__getitem__ = MagicMock(return_value=sliced)
        chain.select_related.return_value.only.return_value = only_qs

        filter_mock = MagicMock(return_value=chain)
        oferta_cls = MagicMock()
        oferta_cls.objects.filter = filter_mock
        taller = MagicMock()

        with patch(
            'mecanimovilapp.apps.servicios.models.OfertaServicio',
            oferta_cls,
        ), patch(
            'mecanimovilapp.apps.servicios.models.Repuesto',
            MagicMock(),
        ):
            out = mod._candidatos_ofertas_taller(taller, 'Toyota')
        filter_mock.assert_called_with(taller=taller, disponible=True)
        self.assertEqual(out, [])

    def test_generar_ia_enrich_failure_no_rompe(self):
        from unittest.mock import patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import generador

        crudo = {
            'servicio_nombre': 'Cambio filtro',
            'mano_obra_clp': 20000,
            'repuestos': [{'nombre': 'Filtro', 'cantidad': 1, 'precio_unitario_clp': 10000}],
        }
        with patch.object(generador, 'asistente_cotizacion_habilitado', return_value=True), patch.object(
            generador,
            'armar_contexto_cotizacion',
            return_value={'marca': 'Toyota', 'modelo': 'Yaris'},
        ), patch.object(
            generador,
            '_construir_prompt',
            return_value='prompt',
        ), patch.object(
            generador,
            '_llamar_gemini',
            return_value=(crudo, {'tokens_entrada': 1, 'tokens_salida': 1, 'modelo': 't'}, None),
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos.enriquecer_repuestos_cotizacion',
            side_effect=Exception('boom'),
        ):
            result = generador.generar_cotizacion_ia(
                taller=None,
                servicio_nombre='Cambio filtro',
                enriquecer_marketplace=True,
            )
        self.assertTrue(result.get('disponible'))
        self.assertIsNotNone(result.get('contenido'))
        self.assertEqual(result['contenido']['servicio_nombre'], 'Cambio filtro')

    def test_recalcular_totales(self):
        rep, mo, total = recalcular_totales(
            [{'cantidad': 2, 'precio_unitario_clp': 10000}],
            5000,
        )
        self.assertEqual(rep, 20000)
        self.assertEqual(mo, 5000)
        self.assertEqual(total, 25000)

    def test_descuento_porcentaje_sobre_mano_obra(self):
        desc, total = calcular_descuento_aplicado(
            costo_repuestos_clp=20000,
            mano_obra_clp=100000,
            descuento_tipo='porcentaje',
            descuento_alcance='mano_obra',
            descuento_valor=10,
        )
        self.assertEqual(desc, 10000)
        self.assertEqual(total, 110000)

    def test_descuento_monto_sobre_total_no_excede_base(self):
        desc, total = calcular_descuento_aplicado(
            costo_repuestos_clp=20000,
            mano_obra_clp=30000,
            descuento_tipo='monto',
            descuento_alcance='total',
            descuento_valor=999999,
        )
        self.assertEqual(desc, 50000)
        self.assertEqual(total, 0)

    def test_descuento_porcentaje_capped_at_100(self):
        desc, total = calcular_descuento_aplicado(
            costo_repuestos_clp=0,
            mano_obra_clp=80000,
            descuento_tipo='porcentaje',
            descuento_alcance='mano_obra',
            descuento_valor=150,
        )
        self.assertEqual(desc, 80000)
        self.assertEqual(total, 0)

    def test_etiqueta_descuento(self):
        self.assertEqual(
            etiqueta_descuento(
                descuento_tipo='porcentaje',
                descuento_alcance='mano_obra',
                descuento_valor=10,
                descuento_clp=10000,
            ),
            'Descuento 10% sobre mano de obra',
        )
        self.assertIn(
            'sobre total',
            etiqueta_descuento(
                descuento_tipo='monto',
                descuento_alcance='total',
                descuento_valor=5000,
                descuento_clp=5000,
            ),
        )

    def test_descuento_visible_deriva_si_no_esta_persistido(self):
        self.assertEqual(
            descuento_visible_clp(
                costo_repuestos_clp=140000,
                mano_obra_clp=30000,
                total_clp=161500,
                descuento_clp=0,
            ),
            8500,
        )
        self.assertEqual(
            descuento_visible_clp(
                costo_repuestos_clp=140000,
                mano_obra_clp=30000,
                total_clp=161500,
                descuento_clp=8500,
            ),
            8500,
        )

    def test_normalizar_cotizacion_completa(self):
        ctx = {'tipo_motor_efectivo': 'GASOLINA', 'tipo_motor_efectivo_label': 'Bencinero (gasolina)'}
        data = {
            'servicio_nombre': 'Cambio bujías',
            'mano_obra_clp': 40000,
            'repuestos': [{'nombre': 'Bujía', 'cantidad': 4, 'precio_unitario_clp': 8000}],
        }
        out = normalizar_cotizacion_ia(data, ctx)
        self.assertEqual(out['servicio_nombre'], 'Cambio bujías')
        self.assertEqual(out['total_clp'], 40000 + 4 * 8000)


class CotizacionCanalUtilTestCase(SimpleTestCase):
    def test_parse_button_aceptar(self):
        self.assertEqual(_parse_button_id('cotizacion_aceptar_42'), ('aceptar', 42))

    def test_parse_button_rechazar(self):
        self.assertEqual(_parse_button_id('cotizacion_rechazar_7'), ('rechazar', 7))

    def test_parse_button_invalido(self):
        self.assertIsNone(_parse_button_id('otro_id'))

    def test_formatear_resumen_incluye_total(self):
        class FakeCot:
            servicio_nombre = 'Diagnóstico'
            modalidad = 'taller'
            vehiculo_marca = 'FIAT'
            vehiculo_modelo = 'Bravo'
            vehiculo_anio = 2010
            vehiculo_patente = 'AB1234'
            vehiculo_cilindraje = '1368'
            tipo_motor_label = 'Bencinero (gasolina)'
            descripcion_problema = 'Fallo encendido'
            repuestos = [{'nombre': 'Bobina', 'cantidad': 1, 'precio_unitario_clp': 50000}]
            costo_repuestos_clp = 50000
            mano_obra_clp = 45000
            total_clp = 95000
            duracion_minutos_estimada = 90
            advertencias = ['Precios referenciales']
            metadata = {}
            url_publica = ''

        texto = formatear_resumen_cotizacion(FakeCot())
        self.assertIn('Diagnóstico', texto)
        self.assertIn('$95.000', texto)
        self.assertIn('Marca: FIAT', texto)
        self.assertIn('Cilindraje: 1368', texto)
        self.assertIn('Mano de obra (IVA incl.):', texto)
        self.assertIn('Condiciones:', texto)


class ContextoCotizacionTestCase(SimpleTestCase):
    def test_incluye_vehiculo_servicio_y_descripcion(self):
        from unittest.mock import patch

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.contexto.resolver_motor_vehiculo',
            return_value='GASOLINA',
        ):
            ctx = armar_contexto_cotizacion(
                servicio_nombre='cambio de aceite',
                descripcion_problema='Aceite sintético 5W40',
                modalidad='taller',
                vehiculo={
                    'marca': 'FIAT',
                    'modelo': 'BRAVO SPORT TJET',
                    'anio': 2010,
                    'patente': 'ABCD12',
                    'cilindraje': '1368',
                },
            )
        self.assertEqual(ctx['marca'], 'FIAT')
        self.assertEqual(ctx['modelo'], 'BRAVO SPORT TJET')
        self.assertEqual(ctx['servicio_nombre'], 'cambio de aceite')
        self.assertEqual(ctx['descripcion_problema'], 'Aceite sintético 5W40')
        self.assertEqual(ctx['tipo_motor_efectivo'], 'GASOLINA')


class PlantillaVehiculoTestCase(SimpleTestCase):
    def test_coincide_marca_modelo_cilindraje(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        snap = {
            'vehiculo_marca': 'FIAT',
            'vehiculo_modelo': 'BRAVO SPORT TJET',
            'vehiculo_cilindraje': '1368',
        }
        self.assertTrue(
            plantilla_coincide_vehiculo(
                snap,
                marca='Fiat',
                modelo='Bravo Sport T-Jet',
                cilindraje='1.368 cc',
            ),
        )

    def test_rechaza_cilindraje_distinto(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        snap = {
            'vehiculo_marca': 'FIAT',
            'vehiculo_modelo': 'BRAVO',
            'vehiculo_cilindraje': '1368',
        }
        self.assertFalse(
            plantilla_coincide_vehiculo(
                snap,
                marca='FIAT',
                modelo='BRAVO',
                cilindraje='1600',
            ),
        )

    def test_rechaza_sin_vehiculo_en_snapshot(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        self.assertFalse(
            plantilla_coincide_vehiculo(
                {'servicio_nombre': 'Cambio aceite'},
                marca='FIAT',
                modelo='BRAVO',
            ),
        )

    def test_rechaza_modelo_parecido_no_identico(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        snap = {'vehiculo_marca': 'Toyota', 'vehiculo_modelo': 'Yaris Cross'}
        self.assertFalse(
            plantilla_coincide_vehiculo(snap, marca='Toyota', modelo='Yaris'),
        )
        self.assertTrue(
            plantilla_coincide_vehiculo(snap, marca='toyota', modelo='Yaris Cross'),
        )

    def test_rechaza_otra_marca_mismo_servicio(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        snap = {'vehiculo_marca': 'Toyota', 'vehiculo_modelo': 'Corolla'}
        self.assertFalse(
            plantilla_coincide_vehiculo(snap, marca='BAIC', modelo='Corolla'),
        )


class VehiculoHistorialExactoTestCase(SimpleTestCase):
    def test_marca_modelo_identicos_ignoran_guion_y_caso(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.vehiculo_exacto import (
            vehiculo_historial_identico,
        )

        self.assertTrue(
            vehiculo_historial_identico('FIAT', 'BRAVO SPORT TJET', 'Fiat', 'Bravo Sport T-Jet'),
        )
        self.assertTrue(vehiculo_historial_identico('Toyota', 'Yaris', 'TOYOTA', 'yaris'))

    def test_no_comparte_toyota_con_baic_ni_yaris_con_cross(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.vehiculo_exacto import (
            vehiculo_historial_identico,
        )

        self.assertFalse(
            vehiculo_historial_identico('Toyota', 'Corolla', 'BAIC', 'X35'),
        )
        self.assertFalse(
            vehiculo_historial_identico('Toyota', 'Yaris', 'Toyota', 'Yaris Cross'),
        )

    def test_falta_modelo_no_reusa(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.vehiculo_exacto import (
            vehiculo_historial_identico,
        )

        self.assertFalse(vehiculo_historial_identico('Toyota', 'Yaris', 'Toyota', ''))
        self.assertFalse(vehiculo_historial_identico('Toyota', '', 'Toyota', 'Yaris'))

    def test_clave_historial_exige_marca_modelo_en_clave(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.vehiculo_exacto import (
            clave_historial_cubre_vehiculo,
        )

        self.assertFalse(
            clave_historial_cubre_vehiculo('pastillas freno', 'Toyota', 'Yaris'),
        )
        self.assertTrue(
            clave_historial_cubre_vehiculo(
                'pastillas freno|toyota yaris 2018',
                'Toyota',
                'Yaris',
            ),
        )
        self.assertFalse(
            clave_historial_cubre_vehiculo(
                'pastillas freno|toyota yaris cross 2018',
                'Toyota',
                'Yaris',
            ),
        )
        self.assertFalse(
            clave_historial_cubre_vehiculo(
                'pastillas freno|baic x35',
                'Toyota',
                'Yaris',
            ),
        )


class SplitServiciosCatalogoTestCase(SimpleTestCase):
    def test_no_parte_aceite_y_filtro(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
            _split_servicios,
        )

        self.assertEqual(
            _split_servicios('Cambio de aceite y filtro'),
            ['Cambio de aceite y filtro'],
        )

    def test_parte_servicios_distintos_por_mas(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
            _split_servicios,
        )

        parts = _split_servicios('Cambio de aceite y filtro + Cambio de filtro de aire')
        self.assertEqual(len(parts), 2)
        self.assertIn('Cambio de aceite y filtro', parts[0])
        self.assertIn('aire', parts[1].lower())


class NormalizarMantieneServicioPedidoTestCase(SimpleTestCase):
    def test_pin_servicio_del_contexto_aunque_ia_expanda(self):
        ctx = {'servicio_nombre': 'Cambio de aceite'}
        data = {
            'servicio_nombre': 'Cambio de aceite + filtro de aire + diagnóstico',
            'mano_obra_clp': 30000,
            'repuestos': [],
        }
        out = normalizar_cotizacion_ia(data, ctx)
        self.assertEqual(out['servicio_nombre'], 'Cambio de aceite')


class HistorialCacheNoCruzaModelosTestCase(SimpleTestCase):
    def test_clave_fuzzy_historial_no_aplica_a_otro_auto(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _candidatos_web_cache,
        )

        row_fuzzy = SimpleNamespace(
            clave='pastillas freno',
            dominio='historial-taller',
            marca_repuesto='Bosch',
            nombre_producto='Pastillas freno',
            precio_clp=99000,
            tienda='Historial del taller',
            url='',
            confianza=0.85,
        )
        row_baic = SimpleNamespace(
            clave='pastillas freno|baic x35',
            dominio='historial-taller',
            marca_repuesto='Bosch',
            nombre_producto='Pastillas freno',
            precio_clp=45000,
            tienda='Historial del taller',
            url='',
            confianza=0.85,
        )
        row_toyota = SimpleNamespace(
            clave='pastillas freno|toyota yaris',
            dominio='historial-taller',
            marca_repuesto='Bosch',
            nombre_producto='Pastillas freno',
            precio_clp=22000,
            tienda='Historial del taller',
            url='',
            confianza=0.85,
        )

        class FakeQS(list):
            def order_by(self, *args, **kwargs):
                return self

            def filter(self, *args, **kwargs):
                return self

            def __getitem__(self, item):
                return list(self)[item]

        fake_qs = FakeQS([row_fuzzy, row_baic, row_toyota])

        with patch(
            'mecanimovilapp.apps.ordenes.models.PrecioRepuestoWeb.objects.filter',
            return_value=fake_qs,
        ):
            hits = _candidatos_web_cache(
                marca_vehiculo='Toyota',
                modelo_vehiculo='Yaris',
            )
        precios = {h.get('precio_unitario_clp') for h in hits}
        self.assertIn(22000, precios)
        self.assertNotIn(99000, precios)
        self.assertNotIn(45000, precios)

    def test_prompt_cotizacion_acota_alcance(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
            _construir_prompt,
        )

        prompt = _construir_prompt({
            'marca': 'Toyota',
            'modelo': 'Yaris',
            'anio': '2018',
            'servicio_nombre': 'Cambio de aceite',
            'descripcion_problema': 'Mantención',
            'chat_reciente': 'Cliente: también hablamos de pastillas el mes pasado',
            'tipo_motor_efectivo_label': 'Bencinero',
        })
        self.assertIn('ALCANCE', prompt)
        self.assertIn('Cambio de aceite', prompt)
        self.assertIn('Toyota ≠ BAIC', prompt)

    def test_gemini_reintenta_timeout_de_red(self):
        from unittest.mock import MagicMock, patch

        import requests

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import generador

        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': '{"servicio_nombre":"X"}'}]}}],
            'usageMetadata': {},
        }
        with patch.object(generador.settings, 'GEMINI_API_KEY', 'k'), patch.object(
            generador.settings, 'GEMINI_RETRY_MAX', 1,
        ), patch.object(generador.time, 'sleep'), patch.object(
            generador.requests,
            'post',
            side_effect=[requests.Timeout('read timed out'), ok],
        ) as post_mock:
            data, _uso, err = generador._llamar_gemini('prompt')
        self.assertIsNone(err)
        self.assertEqual(data.get('servicio_nombre'), 'X')
        self.assertEqual(post_mock.call_count, 2)


class FuenteWebEnrichTestCase(SimpleTestCase):
    def test_web_gana_a_estimado_y_pierde_contra_catalogo(self):
        from unittest.mock import patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        web = [{
            'nombre': 'Pastillas freno',
            'marca_repuesto': 'Bosch',
            'precio_unitario_clp': 38000,
            'fuente_marketplace': 'web',
            'proveedor_nombre': 'AutoPlanet',
            'url_producto': 'https://www.autoplanet.cl/p/1',
            'confianza': 0.8,
            'clave': 'pastillas freno',
        }]
        cat = [{
            'nombre': 'Pastillas freno',
            'marca_repuesto': 'Mann',
            'precio_unitario_clp': 30000,
            'fuente_marketplace': 'catalogo',
            'proveedor_nombre': 'Catálogo del taller',
            'confianza': 0.9,
            'clave': 'pastillas freno',
        }]

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_web_cache',
            return_value=web,
        ):
            solo_web = enriquecer_repuestos_cotizacion(
                [{
                    'id': 'rep-0',
                    'nombre': 'Pastillas freno delanteras',
                    'cantidad': 1,
                    'precio_unitario_clp': 20000,
                }],
                marca_vehiculo='Hyundai',
                modelo_vehiculo='Accent',
                anio_vehiculo=2015,
                usar_ml=False,
                usar_web=True,
            )
        self.assertEqual(solo_web[0].get('fuente_marketplace'), 'web')
        self.assertEqual(solo_web[0].get('marca_repuesto'), 'Bosch')
        self.assertEqual(solo_web[0].get('proveedor_nombre'), 'AutoPlanet')
        self.assertEqual(solo_web[0].get('url_producto'), 'https://www.autoplanet.cl/p/1')
        self.assertTrue(solo_web[0].get('precio_estimado'))
        self.assertTrue(solo_web[0].get('precio_referencia_mercado'))
        self.assertEqual(solo_web[0].get('precio_unitario_clp'), 38000)

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_ofertas_taller',
            return_value=cat,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_historial_taller',
            return_value=[],
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._candidatos_web_cache',
            return_value=web,
        ):
            con_cat = enriquecer_repuestos_cotizacion(
                [{
                    'id': 'rep-0',
                    'nombre': 'Pastillas freno delanteras',
                    'cantidad': 1,
                    'precio_unitario_clp': 20000,
                }],
                marca_vehiculo='Hyundai',
                modelo_vehiculo='Accent',
                usar_ml=False,
                usar_web=True,
            )
        self.assertEqual(con_cat[0].get('fuente_marketplace'), 'catalogo')
        self.assertEqual(con_cat[0].get('marca_repuesto'), 'Mann')
        self.assertEqual(con_cat[0].get('precio_unitario_clp'), 30000)
        self.assertFalse(con_cat[0].get('precio_estimado'))
        self.assertIsNone(con_cat[0].get('precio_referencia_mercado'))

    def test_normalizar_conserva_url_producto_y_referencia_mercado(self):
        rep = normalizar_repuesto(
            {
                'nombre': 'Kit embrague',
                'precio_unitario_clp': 120000,
                'fuente_marketplace': 'web',
                'marca_repuesto': 'Sachs',
                'proveedor_nombre': 'AutoPlanet',
                'url_producto': 'https://www.autoplanet.cl/p/9',
                'precio_estimado': True,
                'precio_referencia_mercado': True,
            },
            0,
        )
        self.assertEqual(rep.get('url_producto'), 'https://www.autoplanet.cl/p/9')
        self.assertTrue(rep.get('precio_referencia_mercado'))
        self.assertEqual(rep.get('fuente_marketplace'), 'web')

    def test_vista_publica_omite_url_producto(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            _repuestos_publicos,
        )

        pubs = _repuestos_publicos([
            {
                'nombre': 'Kit embrague',
                'precio_unitario_clp': 120000,
                'marca_repuesto': 'Sachs',
                'tienda_ml': 'seller',
                'proveedor_nombre': 'AutoPlanet',
                'url_producto': 'https://www.autoplanet.cl/p/9',
            },
        ])
        self.assertEqual(len(pubs), 1)
        self.assertNotIn('url_producto', pubs[0])
        self.assertNotIn('tienda_ml', pubs[0])
        self.assertNotIn('proveedor_nombre', pubs[0])
        self.assertEqual(pubs[0].get('marca_repuesto'), 'Sachs')


class ManoObraLineasTestCase(SimpleTestCase):
    def _cot(self, **kwargs):
        from types import SimpleNamespace
        defaults = {
            'servicio_nombre': 'Mantención 10.000',
            'mano_obra_clp': 70000,
            'metadata': {},
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_backfill_desde_lump(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
            resolver_mano_obra_lineas,
        )
        lineas = resolver_mano_obra_lineas(self._cot())
        self.assertEqual(len(lineas), 1)
        self.assertEqual(lineas[0]['nombre'], 'Mantención 10.000')
        self.assertEqual(lineas[0]['monto_clp'], 70000)

    def test_alias_precio_mano_obra_clp(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
            resolver_mano_obra_lineas,
        )
        cot = self._cot(metadata={
            'servicios_lineas': [
                {'nombre': 'Diagnóstico', 'precio_mano_obra_clp': 20000},
                {'nombre': 'Alineación', 'precio_clp': 15000},
            ],
        })
        lineas = resolver_mano_obra_lineas(cot)
        self.assertEqual([l['monto_clp'] for l in lineas], [20000, 15000])

    def test_lineas_ganan_sobre_lump(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
            aplicar_mano_obra_en_edicion,
        )
        cot = self._cot(metadata={
            'servicios_lineas': [
                {'id': 'a', 'nombre': 'Frenos', 'monto_clp': 35000},
                {'id': 'b', 'nombre': 'Alineación', 'monto_clp': 15000},
            ],
        }, mano_obra_clp=50000)
        aplicar_mano_obra_en_edicion(cot, {'mano_obra_clp': 99999})
        self.assertEqual(int(cot.mano_obra_clp), 50000)

    def test_persistir_lineas_suma(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
            persistir_mano_obra_lineas,
        )
        cot = self._cot(metadata={'servicios_lineas': [
            {'id': 'a', 'nombre': 'Frenos', 'monto_clp': 10000, 'oferta_servicio_id': 7},
        ]})
        persistir_mano_obra_lineas(cot, [
            {'id': 'a', 'nombre': 'Cambio de pastillas', 'monto_clp': 35000},
            {'nombre': 'Rotación', 'monto_clp': 15000},
        ])
        self.assertEqual(int(cot.mano_obra_clp), 50000)
        saved = cot.metadata['servicios_lineas']
        self.assertEqual(saved[0]['oferta_servicio_id'], 7)
        self.assertEqual(saved[0]['nombre'], 'Cambio de pastillas')
        self.assertEqual(len(saved), 2)

    def test_validar_nombre_vacio_con_monto(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
            validar_nombres_mano_obra_para_enviar,
        )
        cot = self._cot(metadata={'servicios_lineas': [
            {'nombre': '', 'monto_clp': 12000},
        ]})
        self.assertTrue(validar_nombres_mano_obra_para_enviar(cot))
        cot_ok = self._cot(metadata={'servicios_lineas': [
            {'nombre': 'Diagnóstico', 'monto_clp': 12000},
        ]})
        self.assertIsNone(validar_nombres_mano_obra_para_enviar(cot_ok))

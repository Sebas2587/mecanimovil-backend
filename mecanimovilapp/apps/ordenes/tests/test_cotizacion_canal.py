"""Tests cotización canal IA."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.contexto import armar_contexto_cotizacion
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
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

        texto = formatear_resumen_cotizacion(FakeCot())
        self.assertIn('Diagnóstico', texto)
        self.assertIn('$95.000', texto)
        self.assertIn('Marca: FIAT', texto)
        self.assertIn('Cilindraje: 1368', texto)
        self.assertIn('Mano de obra:', texto)
        self.assertIn('Condiciones:', texto)


class ContextoCotizacionTestCase(SimpleTestCase):
    def test_incluye_vehiculo_servicio_y_descripcion(self):
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

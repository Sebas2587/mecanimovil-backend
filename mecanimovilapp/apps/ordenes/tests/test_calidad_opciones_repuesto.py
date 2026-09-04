"""Eje de calidad y pool de opciones (PRD selección de repuestos)."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.calidad_repuesto import (
    anotar_calidad_en_linea,
    calidad_pendiente_en_texto,
    detectar_calidad,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.familias_sensibles import (
    familia_tiene_eje_calidad,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.opciones_repuesto import (
    construir_opciones_linea,
    ordenar_pool,
    proyectar_opciones_publicas,
    spread_pool,
)


class CalidadRepuestoTestCase(SimpleTestCase):
    def test_detecta_espanol_chileno(self):
        self.assertEqual(detectar_calidad('quiero original de agencia'), 'original')
        self.assertEqual(detectar_calidad('equivalente OEM Bosch'), 'oem')
        self.assertEqual(detectar_calidad('alternativo más económico'), 'alternativo')

    def test_ambiguo_queda_pendiente(self):
        self.assertIsNone(detectar_calidad('Original o equivalente OEM'))
        self.assertTrue(calidad_pendiente_en_texto('Original o equivalente OEM'))
        linea = anotar_calidad_en_linea({
            'nombre': 'Disco de freno',
            'especificacion': 'Original o equivalente OEM',
        })
        self.assertTrue(linea.get('calidad_pendiente'))
        self.assertNotIn('calidad', linea)

    def test_calidad_decidida_no_confunde_especificacion(self):
        linea = anotar_calidad_en_linea({
            'nombre': 'Pastilla de freno',
            'especificacion': 'Cerámica',
            'calidad': 'oem',
        })
        self.assertEqual(linea['calidad'], 'oem')
        self.assertFalse(linea.get('calidad_pendiente'))

    def test_eje_calidad_familias(self):
        self.assertTrue(familia_tiene_eje_calidad('Pastillas de freno'))
        self.assertTrue(familia_tiene_eje_calidad('Filtro de aire'))
        self.assertFalse(familia_tiene_eje_calidad('Neumático 205/55'))


class OpcionesPoolTestCase(SimpleTestCase):
    def test_orden_jerarquia_d12(self):
        hits = [
            {
                'fuente_marketplace': 'web',
                'nombre': 'Pastilla Bosch',
                'precio_unitario_clp': 31200,
                'proveedor_nombre': 'AutoPlanet',
                'url_producto': 'https://autoplanet.cl/x',
                'confianza': 0.8,
            },
            {
                'fuente_marketplace': 'proveedor',
                'nombre': 'Pastilla Bosch',
                'precio_unitario_clp': 26400,
                'proveedor_nombre': 'Refax Maipú',
                'proveedor_id': 3,
                'confianza': 0.97,
            },
            {
                'fuente_marketplace': 'mercadolibre',
                'nombre': 'Pastilla genérica',
                'precio_unitario_clp': 18900,
                'tienda_ml': 'seller',
                'confianza': 0.6,
            },
        ]
        pool = construir_opciones_linea(
            {'nombre': 'Pastilla de freno', 'calidad': 'oem'},
            hits=hits,
            max_opciones=8,
        )
        self.assertGreaterEqual(len(pool), 2)
        self.assertEqual(pool[0]['fuente'], 'proveedor')
        self.assertTrue(pool[0]['es_proveedor_taller'])

    def test_dedupe_por_dominio_y_max_3(self):
        hits = [
            {
                'fuente_marketplace': 'web',
                'nombre': 'A',
                'precio_unitario_clp': 10000,
                'url_producto': 'https://tienda.cl/a',
            },
            {
                'fuente_marketplace': 'web',
                'nombre': 'B',
                'precio_unitario_clp': 11000,
                'url_producto': 'https://tienda.cl/b',
            },
            {
                'fuente_marketplace': 'web',
                'nombre': 'C',
                'precio_unitario_clp': 12000,
                'url_producto': 'https://otra.cl/c',
            },
            {
                'fuente_marketplace': 'web',
                'nombre': 'D',
                'precio_unitario_clp': 13000,
                'url_producto': 'https://tercera.cl/d',
            },
            {
                'fuente_marketplace': 'web',
                'nombre': 'E',
                'precio_unitario_clp': 14000,
                'url_producto': 'https://cuarta.cl/e',
            },
        ]
        pool = construir_opciones_linea({'nombre': 'Filtro'}, hits=hits, max_opciones=3)
        dominios = [o['dominio'] for o in pool]
        self.assertEqual(len(dominios), len(set(dominios)))
        self.assertLessEqual(len(pool), 3)

    def test_spread_pct(self):
        ops = [{'precio_clp': 10000}, {'precio_clp': 12500}]
        self.assertAlmostEqual(spread_pool(ops), 0.25)
        self.assertEqual(spread_pool([{'precio_clp': 10000}]), 0.0)

    def test_proyeccion_publica_no_filtra_secretos(self):
        pub = proyectar_opciones_publicas([{
            'id': 'abc',
            'nombre': 'Pastilla Bosch',
            'marca_repuesto': 'Bosch',
            'calidad': 'oem',
            'imagen_url': 'https://cdn.mecanimovil.cl/x.jpg',
            'precio_min_clp': 28000,
            'precio_max_clp': 34000,
            'posicion_relativa': 'intermedia',
            'tienda': 'Refax',
            'dominio': 'refax.cl',
            'url': 'https://refax.cl/x',
            'proveedor_id': 9,
            'es_proveedor_taller': True,
            'fuente': 'web',
            'certeza': 'referencial',
            'precio_clp': 31200,
            'confianza': 0.8,
        }])
        self.assertEqual(len(pub), 1)
        for secret in (
            'tienda', 'dominio', 'url', 'proveedor_id', 'es_proveedor_taller',
            'fuente', 'certeza', 'confianza', 'precio_clp',
        ):
            self.assertNotIn(secret, pub[0])
        self.assertEqual(pub[0]['calidad'], 'oem')
        self.assertEqual(pub[0]['nombre'], 'Pastilla Bosch')

    def test_repuestos_publicos_sigue_omitiendo_internos(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import _repuestos_publicos

        pubs = _repuestos_publicos([{
            'nombre': 'Bujía',
            'calidad': 'oem',
            'imagen_url': 'https://cdn.mecanimovil.cl/x.jpg',
            'tienda_ml': 'seller',
            'proveedor_nombre': 'Refax',
            'opciones': [{'id': 'x', 'tienda': 'Refax'}],
            'certeza': 'referencial',
        }])
        self.assertEqual(pubs[0]['calidad'], 'oem')
        self.assertNotIn('tienda_ml', pubs[0])
        self.assertNotIn('opciones', pubs[0])
        self.assertNotIn('certeza', pubs[0])

    def test_ordenar_proveedor_antes_que_web(self):
        orden = ordenar_pool([
            {'fuente': 'web', 'precio_clp': 1, 'confianza': 0.9},
            {'fuente': 'proveedor', 'es_proveedor_taller': True, 'precio_clp': 2, 'confianza': 0.5},
            {'fuente': 'catalogo', 'precio_clp': 3, 'confianza': 0.8},
        ])
        self.assertEqual([o['fuente'] for o in orden], ['proveedor', 'catalogo', 'web'])

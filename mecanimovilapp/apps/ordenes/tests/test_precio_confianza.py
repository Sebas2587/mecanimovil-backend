"""Certeza, banda y factor de mostrador (PRD confianza precio)."""
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.categoria_repuesto import (
    clasificar_categoria,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.familias_sensibles import (
    detectar_familia_sensible,
    especificacion_valida,
    linea_especificacion_pendiente,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
    normalizar_repuesto,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio import (
    resolver_precio_linea,
)


class CategoriaYFamiliaTestCase(SimpleTestCase):
    def test_clasifica_bujias_y_frenos(self):
        self.assertEqual(clasificar_categoria('Bujía de encendido NGK'), 'bujias')
        self.assertEqual(clasificar_categoria('Pastillas de freno delanteras'), 'frenos')
        self.assertEqual(clasificar_categoria('Filtro de aceite'), 'filtros')
        self.assertEqual(clasificar_categoria('Algo desconocido'), 'otros')

    def test_familia_sensible_bujia(self):
        self.assertEqual(detectar_familia_sensible('Bujías de encendido'), 'bujia')
        self.assertTrue(especificacion_valida('bujia', 'Iridio'))
        self.assertFalse(especificacion_valida('bujia', ''))
        self.assertTrue(linea_especificacion_pendiente({
            'nombre': 'Bujía de encendido',
        }))
        self.assertFalse(linea_especificacion_pendiente({
            'nombre': 'Bujía de encendido',
            'especificacion': 'Iridio',
        }))


class BackfillCertezaTestCase(SimpleTestCase):
    def test_catalogo_es_confirmado(self):
        rep = normalizar_repuesto({
            'nombre': 'Filtro de aceite',
            'precio_unitario_clp': 9000,
            'fuente_marketplace': 'catalogo',
        }, 0)
        self.assertEqual(rep['certeza'], 'confirmado')
        self.assertFalse(rep['precio_estimado'])

    def test_web_es_referencial(self):
        rep = normalizar_repuesto({
            'nombre': 'Filtro de aceite',
            'precio_unitario_clp': 7000,
            'fuente_marketplace': 'web',
        }, 0)
        self.assertEqual(rep['certeza'], 'referencial')
        self.assertTrue(rep['precio_estimado'])
        self.assertTrue(rep['precio_referencia_mercado'])

    def test_sin_monto_es_sin_precio(self):
        rep = normalizar_repuesto({
            'nombre': 'Bujía de encendido',
            'precio_unitario_clp': 0,
        }, 0)
        self.assertEqual(rep['certeza'], 'sin_precio')
        self.assertTrue(rep.get('especificacion_pendiente'))


class ResolverPrecioBandaTestCase(SimpleTestCase):
    def _hit(self, fuente, precio, **extra):
        data = {
            'nombre': 'Bujía iridio',
            'fuente_marketplace': fuente,
            'precio_unitario_clp': precio,
            'confianza': 0.8,
        }
        data.update(extra)
        return data

    @override_settings(PRECIO_CONFIANZA_ENABLED=True, FACTOR_MERCADO_MAX=2.50)
    def test_sin_hits_no_escribe_monto(self):
        linea = {
            'nombre': 'Amortiguador delantero',
            'especificacion': 'Gas',
            'precio_unitario_clp': 55000,
            'precio_min_clp': 40000,
            'precio_max_clp': 75000,
        }
        resolver_precio_linea(linea, [], confianza_enabled=True)
        self.assertEqual(linea['certeza'], 'sin_precio')
        self.assertEqual(linea['precio_unitario_clp'], 0)
        self.assertEqual(linea['precio_min_clp'], 40000)
        self.assertEqual(linea['precio_max_clp'], 75000)

    @override_settings(PRECIO_CONFIANZA_ENABLED=True, FACTOR_MERCADO_MAX=2.50)
    def test_especificacion_pendiente_sin_monto(self):
        linea = {
            'nombre': 'Bujía de encendido',
            'precio_unitario_clp': 3200,
        }
        resolver_precio_linea(linea, [self._hit('web', 3200)], confianza_enabled=True)
        self.assertTrue(linea.get('especificacion_pendiente'))
        self.assertEqual(linea['certeza'], 'sin_precio')
        self.assertEqual(linea['precio_unitario_clp'], 0)

    @override_settings(PRECIO_CONFIANZA_ENABLED=True, FACTOR_MERCADO_MAX=2.50)
    @patch(
        'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio.factor_mercado_categoria',
        return_value=2.0,
    )
    def test_un_hit_web_min_crudo_max_ajustado(self, _factor):
        linea = {
            'nombre': 'Bujía de encendido',
            'especificacion': 'Iridio',
            'precio_unitario_clp': 0,
        }
        resolver_precio_linea(linea, [self._hit('web', 10000)], confianza_enabled=True)
        self.assertEqual(linea['certeza'], 'referencial')
        self.assertEqual(linea['precio_min_clp'], 10000)
        self.assertEqual(linea['precio_max_clp'], 20000)
        self.assertEqual(linea['precio_unitario_clp'], 20000)
        self.assertEqual(linea['precio_marketplace_clp'], 10000)
        self.assertEqual(linea['factor_mercado'], 2.0)
        self.assertEqual(linea['fuentes_n'], 1)

    @override_settings(PRECIO_CONFIANZA_ENABLED=True, FACTOR_MERCADO_MAX=2.50)
    @patch(
        'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio.factor_mercado_categoria',
        return_value=1.5,
    )
    def test_tres_hits_banda_y_techo(self, _factor):
        linea = {
            'nombre': 'Filtro de aceite',
            'precio_unitario_clp': 0,
        }
        hits = [
            self._hit('web', 8000),
            self._hit('web', 12000, proveedor_nombre='AutoPlanet'),
            self._hit('historial', 14000),
        ]
        resolver_precio_linea(linea, hits, confianza_enabled=True)
        self.assertEqual(linea['fuentes_n'], 3)
        self.assertEqual(linea['precio_unitario_clp'], linea['precio_max_clp'])
        self.assertGreaterEqual(linea['precio_max_clp'], linea['precio_min_clp'])
        self.assertEqual(linea['certeza'], 'referencial')

    @override_settings(PRECIO_CONFIANZA_ENABLED=True, FACTOR_MERCADO_MAX=2.50)
    @patch(
        'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio.factor_mercado_categoria',
        return_value=9.0,
    )
    def test_factor_respeta_tope(self, _factor):
        linea = {
            'nombre': 'Filtro de aire',
            'precio_unitario_clp': 0,
        }
        resolver_precio_linea(linea, [self._hit('web', 10000)], confianza_enabled=True)
        self.assertEqual(linea['factor_mercado'], 2.50)
        self.assertEqual(linea['precio_max_clp'], 25000)

    def test_flag_apagado_conserva_precio_web_crudo(self):
        linea = {
            'nombre': 'Pastillas freno delanteras',
            'precio_unitario_clp': 20000,
        }
        resolver_precio_linea(
            linea,
            [self._hit('web', 38000, marca_repuesto='Bosch')],
            confianza_enabled=False,
        )
        self.assertEqual(linea['precio_unitario_clp'], 38000)
        self.assertEqual(linea['certeza'], 'referencial')


class FactorTopeTestCase(TestCase):
    def test_factor_capped(self):
        from mecanimovilapp.apps.ordenes.models import FactorMercadoCategoria
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.categoria_repuesto import (
            factor_mercado_categoria,
        )

        FactorMercadoCategoria.objects.update_or_create(
            categoria='bujias',
            defaults={'factor': Decimal('9.00'), 'muestras': 20},
        )
        with override_settings(FACTOR_MERCADO_MAX=2.50):
            self.assertEqual(factor_mercado_categoria('bujias'), 2.50)


class RepuestosPublicosWhitelistTestCase(SimpleTestCase):
    def test_no_expone_campos_internos(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            _repuestos_publicos,
        )

        pubs = _repuestos_publicos([{
            'nombre': 'Bujía iridio',
            'precio_unitario_clp': 24500,
            'marca_repuesto': 'NGK',
            'especificacion': 'Iridio',
            'precio_min_clp': 18900,
            'precio_max_clp': 24500,
            'tienda_ml': 'seller',
            'proveedor_nombre': 'Refax',
            'url_producto': 'https://ml.cl/x',
            'proveedor_id': 9,
            'precio_marketplace_clp': 12250,
            'factor_mercado': 2.0,
            'certeza': 'referencial',
            'fuentes_n': 3,
            'alternativas': [{'etiqueta': 'economica', 'precio_clp': 3200}],
        }])
        self.assertEqual(len(pubs), 1)
        self.assertEqual(pubs[0]['especificacion'], 'Iridio')
        self.assertEqual(pubs[0]['precio_min_clp'], 18900)
        for secret in (
            'tienda_ml', 'proveedor_nombre', 'url_producto', 'proveedor_id',
            'precio_marketplace_clp', 'factor_mercado', 'certeza', 'fuentes_n',
            'alternativas',
        ):
            self.assertNotIn(secret, pubs[0])


class DocumentoPublicoTipoTestCase(SimpleTestCase):
    def test_banda_y_tipo(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            _banda_totales_publica,
            _tipo_documento_publico,
        )

        class _C:
            tipo_documento = 'estimacion'
            estado = 'enviada'
            mano_obra_clp = 10000
            descuento_clp = 0
            repuestos = [{
                'cantidad': 4,
                'precio_min_clp': 18000,
                'precio_max_clp': 24000,
                'precio_unitario_clp': 24000,
            }]

        self.assertEqual(_tipo_documento_publico(_C()), 'estimacion')
        self.assertEqual(_banda_totales_publica(_C()), (82000, 106000))

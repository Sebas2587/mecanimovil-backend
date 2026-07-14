"""
Tests básicos del motor de valoración de mercado.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mecanimovilapp.apps.valoracion_mercado.services.liquidez_engine import compute_liquidity
from mecanimovilapp.apps.valoracion_mercado.services.valor_engine import compute_valor_real


class ValorEngineTests(SimpleTestCase):
    def test_blend_getapi_y_externo(self):
        vehiculo = MagicMock()
        vehiculo.kilometraje = 80000
        vehiculo.precio_mercado_promedio = 10_000_000
        vehiculo.precio_mercado_min = 9_000_000
        vehiculo.precio_mercado_max = 11_000_000
        vehiculo.tasacion_fiscal = 8_000_000
        vehiculo.estados_salud = MagicMock()
        vehiculo.estados_salud.order_by.return_value.first.return_value = None

        comparables = [{'precio': 9_500_000, 'kilometraje': 75000}] * 6
        segmento = {'n_anuncios_activos': 6, 'n_semanas_tracking': 4}

        with patch(
            'mecanimovilapp.apps.valoracion_mercado.services.valor_engine.calculate_suggested_price',
            return_value=10_200_000,
        ):
            result = compute_valor_real(vehiculo, comparables, segmento)

        self.assertGreater(result['valor_real_hoy'], 0)
        self.assertIn(result['confianza'], ('alta', 'media', 'estimado'))

    def test_sin_histograma_inventado_sin_comparables(self):
        vehiculo = MagicMock()
        vehiculo.kilometraje = 50000
        vehiculo.precio_mercado_promedio = 5_000_000
        vehiculo.precio_mercado_min = 4_700_000
        vehiculo.precio_mercado_max = 5_300_000
        vehiculo.tasacion_fiscal = 4_000_000

        with patch(
            'mecanimovilapp.apps.valoracion_mercado.services.valor_engine.calculate_suggested_price',
            return_value=5_459_000,
        ):
            result = compute_valor_real(vehiculo, [], None)

        self.assertEqual(result['confianza'], 'estimado')
        self.assertEqual(result['histograma_origen'], 'estimado')
        self.assertEqual(result['histograma'], [])


class LiquidezEngineTests(SimpleTestCase):
    def test_calculando_sin_datos_suficientes(self):
        vehiculo = MagicMock()
        vehiculo.year = 2018
        vehiculo.marca_id = 1
        vehiculo.modelo_id = 2
        vehiculo.mes_revision_tecnica = 'Marzo'
        vehiculo.vin = 'ABC'
        vehiculo.estados_salud = MagicMock()
        vehiculo.estados_salud.order_by.return_value.first.return_value = MagicMock(
            salud_general_porcentaje=75
        )

        result = compute_liquidity(vehiculo, 8_000_000, [], {'n_comparables': 2, 'n_semanas_tracking': 1})
        self.assertEqual(result['liquidez_label'], 'calculando')
        self.assertIsNone(result['liquidez_score'])
        self.assertFalse(result['precision_suficiente'])

    @patch('mecanimovilapp.apps.valoracion_mercado.services.liquidez_engine._rotation_score', return_value=(50.0, None))
    @patch('mecanimovilapp.apps.valoracion_mercado.services.liquidez_engine._density_score', return_value=(55.0, 'Oferta estable'))
    def test_provisional_con_cinco_avisos(self, _den, _rot):
        vehiculo = MagicMock()
        vehiculo.year = 2018
        vehiculo.marca_id = 1
        vehiculo.modelo_id = 2
        vehiculo.mes_revision_tecnica = 'Marzo'
        vehiculo.vin = 'ABC'
        vehiculo.estados_salud = MagicMock()
        vehiculo.estados_salud.order_by.return_value.first.return_value = MagicMock(
            salud_general_porcentaje=80
        )
        comps = [{'precio': 7_500_000 + i * 100_000} for i in range(6)]
        result = compute_liquidity(
            vehiculo,
            8_000_000,
            comps,
            {'n_comparables': 6, 'n_semanas_tracking': 0, 'n_anuncios_activos': 6},
        )
        self.assertIn(result['liquidez_label'], ('facil', 'moderado', 'dificil'))
        self.assertIsNotNone(result['liquidez_score'])
        self.assertFalse(result['precision_suficiente'])

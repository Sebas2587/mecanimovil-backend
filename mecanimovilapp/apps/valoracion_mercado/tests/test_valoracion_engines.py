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
        self.assertFalse(result['precision_suficiente'])

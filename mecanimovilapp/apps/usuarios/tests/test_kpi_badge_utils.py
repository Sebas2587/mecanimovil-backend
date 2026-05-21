"""Tests de política de insignia KPI pública (sin DB)."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.usuarios.kpi_badge_utils import (
    _sample_points_from_kpis,
    compute_kpi_badge_for_proveedor,
)


class KpiBadgeSamplePointsTests(SimpleTestCase):
    def test_ofertas_solas_pesan_menos_que_terminados(self):
        solo_ofertas = _sample_points_from_kpis({
            'ofertas_total_en_periodo': 10,
            'ordenes_mercado_completadas': 0,
            'resenas_muestra': 0,
        })
        con_terminados = _sample_points_from_kpis({
            'ofertas_total_en_periodo': 0,
            'servicios_terminados_en_periodo': 2,
            'resenas_muestra': 0,
        })
        self.assertLess(solo_ofertas, con_terminados)


class KpiBadgePublicTierTests(SimpleTestCase):
    def test_sin_servicios_terminados_no_elite(self):
        def fake_kpis(_user, dias=30):
            return {
                'score_rendimiento': 95,
                'ofertas_total_en_periodo': 8,
                'ordenes_mercado_completadas': 0,
                'servicios_terminados_en_periodo': 0,
                'resenas_muestra': 0,
            }

        import mecanimovilapp.apps.usuarios.kpi_badge_utils as mod

        original = mod.compute_proveedor_kpis_resumen
        mod.compute_proveedor_kpis_resumen = fake_kpis
        try:
            badge = compute_kpi_badge_for_proveedor(proveedor_usuario=object(), window_days=30)
        finally:
            mod.compute_proveedor_kpis_resumen = original

        self.assertIsNotNone(badge)
        self.assertEqual(badge['code'], 'EN_PROGRESO')
        self.assertFalse(badge['is_active'])
        self.assertLessEqual(badge['score'], 54)

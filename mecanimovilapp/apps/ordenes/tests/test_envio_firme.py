"""Tests unitarios de líneas firmes (precio confirmado/taller) en resolver_precio y generador."""
from django.test import SimpleTestCase, override_settings

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
    _ajustar_rangos_consistentes,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio import (
    CERTEZA_CONFIRMADO,
    aplicar_derivados_certeza,
    aplicar_techo_ia_si_falta_unitario,
    backfill_certeza,
    linea_es_firme,
    marcar_linea_firme_taller,
    resolver_precio_linea,
)


class LineaFirmeResolverPrecioTestCase(SimpleTestCase):
    def _hit(self, fuente: str, precio: int, **extra):
        data = {
            'nombre': 'Pastillas de freno delanteras',
            'fuente_marketplace': fuente,
            'precio_unitario_clp': precio,
            'url_producto': 'https://www.autoplanet.cl/producto/pastillas-123',
        }
        data.update(extra)
        return data

    def test_marcar_linea_firme_taller_fija_certeza_y_banda(self):
        rep = {
            'nombre': 'Pastillas de freno delanteras',
            'precio_unitario_clp': 18000,
            'precio_min_clp': 12000,
            'precio_max_clp': 25000,
            'certeza': 'referencial',
            'precio_estimado': True,
            'precio_referencia_mercado': True,
            'motivo_sin_precio': 'sin_referencia',
            '_estimado': True,
        }
        out = marcar_linea_firme_taller(rep, 35000)
        self.assertIs(out, rep)
        self.assertTrue(linea_es_firme(rep))
        self.assertEqual(rep['precio_unitario_clp'], 35000)
        self.assertEqual(rep['precio_min_clp'], 35000)
        self.assertEqual(rep['precio_max_clp'], 35000)
        self.assertEqual(rep['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(rep['origen_precio'], 'taller')
        self.assertFalse(rep['precio_estimado'])
        self.assertNotIn('precio_referencia_mercado', rep)
        self.assertNotIn('motivo_sin_precio', rep)
        self.assertNotIn('_estimado', rep)

    def test_linea_es_firme_variantes_y_sin_monto(self):
        self.assertFalse(linea_es_firme(None))
        self.assertFalse(linea_es_firme({'precio_unitario_clp': 0, 'origen_precio': 'taller'}))
        self.assertTrue(linea_es_firme({'precio_unitario_clp': 22000, 'origen_precio': 'taller'}))
        self.assertTrue(linea_es_firme({'precio_unitario_clp': 22000, 'certeza': 'confirmado'}))
        self.assertTrue(
            linea_es_firme({
                'precio_unitario_clp': 22000,
                'fuente_marketplace': 'catalogo',
                'precio_estimado': False,
            })
        )
        self.assertEqual(
            backfill_certeza({'precio_unitario_clp': 22000, 'origen_precio': 'taller'}),
            CERTEZA_CONFIRMADO,
        )

    @override_settings(PRECIO_CONFIANZA_ENABLED=True, FACTOR_MERCADO_MAX=2.50)
    def test_resolver_precio_con_confianza_no_pisa_linea_firme(self):
        linea = marcar_linea_firme_taller(
            {
                'nombre': 'Bujía de encendido',
                'cantidad': 4,
                'precio_min_clp': 10000,
                'precio_max_clp': 20000,
            },
            15000,
        )
        # Incluso sin especificación en familia sensible y sin hits (o con hit web distinto),
        # resolver_precio_linea no pisa el monto firme del taller.
        resolver_precio_linea(linea, [], confianza_enabled=True)
        self.assertEqual(linea['precio_unitario_clp'], 15000)
        self.assertEqual(linea['precio_min_clp'], 15000)
        self.assertEqual(linea['precio_max_clp'], 15000)
        self.assertEqual(linea['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(linea['origen_precio'], 'taller')
        self.assertFalse(linea['precio_estimado'])

        resolver_precio_linea(
            linea,
            [self._hit('web', 8990, nombre='Bujía de encendido')],
            confianza_enabled=True,
        )
        self.assertEqual(linea['precio_unitario_clp'], 15000)
        self.assertEqual(linea['precio_min_clp'], 15000)
        self.assertEqual(linea['precio_max_clp'], 15000)
        self.assertEqual(linea['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(linea['origen_precio'], 'taller')
        self.assertFalse(linea['precio_estimado'])

    def test_resolver_precio_legacy_no_pisa_linea_firme(self):
        linea = {
            'nombre': 'Pastillas de freno delanteras',
            'precio_unitario_clp': 42000,
            'precio_min_clp': 20000,
            'precio_max_clp': 60000,
            'certeza': CERTEZA_CONFIRMADO,
            'origen_precio': 'taller',
            'precio_estimado': False,
        }
        resolver_precio_linea(
            linea,
            [self._hit('catalogo', 19990), self._hit('web', 25000)],
            confianza_enabled=False,
        )
        self.assertEqual(linea['precio_unitario_clp'], 42000)
        self.assertEqual(linea['precio_min_clp'], 42000)
        self.assertEqual(linea['precio_max_clp'], 42000)
        self.assertEqual(linea['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(linea['origen_precio'], 'taller')
        self.assertFalse(linea['precio_estimado'])

    @override_settings(PRECIO_CONFIANZA_ENABLED=True, FACTOR_MERCADO_MAX=2.50)
    def test_hit_historial_taller_resuelve_como_firme_confirmado(self):
        linea = {
            'nombre': 'Pastillas de freno delanteras',
            'especificacion': 'Cerámica',
            'precio_unitario_clp': 0,
        }
        hit_hist_taller = {
            'nombre': 'Pastillas de freno delanteras',
            'fuente_marketplace': 'historial',
            'precio_unitario_clp': 38000,
            'origen_precio': 'taller',
            'certeza': CERTEZA_CONFIRMADO,
        }
        resolver_precio_linea(
            linea,
            [hit_hist_taller, self._hit('web', 21000)],
            confianza_enabled=True,
        )
        self.assertEqual(linea['precio_unitario_clp'], 38000)
        self.assertEqual(linea['precio_min_clp'], 38000)
        self.assertEqual(linea['precio_max_clp'], 38000)
        self.assertEqual(linea['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(linea['origen_precio'], 'taller')
        self.assertFalse(linea['precio_estimado'])

    def test_aplicar_techo_ia_no_parte_bujia_firme(self):
        rep = {
            'nombre': 'Bujías NGK',
            'cantidad': 4,
            'precio_unitario_clp': 32000,
            'precio_min_clp': 20000,
            'precio_max_clp': 40000,
            'origen_precio': 'taller',
            'certeza': CERTEZA_CONFIRMADO,
            'precio_estimado': False,
        }
        out = aplicar_techo_ia_si_falta_unitario(rep)
        self.assertEqual(out['precio_unitario_clp'], 32000)
        self.assertEqual(out['precio_min_clp'], 32000)
        self.assertEqual(out['precio_max_clp'], 32000)
        self.assertEqual(out['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(out['origen_precio'], 'taller')
        self.assertFalse(out['precio_estimado'])

    def test_ajustar_rangos_consistentes_respeta_linea_firme(self):
        firme = {
            'nombre': 'Aceite de motor 5W30',
            'cantidad': 4,
            'precio_unitario_clp': 12000,
            'precio_min_clp': 8000,
            'precio_max_clp': 15000,
            'certeza': CERTEZA_CONFIRMADO,
            'origen_precio': 'taller',
            'precio_estimado': False,
            'precio_referencia_mercado': True,
        }
        estimada = {
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 31000,
            'precio_min_clp': 8000,
            'precio_max_clp': 15000,
            'certeza': 'asumido',
            'precio_estimado': True,
        }
        out = _ajustar_rangos_consistentes([firme, estimada])
        self.assertEqual(out[0]['precio_unitario_clp'], 12000)
        self.assertEqual(out[0]['precio_min_clp'], 12000)
        self.assertEqual(out[0]['precio_max_clp'], 12000)
        self.assertEqual(out[0]['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(out[0]['origen_precio'], 'taller')
        self.assertFalse(out[0]['precio_estimado'])
        self.assertNotIn('precio_referencia_mercado', out[0])

        # La línea no firme sí ajusta su rango para contener el precio total
        self.assertLessEqual(out[1]['precio_min_clp'], 31000)
        self.assertGreaterEqual(out[1]['precio_max_clp'], 31000)

    def test_aplicar_derivados_certeza_completa_origen_taller_en_confirmado(self):
        rep = {
            'nombre': 'Kit de embrague',
            'precio_unitario_clp': 185000,
            'precio_min_clp': 140000,
            'precio_max_clp': 220000,
            'certeza': CERTEZA_CONFIRMADO,
        }
        aplicar_derivados_certeza(rep)
        self.assertEqual(rep['certeza'], CERTEZA_CONFIRMADO)
        self.assertEqual(rep['origen_precio'], 'taller')
        self.assertFalse(rep['precio_estimado'])
        self.assertEqual(rep['precio_min_clp'], 185000)
        self.assertEqual(rep['precio_max_clp'], 185000)

"""Tests scoring geográfico en motor_match (sin PostGIS en runtime simple)."""
import json
import math

from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _build_desglose,
    _filtrar_comunas_validas,
    _gestion_catalogo_sin_iva,
    _haversine_km,
    _normalizar_lat_lng_chile,
    _oferta_catalogo_completa,
    _ordenar_candidatos_por_distancia,
    _safe_float,
    _score_y_explicacion,
)


class MotorMatchComunasTests(SimpleTestCase):
    def test_descarta_calle_como_comuna(self):
        self.assertEqual(_filtrar_comunas_validas(['manuel de Amat 2960']), [])
        self.assertEqual(_filtrar_comunas_validas(['Providencia']), ['Providencia'])


class MotorMatchSafeFloatTests(SimpleTestCase):
    def test_nan_no_rompe_json(self):
        score, _ = _score_y_explicacion(dist_km=float('nan'), rating=float('nan'))
        payload = {'score_match': round(_safe_float(score), 3), 'rating': _safe_float(float('nan'))}
        json.dumps(payload)

    def test_safe_float_defaults(self):
        self.assertEqual(_safe_float(None), 0.0)
        self.assertEqual(_safe_float('bad'), 0.0)
        self.assertEqual(_safe_float(math.inf), 0.0)


class MotorMatchCatalogoCompletoTests(SimpleTestCase):
    def test_desglose_sin_atributo_gestion(self):
        class OfertaFake:
            costo_mano_de_obra_sin_iva = 10000
            costo_repuestos_sin_iva = 5000
            precio_publicado_cliente = 20000
            precio_con_repuestos = 20000
            precio_sin_repuestos = 15000

        d = _build_desglose(OfertaFake(), requiere_repuestos=True)
        self.assertEqual(d['gestion'], 0.0)
        self.assertEqual(_gestion_catalogo_sin_iva(OfertaFake()), 0.0)

    def test_oferta_incompleta_precio_cero(self):
        class OfertaFake:
            disponible = True
            costo_mano_de_obra_sin_iva = 0
            precio_publicado_cliente = 0
            precio_con_repuestos = 0
            precio_sin_repuestos = 0

        self.assertFalse(_oferta_catalogo_completa(OfertaFake(), requiere_repuestos=True))

    def test_oferta_legacy_solo_precio_agregado(self):
        class OfertaFake:
            disponible = True
            costo_mano_de_obra_sin_iva = 0
            precio_publicado_cliente = 45000
            precio_con_repuestos = 45000
            precio_sin_repuestos = 38000

        self.assertTrue(_oferta_catalogo_completa(OfertaFake(), requiere_repuestos=True))


class MotorMatchGeoScoreTests(SimpleTestCase):
    def test_cerca_sube_score(self):
        cerca, _ = _score_y_explicacion(dist_km=2.0, rating=4.5)
        lejos, _ = _score_y_explicacion(dist_km=60.0, rating=4.5)
        self.assertGreater(cerca, lejos)

    def test_con_ubicacion_prioriza_proximidad(self):
        cerca, _ = _score_y_explicacion(
            dist_km=8.0, rating=3.0, con_ubicacion_cliente=True
        )
        lejos_mejor_rating, _ = _score_y_explicacion(
            dist_km=40.0, rating=5.0, con_ubicacion_cliente=True
        )
        self.assertGreater(cerca, lejos_mejor_rating)

    def test_explicacion_menciona_km(self):
        _, expl = _score_y_explicacion(dist_km=12.0, rating=5.0)
        self.assertIn('km', expl.lower())


class MotorMatchHaversineTests(SimpleTestCase):
    def test_santiago_cercania_aprox_5km(self):
        # Providencia ~ -33.43, -70.61 vs Las Condes ~ -33.41, -70.57
        km = _haversine_km(-33.43, -70.61, -33.41, -70.57)
        self.assertGreater(km, 2.0)
        self.assertLess(km, 12.0)

    def test_mantiene_geojson_valido(self):
        par = _normalizar_lat_lng_chile(-33.43, -70.61)
        self.assertIsNotNone(par)
        lat, lng = par
        self.assertAlmostEqual(lat, -33.43, places=1)
        self.assertAlmostEqual(lng, -70.61, places=1)

    def test_normaliza_lat_lng_invertidos(self):
        par = _normalizar_lat_lng_chile(-70.61, -33.43)
        self.assertIsNotNone(par)
        lat, lng = par
        self.assertAlmostEqual(lat, -33.43, places=1)
        self.assertAlmostEqual(lng, -70.61, places=1)


class MotorMatchOrdenCandidatosTests(SimpleTestCase):
    def test_orden_por_distancia(self):
        lista = [
            {'distancia_km': 25, 'score_match': 0.9},
            {'distancia_km': 5, 'score_match': 0.7},
            {'distancia_km': None, 'score_match': 0.95},
        ]
        ordenada = _ordenar_candidatos_por_distancia(lista)
        self.assertEqual(ordenada[0]['distancia_km'], 5)
        self.assertEqual(ordenada[1]['distancia_km'], 25)
        self.assertIsNone(ordenada[2]['distancia_km'])

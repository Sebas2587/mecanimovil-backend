"""Tests scoring geográfico en motor_match (sin PostGIS en runtime simple)."""
import json
import math

from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _filtrar_comunas_validas,
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


class MotorMatchGeoScoreTests(SimpleTestCase):
    def test_cerca_sube_score(self):
        cerca, _ = _score_y_explicacion(dist_km=2.0, rating=4.5)
        lejos, _ = _score_y_explicacion(dist_km=60.0, rating=4.5)
        self.assertGreater(cerca, lejos)

    def test_explicacion_menciona_km(self):
        _, expl = _score_y_explicacion(dist_km=12.0, rating=5.0)
        self.assertIn('km', expl.lower())

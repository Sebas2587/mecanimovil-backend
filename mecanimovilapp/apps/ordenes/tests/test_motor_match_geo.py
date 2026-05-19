"""Tests scoring geográfico en motor_match (sin PostGIS en runtime simple)."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _filtrar_comunas_validas,
    _score_y_explicacion,
)


class MotorMatchComunasTests(SimpleTestCase):
    def test_descarta_calle_como_comuna(self):
        self.assertEqual(_filtrar_comunas_validas(['manuel de Amat 2960']), [])
        self.assertEqual(_filtrar_comunas_validas(['Providencia']), ['Providencia'])


class MotorMatchGeoScoreTests(SimpleTestCase):
    def test_cerca_sube_score(self):
        cerca, _ = _score_y_explicacion(dist_km=2.0, rating=4.5)
        lejos, _ = _score_y_explicacion(dist_km=60.0, rating=4.5)
        self.assertGreater(cerca, lejos)

    def test_explicacion_menciona_km(self):
        _, expl = _score_y_explicacion(dist_km=12.0, rating=5.0)
        self.assertIn('km', expl.lower())

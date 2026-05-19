"""Tests unitarios del léxico (sin BD)."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.lexico_necesidad import (
    detectar_sintomas,
    expandir_texto_busqueda,
    servicio_coincide_terminos,
)


class LexicoNecesidadTests(SimpleTestCase):
    def test_detecta_frenos(self):
        reglas = detectar_sintomas('ruido al frenar y pedal blando')
        ids = [r.id for r in reglas]
        self.assertIn('frenos', ids)

    def test_expande_terminos_freno(self):
        exp = expandir_texto_busqueda('ruido al frenar')
        self.assertIn('pastilla', exp.lower())

    def test_coincide_servicio_catalogo(self):
        self.assertTrue(
            servicio_coincide_terminos(
                'Cambio de pastillas de frenos',
                'Rectificado de discos',
                ('freno', 'pastilla'),
            )
        )

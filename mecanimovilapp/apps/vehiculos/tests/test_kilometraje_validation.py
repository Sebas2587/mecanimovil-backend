"""
Tests validación kilometraje vs mileage SII.
"""
from django.test import TestCase

from mecanimovilapp.apps.vehiculos.kilometraje_validation import (
    merge_mileage_metadata,
    validar_kilometraje_usuario,
)


class KilometrajeValidationTestCase(TestCase):
    def test_merge_mileage_prefers_plate(self):
        meta = merge_mileage_metadata({'mileage': 120000}, {'mileage': 80000})
        self.assertEqual(meta['mileage'], 120000)
        self.assertEqual(meta['mileage_fuente'], 'plate')
        self.assertTrue(meta['tiene_mileage_sii'])

    def test_km_menor_que_sii_error(self):
        r = validar_kilometraje_usuario(95000, mileage_sii=120000, tiene_mileage_sii=True)
        self.assertFalse(r['valid'])
        self.assertEqual(r['code'], 'km_menor_que_sii')

    def test_km_mayor_igual_sii_ok(self):
        r = validar_kilometraje_usuario(125000, mileage_sii=120000, tiene_mileage_sii=True)
        self.assertTrue(r['valid'])
        self.assertEqual(r['nivel'], 'ok')

    def test_sin_mileage_sii_aviso(self):
        r = validar_kilometraje_usuario(50000, mileage_sii=None, tiene_mileage_sii=False)
        self.assertTrue(r['valid'])
        self.assertEqual(r['nivel'], 'aviso')
        self.assertEqual(r['code'], 'sin_mileage_sii')

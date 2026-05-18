"""
Tests validación kilometraje vs mileage SII y plausibilidad por edad.
"""
from datetime import date

from django.test import TestCase

from mecanimovilapp.apps.vehiculos.kilometraje_validation import (
    calcular_banda_kilometraje,
    merge_mileage_metadata,
    validar_kilometraje_usuario,
    validar_plausibilidad_por_edad,
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
        self.assertEqual(r['code'], 'km_coherente_sii')

    def test_con_sii_no_aplica_plausibilidad_por_edad(self):
        r = validar_kilometraje_usuario(
            125000,
            mileage_sii=120000,
            tiene_mileage_sii=True,
            year=2010,
        )
        self.assertEqual(r['code'], 'km_coherente_sii')
        self.assertNotIn('banda', r)

    def test_sin_mileage_sii_sin_year_aviso(self):
        r = validar_kilometraje_usuario(50000, mileage_sii=None, tiene_mileage_sii=False)
        self.assertTrue(r['valid'])
        self.assertEqual(r['nivel'], 'aviso')
        self.assertEqual(r['code'], 'sin_year_plausibilidad')

    def test_plausible_edad_ok(self):
        year = date.today().year - 12
        r = validar_plausibilidad_por_edad(150000, year=year)
        self.assertTrue(r['valid'])
        self.assertEqual(r['code'], 'km_plausible_edad')

    def test_muy_bajo_edad_error(self):
        year = date.today().year - 16
        r = validar_plausibilidad_por_edad(2000, year=year)
        self.assertFalse(r['valid'])
        self.assertEqual(r['code'], 'km_muy_bajo_edad')

    def test_alto_edad_requiere_confirmacion(self):
        year = date.today().year - 10
        banda = calcular_banda_kilometraje(year)
        km_alto = banda['max'] + 10_000
        r = validar_plausibilidad_por_edad(km_alto, year=year)
        self.assertTrue(r['valid'])
        self.assertEqual(r['code'], 'km_alto_edad')
        self.assertTrue(r['requiere_confirmacion'])

    def test_posible_typo(self):
        year = date.today().year - 12
        r = validar_plausibilidad_por_edad(15800, year=year)
        self.assertTrue(r['valid'])
        self.assertEqual(r['code'], 'km_posible_typo')
        self.assertEqual(r['km_sugerido'], 158000)

    def test_sin_mileage_con_year_plausible(self):
        year = date.today().year - 12
        r = validar_kilometraje_usuario(
            150000,
            mileage_sii=None,
            tiene_mileage_sii=False,
            year=year,
        )
        self.assertTrue(r['valid'])
        self.assertEqual(r['code'], 'km_plausible_edad')

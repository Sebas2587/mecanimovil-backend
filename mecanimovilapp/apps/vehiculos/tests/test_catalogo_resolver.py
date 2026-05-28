"""
Tests resolución de marcas/modelos sin duplicados por mayúsculas.
"""
from django.test import TestCase

from mecanimovilapp.apps.vehiculos.catalogo_resolver import (
    resolve_marca,
    resolve_modelo,
    resolve_or_create_marca,
    resolve_or_create_modelo,
)
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo


class CatalogoResolverTestCase(TestCase):
    def setUp(self):
        self.toyota = MarcaVehiculo.objects.create(nombre='Toyota')
        self.corolla = Modelo.objects.create(marca=self.toyota, nombre='Corolla')

    def test_resolve_marca_iexact_reusa_existente(self):
        self.assertEqual(resolve_marca('TOYOTA').id, self.toyota.id)
        self.assertEqual(resolve_marca('toyota').id, self.toyota.id)

    def test_resolve_or_create_marca_no_duplica(self):
        marca, created = resolve_or_create_marca('TOYOTA')
        self.assertFalse(created)
        self.assertEqual(marca.id, self.toyota.id)
        self.assertEqual(MarcaVehiculo.objects.count(), 1)

    def test_resolve_or_create_marca_crea_si_no_existe(self):
        marca, created = resolve_or_create_marca('FERRARI')
        self.assertTrue(created)
        self.assertEqual(marca.nombre, 'Ferrari')
        self.assertEqual(MarcaVehiculo.objects.filter(nombre__iexact='FERRARI').count(), 1)

    def test_resolve_modelo_iexact(self):
        self.assertEqual(resolve_modelo(self.toyota, 'COROLLA').id, self.corolla.id)

    def test_resolve_modelo_por_primer_token(self):
        self.assertEqual(
            resolve_modelo(self.toyota, 'COROLLA XLI 1.8').id,
            self.corolla.id,
        )

    def test_resolve_or_create_modelo_no_duplica(self):
        modelo, created = resolve_or_create_modelo(self.toyota, 'corolla')
        self.assertFalse(created)
        self.assertEqual(modelo.id, self.corolla.id)
        self.assertEqual(Modelo.objects.filter(marca=self.toyota).count(), 1)

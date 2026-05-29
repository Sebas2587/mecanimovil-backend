"""Tests de compatibilidad catálogo Repuesto ↔ vehículo."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.servicios.compatibilidad_repuesto import (
    queryset_repuestos_compatibles_vehiculo,
    queryset_repuestos_por_marca_modelo,
    repuesto_compatible_con_marca_modelo,
    repuesto_es_generico,
)
from mecanimovilapp.apps.servicios.models import Repuesto
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

User = get_user_model()


class CompatibilidadRepuestoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marca_toyota = MarcaVehiculo.objects.create(nombre='Toyota Rep')
        cls.modelo_corolla = Modelo.objects.create(nombre='Corolla', marca=cls.marca_toyota)
        cls.modelo_hilux = Modelo.objects.create(nombre='Hilux', marca=cls.marca_toyota)

        cls.repuesto_generico = Repuesto.objects.create(
            nombre='Líquido limpiaparabrisas',
            marca='Genérico',
            categoria_repuesto='otros',
        )
        cls.repuesto_toyota = Repuesto.objects.create(
            nombre='Filtro aceite Toyota',
            marca='OEM',
            categoria_repuesto='filtros',
        )
        cls.repuesto_toyota.marcas_compatibles.add(cls.marca_toyota)

        cls.repuesto_corolla = Repuesto.objects.create(
            nombre='Bujía Corolla',
            marca='NGK',
            categoria_repuesto='motor',
        )
        cls.repuesto_corolla.marcas_compatibles.add(cls.marca_toyota)
        cls.repuesto_corolla.modelos_compatibles.add(cls.modelo_corolla)

        user = User.objects.create_user(
            username='cliente_rep@test.com',
            email='cliente_rep@test.com',
            password='testpass123',
        )
        cls.cliente = Cliente.objects.create(
            usuario=user,
            nombre='Test',
            apellido='Rep',
            email='cliente_rep@test.com',
        )
        cls.vehiculo_hilux = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca_toyota,
            modelo=cls.modelo_hilux,
            patente='REP01',
            year=2024,
        )

    def test_repuesto_generico(self):
        self.assertTrue(repuesto_es_generico(self.repuesto_generico))

    def test_marca_aplica_a_todos_modelos(self):
        ids = set(
            queryset_repuestos_por_marca_modelo(
                self.modelo_hilux,
                self.marca_toyota,
            ).values_list('id', flat=True)
        )
        self.assertIn(self.repuesto_toyota.id, ids)
        self.assertNotIn(self.repuesto_corolla.id, ids)

    def test_por_vehiculo_hilux(self):
        ids = set(queryset_repuestos_compatibles_vehiculo(self.vehiculo_hilux).values_list('id', flat=True))
        self.assertIn(self.repuesto_toyota.id, ids)

    def test_instancia_compatible(self):
        self.assertTrue(
            repuesto_compatible_con_marca_modelo(
                self.repuesto_toyota,
                self.marca_toyota,
                self.modelo_hilux,
            )
        )
        self.assertFalse(
            repuesto_compatible_con_marca_modelo(
                self.repuesto_corolla,
                self.marca_toyota,
                self.modelo_hilux,
            )
        )

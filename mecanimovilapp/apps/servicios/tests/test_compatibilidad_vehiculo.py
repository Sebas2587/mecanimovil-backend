"""Tests de compatibilidad catálogo Servicio ↔ vehículo."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.servicios.compatibilidad_vehiculo import (
    queryset_servicios_catalogo_por_marca,
    queryset_servicios_catalogo_por_marca_modelo,
    queryset_servicios_compatibles_vehiculo,
    queryset_servicios_genericos,
    servicio_compatible_con_marca_modelo,
    servicio_es_generico,
)
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

User = get_user_model()


class CompatibilidadVehiculoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marca_toyota = MarcaVehiculo.objects.create(nombre='Toyota Test')
        cls.marca_nissan = MarcaVehiculo.objects.create(nombre='Nissan Test')
        cls.modelo_corolla = Modelo.objects.create(nombre='Corolla', marca=cls.marca_toyota)
        cls.modelo_hilux = Modelo.objects.create(nombre='Hilux', marca=cls.marca_toyota)
        cls.modelo_sentra = Modelo.objects.create(nombre='Sentra', marca=cls.marca_nissan)

        cls.servicio_generico = Servicio.objects.create(nombre='Diagnóstico general')
        cls.servicio_toyota = Servicio.objects.create(nombre='Aceite Toyota')
        cls.servicio_toyota.marcas_compatibles.add(cls.marca_toyota)

        cls.servicio_corolla = Servicio.objects.create(nombre='Bujías Corolla')
        cls.servicio_corolla.marcas_compatibles.add(cls.marca_toyota)
        cls.servicio_corolla.modelos_compatibles.add(cls.modelo_corolla)

        cls.servicio_legacy = Servicio.objects.create(nombre='Legacy por modelo')
        cls.servicio_legacy.modelos_compatibles.add(cls.modelo_sentra)

        user = User.objects.create_user(
            username='cliente_compat@test.com',
            email='compat@test.com',
            password='testpass123',
        )
        cls.cliente = Cliente.objects.create(
            usuario=user,
            nombre='Test',
            apellido='Compat',
            email='compat@test.com',
        )
        cls.vehiculo_hilux = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca_toyota,
            modelo=cls.modelo_hilux,
            patente='HILU01',
            year=2024,
        )
        cls.vehiculo_corolla = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca_toyota,
            modelo=cls.modelo_corolla,
            patente='CORO01',
            year=2023,
        )

    def test_servicio_generico_sin_marcas_ni_modelos(self):
        self.assertTrue(servicio_es_generico(self.servicio_generico))
        ids = set(queryset_servicios_genericos().values_list('id', flat=True))
        self.assertIn(self.servicio_generico.id, ids)

    def test_marca_directa_aplica_a_todos_los_modelos(self):
        qs = queryset_servicios_catalogo_por_marca_modelo(
            self.modelo_hilux,
            self.marca_toyota,
        )
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.servicio_toyota.id, ids)

    def test_restriccion_por_modelo_excluye_otros_modelos_misma_marca(self):
        qs = queryset_servicios_catalogo_por_marca_modelo(
            self.modelo_hilux,
            self.marca_toyota,
        )
        ids = set(qs.values_list('id', flat=True))
        self.assertNotIn(self.servicio_corolla.id, ids)

        qs_corolla = queryset_servicios_catalogo_por_marca_modelo(
            self.modelo_corolla,
            self.marca_toyota,
        )
        self.assertIn(self.servicio_corolla.id, set(qs_corolla.values_list('id', flat=True)))

    def test_legacy_modelos_inferencia_marca(self):
        qs = queryset_servicios_catalogo_por_marca(self.marca_nissan.id)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.servicio_legacy.id, ids)

    def test_queryset_por_vehiculo_nuevo_modelo_misma_marca(self):
        qs = queryset_servicios_compatibles_vehiculo(self.vehiculo_hilux)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.servicio_toyota.id, ids)
        self.assertNotIn(self.servicio_corolla.id, ids)

    def test_servicio_compatible_con_marca_modelo_instancia(self):
        self.assertTrue(
            servicio_compatible_con_marca_modelo(
                self.servicio_toyota,
                self.marca_toyota,
                self.modelo_hilux,
            )
        )
        self.assertFalse(
            servicio_compatible_con_marca_modelo(
                self.servicio_corolla,
                self.marca_toyota,
                self.modelo_hilux,
            )
        )

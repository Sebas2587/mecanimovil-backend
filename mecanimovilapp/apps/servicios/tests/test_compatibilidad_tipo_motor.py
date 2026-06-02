"""Tests de compatibilidad por tipo de motor."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.servicios.compatibilidad_vehiculo import (
    queryset_servicios_compatibles_vehiculo,
    servicio_compatible_con_marca_modelo,
    servicio_compatible_con_vehiculo,
)
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.servicios.tipos_motor_utils import servicio_compatible_con_tipo_motor
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

User = get_user_model()


class CompatibilidadTipoMotorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marca = MarcaVehiculo.objects.create(nombre='Marca Motor Test')
        cls.modelo = Modelo.objects.create(nombre='Modelo X', marca=cls.marca)

        cls.servicio_universal = Servicio.objects.create(nombre='Diagnóstico universal')
        cls.servicio_bencina = Servicio.objects.create(
            nombre='Cambio bujías test',
            tipos_motor_compatibles=['GASOLINA'],
        )
        cls.servicio_bencina.marcas_compatibles.add(cls.marca)

        cls.servicio_diesel = Servicio.objects.create(
            nombre='AdBlue test',
            tipos_motor_compatibles=['DIESEL'],
        )
        cls.servicio_diesel.marcas_compatibles.add(cls.marca)

        user = User.objects.create_user(
            username='motor_compat@test.com',
            email='motor@test.com',
            password='testpass123',
        )
        cls.cliente = Cliente.objects.create(
            usuario=user,
            nombre='Motor',
            apellido='Test',
            email='motor@test.com',
        )
        cls.vehiculo_gasolina = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca,
            modelo=cls.modelo,
            patente='GAS01',
            year=2024,
            tipo_motor='GASOLINA',
        )
        cls.vehiculo_diesel = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca,
            modelo=cls.modelo,
            patente='DIE01',
            year=2024,
            tipo_motor='DIESEL',
        )

    def test_lista_vacia_es_universal(self):
        self.assertTrue(servicio_compatible_con_tipo_motor(self.servicio_universal, 'DIESEL'))

    def test_solo_gasolina_excluye_diesel(self):
        self.assertTrue(servicio_compatible_con_tipo_motor(self.servicio_bencina, 'BENCINA'))
        self.assertFalse(servicio_compatible_con_tipo_motor(self.servicio_bencina, 'DIESEL'))

    def test_queryset_por_vehiculo_filtra_motor(self):
        qs_gas = queryset_servicios_compatibles_vehiculo(self.vehiculo_gasolina)
        ids_gas = set(qs_gas.values_list('id', flat=True))
        self.assertIn(self.servicio_bencina.id, ids_gas)
        self.assertNotIn(self.servicio_diesel.id, ids_gas)

        qs_diesel = queryset_servicios_compatibles_vehiculo(self.vehiculo_diesel)
        ids_diesel = set(qs_diesel.values_list('id', flat=True))
        self.assertNotIn(self.servicio_bencina.id, ids_diesel)
        self.assertIn(self.servicio_diesel.id, ids_diesel)

    def test_compatible_con_vehiculo_combinado(self):
        self.assertTrue(servicio_compatible_con_vehiculo(self.servicio_bencina, self.vehiculo_gasolina))
        self.assertFalse(servicio_compatible_con_vehiculo(self.servicio_bencina, self.vehiculo_diesel))

    def test_marca_modelo_con_tipo_motor(self):
        self.assertTrue(
            servicio_compatible_con_marca_modelo(
                self.servicio_bencina,
                self.marca,
                self.modelo,
                tipo_motor='GASOLINA',
            )
        )
        self.assertFalse(
            servicio_compatible_con_marca_modelo(
                self.servicio_bencina,
                self.marca,
                self.modelo,
                tipo_motor='DIESEL',
            )
        )

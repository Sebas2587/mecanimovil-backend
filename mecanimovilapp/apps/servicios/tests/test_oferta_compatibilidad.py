"""Tests de OfertaServicio.tipo_motor y oferta_compatibilidad."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.servicios.oferta_compatibilidad import (
    oferta_compatible_con_tipo_motor,
    validar_tipo_motor_oferta,
)
from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo

User = get_user_model()


class OfertaCompatibilidadMotorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marca = MarcaVehiculo.objects.create(nombre='Marca Oferta Motor')
        cls.servicio_gasolina = Servicio.objects.create(
            nombre='Bujías test',
            tipos_motor_compatibles=['GASOLINA'],
        )
        cls.servicio_universal = Servicio.objects.create(nombre='Diagnóstico test')

        user = User.objects.create_user(
            username='taller_oferta_motor@test.com',
            email='taller_om@test.com',
            password='testpass123',
        )
        cls.taller = Taller.objects.create(
            usuario=user,
            nombre='Taller Oferta Motor',
            verificado=True,
            activo=True,
        )

        cls.oferta_todos = OfertaServicio.objects.create(
            servicio=cls.servicio_gasolina,
            tipo_proveedor='taller',
            taller=cls.taller,
            marca_vehiculo_seleccionada=cls.marca,
            tipo_motor='',
            disponible=True,
            precio_sin_repuestos=Decimal('30000'),
            precio_con_repuestos=Decimal('40000'),
            precio_publicado_cliente=Decimal('40000'),
            costo_mano_de_obra_sin_iva=Decimal('25000'),
            costo_repuestos_sin_iva=Decimal('5000'),
        )
        cls.oferta_solo_gasolina = OfertaServicio.objects.create(
            servicio=cls.servicio_gasolina,
            tipo_proveedor='taller',
            taller=cls.taller,
            marca_vehiculo_seleccionada=cls.marca,
            tipo_motor='GASOLINA',
            disponible=True,
            precio_sin_repuestos=Decimal('32000'),
            precio_con_repuestos=Decimal('42000'),
            precio_publicado_cliente=Decimal('42000'),
            costo_mano_de_obra_sin_iva=Decimal('27000'),
            costo_repuestos_sin_iva=Decimal('5000'),
        )

    def test_validar_tipo_motor_vacio_aceptado(self):
        self.assertEqual(validar_tipo_motor_oferta(self.servicio_gasolina, ''), '')

    def test_validar_tipo_motor_subconjunto_catalogo(self):
        self.assertEqual(
            validar_tipo_motor_oferta(self.servicio_gasolina, 'GASOLINA'),
            'GASOLINA',
        )

    def test_validar_tipo_motor_rechaza_fuera_catalogo(self):
        with self.assertRaises(ValidationError):
            validar_tipo_motor_oferta(self.servicio_gasolina, 'DIESEL')

    def test_oferta_universal_aplica_a_cualquier_motor_del_servicio(self):
        self.assertTrue(oferta_compatible_con_tipo_motor(self.oferta_todos, 'GASOLINA'))
        self.assertFalse(oferta_compatible_con_tipo_motor(self.oferta_todos, 'DIESEL'))

    def test_oferta_especifica_solo_su_motor(self):
        self.assertTrue(oferta_compatible_con_tipo_motor(self.oferta_solo_gasolina, 'BENCINA'))
        self.assertFalse(oferta_compatible_con_tipo_motor(self.oferta_solo_gasolina, 'DIESEL'))

    def test_servicio_universal_acepta_cualquier_motor_en_oferta(self):
        oferta = OfertaServicio.objects.create(
            servicio=self.servicio_universal,
            tipo_proveedor='taller',
            taller=self.taller,
            marca_vehiculo_seleccionada=self.marca,
            tipo_motor='DIESEL',
            disponible=True,
            precio_sin_repuestos=Decimal('20000'),
            precio_con_repuestos=Decimal('25000'),
            precio_publicado_cliente=Decimal('25000'),
            costo_mano_de_obra_sin_iva=Decimal('15000'),
            costo_repuestos_sin_iva=Decimal('5000'),
        )
        self.assertTrue(oferta_compatible_con_tipo_motor(oferta, 'DIESEL'))
        self.assertFalse(oferta_compatible_con_tipo_motor(oferta, 'GASOLINA'))

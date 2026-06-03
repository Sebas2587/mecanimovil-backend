"""Tests: motor_match resuelve y puntúa ofertas por tipo de motor del vehículo."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _queryset_ofertas_compatibles,
    listar_candidatos_proveedor,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.servicios.oferta_resolucion import (
    prioridad_oferta_para_motor,
    resolver_ofertas_preferidas_por_marca,
)
from mecanimovilapp.apps.usuarios.models import Cliente, Taller
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

User = get_user_model()


class MotorMatchTipoMotorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marca = MarcaVehiculo.objects.create(nombre='Marca Motor Test')
        cls.modelo = Modelo.objects.create(nombre='ModeloM', marca=cls.marca)
        cls.servicio = Servicio.objects.create(
            nombre='Servicio Motor Test',
            tipos_motor_compatibles=['GASOLINA', 'DIESEL'],
        )

        user_prov = User.objects.create_user(
            username='taller_motor_match@test.com',
            email='taller_motor@test.com',
            password='testpass123',
        )
        cls.taller = Taller.objects.create(
            usuario=user_prov,
            nombre='Taller Motor Test',
            verificado=True,
            activo=True,
        )

        cls.oferta_gasolina = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='taller',
            taller=cls.taller,
            tipo_motor='GASOLINA',
            disponible=True,
            precio_sin_repuestos=Decimal('40000'),
            precio_con_repuestos=Decimal('50000'),
            precio_publicado_cliente=Decimal('50000'),
            costo_mano_de_obra_sin_iva=Decimal('30000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )
        cls.oferta_diesel = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='taller',
            taller=cls.taller,
            tipo_motor='DIESEL',
            disponible=True,
            precio_sin_repuestos=Decimal('42000'),
            precio_con_repuestos=Decimal('52000'),
            precio_publicado_cliente=Decimal('52000'),
            costo_mano_de_obra_sin_iva=Decimal('32000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )
        cls.oferta_universal = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='taller',
            taller=cls.taller,
            tipo_motor='',
            disponible=True,
            precio_sin_repuestos=Decimal('45000'),
            precio_con_repuestos=Decimal('55000'),
            precio_publicado_cliente=Decimal('55000'),
            costo_mano_de_obra_sin_iva=Decimal('35000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )

        user_cli = User.objects.create_user(
            username='cliente_motor_match@test.com',
            email='cliente_motor@test.com',
            password='testpass123',
        )
        cls.cliente = Cliente.objects.create(
            usuario=user_cli,
            nombre='Cliente',
            apellido='Motor',
            email='cliente_motor@test.com',
        )
        cls.vehiculo_diesel = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca,
            modelo=cls.modelo,
            year=2020,
            patente='MOTTEST1',
            tipo_motor='DIESEL',
        )

    def test_prioridad_motor_exacto_sobre_universal(self):
        prio_d = prioridad_oferta_para_motor(self.oferta_diesel, 'DIESEL')
        prio_u = prioridad_oferta_para_motor(self.oferta_universal, 'DIESEL')
        self.assertEqual(prio_d, 2)
        self.assertEqual(prio_u, 0)
        self.assertGreater(prio_d, prio_u)

    def test_resolver_elige_motor_exacto_sobre_universal(self):
        resueltas = resolver_ofertas_preferidas_por_marca(
            [self.oferta_diesel, self.oferta_universal, self.oferta_gasolina],
            self.marca,
            tipo_motor='DIESEL',
        )
        self.assertEqual(len(resueltas), 1)
        self.assertEqual(resueltas[0].id, self.oferta_diesel.id)

    def test_queryset_excluye_motor_incompatible(self):
        qs = _queryset_ofertas_compatibles(
            [self.servicio.id],
            self.marca,
            tipo_motor='DIESEL',
        )
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.oferta_diesel.id, ids)
        self.assertNotIn(self.oferta_gasolina.id, ids)

    def test_listar_candidatos_devuelve_oferta_diesel(self):
        resultado = listar_candidatos_proveedor(
            vehiculo_id=self.vehiculo_diesel.id,
            servicio_ids=[self.servicio.id],
            requiere_repuestos=True,
            lat=-33.45,
            lng=-70.65,
        )
        candidatos = resultado.get('candidatos_recomendados') or resultado.get('candidatos') or []
        self.assertGreaterEqual(len(candidatos), 1)
        self.assertEqual(candidatos[0]['oferta_servicio_id'], self.oferta_diesel.id)
        self.assertEqual(candidatos[0].get('motor_coincidencia'), 'exacta')

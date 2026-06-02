"""Tests: motor_match incluye ofertas multimarca y resuelve por marca del vehículo."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _queryset_ofertas_compatibles,
    listar_candidatos_proveedor,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import Cliente, Taller
from mecanimovilapp.apps.usuarios.proveedor_cobertura import TIPO_COBERTURA_MULTIMARCA
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

User = get_user_model()


class MotorMatchMultimarcaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marca_a = MarcaVehiculo.objects.create(nombre='MarcaA MM Test')
        cls.marca_b = MarcaVehiculo.objects.create(nombre='MarcaB MM Test')
        cls.modelo_a = Modelo.objects.create(nombre='ModeloA', marca=cls.marca_a)
        cls.servicio = Servicio.objects.create(nombre='Servicio MM Test')

        user_prov = User.objects.create_user(
            username='taller_mm_match@test.com',
            email='taller_mm@test.com',
            password='testpass123',
        )
        cls.taller_mm = Taller.objects.create(
            usuario=user_prov,
            nombre='Taller Multimarca Test',
            verificado=True,
            activo=True,
            tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
        )

        cls.oferta_marca_b = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='taller',
            taller=cls.taller_mm,
            marca_vehiculo_seleccionada=cls.marca_b,
            disponible=True,
            precio_sin_repuestos=Decimal('50000'),
            precio_con_repuestos=Decimal('60000'),
            precio_publicado_cliente=Decimal('60000'),
            costo_mano_de_obra_sin_iva=Decimal('40000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )
        cls.oferta_marca_a = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='taller',
            taller=cls.taller_mm,
            marca_vehiculo_seleccionada=cls.marca_a,
            disponible=True,
            precio_sin_repuestos=Decimal('45000'),
            precio_con_repuestos=Decimal('55000'),
            precio_publicado_cliente=Decimal('55000'),
            costo_mano_de_obra_sin_iva=Decimal('35000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )

        user_cli = User.objects.create_user(
            username='cliente_mm_match@test.com',
            email='cliente_mm@test.com',
            password='testpass123',
        )
        cls.cliente = Cliente.objects.create(
            usuario=user_cli,
            nombre='Cliente',
            apellido='MM',
            email='cliente_mm@test.com',
        )
        cls.vehiculo_b = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca_b,
            modelo=cls.modelo_a,
            year=2020,
            patente='MMTEST01',
        )

    def test_queryset_incluye_oferta_multimarca_para_marca_vehiculo(self):
        qs = _queryset_ofertas_compatibles([self.servicio.id], self.marca_b)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.oferta_marca_b.id, ids)
        self.assertNotIn(self.oferta_marca_a.id, ids)

    def test_listar_candidatos_devuelve_proveedor_multimarca(self):
        resultado = listar_candidatos_proveedor(
            vehiculo_id=self.vehiculo_b.id,
            servicio_ids=[self.servicio.id],
            requiere_repuestos=True,
            lat=-33.45,
            lng=-70.65,
        )
        candidatos = resultado.get('candidatos_recomendados') or resultado.get('candidatos') or []
        self.assertGreaterEqual(len(candidatos), 1)
        self.assertEqual(
            candidatos[0]['oferta_servicio_id'],
            self.oferta_marca_b.id,
        )

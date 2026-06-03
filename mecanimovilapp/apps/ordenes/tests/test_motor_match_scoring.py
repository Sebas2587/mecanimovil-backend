"""Tests del scorer ML unificado de coincidencia catálogo ↔ vehículo."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match_scoring import (
    CoincidenciaCatalogoContext,
    calcular_score_coincidencia,
    extraer_features_coincidencia,
    prioridad_orden_cobertura_proveedor,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import Cliente, Taller
from mecanimovilapp.apps.usuarios.proveedor_cobertura import (
    TIPO_COBERTURA_ESPECIALISTA,
    TIPO_COBERTURA_MULTIMARCA,
)
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

User = get_user_model()


class MotorMatchScoringUnitTests(SimpleTestCase):
    def test_especialista_supera_multimarca_misma_proximidad(self):
        marca_id = 10
        oferta_esp = SimpleNamespace(
            tipo_proveedor='taller',
            taller=SimpleNamespace(
                calificacion_promedio=4.0,
                tipo_cobertura_marca=TIPO_COBERTURA_ESPECIALISTA,
            ),
            mecanico=None,
            marca_vehiculo_seleccionada_id=marca_id,
            tipo_motor='DIESEL',
            servicio=SimpleNamespace(categorias=MagicMock(first=lambda: None)),
        )
        oferta_mm = SimpleNamespace(
            tipo_proveedor='taller',
            taller=SimpleNamespace(
                calificacion_promedio=4.0,
                tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
            ),
            mecanico=None,
            marca_vehiculo_seleccionada_id=marca_id,
            tipo_motor='DIESEL',
            servicio=SimpleNamespace(categorias=MagicMock(first=lambda: None)),
        )
        vehiculo = SimpleNamespace(tipo_motor='DIESEL')
        ctx = CoincidenciaCatalogoContext(
            vehiculo=vehiculo,
            marca_id=marca_id,
            requiere_repuestos=True,
            dist_km=2.0,
            con_ubicacion_cliente=True,
            catalogo_completo=True,
            oferta_ofrece_repuestos=True,
        )
        score_esp = calcular_score_coincidencia(oferta_esp, ctx).score
        score_mm = calcular_score_coincidencia(oferta_mm, ctx).score
        self.assertGreater(score_esp, score_mm)

    def test_especialista_diesel_supera_multimarca_universal_a_distancia(self):
        """Caso prod: esp. motor DIESEL vs multimarca todos los motores."""
        marca_id = 11
        oferta_esp = SimpleNamespace(
            tipo_proveedor='mecanico',
            taller=None,
            mecanico=SimpleNamespace(
                calificacion_promedio=0,
                tipo_cobertura_marca=TIPO_COBERTURA_ESPECIALISTA,
            ),
            marca_vehiculo_seleccionada_id=marca_id,
            tipo_motor='DIESEL',
            servicio=SimpleNamespace(categorias=MagicMock(first=lambda: None)),
        )
        oferta_mm = SimpleNamespace(
            tipo_proveedor='taller',
            taller=SimpleNamespace(
                calificacion_promedio=0,
                tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
            ),
            mecanico=None,
            marca_vehiculo_seleccionada_id=marca_id,
            tipo_motor='',
            servicio=SimpleNamespace(categorias=MagicMock(first=lambda: None)),
        )
        vehiculo = SimpleNamespace(tipo_motor='DIESEL')
        ctx_esp = CoincidenciaCatalogoContext(
            vehiculo=vehiculo,
            marca_id=marca_id,
            requiere_repuestos=True,
            dist_km=4.5,
            con_ubicacion_cliente=True,
            catalogo_completo=True,
            oferta_ofrece_repuestos=True,
        )
        ctx_mm = CoincidenciaCatalogoContext(
            vehiculo=vehiculo,
            marca_id=marca_id,
            requiere_repuestos=True,
            dist_km=0.8,
            con_ubicacion_cliente=True,
            catalogo_completo=True,
            oferta_ofrece_repuestos=True,
        )
        score_esp = calcular_score_coincidencia(oferta_esp, ctx_esp).score
        score_mm = calcular_score_coincidencia(oferta_mm, ctx_mm).score
        self.assertGreater(
            score_esp,
            score_mm,
            'Especialista con motor exacto debe superar multimarca universal aunque esté más lejos',
        )

    def test_prioridad_orden_cobertura_especialista_primero(self):
        self.assertLess(
            prioridad_orden_cobertura_proveedor({'tipo_cobertura_marca': 'especialista'}),
            prioridad_orden_cobertura_proveedor({'tipo_cobertura_marca': 'multimarca'}),
        )


class MotorMatchScoringIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marca = MarcaVehiculo.objects.create(nombre='MarcaScore Test')
        cls.modelo = Modelo.objects.create(nombre='ModScore', marca=cls.marca)
        cls.servicio = Servicio.objects.create(
            nombre='Servicio Score Test',
            tipos_motor_compatibles=['GASOLINA', 'DIESEL'],
        )

        user_esp = User.objects.create_user(
            username='esp_score@test.com',
            email='esp_score@test.com',
            password='testpass123',
        )
        cls.taller_esp = Taller.objects.create(
            usuario=user_esp,
            nombre='Taller Especialista Score',
            verificado=True,
            activo=True,
            tipo_cobertura_marca=TIPO_COBERTURA_ESPECIALISTA,
        )
        cls.taller_esp.marcas_atendidas.add(cls.marca)

        user_mm = User.objects.create_user(
            username='mm_score@test.com',
            email='mm_score@test.com',
            password='testpass123',
        )
        cls.taller_mm = Taller.objects.create(
            usuario=user_mm,
            nombre='Taller Multimarca Score',
            verificado=True,
            activo=True,
            tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
        )

        cls.oferta_esp = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='taller',
            taller=cls.taller_esp,
            marca_vehiculo_seleccionada=cls.marca,
            tipo_motor='DIESEL',
            disponible=True,
            precio_sin_repuestos=Decimal('40000'),
            precio_con_repuestos=Decimal('50000'),
            precio_publicado_cliente=Decimal('50000'),
            costo_mano_de_obra_sin_iva=Decimal('30000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )
        cls.oferta_mm = OfertaServicio.objects.create(
            servicio=cls.servicio,
            tipo_proveedor='taller',
            taller=cls.taller_mm,
            marca_vehiculo_seleccionada=cls.marca,
            tipo_motor='DIESEL',
            disponible=True,
            precio_sin_repuestos=Decimal('40000'),
            precio_con_repuestos=Decimal('50000'),
            precio_publicado_cliente=Decimal('50000'),
            costo_mano_de_obra_sin_iva=Decimal('30000'),
            costo_repuestos_sin_iva=Decimal('10000'),
        )

        user_cli = User.objects.create_user(
            username='cli_score@test.com',
            email='cli_score@test.com',
            password='testpass123',
        )
        cls.cliente = Cliente.objects.create(
            usuario=user_cli,
            nombre='Cli',
            apellido='Score',
            email='cli_score@test.com',
        )
        cls.vehiculo = Vehiculo.objects.create(
            cliente=cls.cliente,
            marca=cls.marca,
            modelo=cls.modelo,
            year=2020,
            patente='SCORE01',
            tipo_motor='DIESEL',
        )

    def test_features_incluyen_cobertura_y_motor(self):
        ctx = CoincidenciaCatalogoContext(
            vehiculo=self.vehiculo,
            marca_id=self.marca.id,
            requiere_repuestos=True,
            dist_km=1.5,
            con_ubicacion_cliente=True,
            catalogo_completo=True,
            oferta_ofrece_repuestos=True,
        )
        f_esp = extraer_features_coincidencia(self.oferta_esp, ctx)
        f_mm = extraer_features_coincidencia(self.oferta_mm, ctx)
        self.assertEqual(f_esp['motor'], 1.0)
        self.assertGreater(f_esp['cobertura_proveedor'], f_mm['cobertura_proveedor'])

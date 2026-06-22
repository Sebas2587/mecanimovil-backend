"""Tests: motor_match filtra por modalidad y excluye talleres sin mecánico apto activo."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _queryset_ofertas_compatibles,
    _talleres_excluidos_por_equipo,
)
from mecanimovilapp.apps.servicios.models import CategoriaServicio, OfertaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import MiembroTaller, Taller

User = get_user_model()


def _crear_taller(nombre, modalidad):
    user = User.objects.create_user(username=f'{nombre}@t.com', email=f'{nombre}@t.com', password='x')
    return Taller.objects.create(
        usuario=user, nombre=nombre, estado_verificacion='aprobado', activo=True,
        modalidad_atencion=modalidad,
    )


def _crear_oferta(servicio, taller):
    return OfertaServicio.objects.create(
        servicio=servicio,
        tipo_proveedor='taller',
        taller=taller,
        marca_vehiculo_seleccionada=None,
        disponible=True,
        precio_sin_repuestos=Decimal('50000'),
        precio_con_repuestos=Decimal('60000'),
        precio_publicado_cliente=Decimal('60000'),
        costo_mano_de_obra_sin_iva=Decimal('40000'),
        costo_repuestos_sin_iva=Decimal('10000'),
    )


class MotorMatchModalidadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categoria = CategoriaServicio.objects.create(nombre='Cat Modalidad Test')
        cls.servicio = Servicio.objects.create(nombre='Servicio Modalidad Test')
        cls.servicio.categorias.add(cls.categoria)

        cls.taller_en_taller = _crear_taller('mod_entaller', 'en_taller')
        cls.taller_ambas = _crear_taller('mod_ambas', 'ambas')
        cls.taller_domicilio = _crear_taller('mod_domicilio', 'a_domicilio')

        cls.of_en_taller = _crear_oferta(cls.servicio, cls.taller_en_taller)
        cls.of_ambas = _crear_oferta(cls.servicio, cls.taller_ambas)
        cls.of_domicilio = _crear_oferta(cls.servicio, cls.taller_domicilio)

    def test_busqueda_domicilio_incluye_ambas_excluye_solo_taller(self):
        qs = _queryset_ofertas_compatibles(
            [self.servicio.id], marca=None, modalidad='a_domicilio',
        )
        talleres = set(qs.values_list('taller_id', flat=True))
        self.assertIn(self.taller_ambas.id, talleres)
        self.assertIn(self.taller_domicilio.id, talleres)
        self.assertNotIn(self.taller_en_taller.id, talleres)

    def test_busqueda_en_taller_incluye_ambas_excluye_solo_domicilio(self):
        qs = _queryset_ofertas_compatibles(
            [self.servicio.id], marca=None, modalidad='en_taller',
        )
        talleres = set(qs.values_list('taller_id', flat=True))
        self.assertIn(self.taller_en_taller.id, talleres)
        self.assertIn(self.taller_ambas.id, talleres)
        self.assertNotIn(self.taller_domicilio.id, talleres)

    def test_sin_modalidad_incluye_todos(self):
        qs = _queryset_ofertas_compatibles([self.servicio.id], marca=None, modalidad=None)
        talleres = set(qs.values_list('taller_id', flat=True))
        self.assertEqual(
            talleres,
            {self.taller_en_taller.id, self.taller_ambas.id, self.taller_domicilio.id},
        )

    def test_taller_con_equipo_sin_mecanico_apto_se_excluye(self):
        # Taller ambas con un mecánico activo SIN la especialidad requerida → excluido.
        otra_cat = CategoriaServicio.objects.create(nombre='Otra Cat Modalidad')
        mec = MiembroTaller.objects.create(
            taller=self.taller_ambas, rol='mecanico', nombre='Mec Sin Apto',
            modalidad_tecnico='ambas', activo=True,
        )
        mec.especialidades.add(otra_cat)

        excluidos = _talleres_excluidos_por_equipo([self.servicio.id])
        self.assertIn(self.taller_ambas.id, excluidos)
        # Talleres sin equipo NO se excluyen (fallback a nivel taller).
        self.assertNotIn(self.taller_en_taller.id, excluidos)
        self.assertNotIn(self.taller_domicilio.id, excluidos)

    def test_taller_con_mecanico_apto_no_se_excluye(self):
        mec = MiembroTaller.objects.create(
            taller=self.taller_domicilio, rol='mecanico', nombre='Mec Apto',
            modalidad_tecnico='a_domicilio', activo=True,
        )
        mec.especialidades.add(self.categoria)
        excluidos = _talleres_excluidos_por_equipo([self.servicio.id])
        self.assertNotIn(self.taller_domicilio.id, excluidos)

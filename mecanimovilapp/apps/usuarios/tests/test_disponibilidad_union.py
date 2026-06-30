"""Tests: disponibilidad por unión de equipo y no-regresión de talleres sin equipo (fallback)."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.servicios.models import CategoriaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import HorarioProveedor, MiembroTaller, Taller
from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import (
    disponibilidad_con_duracion,
)

User = get_user_model()

# 2030-01-07 es lunes (weekday 0).
FECHA_LUNES = date(2030, 1, 7)


class DisponibilidadUnionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categoria = CategoriaServicio.objects.create(nombre='Cat Disp Union')
        cls.servicio = Servicio.objects.create(nombre='Servicio Disp Union')
        cls.servicio.categorias.add(cls.categoria)

        user = User.objects.create_user(
            username='taller_disp@test.com', email='taller_disp@test.com', password='x',
        )
        cls.taller = Taller.objects.create(
            usuario=user, nombre='Taller Disp Union',
            estado_verificacion='aprobado', activo=True, modalidad_atencion='ambas',
        )
        # Horario a nivel taller (fallback) para el lunes.
        HorarioProveedor.objects.create(
            taller=cls.taller, dia_semana=0, activo=True,
            hora_inicio=time(9, 0), hora_fin=time(13, 0),
            duracion_slot=60, tiempo_descanso=0,
        )

    def test_taller_sin_equipo_usa_fallback(self):
        """Sin mecánicos: comportamiento histórico a nivel taller (no regresión)."""
        data = disponibilidad_con_duracion(taller=self.taller, fecha=FECHA_LUNES)
        self.assertTrue(data['proveedor_disponible'])
        self.assertGreater(len(data['slots_disponibles']), 0)

    def test_taller_con_equipo_usa_union(self):
        mec = MiembroTaller.objects.create(
            taller=self.taller, rol='mecanico', nombre='Mec Disp',
            modalidad_tecnico='ambas', activo=True,
        )
        mec.especialidades.add(self.categoria)
        data = disponibilidad_con_duracion(taller=self.taller, fecha=FECHA_LUNES)
        self.assertTrue(data['proveedor_disponible'])
        self.assertGreater(len(data['slots_disponibles']), 0)

    def test_mecanico_deshabilitado_vuelve_a_fallback(self):
        mec = MiembroTaller.objects.create(
            taller=self.taller, rol='mecanico', nombre='Mec Off',
            modalidad_tecnico='ambas', activo=False,
        )
        mec.especialidades.add(self.categoria)
        # Con el único mecánico deshabilitado, tiene_equipo=False → fallback taller.
        data = disponibilidad_con_duracion(taller=self.taller, fecha=FECHA_LUNES)
        self.assertTrue(data['proveedor_disponible'])
        self.assertGreater(len(data['slots_disponibles']), 0)

    def test_dia_sin_horario_no_disponible(self):
        # Domingo (2030-01-06) sin horario configurado.
        domingo = date(2030, 1, 6)
        data = disponibilidad_con_duracion(taller=self.taller, fecha=domingo)
        self.assertFalse(data['proveedor_disponible'])

    def test_mecanico_dia_inactivo_no_hereda_horario_taller(self):
        """Un día desactivado en la agenda del mecánico no debe usar el horario general del taller."""
        mec = MiembroTaller.objects.create(
            taller=self.taller, rol='mecanico', nombre='Mec Lun Off',
            modalidad_tecnico='ambas', activo=True,
        )
        mec.especialidades.add(self.categoria)
        HorarioProveedor.objects.create(
            taller=self.taller,
            miembro_taller=mec,
            dia_semana=0,
            activo=False,
            hora_inicio=time(9, 0),
            hora_fin=time(13, 0),
            duracion_slot=60,
            tiempo_descanso=0,
        )
        data = disponibilidad_con_duracion(
            taller=self.taller,
            fecha=FECHA_LUNES,
            miembro_taller_id=mec.id,
        )
        self.assertFalse(data['proveedor_disponible'])
        self.assertEqual(data['slots_disponibles'], [])

    def test_mecanico_sin_config_dia_hereda_taller(self):
        """Sin horario propio para el día, el mecánico sigue heredando la agenda general del taller."""
        mec = MiembroTaller.objects.create(
            taller=self.taller, rol='mecanico', nombre='Mec Sin Config',
            modalidad_tecnico='ambas', activo=True,
        )
        mec.especialidades.add(self.categoria)
        data = disponibilidad_con_duracion(
            taller=self.taller,
            fecha=FECHA_LUNES,
            miembro_taller_id=mec.id,
        )
        self.assertTrue(data['proveedor_disponible'])
        self.assertGreater(len(data['slots_disponibles']), 0)

"""Tests: asignación automática de mecánico (MiembroTaller) y disponibilidad por equipo."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.asignacion_mecanico import seleccionar_mecanico
from mecanimovilapp.apps.servicios.models import CategoriaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import HorarioProveedor, MiembroTaller, Taller
from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import mecanicos_aptos_taller

User = get_user_model()

# Fecha futura fija que cae en lunes (weekday 0). 2030-01-07 es lunes.
FECHA_LUNES = date(2030, 1, 7)


class AsignacionMecanicoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categoria = CategoriaServicio.objects.create(nombre='Frenos Test Asignacion')
        cls.servicio = Servicio.objects.create(nombre='Cambio pastillas Test')
        cls.servicio.categorias.add(cls.categoria)

        user = User.objects.create_user(
            username='taller_asig@test.com',
            email='taller_asig@test.com',
            password='x',
        )
        cls.taller = Taller.objects.create(
            usuario=user,
            nombre='Taller Asignacion Test',
            verificado=True,
            activo=True,
            modalidad_atencion='ambas',
        )

        # Horario a nivel taller para todos los días (los mecánicos lo heredan).
        for dia in range(7):
            HorarioProveedor.objects.create(
                taller=cls.taller,
                dia_semana=dia,
                activo=True,
                hora_inicio=time(8, 0),
                hora_fin=time(18, 0),
                duracion_slot=60,
                tiempo_descanso=0,
            )

        cls.mec_a = MiembroTaller.objects.create(
            taller=cls.taller, rol='mecanico', nombre='Mec A',
            modalidad_tecnico='ambas', activo=True,
        )
        cls.mec_a.especialidades.add(cls.categoria)

        cls.mec_b = MiembroTaller.objects.create(
            taller=cls.taller, rol='mecanico', nombre='Mec B',
            modalidad_tecnico='en_taller', activo=True,
        )
        cls.mec_b.especialidades.add(cls.categoria)

    def test_selecciona_mecanico_apto_en_slot(self):
        elegido = seleccionar_mecanico(
            taller=self.taller,
            fecha=FECHA_LUNES,
            hora=time(10, 0),
            duracion_minutos=60,
            categorias_requeridas=[self.categoria.id],
            modalidad='en_taller',
        )
        self.assertIsNotNone(elegido)
        self.assertIn(elegido.id, {self.mec_a.id, self.mec_b.id})

    def test_modalidad_domicilio_excluye_mecanico_solo_taller(self):
        aptos = mecanicos_aptos_taller(
            self.taller,
            categorias_requeridas=[self.categoria.id],
            modalidad='a_domicilio',
        )
        ids = {m.id for m in aptos}
        self.assertIn(self.mec_a.id, ids)  # ambas → compatible
        self.assertNotIn(self.mec_b.id, ids)  # en_taller → no atiende a domicilio

    def test_sin_especialidad_no_es_apto(self):
        otra = CategoriaServicio.objects.create(nombre='Motor Test Asignacion')
        aptos = mecanicos_aptos_taller(
            self.taller,
            categorias_requeridas=[otra.id],
        )
        self.assertEqual(aptos, [])

    def test_mecanicos_deshabilitados_no_se_asignan(self):
        self.mec_a.activo = False
        self.mec_a.save(update_fields=['activo'])
        self.mec_b.activo = False
        self.mec_b.save(update_fields=['activo'])
        elegido = seleccionar_mecanico(
            taller=self.taller,
            fecha=FECHA_LUNES,
            hora=time(10, 0),
            duracion_minutos=60,
            categorias_requeridas=[self.categoria.id],
        )
        self.assertIsNone(elegido)

    def test_fuera_de_horario_no_asigna(self):
        elegido = seleccionar_mecanico(
            taller=self.taller,
            fecha=FECHA_LUNES,
            hora=time(20, 0),  # fuera de 08:00-18:00
            duracion_minutos=60,
            categorias_requeridas=[self.categoria.id],
        )
        self.assertIsNone(elegido)

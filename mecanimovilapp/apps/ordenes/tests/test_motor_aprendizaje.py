"""Tests aprendizaje semántico (sin BD cuando es posible)."""
import re

from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.lexico_necesidad import REGLAS_SINTOMA
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_aprendizaje import (
    _generar_fragmentos,
    build_metadata_ia_entrada,
)
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_salud_cruzada import (
    cruzar_salud_con_texto,
    interpretar_metricas_salud,
)


class LexicoNecesidadPatronesTests(SimpleTestCase):
    def test_todos_los_patrones_son_regex_validos(self):
        for regla in REGLAS_SINTOMA:
            for patron in regla.patrones:
                with self.subTest(regla=regla.id, patron=patron):
                    re.compile(patron)


class MotorAprendizajeFragmentosTests(SimpleTestCase):
    def test_genera_bigramas(self):
        frags = _generar_fragmentos('ruido al frenar pedal blando')
        self.assertTrue(any('fren' in f for f in frags))

    def test_metadata_entrada_sin_pii_largo(self):
        meta = build_metadata_ia_entrada(
            analisis={
                'motor_analisis': 'lexico',
                'interpretacion': 'Posible desgaste de frenos',
                'sintomas_detectados': ['ruido_freno'],
                'servicios_recomendados': [{'servicio_id': 42}],
            },
            componentes_salud=[
                {'slug': 'brakes', 'nombre': 'Frenos', 'nivel_alerta': 'URGENTE', 'salud_porcentaje': 30},
            ],
        )
        self.assertEqual(meta['motor_analisis'], 'lexico')
        self.assertEqual(meta['servicios_recomendados_ids'], [42])
        self.assertEqual(len(meta['componentes_salud']), 1)


class MotorSaludCruceTests(SimpleTestCase):
    def test_interpreta_salud_critica(self):
        info = interpretar_metricas_salud([
            {
                'slug': 'brakes',
                'nombre': 'Pastillas de freno',
                'nivel_alerta': 'URGENTE',
                'salud_porcentaje': 25,
            },
        ])
        self.assertIsNotNone(info.get('resumen_salud'))
        self.assertEqual(len(info.get('componentes_criticos') or []), 1)

    def test_alerta_si_salud_critica_no_mencionada(self):
        cruce = cruzar_salud_con_texto(
            'ruido en el motor',
            [
                {
                    'slug': 'brakes',
                    'nombre': 'Pastillas',
                    'nivel_alerta': 'CRITICO',
                    'salud_porcentaje': 20,
                },
            ],
        )
        self.assertTrue(len(cruce.get('alertas_cruce') or []) >= 1)

"""Tests: contexto de tipo de motor para asistente IA."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.contexto_motor import (
    consolidar_contexto_motor,
    inferir_tipo_motor_desde_texto,
    parse_tipo_motor_si_presente,
)


class ContextoMotorAsistenteTestCase(SimpleTestCase):
    def test_inferir_diesel_desde_nombre_servicio(self):
        self.assertEqual(
            inferir_tipo_motor_desde_texto('Diagnóstico mecánico Diesel'),
            'DIESEL',
        )

    def test_inferir_gasolina_desde_nota(self):
        self.assertEqual(
            inferir_tipo_motor_desde_texto('necesito cambio de bujías bencinero'),
            'GASOLINA',
        )

    def test_prioriza_motor_vehiculo_sobre_servicio(self):
        ctx = consolidar_contexto_motor(
            motor_vehiculo='GASOLINA',
            motor_servicio='DIESEL',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'GASOLINA')
        self.assertTrue(ctx['tipo_motor_conflicto'])

    def test_usa_motor_servicio_si_no_hay_vehiculo(self):
        ctx = consolidar_contexto_motor(
            motor_vehiculo=None,
            motor_servicio='DIESEL',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'DIESEL')

    def test_parse_tipo_motor_vacio_es_none(self):
        self.assertIsNone(parse_tipo_motor_si_presente(''))
        self.assertIsNone(parse_tipo_motor_si_presente(None))

    def test_normaliza_bencina(self):
        self.assertEqual(parse_tipo_motor_si_presente('BENCINA'), 'GASOLINA')

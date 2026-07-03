"""Tests: contexto de tipo de motor para asistente IA."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.contexto_motor import (
    consolidar_contexto_motor,
    inferir_motor_desde_modelo,
    inferir_tipo_motor_desde_texto,
    parse_tipo_motor_si_presente,
)


class ContextoMotorAsistenteTestCase(SimpleTestCase):
    def test_inferir_diesel_desde_nombre_servicio(self):
        self.assertEqual(
            inferir_tipo_motor_desde_texto('Diagnóstico mecánico Diesel'),
            'DIESEL',
        )

    def test_inferir_diesel_desde_petrolero(self):
        self.assertEqual(
            inferir_tipo_motor_desde_texto(
                'vehiculo petrolero, revision sistema de encendido, inyectores'
            ),
            'DIESEL',
        )

    def test_inferir_gasolina_desde_nota(self):
        self.assertEqual(
            inferir_tipo_motor_desde_texto('necesito cambio de bujías bencinero'),
            'GASOLINA',
        )

    def test_inferir_gasolina_desde_tjet(self):
        self.assertEqual(
            inferir_motor_desde_modelo('FIAT', 'BRAVO SPORT TJET', ''),
            'GASOLINA',
        )

    def test_caso_fiat_tjet_servicio_diesel_usa_patente(self):
        """T-Jet bencinero + servicio Diesel mal asignado → guía bencinera."""
        ctx = consolidar_contexto_motor(
            motor_vehiculo='GASOLINA',
            motor_servicio='DIESEL',
            motor_problema='DIESEL',
            motor_modelo='GASOLINA',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'GASOLINA')
        self.assertEqual(ctx['tipo_motor_efectivo_label'], 'Bencinero (gasolina)')
        self.assertTrue(ctx['tipo_motor_conflicto'])
        self.assertTrue(ctx['tipo_motor_servicio_posible_error'])
        self.assertIn('posible error de asignación', ctx['tipo_motor_conflicto_detalle'])

    def test_patente_prevalece_sobre_servicio_diesel(self):
        ctx = consolidar_contexto_motor(
            motor_vehiculo='GASOLINA',
            motor_servicio='DIESEL',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'GASOLINA')
        self.assertTrue(ctx['tipo_motor_servicio_posible_error'])

    def test_usa_motor_servicio_si_no_hay_datos_vehiculo(self):
        ctx = consolidar_contexto_motor(
            motor_vehiculo=None,
            motor_servicio='DIESEL',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'DIESEL')

    def test_usa_modelo_si_no_hay_patente_ni_servicio_conflicto(self):
        ctx = consolidar_contexto_motor(
            motor_vehiculo=None,
            motor_servicio='DIESEL',
            motor_modelo='GASOLINA',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'GASOLINA')
        self.assertTrue(ctx['tipo_motor_servicio_posible_error'])

    def test_sin_patente_ni_modelo_usa_problema_y_servicio(self):
        ctx = consolidar_contexto_motor(
            motor_vehiculo=None,
            motor_servicio='DIESEL',
            motor_problema='DIESEL',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'DIESEL')

    def test_patente_sin_conflicto(self):
        ctx = consolidar_contexto_motor(
            motor_vehiculo='GASOLINA',
            motor_servicio=None,
            motor_problema=None,
            motor_modelo='GASOLINA',
        )
        self.assertEqual(ctx['tipo_motor_efectivo'], 'GASOLINA')
        self.assertFalse(ctx['tipo_motor_conflicto'])

    def test_parse_tipo_motor_vacio_es_none(self):
        self.assertIsNone(parse_tipo_motor_si_presente(''))
        self.assertIsNone(parse_tipo_motor_si_presente(None))

    def test_normaliza_bencina(self):
        self.assertEqual(parse_tipo_motor_si_presente('BENCINA'), 'GASOLINA')

"""Tests resumen operación agendamiento IA."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_operacion import (
    obtener_resumen_operacion_agendamiento_ia,
)


User = get_user_model()


@override_settings(
    AGENDAMIENTO_IA_ASISTIDO=True,
    AGENDAMIENTO_IA_SEMANTICO_ENABLED=True,
    AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR='lexico',
)
class MotorOperacionResumenTests(TestCase):
    def test_resumen_incluye_flags_y_patrones(self):
        resumen = obtener_resumen_operacion_agendamiento_ia()
        self.assertTrue(resumen['flags']['agendamiento_ia_asistido'])
        self.assertEqual(resumen['flags']['semantico_proveedor'], 'lexico')
        self.assertIn('patrones_aprendizaje_activos', resumen)
        self.assertIn('catalogo_ultimos_30_dias', resumen)
        self.assertIn('generado_at', resumen)

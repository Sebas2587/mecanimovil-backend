"""
Tests del cap por antigüedad del HealthEngine.

Bloquean la regresión reportada: un componente que degrada por tiempo
(ej. líquido de frenos) recién cambiado en un vehículo ANTIGUO debe partir
cerca del 100 % y NO ser forzado a 20 % por la edad de fabricación del auto.

La edad relevante es la del COMPONENTE (tiempo desde su último cambio), no la
antigüedad del vehículo. Solo cuando no hay historial confirmado se cae a la
antigüedad del vehículo como estimación conservadora (seguridad preservada).
"""
from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.vehiculos.services.health_engine import (
    _age_health_cap,
    _component_age_years,
)
from mecanimovilapp.apps.vehiculos.tasks import _nivel_alerta_desde_pct


def _vehiculo(antiguedad_anios):
    return SimpleNamespace(year=timezone.now().year - antiguedad_anios)


def _comp(fecha_ultimo_servicio=None, historial_conocido=False):
    return SimpleNamespace(
        fecha_ultimo_servicio=fecha_ultimo_servicio,
        historial_conocido=historial_conocido,
    )


class AgeHealthCapTestCase(TestCase):
    def test_liquido_frenos_recien_cambiado_en_auto_viejo_no_se_degrada(self):
        """Regresión principal: brake-fluid cambiado hoy en auto de 13 años => ~100%."""
        veh = _vehiculo(13)
        comp = _comp(fecha_ultimo_servicio=timezone.now(), historial_conocido=True)
        salud, msg = _age_health_cap(veh, 'brake-fluid', 100.0, comp_estado=comp)
        self.assertEqual(salud, 100.0)
        self.assertIsNone(msg)

    def test_liquido_frenos_sin_historial_en_auto_viejo_se_capa(self):
        """Seguridad: sin historial confirmado en auto viejo => sigue capado a 20%."""
        veh = _vehiculo(13)
        comp = _comp(fecha_ultimo_servicio=None, historial_conocido=False)
        salud, msg = _age_health_cap(veh, 'brake-fluid', 100.0, comp_estado=comp)
        self.assertEqual(salud, 20.0)
        self.assertIsNotNone(msg)
        self.assertIn('sin registro', msg.lower())

    def test_liquido_frenos_cambiado_hace_tres_anios_degrada_parcial(self):
        """3 años desde el cambio (entre óptimo=2 y crítico=4) => degradación parcial."""
        veh = _vehiculo(13)
        comp = _comp(
            fecha_ultimo_servicio=timezone.now() - timedelta(days=365 * 3),
            historial_conocido=True,
        )
        salud, msg = _age_health_cap(veh, 'brake-fluid', 100.0, comp_estado=comp)
        self.assertLess(salud, 100.0)
        self.assertGreater(salud, 20.0)
        self.assertIsNotNone(msg)

    def test_liquido_frenos_cambiado_hace_seis_anios_supera_critico(self):
        """6 años desde el cambio (> crítico=4) => capado a 20% aunque haya historial."""
        veh = _vehiculo(13)
        comp = _comp(
            fecha_ultimo_servicio=timezone.now() - timedelta(days=365 * 6),
            historial_conocido=True,
        )
        salud, msg = _age_health_cap(veh, 'brake-fluid', 100.0, comp_estado=comp)
        self.assertEqual(salud, 20.0)
        self.assertIn('último cambio', msg.lower())

    def test_componente_sin_age_cap_no_se_altera(self):
        veh = _vehiculo(13)
        comp = _comp(fecha_ultimo_servicio=None, historial_conocido=False)
        salud, msg = _age_health_cap(veh, 'oil', 88.0, comp_estado=comp)
        self.assertEqual(salud, 88.0)
        self.assertIsNone(msg)

    def test_age_cap_no_sube_la_salud(self):
        """El cap solo puede BAJAR la salud, nunca subirla."""
        veh = _vehiculo(20)
        comp = _comp(fecha_ultimo_servicio=None, historial_conocido=False)
        salud, _ = _age_health_cap(veh, 'brake-fluid', 12.0, comp_estado=comp)
        self.assertEqual(salud, 12.0)


class ComponentAgeYearsTestCase(TestCase):
    def test_prefiere_fecha_servicio_cuando_hay_historial(self):
        veh = _vehiculo(13)
        comp = _comp(fecha_ultimo_servicio=timezone.now(), historial_conocido=True)
        anios, desde_servicio = _component_age_years(veh, comp)
        self.assertTrue(desde_servicio)
        self.assertLess(anios, 1)

    def test_cae_a_antiguedad_vehiculo_sin_historial(self):
        veh = _vehiculo(13)
        comp = _comp(fecha_ultimo_servicio=None, historial_conocido=False)
        anios, desde_servicio = _component_age_years(veh, comp)
        self.assertFalse(desde_servicio)
        self.assertEqual(int(anios), 13)

    def test_sin_fecha_ni_year_devuelve_none(self):
        veh = SimpleNamespace(year=None)
        comp = _comp(fecha_ultimo_servicio=None, historial_conocido=False)
        anios, desde_servicio = _component_age_years(veh, comp)
        self.assertIsNone(anios)
        self.assertFalse(desde_servicio)

    def test_historial_conocido_pero_sin_fecha_cae_a_year(self):
        """historial_conocido=True pero sin fecha => no podemos medir desde servicio."""
        veh = _vehiculo(8)
        comp = _comp(fecha_ultimo_servicio=None, historial_conocido=True)
        anios, desde_servicio = _component_age_years(veh, comp)
        self.assertFalse(desde_servicio)
        self.assertEqual(int(anios), 8)


class NivelAlertaUmbralesTestCase(TestCase):
    """Los umbrales de tasks deben coincidir con los del HealthEngine (70/40/10)."""

    def test_umbrales_alineados_con_health_engine(self):
        self.assertEqual(_nivel_alerta_desde_pct(100), 'OPTIMO')
        self.assertEqual(_nivel_alerta_desde_pct(70), 'OPTIMO')
        self.assertEqual(_nivel_alerta_desde_pct(69.9), 'ATENCION')
        self.assertEqual(_nivel_alerta_desde_pct(40), 'ATENCION')
        self.assertEqual(_nivel_alerta_desde_pct(39.9), 'URGENTE')
        self.assertEqual(_nivel_alerta_desde_pct(20), 'URGENTE')
        self.assertEqual(_nivel_alerta_desde_pct(10), 'URGENTE')
        self.assertEqual(_nivel_alerta_desde_pct(9.9), 'CRITICO')
        self.assertEqual(_nivel_alerta_desde_pct(0), 'CRITICO')

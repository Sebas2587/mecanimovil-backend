"""Alcance de pedido del agente: mención ≠ cotizar; suma solo explícita."""
from __future__ import annotations

from django.test import SimpleTestCase

from mecanimovilapp.apps.agente_ia.services.alcance_pedido import (
    _acotar_servicios_al_pedido,
    _cliente_pide_agregar_a_cotizacion,
    _cliente_pide_quitar_de_cotizacion,
    _extraer_servicios_mencionados_en_texto,
)


class PedidoExplicitoVsMencionTestCase(SimpleTestCase):
    def test_mencion_aceite_no_es_agregar(self):
        self.assertFalse(
            _cliente_pide_agregar_a_cotizacion('el aceite lo hice la semana pasada'),
        )
        self.assertFalse(
            _cliente_pide_agregar_a_cotizacion('¿ustedes hacen frenos?'),
        )

    def test_sumale_si_es_agregar(self):
        self.assertTrue(_cliente_pide_agregar_a_cotizacion('súmale el filtro de aire'))
        self.assertTrue(_cliente_pide_agregar_a_cotizacion('también quiero el cambio de aceite'))

    def test_quita_detecta_pedido(self):
        self.assertTrue(_cliente_pide_quitar_de_cotizacion('quita las pastillas'))

    def test_acotar_no_suma_mencion_suelta(self):
        previos = {'servicios': ['Cambio de aceite'], 'servicio_nombre': 'Cambio de aceite'}
        datos = {
            'servicios': ['Cambio de aceite', 'Diagnóstico de frenos'],
            'servicio_nombre': 'Cambio de aceite',
        }
        out = _acotar_servicios_al_pedido(
            previos=previos,
            datos=datos,
            texto_cliente='¿ustedes hacen frenos?',
        )
        self.assertEqual(out['servicios'], ['Cambio de aceite'])

    def test_acotar_suma_si_pide_explicito(self):
        previos = {'servicios': ['Cambio de aceite'], 'servicio_nombre': 'Cambio de aceite'}
        datos = {'servicios': ['Cambio de aceite'], 'servicio_nombre': 'Cambio de aceite'}
        out = _acotar_servicios_al_pedido(
            previos=previos,
            datos=datos,
            texto_cliente='súmale el filtro de aire',
        )
        claves = ' '.join(str(s).lower() for s in out.get('servicios') or [])
        self.assertIn('aire', claves)

    def test_acotar_solo_aceite_quita_el_resto(self):
        previos = {
            'servicios': ['Cambio de aceite', 'Cambio de pastillas de freno'],
            'servicio_nombre': 'Cambio de aceite',
        }
        datos = {
            'servicios': ['Cambio de aceite', 'Cambio de pastillas de freno'],
        }
        out = _acotar_servicios_al_pedido(
            previos=previos,
            datos=datos,
            texto_cliente='solo el cambio de aceite',
        )
        self.assertEqual(len(out['servicios']), 1)
        self.assertIn('aceite', out['servicios'][0].lower())

    def test_cambio_patente_no_hereda_servicios(self):
        previos = {
            'servicios': ['Cambio de pastillas de freno'],
            'servicio_nombre': 'Cambio de pastillas de freno',
            'patente_enriquecida': 'ABCD12',
            'vehiculo': {'patente': 'ABCD12', 'marca': 'Toyota', 'modelo': 'Yaris'},
        }
        datos = {
            'servicios': ['Cambio de pastillas de freno', 'Cambio de aceite'],
            'servicio_nombre': 'Cambio de aceite',
            'patente_enriquecida': 'EFGH34',
            'vehiculo': {'patente': 'EFGH34', 'marca': 'BAIC', 'modelo': 'X35'},
        }
        out = _acotar_servicios_al_pedido(
            previos=previos,
            datos=datos,
            texto_cliente='quiero cotizar cambio de aceite',
        )
        self.assertTrue(any('aceite' in str(s).lower() for s in out.get('servicios') or []))
        self.assertFalse(any('pastilla' in str(s).lower() for s in out.get('servicios') or []))

    def test_extraer_menciones_no_se_usa_como_pedido(self):
        nombres = _extraer_servicios_mencionados_en_texto(
            'el cambio de aceite lo hice; ¿hacen diagnóstico?',
        )
        self.assertTrue(nombres)

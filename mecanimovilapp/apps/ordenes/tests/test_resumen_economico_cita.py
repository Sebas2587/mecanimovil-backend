"""Tests resumen económico de cita personal."""
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.resumen_economico_cita import (
    _desglose_iva_desde_total,
    construir_resumen_economico_cita,
)


class ResumenEconomicoCitaTests(SimpleTestCase):
    def test_desglose_iva_desde_total_sail(self):
        d = _desglose_iva_desde_total(48_552)
        self.assertEqual(d['total_clp'], 48_552)
        self.assertEqual(d['neto_clp'], 40_800)
        self.assertEqual(d['iva_clp'], 7_752)

    def test_resumen_desde_cotizacion_con_repuestos(self):
        cot = MagicMock()
        cot.id = 99
        cot.servicio_nombre = 'Cambio de bujías'
        cot.descripcion_problema = 'Cliente pide juego completo'
        cot.mano_obra_clp = 29_750
        cot.costo_repuestos_clp = 18_802
        cot.total_clp = 48_552
        cot.notas_internas = '1. Revisar bujías iridium'
        cot.metadata = {'servicios_lineas': [{'nombre': 'Cambio de bujías', 'monto_clp': 48_552}]}
        cot.repuestos = [
            {
                'nombre': 'Bujías (Juego de 4)',
                'cantidad': 1,
                'precio_unitario_clp': 18_802,
                'marca_repuesto': 'Genérico',
                'proveedor_nombre': 'Catálogo del taller',
            }
        ]

        det = MagicMock()
        det.servicio_nombre = 'Cambio de bujías'
        det.descripcion = 'Cliente pide juego completo'
        det.oferta_servicio_id = None
        det.oferta_servicio = None
        det.precio_referencia = Decimal('48552')

        cita = MagicMock()
        cita.detalle = det
        cita.cotizacion_canal_origen = cot

        res = construir_resumen_economico_cita(cita)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res['fuente'], 'cotizacion')
        self.assertEqual(res['total_clp'], 48_552)
        self.assertEqual(len(res['repuestos']), 1)
        self.assertEqual(res['repuestos'][0]['marca_repuesto'], 'Genérico')
        self.assertEqual(res['iva_clp'], 7_752)

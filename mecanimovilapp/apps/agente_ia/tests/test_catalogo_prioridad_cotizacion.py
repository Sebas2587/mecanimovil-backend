"""Catálogo del taller gana sobre IA/web cuando hay OfertaServicio match."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
    _clp_con_iva,
    _desglose_oferta_catalogo,
)


class DesgloseOfertaCatalogoIvaTests(SimpleTestCase):
    """La cotización muestra precios con IVA; el config muestra netos."""

    def test_clp_con_iva_sail_bujias_montos(self):
        # Netos de la tarifa configurada
        self.assertEqual(_clp_con_iva(25_000), 29_750)
        self.assertEqual(_clp_con_iva(15_800), 18_802)
        # Público = (25000+15800)*1.19
        self.assertEqual(_clp_con_iva(40_800), 48_552)

    def test_desglose_usa_precio_sin_repuestos_con_iva(self):
        oferta = MagicMock()
        oferta.id = 1
        oferta.precio_sin_repuestos = 29_750
        oferta.precio_con_repuestos = 48_552
        oferta.costo_mano_de_obra_sin_iva = Decimal('25000')
        oferta.costo_repuestos_sin_iva = Decimal('15800')
        oferta.servicio.nombre = 'Cambio de bujías'
        oferta.repuestos_seleccionados = [
            {
                'nombre': 'Bujías (Juego de 4)',
                'marca_repuesto': 'Genérico',
                'cantidad': 1,
                'precio_unitario_clp': 15_800,
            }
        ]

        mano, reps = _desglose_oferta_catalogo(oferta, con_repuestos=True)
        self.assertEqual(mano, 29_750)
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]['precio_unitario_clp'], 18_802)
        self.assertEqual(reps[0]['fuente_marketplace'], 'catalogo')
        self.assertEqual(reps[0]['proveedor_nombre'], 'Catálogo del taller')
        self.assertEqual(mano + reps[0]['precio_unitario_clp'], 48_552)

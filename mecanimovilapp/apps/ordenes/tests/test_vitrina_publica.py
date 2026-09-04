import json

from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.opciones_repuesto import (
    proyectar_opciones_publicas,
)
from mecanimovilapp.apps.ordenes.services.vitrina_repuestos import (
    _PROHIBIDOS,
    _sanitizar,
    vitrina_tiene_contenido,
)


class VitrinaPublicaWhitelistTest(SimpleTestCase):
    def test_json_no_expone_internos(self):
        pubs = proyectar_opciones_publicas([
            {
                'id': 'op1',
                'nombre': 'Pastilla Bosch',
                'marca_repuesto': 'Bosch',
                'calidad': 'oem',
                'imagen_url': 'https://cdn.mecanimovil.cl/repuestos/og/abc.jpg',
                'precio_min_clp': 28000,
                'precio_max_clp': 34000,
                'tienda': 'NO',
                'dominio': 'autoplanet.cl',
                'url': 'https://autoplanet.cl/x',
                'proveedor_id': 9,
                'fuente': 'web',
                'precio_clp': 29900,
            }
        ])
        keys = set()
        for op in pubs:
            keys.update(op.keys())
        for word in ('tienda', 'dominio', 'url', 'proveedor', 'proveedor_id', 'precio_clp', 'fuente'):
            self.assertNotIn(word, keys)
        self.assertNotIn('autoplanet', json.dumps(pubs))

    def test_sanitizar_quita_claves_internas(self):
        raw = {
            'lineas': [{
                'nombre': 'Filtro',
                'tienda': 'X',
                'opciones': [{'id': 'a', 'marca_repuesto': 'Mann', 'url': 'http://x'}],
            }]
        }
        clean = _sanitizar(raw)
        blob = json.dumps(clean, ensure_ascii=False)
        for k in _PROHIBIDOS:
            self.assertNotIn(f'"{k}"', blob)

    def test_no_manda_vitrina_con_una_opcion(self):
        self.assertFalse(vitrina_tiene_contenido([
            {'opciones': [{'id': 'a', 'posicion_relativa': 'unica'}]},
        ]))
        self.assertTrue(vitrina_tiene_contenido([
            {'opciones': [{'id': 'a'}, {'id': 'b'}]},
        ]))

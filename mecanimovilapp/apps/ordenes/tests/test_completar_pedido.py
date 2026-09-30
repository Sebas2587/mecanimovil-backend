"""Un kit de embrague trae la faena y las piezas del cambio."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.completar_pedido import (
    completar_pedido_con_faena,
)


class CompletarPedidoEmbragueTests(SimpleTestCase):
    def test_el_kit_se_cotiza_entero_con_la_faena(self):
        contenido = completar_pedido_con_faena(
            {
                'servicio_nombre': 'Kit de embrague',
                'mano_obra_clp': 180000,
                'repuestos': [
                    {'nombre': 'Disco de embrague', 'cantidad': 1, 'precio_unitario_clp': 0},
                    {'nombre': 'Prensa de embrague', 'cantidad': 1, 'precio_unitario_clp': 0},
                    {'nombre': 'Rodamiento de empuje', 'cantidad': 1, 'precio_unitario_clp': 0},
                ],
                'servicios_lineas': [],
            },
            servicio_nombre='Kit de embrague',
        )
        nombres = [rep['nombre'] for rep in contenido['repuestos']]
        self.assertIn('Kit de embrague', nombres)
        self.assertNotIn('Disco de embrague', nombres)
        self.assertNotIn('Prensa de embrague', nombres)
        self.assertIn('Aceite de caja de cambios', nombres)
        self.assertIn('disco', contenido['repuestos'][0]['comentario'].lower())
        self.assertEqual(contenido['servicios_lineas'][0]['nombre'], 'Cambio de embrague')
        self.assertEqual(contenido['servicios_lineas'][0]['monto_clp'], 180000)

    def test_no_duplica_si_el_kit_ya_esta(self):
        contenido = completar_pedido_con_faena(
            {
                'servicio_nombre': 'Cambio de embrague',
                'mano_obra_clp': 90000,
                'repuestos': [
                    {'nombre': 'Kit de embrague', 'cantidad': 1, 'precio_unitario_clp': 0},
                    {'nombre': 'Aceite de caja', 'cantidad': 1, 'precio_unitario_clp': 0},
                ],
                'servicios_lineas': [{'nombre': 'Cambio de embrague', 'monto_clp': 90000}],
            },
            servicio_nombre='Cambio de embrague',
        )
        self.assertEqual(len(contenido['repuestos']), 2)
        self.assertEqual(len(contenido['servicios_lineas']), 1)

    def test_otro_servicio_no_se_parte(self):
        original = {
            'servicio_nombre': 'Cambio de aceite',
            'repuestos': [{'nombre': 'Aceite de motor', 'cantidad': 1, 'precio_unitario_clp': 0}],
            'servicios_lineas': [{'nombre': 'Cambio de aceite', 'monto_clp': 25000}],
        }
        contenido = completar_pedido_con_faena(original, servicio_nombre='Cambio de aceite')
        self.assertEqual(
            [rep['nombre'] for rep in contenido['repuestos']],
            ['Aceite de motor'],
        )
        self.assertEqual(contenido['servicios_lineas'][0]['nombre'], 'Cambio de aceite')

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
        self.assertIn('Rodamiento de volante', nombres)
        self.assertIn('Retén trasero de cigüeñal', nombres)
        self.assertNotIn('Piola de embrague', nombres)
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
        nombres = [rep['nombre'] for rep in contenido['repuestos']]
        self.assertEqual(nombres.count('Kit de embrague'), 1)
        self.assertEqual(sum(1 for n in nombres if 'aceite' in n.lower()), 1)
        self.assertIn('Rodamiento de volante', nombres)
        self.assertIn('Retén trasero de cigüeñal', nombres)
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


class PedidoEmbragueCompletoTests(SimpleTestCase):
    PEDIDO = (
        'servicio para cambio de embrague completo, cambio de piola de embrague '
        'tambien y rodamiento de volante'
    )

    def test_piola_es_repuesto_y_la_faena_es_una(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            normalizar_cotizacion_ia,
        )

        out = normalizar_cotizacion_ia(
            {
                'servicio_nombre': self.PEDIDO,
                'mano_obra_clp': 160000,
                'servicios_lineas': [
                    {'nombre': 'Cambio de embrague completo', 'monto_clp': 120000},
                    {'nombre': 'Cambio de piola de embrague', 'monto_clp': 40000},
                ],
                'repuestos': [
                    {'nombre': 'Embrague completo', 'precio_unitario_clp': 0},
                ],
            },
            {'servicio_nombre': self.PEDIDO},
        )
        out = completar_pedido_con_faena(out, servicio_nombre=self.PEDIDO)
        nombres = [rep['nombre'] for rep in out['repuestos']]
        self.assertIn('Kit de embrague', nombres)
        self.assertIn('Piola de embrague', nombres)
        self.assertIn('Rodamiento de volante', nombres)
        self.assertIn('Aceite de caja de cambios', nombres)
        self.assertIn('Retén trasero de cigüeñal', nombres)
        self.assertNotIn('Embrague completo', nombres)
        self.assertEqual(
            [(lin['nombre'], lin['monto_clp']) for lin in out['servicios_lineas']],
            [('Cambio de embrague', 160000)],
        )
        self.assertEqual(out['mano_obra_clp'], 160000)

    def test_rodamiento_no_hereda_tipo_de_aceite(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.familias_sensibles import (
            anotar_familia_en_linea,
            detectar_familia_sensible,
        )

        self.assertIsNone(detectar_familia_sensible('Rodamiento de volante'))
        self.assertIsNone(detectar_familia_sensible('Aceite de caja de cambios'))
        self.assertIsNone(detectar_familia_sensible('Piola de embrague'))
        linea = anotar_familia_en_linea({
            'nombre': 'Rodamiento de volante',
            'familia_sensible': 'aceite_motor',
            'especificacion_pendiente': True,
        })
        self.assertNotIn('familia_sensible', linea)


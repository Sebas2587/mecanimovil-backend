"""El cotizador distingue piezas que comparten una palabra.

Kit, bomba y cilindro de embrague no son el mismo ítem. Una ficha de kit no
les pone su precio. La tienda del enlace no se cambia por la casa sugerida.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
    _ficha_cubre_pieza,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.completar_pedido import (
    completar_pedido_con_faena,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
    comprender_pedido,
    validar_comprension,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    aplicar_margen_taller,
    economia_repuesto,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
    linea_visible_cliente,
    proponer_complementos,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
    validar_repuesto,
)

PEDIDO = (
    'Renault Oroch 1.6 2019, patente LCKS16: cambio de kit de embrague, '
    'bomba de embrague, cilindro (bombín) de embrague, cambio de líquido de frenos, '
    'purgar sistema hidráulico, aceite de caja'
)
VEHICULO = {'marca': 'Renault', 'modelo': 'Oroch', 'anio': 2019, 'motor': '1.6'}
PRECIO_KIT = 89000
URL_KIT = 'https://www.imaparts.cl/kit-embrague-oroch'


def _borrador_con_precio_copiado():
    return {
        'servicio_nombre': PEDIDO,
        'descripcion_problema': PEDIDO,
        'mano_obra_clp': 180000,
        'servicios_lineas': [{'nombre': 'Cambio de embrague', 'monto_clp': 180000}],
        'repuestos': [
            {
                'nombre': 'Kit de embrague',
                'cantidad': 1,
                'precio_unitario_clp': PRECIO_KIT,
                'url_producto': URL_KIT,
                'nombre_producto': 'Kit de embrague Renault Oroch disco prensa y rodamiento',
                'proveedor_nombre': 'Adriazola',
            },
            {
                'nombre': 'Bomba de embrague',
                'cantidad': 1,
                'precio_unitario_clp': PRECIO_KIT,
                'url_producto': URL_KIT,
                'nombre_producto': 'Kit de embrague Renault Oroch disco prensa y rodamiento',
                'proveedor_nombre': 'Adriazola',
            },
            {
                'nombre': 'Cilindro de embrague',
                'cantidad': 1,
                'precio_unitario_clp': PRECIO_KIT,
                'url_producto': URL_KIT,
                'nombre_producto': 'Kit de embrague Renault Oroch disco prensa y rodamiento',
                'proveedor_nombre': 'Adriazola',
            },
            {
                'nombre': 'Sistema hidráulico de frenos para Renault Oroch 1.6 2019',
                'cantidad': 1,
                'precio_unitario_clp': 15000,
            },
        ],
        'vehiculo': VEHICULO,
    }


class ComprensionLCKS16Tests(SimpleTestCase):
    def test_schema_rechaza_identidad_repetida_o_desconocida(self):
        valido = validar_comprension({
            'items': [
                {'identidad': 'kit_embrague', 'rol': 'repuesto', 'nombre': 'Kit de embrague'},
                {'identidad': 'bomba_embrague', 'rol': 'repuesto', 'nombre': 'Bomba de embrague'},
                {'identidad': 'cilindro_receptor_embrague', 'rol': 'repuesto', 'nombre': 'Cilindro de embrague'},
            ],
            'faenas': ['Cambio de embrague'],
            'dudas': [],
        })
        self.assertEqual(
            [item['identidad'] for item in valido['items']],
            ['kit_embrague', 'bomba_embrague', 'cilindro_receptor_embrague'],
        )
        with self.assertRaises(ValueError):
            validar_comprension({
                'items': [
                    {'identidad': 'kit_embrague', 'rol': 'repuesto', 'nombre': 'Kit'},
                    {'identidad': 'kit_embrague', 'rol': 'repuesto', 'nombre': 'Otra vez el kit'},
                ],
            })
        with self.assertRaises(ValueError):
            validar_comprension({
                'items': [{'identidad': 'embrague_generico', 'rol': 'repuesto', 'nombre': 'Embrague'}],
            })

    def test_el_modelo_no_se_llama_si_no_hay_respuesta(self):
        """La taxonomía cubre el pedido. No abre una llamada nueva al modelo."""
        leido = comprender_pedido(PEDIDO, VEHICULO)
        self.assertEqual(
            [item['identidad'] for item in leido['items']],
            [
                'kit_embrague', 'bomba_embrague', 'cilindro_receptor_embrague',
                'liquido_frenos', 'aceite_caja',
            ],
        )
        self.assertNotIn('sistema', ' '.join(item['nombre'] for item in leido['items']).lower())

    def test_lcks16_separa_precios_y_no_cotiza_el_sistema(self):
        out = completar_pedido_con_faena(_borrador_con_precio_copiado(), PEDIDO, vehiculo=VEHICULO)
        lineas = {rep['nombre']: rep for rep in out['repuestos']}
        self.assertEqual(lineas['Kit de embrague']['precio_unitario_clp'], PRECIO_KIT)
        self.assertEqual(lineas['Kit de embrague']['url_producto'], URL_KIT)
        self.assertEqual(lineas['Bomba de embrague']['precio_unitario_clp'], 0)
        self.assertEqual(lineas['Cilindro de embrague']['precio_unitario_clp'], 0)
        self.assertNotEqual(lineas['Bomba de embrague'].get('url_producto'), URL_KIT)
        self.assertNotIn('Sistema hidráulico de frenos para Renault Oroch 1.6 2019', lineas)
        aceite = lineas['Aceite de caja de cambios']
        self.assertIn('75W-80', aceite['especificacion'])
        self.assertIn('2.5', aceite['especificacion'])
        self.assertIn('DOT4', lineas['Líquido de frenos']['especificacion'])
        faenas = [lin['nombre'] for lin in out['servicios_lineas']]
        self.assertIn('Cambio de embrague', faenas)
        self.assertIn('Cambio de bomba de embrague', faenas)
        self.assertIn('Cambio de cilindro de embrague', faenas)
        self.assertIn('Purga del sistema hidráulico', faenas)
        self.assertIn('Cambio de aceite de caja', faenas)
        self.assertEqual(len(faenas), len(set(faenas)))
        ids = {duda['id'] for duda in out['dudas']}
        self.assertTrue(any(i.startswith('precio-copiado-') for i in ids))

    def test_la_ficha_de_kit_no_cubre_bomba_ni_cilindro(self):
        ficha = 'Kit de embrague Renault Oroch disco prensa y rodamiento'
        self.assertTrue(_ficha_cubre_pieza('Kit de embrague', ficha))
        self.assertFalse(_ficha_cubre_pieza('Bomba de embrague', ficha))
        self.assertFalse(_ficha_cubre_pieza('Cilindro de embrague', ficha))
        self.assertTrue(_ficha_cubre_pieza(
            'Bomba de embrague', 'Bomba de embrague Renault Oroch',
        ))

    def test_kit_con_rodamiento_no_sugiere_otro(self):
        out = completar_pedido_con_faena(
            {
                'repuestos': [{
                    'nombre': 'Kit de embrague',
                    'cantidad': 1,
                    'precio_unitario_clp': PRECIO_KIT,
                    'nombre_producto': 'Kit embrague disco, prensa y rodamiento de empuje',
                }],
            },
            'cambio de kit de embrague',
        )
        nombres = [rep['nombre'] for rep in out['repuestos']]
        self.assertNotIn('Rodamiento de volante', nombres)
        self.assertNotIn('kit-composicion', {d['id'] for d in out['dudas']})

    def test_kit_sin_ficha_deja_duda_y_no_agrega_rodamiento(self):
        out = completar_pedido_con_faena(
            {'repuestos': [{'nombre': 'Kit de embrague', 'cantidad': 1, 'precio_unitario_clp': 0}]},
            'cambio de kit de embrague',
        )
        self.assertNotIn('Rodamiento de volante', [rep['nombre'] for rep in out['repuestos']])
        self.assertIn('kit-composicion', {d['id'] for d in out['dudas']})

    def test_ficha_que_excluye_el_piloto_lo_sugiere_pendiente(self):
        out = completar_pedido_con_faena(
            {'repuestos': [{
                'nombre': 'Kit de embrague',
                'cantidad': 1,
                'precio_unitario_clp': PRECIO_KIT,
                'nombre_producto': 'Kit embrague disco y prensa, sin piloto',
            }]},
            'cambio de kit de embrague',
        )
        piloto = next(rep for rep in out['repuestos'] if rep['nombre'] == 'Rodamiento de volante')
        self.assertEqual(piloto['origen'], 'sugerencia')
        self.assertEqual(piloto['estado_sugerencia'], 'pendiente')

    def test_precio_asumido_lleva_margen_y_queda_estimado(self):
        linea = {
            'nombre': 'Bomba de embrague',
            'cantidad': 1,
            'precio_unitario_clp': 10000,
            'certeza': 'asumido',
            'origen': 'pedido',
            'estado_sugerencia': 'aceptada',
        }
        aplicar_margen_taller(linea, SimpleNamespace(margen_ganancia_pct=20))
        self.assertEqual(linea['costo_estimado_clp'], 10000)
        self.assertEqual(linea['precio_unitario_clp'], 12000)
        self.assertTrue(linea['precio_estimado'])
        self.assertTrue(linea['ganancia_estimada'])
        economia = economia_repuesto(linea)
        self.assertEqual(economia['costo_origen'], 'estimado')
        self.assertTrue(economia['ganancia_estimada'])
        self.assertEqual(economia['margen_clp'], 2000)
        out = completar_pedido_con_faena(
            {'repuestos': [linea], 'mano_obra_clp': 0, 'servicios_lineas': []},
            'bomba de embrague',
        )
        ids = {duda['id'] for duda in out['dudas']}
        self.assertTrue(any(i.startswith('precio-estimado-') for i in ids))

    def test_imaparts_no_se_rotula_como_adriazola(self):
        linea = {
            'nombre': 'Kit de embrague',
            'cantidad': 1,
            'precio_unitario_clp': PRECIO_KIT,
            'url_producto': URL_KIT,
            'proveedor_nombre': 'Adriazola',
            'tienda_ml': 'Adriazola',
            'nombre_producto': 'Kit de embrague Renault Oroch',
        }
        ficha = validar_repuesto(linea, marca='Renault', modelo='Oroch', anio=2019)
        self.assertEqual(linea['proveedor_nombre'].casefold(), 'imaparts')
        self.assertEqual(ficha['casa_sugerida'], 'Adriazola')
        self.assertNotEqual(str(ficha.get('tienda_referencia') or '').casefold(), 'adriazola')
        self.assertIn('no verificado en Adriazola', ficha['nota_referencia'])
        self.assertFalse(ficha['precio_verificado_en_casa'])

    def test_los_tres_caminos_dejan_las_piezas_distintas(self):
        generado = completar_pedido_con_faena(
            _borrador_con_precio_copiado(), PEDIDO, vehiculo=VEHICULO,
        )
        manual, dudas = proponer_complementos(
            _borrador_con_precio_copiado()['repuestos'],
            PEDIDO,
            vehiculo=VEHICULO,
        )
        agente = [rep for rep in generado['repuestos'] if linea_visible_cliente(rep)]

        def precios(reps):
            return {
                rep['nombre']: (rep.get('identidad'), rep.get('precio_unitario_clp'))
                for rep in reps
            }

        for camino in (generado['repuestos'], manual, agente):
            visto = precios(camino)
            self.assertEqual(visto['Kit de embrague'][0], 'kit_embrague')
            self.assertEqual(visto['Bomba de embrague'][0], 'bomba_embrague')
            self.assertEqual(visto['Cilindro de embrague'][0], 'cilindro_receptor_embrague')
            self.assertNotEqual(visto['Kit de embrague'][1], visto['Bomba de embrague'][1])
            self.assertNotIn(
                'Sistema hidráulico de frenos para Renault Oroch 1.6 2019',
                visto,
            )
        self.assertTrue(any(d['id'].startswith('precio-copiado-') for d in dudas))
        self.assertTrue(all(linea_visible_cliente(rep) for rep in agente))

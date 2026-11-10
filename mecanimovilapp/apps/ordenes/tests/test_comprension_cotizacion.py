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


def _ficha(titulo, url, precio):
    return {
        'title': titulo,
        'url': url,
        'content': f'{titulo}\nPrecio: ${precio}',
    }


_CATALOGO_OROCH = [
    _ficha(
        'Kit de embrague Renault Oroch 2019',
        'https://www.imaparts.cl/kit-embrague-oroch',
        '89.000',
    ),
    _ficha(
        'Bomba de embrague Renault Oroch 2019',
        'https://www.sergioescobar.cl/bomba-embrague-oroch',
        '28.990',
    ),
    _ficha(
        'Cilindro de embrague Renault Oroch 2019',
        'https://www.todoauto.cl/cilindro-embrague-oroch',
        '18.990',
    ),
    _ficha(
        'Aceite de motor 5W30 4 litros',
        'https://www.imaparts.cl/aceite-motor-5w30',
        '32.000',
    ),
    _ficha(
        'Aceite de caja 75W-80 1 litro',
        'https://www.todoauto.cl/aceite-caja-75w80-1l',
        '8.990',
    ),
    _ficha(
        'Liquido de frenos DOT3 500 ml',
        'https://www.imaparts.cl/liquido-dot3',
        '4.990',
    ),
    _ficha(
        'Liquido de frenos DOT4 500 ml',
        'https://www.sergioescobar.cl/liquido-dot4-500',
        '6.990',
    ),
]


class PreciosPropiosTests(SimpleTestCase):
    """Cada identidad sale con su ficha. El 0 solo aparece si ninguna tienda la tiene."""

    def _buscar(self, nombres, catalogo, especificaciones=None):
        from unittest.mock import patch

        from django.test.utils import override_settings

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import (
            busqueda_web_repuestos as bw,
        )

        def fake(_query, _whitelist):
            return [dict(cand) for cand in catalogo]

        with override_settings(TAVILY_API_KEY='tvly-test', GEMINI_API_KEY='k'), patch.object(
            bw, '_candidatos_validos', side_effect=fake,
        ), patch.object(
            bw, '_leer_html_fichas', return_value={},
        ), patch.object(
            bw, '_tavily_extraer', return_value=[],
        ), patch.object(
            bw, '_gemini_generar', return_value=None,
        ):
            hits = bw._buscar_repuestos_web_tavily(
                nombres,
                marca='Renault',
                modelo='Oroch',
                anio=2019,
                cilindraje='',
                tipo_motor='',
                servicio_nombre='embrague',
                timeout=5,
                especificaciones=especificaciones or {},
            )
        return {hit['nombre_buscado']: hit for hit in hits.values()}

    def test_kit_bomba_y_cilindro_tienen_precio_y_tienda_propios(self):
        hits = self._buscar(
            ['Kit de embrague', 'Bomba de embrague', 'Cilindro de embrague'],
            _CATALOGO_OROCH,
        )
        self.assertEqual(set(hits), {
            'Kit de embrague', 'Bomba de embrague', 'Cilindro de embrague',
        })
        precios = {nombre: hit['precio_clp'] for nombre, hit in hits.items()}
        urls = {nombre: hit['url'] for nombre, hit in hits.items()}
        self.assertEqual(len(set(precios.values())), 3)
        self.assertEqual(len(set(urls.values())), 3)
        self.assertEqual(precios['Kit de embrague'], 89000)
        self.assertEqual(precios['Bomba de embrague'], 28990)
        self.assertEqual(precios['Cilindro de embrague'], 18990)
        for nombre, hit in hits.items():
            host = hit['url'].split('/')[2].removeprefix('www.')
            self.assertIn(host.split('.')[0].replace('-', ''), hit['tienda'].casefold().replace(' ', ''))
            self.assertNotEqual(hit['url'], urls['Kit de embrague'] if nombre != 'Kit de embrague' else '')

    def test_sin_ficha_propia_el_cero_es_el_ultimo_recurso(self):
        solo_kit = _CATALOGO_OROCH[:1]
        hits = self._buscar(
            ['Kit de embrague', 'Bomba de embrague', 'Cilindro de embrague'],
            solo_kit,
        )
        self.assertEqual(hits['Kit de embrague']['precio_clp'], 89000)
        self.assertNotIn('Bomba de embrague', hits)
        self.assertNotIn('Cilindro de embrague', hits)

    def test_aceite_de_caja_y_dot4_cotizan_el_envase_y_la_cantidad(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            aplicar_cantidad_envase,
            precio_unitario_desde_envase,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.razonar_pedido import (
            planificar,
        )

        plan = planificar(PEDIDO, VEHICULO, descripcion=PEDIDO, usar_llm=False)
        consultas = ' '.join(p['consulta'] for p in plan['piezas']).lower()
        self.assertIn('75w-80', consultas.replace(' ', ''))
        self.assertIn('dot4', consultas.replace(' ', ''))
        nombres = [p['nombre'] for p in plan['piezas']]
        self.assertIn('Bomba de embrague', nombres)
        self.assertIn('Cilindro de embrague', nombres)
        self.assertIn('Aceite de caja de cambios', nombres)

        hits = self._buscar(
            ['Aceite de caja de cambios', 'Líquido de frenos'],
            _CATALOGO_OROCH,
            especificaciones={
                'Aceite de caja de cambios': '75W-80 · 2.5 L',
                'Líquido de frenos': 'DOT4',
            },
        )
        aceite = hits['Aceite de caja de cambios']
        liquido = hits['Líquido de frenos']
        self.assertIn('75w-80', aceite['nombre_producto'].lower())
        self.assertIn('dot4', liquido['nombre_producto'].lower())
        self.assertNotEqual(aceite['url'], liquido['url'])
        unitario, nota = precio_unitario_desde_envase(
            'Aceite de caja de cambios', 8990, aceite['nombre_producto'],
        )
        self.assertEqual(unitario, 8990)
        self.assertEqual(nota, '')
        linea_aceite = aplicar_cantidad_envase(
            {
                'nombre': 'Aceite de caja de cambios',
                'identidad': 'aceite_caja',
                'nombre_producto': aceite['nombre_producto'],
                'precio_unitario_clp': unitario,
                'especificacion': '75W-80 · 2.5 L',
            },
            marca='Renault',
            modelo='Oroch',
        )
        self.assertEqual(linea_aceite['cantidad'], 3)
        self.assertEqual(linea_aceite['precio_unitario_clp'], 8990)
        linea_dot = aplicar_cantidad_envase(
            {
                'nombre': 'Líquido de frenos',
                'identidad': 'liquido_frenos',
                'nombre_producto': liquido['nombre_producto'],
                'precio_unitario_clp': liquido['precio_clp'],
                'especificacion': 'DOT4',
            },
            marca='Renault',
            modelo='Oroch',
        )
        self.assertEqual(linea_dot['cantidad'], 2)
        self.assertEqual(linea_dot['precio_unitario_clp'], 6990)
        bidon = aplicar_cantidad_envase(
            {
                'nombre': 'Aceite de caja de cambios',
                'identidad': 'aceite_caja',
                'nombre_producto': 'Aceite de caja 75W-80 4 litros',
                'precio_unitario_clp': 22000,
            },
            marca='Renault',
            modelo='Oroch',
        )
        self.assertEqual(bidon['cantidad'], 1)
        self.assertEqual(bidon['precio_unitario_clp'], 22000)

    def test_lo_que_no_esta_en_la_taxonomia_no_se_fusiona_ni_se_tira(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            comprension_desde_pedido,
            comprender_pedido,
        )

        pedido = SimpleNamespace(
            repuestos_mencionados=[
                SimpleNamespace(nombre='flexible de embrague'),
                SimpleNamespace(nombre='horquilla'),
                SimpleNamespace(nombre='piloto'),
                SimpleNamespace(nombre='sensor de detonación'),
            ],
            servicios=[],
        )
        validado = comprension_desde_pedido(pedido)
        por_id = {item['identidad']: item['nombre'] for item in validado['items'] if item['identidad'] != 'sin_clasificar'}
        self.assertEqual(por_id['flexible_embrague'], 'Flexible de embrague')
        self.assertEqual(por_id['horquilla_embrague'], 'Horquilla de embrague')
        self.assertEqual(por_id['rodamiento_piloto'], 'Rodamiento de volante')
        self.assertNotIn('kit_embrague', por_id)
        sueltos = [item['nombre'] for item in validado['items'] if item['identidad'] == 'sin_clasificar']
        self.assertTrue(any('sensor' in nombre.lower() for nombre in sueltos))
        self.assertTrue(any(duda['id'].startswith('pieza-') for duda in validado['dudas']))

        crudo = comprender_pedido(
            'cambio de kit de embrague, flexible de embrague, horquilla, piloto',
        )
        ids = [item['identidad'] for item in crudo['items']]
        self.assertEqual(ids.count('kit_embrague'), 1)
        self.assertIn('flexible_embrague', ids)
        self.assertIn('horquilla_embrague', ids)
        self.assertIn('rodamiento_piloto', ids)

    def test_el_agente_no_muestra_un_estimado_ni_una_duda(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
            resumen_para_cliente,
        )
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            formatear_resumen_cotizacion,
        )

        cot = SimpleNamespace(
            servicio_nombre='Embrague',
            modalidad='taller',
            vehiculo_marca='Renault',
            vehiculo_modelo='Oroch',
            vehiculo_anio=2019,
            vehiculo_patente='LCKS16',
            vehiculo_cilindraje='1.6',
            tipo_motor_label='',
            descripcion_problema='',
            repuestos=[{
                'nombre': 'Bomba de embrague',
                'cantidad': 1,
                'precio_unitario_clp': 10000,
                'precio_estimado': True,
                'certeza': 'asumido',
                'origen': 'pedido',
                'estado_sugerencia': 'aceptada',
            }],
            costo_repuestos_clp=10000,
            mano_obra_clp=0,
            total_clp=12000,
            duracion_minutos_estimada=60,
            advertencias=[],
            metadata={
                'dudas': [{
                    'id': 'precio-estimado-bomba',
                    'texto': 'El precio es estimado secreto',
                    'confirmada': False,
                }],
            },
            url_publica='',
            tipo_documento='',
            descuento_clp=0,
        )
        texto = formatear_resumen_cotizacion(cot)
        self.assertIn('precio por confirmar', texto)
        self.assertIn('Total por confirmar', texto)
        self.assertNotIn('10.000', texto)
        self.assertNotIn('12.000', texto)
        self.assertNotIn('estimado secreto', texto)
        resumen = resumen_para_cliente(cot)
        self.assertIn('No des un precio cerrado', resumen)
        self.assertNotIn('10000', resumen)
        self.assertNotIn('secreto', resumen)


class ConsolidacionTiendaTests(SimpleTestCase):
    """Una tienda que tiene el pedido se queda con las piezas, salvo falta o precio."""

    def _buscar(self, nombres, catalogo, especificaciones=None):
        from unittest.mock import patch

        from django.test.utils import override_settings

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import (
            busqueda_web_repuestos as bw,
        )

        def fake(_query, _whitelist):
            return [dict(cand) for cand in catalogo]

        with override_settings(TAVILY_API_KEY='tvly-test', GEMINI_API_KEY='k'), patch.object(
            bw, '_candidatos_validos', side_effect=fake,
        ), patch.object(
            bw, '_leer_html_fichas', return_value={},
        ), patch.object(
            bw, '_tavily_extraer', return_value=[],
        ), patch.object(
            bw, '_gemini_generar', return_value=None,
        ):
            return bw._buscar_repuestos_web_tavily(
                nombres,
                marca='Renault',
                modelo='Oroch',
                anio=2019,
                cilindraje='2.0',
                tipo_motor='',
                servicio_nombre='Cambio de kit de embrague',
                timeout=5,
                especificaciones=especificaciones or {},
            )

    def test_una_tienda_con_todo_se_queda_el_pedido(self):
        catalogo = [
            {
                'url': 'https://www.tiendaunica.cl/kit-oroch',
                'title': 'Kit de embrague Renault Oroch 2019',
                'content': 'Precio: $89.000',
            },
            {
                'url': 'https://www.barata.cl/bomba-oroch',
                'title': 'Bomba de embrague Renault Oroch 2019',
                'content': 'Precio: $27.500',
            },
            {
                'url': 'https://www.tiendaunica.cl/bomba-oroch',
                'title': 'Bomba de embrague Renault Oroch 2019',
                'content': 'Precio: $28.990',
            },
            {
                'url': 'https://www.tiendaunica.cl/cilindro-oroch',
                'title': 'Cilindro receptor de embrague Renault Oroch 2019',
                'content': 'Precio: $18.990',
            },
            {
                'url': 'https://www.tiendaunica.cl/aceite-caja',
                'title': 'Aceite de caja 75W-80 1 litro',
                'content': 'Precio: $8.990',
            },
        ]
        hits = self._buscar(
            ['Kit de embrague', 'Bomba de embrague', 'Cilindro receptor de embrague', 'Aceite de caja'],
            catalogo,
            {'Aceite de caja': '75W-80'},
        )
        urls = [hits[clave]['url'] for clave in hits]
        self.assertEqual(len(urls), 4)
        self.assertTrue(all('tiendaunica.cl' in url for url in urls))
        self.assertFalse(any(hit.get('motivo_tienda') for hit in hits.values()))

    def test_la_pieza_que_falta_va_a_otra_tienda_con_motivo(self):
        catalogo = [
            {
                'url': 'https://www.tiendaunica.cl/kit-oroch',
                'title': 'Kit de embrague Renault Oroch 2019',
                'content': 'Precio: $89.000',
            },
            {
                'url': 'https://www.barata.cl/bomba-oroch',
                'title': 'Bomba de embrague Renault Oroch 2019',
                'content': 'Precio: $28.990',
            },
            {
                'url': 'https://www.tiendaunica.cl/cilindro-oroch',
                'title': 'Cilindro receptor de embrague Renault Oroch 2019',
                'content': 'Precio: $18.990',
            },
            {
                'url': 'https://www.tiendaunica.cl/aceite-caja',
                'title': 'Aceite de caja 75W-80 1 litro',
                'content': 'Precio: $8.990',
            },
        ]
        hits = self._buscar(
            ['Kit de embrague', 'Bomba de embrague', 'Cilindro receptor de embrague', 'Aceite de caja'],
            catalogo,
            {'Aceite de caja': '75W-80'},
        )
        bomba = next(hit for hit in hits.values() if 'bomba' in hit['url'])
        self.assertIn('barata.cl', bomba['url'])
        self.assertIn('no disponible en', bomba.get('motivo_tienda', '').lower())
        self.assertIn('tiendaunica', bomba['motivo_tienda'].lower())

    def test_una_pieza_mucho_mas_barata_cambia_de_tienda_con_motivo(self):
        catalogo = [
            {
                'url': 'https://www.tiendaunica.cl/kit-oroch',
                'title': 'Kit de embrague Renault Oroch 2019',
                'content': 'Precio: $89.000',
            },
            {
                'url': 'https://www.tiendaunica.cl/bomba-oroch',
                'title': 'Bomba de embrague Renault Oroch 2019',
                'content': 'Precio: $40.000',
            },
            {
                'url': 'https://www.barata.cl/bomba-oroch',
                'title': 'Bomba de embrague Renault Oroch 2019',
                'content': 'Precio: $10.000',
            },
            {
                'url': 'https://www.tiendaunica.cl/cilindro-oroch',
                'title': 'Cilindro receptor de embrague Renault Oroch 2019',
                'content': 'Precio: $18.990',
            },
            {
                'url': 'https://www.tiendaunica.cl/aceite-caja',
                'title': 'Aceite de caja 75W-80 1 litro',
                'content': 'Precio: $8.990',
            },
        ]
        hits = self._buscar(
            ['Kit de embrague', 'Bomba de embrague', 'Cilindro receptor de embrague', 'Aceite de caja'],
            catalogo,
            {'Aceite de caja': '75W-80'},
        )
        bomba = next(hit for hit in hits.values() if 'bomba' in hit['nombre_producto'].lower())
        self.assertIn('barata.cl', bomba['url'])
        motivo = bomba.get('motivo_tienda', '')
        self.assertIn('más barato', motivo.lower())
        porcentaje = int(motivo.split('%', 1)[0])
        self.assertGreaterEqual(porcentaje, 25)
        resto = [hit for hit in hits.values() if hit is not bomba]
        self.assertTrue(all('tiendaunica.cl' in hit['url'] for hit in resto))

    def test_una_bomba_incompatible_no_se_consolida(self):
        catalogo = [
            {
                'url': 'https://www.tiendaunica.cl/kit-oroch',
                'title': 'Kit de embrague Renault Oroch 2019',
                'content': 'Precio: $89.000',
            },
            {
                'url': 'https://www.tiendaunica.cl/bomba-duster',
                'title': 'Bomba de embrague Renault Duster 2019',
                'content': 'Precio: $25.000',
            },
            {
                'url': 'https://www.barata.cl/bomba-oroch',
                'title': 'Bomba de embrague Renault Oroch 2019',
                'content': 'Precio: $28.990',
            },
            {
                'url': 'https://www.tiendaunica.cl/cilindro-oroch',
                'title': 'Cilindro receptor de embrague Renault Oroch 2019',
                'content': 'Precio: $18.990',
            },
            {
                'url': 'https://www.tiendaunica.cl/aceite-caja',
                'title': 'Aceite de caja 75W-80 1 litro',
                'content': 'Precio: $8.990',
            },
        ]
        hits = self._buscar(
            ['Kit de embrague', 'Bomba de embrague', 'Cilindro receptor de embrague', 'Aceite de caja'],
            catalogo,
            {'Aceite de caja': '75W-80'},
        )
        bomba = next(hit for hit in hits.values() if 'bomba' in hit['nombre_producto'].lower())
        self.assertNotIn('duster', bomba['url'])
        self.assertIn('oroch', bomba['nombre_producto'].lower())
        self.assertIn('no disponible en', bomba.get('motivo_tienda', '').lower())

    def test_la_especialista_se_queda_el_pedido_si_la_diferencia_es_chica(self):
        def ficha(host, slug, titulo, precio):
            return {
                'url': f'https://www.{host}/{slug}',
                'title': titulo,
                'content': f'Precio: ${precio}',
            }

        barata = [
            ficha('tiendaunica.cl', 'kit-oroch', 'Kit de embrague Renault Oroch 2019', '85.000'),
            ficha('tiendaunica.cl', 'bomba-oroch', 'Bomba de embrague Renault Oroch 2019', '27.000'),
            ficha('tiendaunica.cl', 'cilindro-oroch', 'Cilindro receptor de embrague Renault Oroch 2019', '18.000'),
            ficha('tiendaunica.cl', 'aceite-caja', 'Aceite de caja 75W-80 1 litro', '8.500'),
        ]
        especialista = [
            ficha('adriazolarepuestos.com', 'kit-oroch', 'Kit de embrague Renault Oroch 2019', '89.000'),
            ficha('adriazolarepuestos.com', 'bomba-oroch', 'Bomba de embrague Renault Oroch 2019', '28.990'),
            ficha('adriazolarepuestos.com', 'cilindro-oroch', 'Cilindro receptor de embrague Renault Oroch 2019', '18.990'),
            ficha('adriazolarepuestos.com', 'aceite-caja', 'Aceite de caja 75W-80 1 litro', '8.990'),
        ]
        hits = self._buscar(
            ['Kit de embrague', 'Bomba de embrague', 'Cilindro receptor de embrague', 'Aceite de caja'],
            barata + especialista,
            {'Aceite de caja': '75W-80'},
        )
        self.assertEqual(len(hits), 4)
        self.assertTrue(all('adriazolarepuestos.com' in hit['url'] for hit in hits.values()))


_EMBRAGUE = {
    'kit_embrague', 'bomba_embrague', 'cilindro_receptor_embrague',
    'flexible_embrague', 'horquilla_embrague', 'piola_embrague',
    'rodamiento_piloto', 'rodamiento_empuje', 'reten_ciguenal',
}

_CASOS_B2 = (
    'bombín de freno',
    'cilindro maestro de frenos',
    'piloto automático',
    'piola de acelerador',
    'horquilla de suspensión',
    'ruleman de rueda',
    'retén de rueda',
    'guaya de puerta',
)

_CASOS_B3 = (
    (
        'kit de embrague, bomba y cilindro (bombín)',
        {'kit_embrague', 'bomba_embrague', 'cilindro_receptor_embrague'},
    ),
    (
        'cambiar kit bomba cilindro de embrague',
        {'kit_embrague', 'bomba_embrague', 'cilindro_receptor_embrague'},
    ),
    ('kit de embrage', {'kit_embrague'}),
    ('collarín', {'rodamiento_empuje'}),
    ('crapodina', {'rodamiento_empuje'}),
)


def _item_llm(texto, identidad, rol='repuesto', sistema='embrague', confianza=0.9):
    return {
        'texto_original': texto,
        'rol': rol,
        'sistema': sistema,
        'identidad': identidad,
        'nombre': texto,
        'especificacion': '',
        'cantidad': '',
        'confianza': confianza,
    }


class RevisionIdentidadTests(SimpleTestCase):
    def test_marcadores_cortos_no_son_embrague_sin_el_modelo_y_con_fixture(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            comprender_pedido,
        )

        for texto in _CASOS_B2:
            caido = comprender_pedido(texto)
            ids = {item['identidad'] for item in caido['items']}
            self.assertFalse(ids & _EMBRAGUE, texto)
            self.assertTrue(caido['dudas'])
            mal = comprender_pedido(texto, respuesta_llm={
                'items': [_item_llm(texto, 'cilindro_receptor_embrague')],
                'faenas': [],
                'dudas': [],
            })
            self.assertFalse(
                {item['identidad'] for item in mal['items']} & _EMBRAGUE,
                texto,
            )
            self.assertTrue(mal['dudas'])

    def test_la_enumeracion_hereda_embrague_sin_el_modelo_y_con_fixture(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            comprender_pedido,
        )

        for texto, esperadas in _CASOS_B3:
            caido = {item['identidad'] for item in comprender_pedido(texto)['items']}
            self.assertEqual(caido, esperadas, texto)
            fixture = comprender_pedido(texto, respuesta_llm={
                'items': [_item_llm(texto, ident) for ident in sorted(esperadas)],
                'faenas': [],
                'dudas': [],
            })
            self.assertEqual({item['identidad'] for item in fixture['items']}, esperadas, texto)

    def test_una_lectura_vacia_no_inventa_otra_pieza(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            comprender_pedido,
            validar_comprension,
        )

        with self.assertRaises(ValueError):
            validar_comprension({})
        out = comprender_pedido('kit de embrague', respuesta_llm={})
        self.assertEqual([item['identidad'] for item in out['items']], ['kit_embrague'])
        self.assertTrue(any(duda['id'] == 'lectura-no-usable' for duda in out['dudas']))
        baja = comprender_pedido('kit de embrague', respuesta_llm={
            'items': [_item_llm('kit de embrague', 'bomba_embrague', confianza=0.2)],
            'faenas': [],
            'dudas': [],
        })
        self.assertEqual(baja['items'], [])
        self.assertTrue(baja['dudas'])

    def test_aceite_y_filtro_no_crea_una_linea_fantasma(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
            aplicar_pedido_y_sugerencias,
        )

        out = aplicar_pedido_y_sugerencias(
            {
                'servicio_nombre': 'Cambio de aceite y filtro',
                'repuestos': [
                    {'nombre': 'Aceite de motor', 'cantidad': 4, 'precio_unitario_clp': 8000},
                    {'nombre': 'Filtro de aceite', 'cantidad': 1, 'precio_unitario_clp': 5000},
                ],
            },
            servicio_nombre='Cambio de aceite y filtro',
        )
        self.assertEqual(
            [rep['nombre'] for rep in out['repuestos']],
            ['Aceite de motor', 'Filtro de aceite'],
        )

    def test_elige_el_envase_mas_barato_para_cubrir_los_litros(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            aplicar_cantidad_envase,
        )

        aceite = aplicar_cantidad_envase(
            {
                'nombre': 'Aceite de caja de cambios',
                'identidad': 'aceite_caja',
                'especificacion': '75W-80 · 2.5 L',
                'nombre_producto': 'Aceite de caja 75W-80 1 litro',
                'precio_unitario_clp': 8990,
                'candidatos_envase': [
                    {
                        'nombre_producto': 'Aceite de caja 75W-80 1 litro',
                        'precio_unitario_clp': 8990,
                        'url': 'https://www.tienda.cl/1l',
                    },
                    {
                        'nombre_producto': 'Aceite de caja 75W-80 4 litros',
                        'precio_unitario_clp': 22000,
                        'url': 'https://www.tienda.cl/4l',
                    },
                ],
            },
            marca='Renault',
            modelo='Oroch',
        )
        self.assertEqual(aceite['cantidad'], 1)
        self.assertEqual(aceite['precio_unitario_clp'], 22000)
        self.assertIn('4 litro', aceite['nombre_producto'].lower())
        self.assertEqual(aceite['costo_envases_clp'], 22000)
        dot = aplicar_cantidad_envase(
            {
                'nombre': 'Líquido de frenos',
                'identidad': 'liquido_frenos',
                'especificacion': 'DOT4',
                'nombre_producto': 'Liquido de frenos DOT4 500 ml',
                'precio_unitario_clp': 6990,
                'candidatos_envase': [
                    {
                        'nombre_producto': 'Liquido de frenos DOT4 500 ml',
                        'precio_unitario_clp': 6990,
                    },
                    {
                        'nombre_producto': 'Liquido de frenos DOT4 1 litro',
                        'precio_unitario_clp': 9000,
                    },
                ],
            },
            marca='Renault',
            modelo='Oroch',
        )
        self.assertEqual(dot['cantidad'], 1)
        self.assertEqual(dot['precio_unitario_clp'], 9000)

    def test_otro_auto_toma_la_spec_del_llm_y_la_tabla_queda_de_respaldo(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            comprender_pedido,
        )

        yaris = comprender_pedido(
            'aceite de caja',
            vehiculo={'marca': 'Toyota', 'modelo': 'Yaris', 'anio': 2018, 'motor': '1.5'},
            respuesta_llm={
                'items': [_item_llm('aceite de caja', 'aceite_caja', rol='insumo', sistema='transmision')],
                'fluidos': {
                    'aceite_caja': {
                        'especificacion': '75W-90',
                        'litros': '1.9',
                        'confianza': 0.8,
                    },
                },
                'faenas': [],
                'dudas': [],
            },
        )
        aceite = yaris['items'][0]
        self.assertIn('75W-90', aceite['especificacion'])
        self.assertIn('1.9', aceite['especificacion'])
        self.assertNotIn('75W-80', aceite['especificacion'])
        sin_modelo = comprender_pedido(
            'aceite de caja',
            vehiculo={'marca': 'Toyota', 'modelo': 'Yaris', 'anio': 2018},
        )
        self.assertNotIn('75W-80', sin_modelo['items'][0].get('especificacion', ''))
        oroch = comprender_pedido(
            'aceite de caja',
            vehiculo={'marca': 'Renault', 'modelo': 'Oroch', 'motor': '1.6'},
        )
        self.assertIn('75W-80', oroch['items'][0]['especificacion'])

    def test_sin_enlace_el_nombre_de_tienda_no_vuelve_el_costo_verificado(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _costo_sin_ficha,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
            _rotulo_es_el_dominio,
            _sellar_tienda_real,
        )

        self.assertTrue(_costo_sin_ficha({
            'proveedor_nombre': 'TodoAuto',
            'precio_unitario_clp': 10000,
        }))
        self.assertFalse(_rotulo_es_el_dominio('todo', 'todoauto.cl'))
        linea = {
            'proveedor_nombre': 'todo',
            'url_producto': 'https://www.todoauto.cl/aceite',
        }
        _sellar_tienda_real(linea)
        self.assertNotEqual(linea['proveedor_nombre'].casefold(), 'todo')

    def test_una_duda_no_esconde_el_monto_de_otra_cotizacion(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
            monto_para_agente,
        )

        firme = SimpleNamespace(total_clp=89000, repuestos=[], metadata={'dudas': []})
        dudosa = SimpleNamespace(
            total_clp=12000,
            repuestos=[],
            metadata={'dudas': [{'id': 'pieza-x', 'texto': 'duda', 'confirmada': False}]},
        )
        self.assertEqual(monto_para_agente(firme), '$89000')
        self.assertEqual(monto_para_agente(dudosa), 'por confirmar')

    def test_el_aceite_de_caja_queda_sugerido_si_el_kit_no_trae_piloto(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
            aplicar_pedido_y_sugerencias,
        )

        out = aplicar_pedido_y_sugerencias(
            {
                'servicio_nombre': 'Cambio de kit de embrague',
                'repuestos': [{
                    'nombre': 'Kit de embrague',
                    'cantidad': 1,
                    'precio_unitario_clp': 89000,
                    'nombre_producto': 'Kit de embrague sin piloto',
                    'origen': 'pedido',
                    'estado_sugerencia': 'aceptada',
                }],
            },
            servicio_nombre='Cambio de kit de embrague',
        )
        aceite = next(
            rep for rep in out['repuestos']
            if rep['nombre'] == 'Aceite de caja de cambios'
        )
        self.assertEqual(aceite['origen'], 'sugerencia')
        self.assertEqual(aceite['estado_sugerencia'], 'pendiente')
        self.assertIn('aceite', aceite['motivo_sugerencia'].lower())

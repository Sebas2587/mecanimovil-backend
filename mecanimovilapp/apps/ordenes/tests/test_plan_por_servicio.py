"""El cotizador lee el servicio, no la frase literal del cliente."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import (
    PedidoExtraido,
    PiezaPlan,
    ServicioExtraido,
    VehiculoExtraido,
)
from mecanimovilapp.apps.agente_ia.services.notificaciones import (
    notificar_cotizacion_borrador_agente,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.plan_por_servicio import (
    completar_cotizacion_en_blanco,
    cotizar_por_servicio,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
    notificar_revision_al_taller,
    resumen_para_cliente,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()

EMBRAGUE = 'necesito cambiar el embrague a mi oroch 2019 1.6, hace ruido y patina'
FRENOS = 'mantencion de frenos traseros boxer 2018'
ACEITE = 'cambio aceite y filtros sail 2015'
HIDRAULICO = 'revisar sistema hidraulico de frenos'
TYPO = 'cambie el embrage, bba y cil. rec. del oroch 2019'


def _por_identidad(repuestos):
    return {rep['identidad']: rep for rep in repuestos}


class PlanPorServicioTests(SimpleTestCase):
    def test_embrague_es_servicio_no_la_frase_del_ruido(self):
        out = cotizar_por_servicio(EMBRAGUE)
        self.assertEqual(out['servicios'][0]['nombre'], 'Cambio de embrague')
        auto = out['servicios'][0]['vehiculo']
        self.assertEqual(auto['marca'], 'Renault')
        self.assertEqual(auto['modelo'], 'Oroch')
        self.assertEqual(auto['anio'], 2019)
        self.assertEqual(auto['motor'], '1.6')
        self.assertGreater(out['mano_obra_clp'], 0)
        self.assertTrue(out['servicios_lineas'][0]['estimada'])
        lineas = _por_identidad(out['repuestos'])
        self.assertEqual(lineas['kit_embrague']['origen'], 'pedido')
        self.assertGreater(lineas['kit_embrague']['precio_unitario_clp'], 0)
        self.assertTrue(lineas['kit_embrague']['precio_estimado'])
        self.assertIn('oroch', lineas['kit_embrague']['consulta'].lower())
        self.assertNotIn('ruido', lineas['kit_embrague']['consulta'].lower())
        for ident in ('aceite_caja', 'rodamiento_piloto'):
            self.assertEqual(lineas[ident]['origen'], 'sugerencia')
            self.assertEqual(lineas[ident]['estado_sugerencia'], 'pendiente')
            self.assertTrue(lineas[ident]['motivo_sugerencia'])
        nombres = ' '.join(rep['nombre'].lower() for rep in out['repuestos'])
        self.assertNotIn('patina', nombres)
        self.assertNotIn('ruido', nombres)
        self.assertGreater(out['total_clp'], out['mano_obra_clp'])

    def test_frenos_traseros_son_balatas(self):
        def buscar(linea):
            if str(linea.get('consulta') or '').endswith('repuesto'):
                return {
                    'precio_unitario_clp': 31000,
                    'url_producto': 'https://www.casafrenos.cl/balatas-boxer',
                    'proveedor_nombre': 'Casa Frenos',
                    'nombre_producto': 'Balatas traseras Peugeot Boxer',
                }
            return {
                'precio_unitario_clp': 24990,
                'url_producto': 'https://www.casafrenos.cl/pastillas-boxer',
                'proveedor_nombre': 'Casa Frenos',
                'nombre_producto': 'Pastillas traseras Peugeot Boxer',
            }

        out = cotizar_por_servicio(FRENOS, buscar=buscar)
        linea = _por_identidad(out['repuestos'])['balatas_freno']
        self.assertNotIn('pastilla', linea['nombre'].lower())
        self.assertEqual(linea['precio_unitario_clp'], 31000)
        self.assertFalse(linea['precio_estimado'])
        self.assertIn('casafrenos.cl', linea['url_producto'])
        self.assertGreaterEqual(linea['reintentos_busqueda'], 1)
        self.assertGreater(out['mano_obra_clp'], 0)
        self.assertEqual(out['servicios'][0]['vehiculo']['modelo'], 'Boxer')

    def test_aceite_y_filtros_no_crea_la_linea_filtro(self):
        out = cotizar_por_servicio(ACEITE)
        lineas = _por_identidad(out['repuestos'])
        self.assertIn('aceite_motor', lineas)
        self.assertIn('filtro_aceite', lineas)
        self.assertEqual(lineas['filtro_aire']['origen'], 'sugerencia')
        self.assertTrue(lineas['filtro_aire']['motivo_sugerencia'])
        self.assertNotIn('filtro', [rep['nombre'].lower() for rep in out['repuestos']])
        self.assertGreater(lineas['aceite_motor']['precio_unitario_clp'], 0)
        self.assertTrue(lineas['aceite_motor']['precio_estimado'])
        self.assertGreater(out['mano_obra_clp'], 0)
        self.assertEqual(out['servicios'][0]['vehiculo']['modelo'], 'Sail')
        self.assertTrue(any(duda['id'] == 'aceite-viscosidad' for duda in out['dudas']))

    def test_revisar_el_hidraulico_es_mano_de_obra(self):
        out = cotizar_por_servicio(HIDRAULICO)
        self.assertEqual(out['repuestos'], [])
        self.assertGreater(out['mano_obra_clp'], 0)
        self.assertIn('hidráulico', out['servicios'][0]['nombre'].lower())
        self.assertTrue(any(duda['id'] == 'sistema-no-repuesto' for duda in out['dudas']))
        self.assertEqual(out['total_clp'], out['mano_obra_clp'])

    def test_abreviaturas_y_typos_siguen_siendo_el_embrague(self):
        out = cotizar_por_servicio(TYPO)
        lineas = _por_identidad(out['repuestos'])
        self.assertIn('kit_embrague', lineas)
        self.assertIn('bomba_embrague', lineas)
        self.assertIn('cilindro_receptor_embrague', lineas)
        self.assertEqual(lineas['aceite_caja']['estado_sugerencia'], 'pendiente')
        self.assertGreater(out['mano_obra_clp'], 0)
        for rep in out['repuestos']:
            self.assertGreater(rep['precio_unitario_clp'], 0)
            self.assertTrue(rep['precio_estimado'] or rep.get('url_producto'))
        self.assertEqual(out['servicios'][0]['vehiculo']['modelo'], 'Oroch')

    def test_el_cliente_oye_precio_por_confirmar(self):
        out = cotizar_por_servicio(EMBRAGUE)
        cot = SimpleNamespace(
            servicio_nombre=out['servicio_nombre'],
            repuestos=out['repuestos'],
            metadata={'dudas': out['dudas']},
        )
        texto = resumen_para_cliente(cot)
        self.assertIn('precio por confirmar', texto)
        self.assertNotIn('Aceite de caja', texto)
        self.assertIn('Kit de embrague', texto)


@override_settings(ASISTENTE_COTIZACION_IA_ENABLED=True)
class TresCaminosYPushTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_plan', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Plan',
            telefono='900000088',
            estado_verificacion='aprobado',
        )

    def _cot(self, **kwargs):
        datos = {
            'es_libre': True,
            'taller': self.taller,
            'creado_por': self.user,
            'estado': 'borrador',
            'servicio_nombre': 'Cambio de embrague',
            'vehiculo_marca': 'Renault',
            'vehiculo_modelo': 'Oroch',
            'mano_obra_clp': 0,
            'repuestos': [{
                'nombre': 'Aceite de caja de cambios',
                'origen': 'sugerencia',
                'estado_sugerencia': 'pendiente',
                'motivo_sugerencia': 'Al bajar la caja se pierde la valvulina.',
                'precio_unitario_clp': 22000,
                'precio_estimado': True,
            }],
            'metadata': {'dudas': [{'id': 'aceite', 'texto': 'confirmar', 'confirmada': False}]},
            'token': 'tok-plan-push',
        }
        datos.update(kwargs)
        return CotizacionCanal.objects.create(**datos)

    def test_sin_el_taller_presente_sale_una_sola_push(self):
        cot = self._cot()
        with patch(
            'mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay',
        ) as push:
            notificar_revision_al_taller(cot, taller_presente=False)
            notificar_revision_al_taller(cot, taller_presente=False)
        self.assertEqual(push.call_count, 1)
        self.assertEqual(push.call_args.args[0], self.user.id)
        self.assertEqual(push.call_args.args[3]['cotizacion_id'], cot.id)

    def test_con_el_taller_en_la_cotizacion_no_hay_push(self):
        cot = self._cot(token='tok-plan-presente')
        with patch(
            'mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay',
        ) as push:
            notificar_revision_al_taller(cot, taller_presente=True)
        push.assert_not_called()

    def test_la_ia_del_taller_no_deja_el_pedido_en_blanco(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
            generar_cotizacion_ia,
        )

        with (
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador._llamar_gemini',
                return_value=({
                    'servicio_nombre': EMBRAGUE,
                    'repuestos': [],
                    'mano_obra_clp': 0,
                }, {'tokens_entrada': 1, 'tokens_salida': 1, 'modelo': 'test'}, None),
            ),
            patch(
                'mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm.extraer_pedido_con_llm',
                side_effect=RuntimeError('sin red'),
            ),
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos.enriquecer_repuestos_cotizacion',
                side_effect=lambda repuestos, **_kwargs: list(repuestos or []),
            ),
        ):
            resultado = generar_cotizacion_ia(
                servicio_nombre=EMBRAGUE,
                descripcion_problema=EMBRAGUE,
                vehiculo={'marca': 'Renault', 'modelo': 'Oroch', 'anio': 2019, 'cilindraje': '1.6'},
                taller=self.taller,
                usar_web=False,
                enriquecer_ml=False,
            )
        contenido = resultado['contenido']
        self.assertGreater(contenido['mano_obra_clp'], 0)
        nombres = [rep['nombre'] for rep in contenido['repuestos']]
        self.assertIn('Kit de embrague', nombres)
        self.assertTrue(any(rep.get('origen') == 'sugerencia' for rep in contenido['repuestos']))
        self.assertTrue(all(int(rep['precio_unitario_clp']) > 0 for rep in contenido['repuestos']))

    def test_la_edicion_manual_interpreta_la_frase(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes import (
            _absorber_frase_de_servicio,
        )

        cot = self._cot(
            token='tok-plan-manual',
            repuestos=[],
            metadata={},
            servicio_nombre=FRENOS,
            vehiculo_marca='Peugeot',
            vehiculo_modelo='Boxer',
            vehiculo_anio=2018,
        )
        nombres, base = _absorber_frase_de_servicio(cot, [FRENOS], [])
        self.assertEqual(nombres, [])
        self.assertTrue(any('balata' in rep['nombre'].lower() for rep in base))
        self.assertFalse(any('pastilla' in rep['nombre'].lower() for rep in base))
        self.assertGreater(cot.mano_obra_clp, 0)
        self.assertTrue(cot.metadata.get('servicios_lineas'))


def _buscar_casa(linea):
    """Precio que no está en la tabla fija. Prueba que se usó el buscador."""
    if str(linea.get('consulta') or '').endswith('repuesto'):
        return {
            'precio_unitario_clp': 31000,
            'url_producto': 'https://www.casafrenos.cl/balatas',
            'proveedor_nombre': 'Casa Frenos',
            'nombre_producto': 'Balatas traseras',
        }
    nombre = str(linea.get('nombre') or 'Pieza')
    if nombre == 'Aceite de motor':
        return {
            'precio_unitario_clp': 8990,
            'url_producto': 'https://www.casaaceite.cl/1l',
            'proveedor_nombre': 'Casa Aceite',
            'nombre_producto': 'Aceite 5W30 1L',
            'candidatos_envase': [
                {
                    'nombre_producto': 'Aceite 5W30 1L',
                    'precio_unitario_clp': 8990,
                    'url': 'https://www.casaaceite.cl/1l',
                },
                {
                    'nombre_producto': 'Aceite 5W30 4L',
                    'precio_unitario_clp': 24990,
                    'url': 'https://www.casaaceite.cl/4l',
                },
            ],
        }
    return {
        'precio_unitario_clp': 11111,
        'url_producto': 'https://www.casamock.cl/pieza',
        'proveedor_nombre': 'Casa Mock',
        'nombre_producto': nombre,
    }


_FRASES = (
    'me suena la suspension delantera del yaris 2016',
    'quiero hacer la mantencion de los 60 mil al corolla 2018',
    'cambiar correa de distribucion y bomba de agua a un spark 2014',
    'frenos delanteros y aceite para hilux 2.4 2020',
    'pastillas',
    'cambiar pastillas delanteras y zapatas traseras',
    'kit de embrague, bomba y cilindro receptor',
    EMBRAGUE,
    FRENOS,
    ACEITE,
    HIDRAULICO,
    TYPO,
)


class CatalogoYLlmTests(SimpleTestCase):
    def test_el_fallback_cotiza_las_frases_que_el_revisor_dejo_vacias(self):
        for frase in _FRASES:
            with self.subTest(frase=frase):
                out = cotizar_por_servicio(frase, buscar=_buscar_casa)
                self.assertTrue(out['servicios'], frase)
                self.assertGreater(out['mano_obra_clp'], 0, frase)
                self.assertTrue(out['verificacion']['ok'], frase)
                if frase != HIDRAULICO:
                    pedidos = [r for r in out['repuestos'] if r['origen'] == 'pedido']
                    self.assertTrue(pedidos, frase)
                    for rep in pedidos:
                        self.assertGreater(rep['precio_unitario_clp'], 0, rep['nombre'])
                        self.assertTrue(rep.get('proveedor_nombre'), rep['nombre'])
                        self.assertNotEqual(rep['precio_unitario_clp'], 0)
                        self.assertIn(
                            rep['proveedor_nombre'],
                            {'Casa Mock', 'Casa Aceite', 'Casa Frenos'},
                        )
                for sug in (r for r in out['repuestos'] if r['origen'] == 'sugerencia'):
                    self.assertTrue(sug['motivo_sugerencia'], sug['nombre'])

    def test_el_llm_mockeado_manda_sobre_el_catalogo(self):
        for frase in _FRASES:
            with self.subTest(frase=frase):
                pedido = PedidoExtraido(
                    vehiculo=VehiculoExtraido(marca='Toyota', modelo='Yaris', anio=2016),
                    servicios=[ServicioExtraido(
                        nombre=f'Trabajo leído: {frase[:40]}',
                        horas=2,
                        repuestos_requeridos=[] if frase == HIDRAULICO else [
                            PiezaPlan(nombre='Pieza leída', identidad='pieza_leida'),
                        ],
                        sugeridos=[] if frase == HIDRAULICO else [
                            PiezaPlan(
                                nombre='Sugerida leída',
                                identidad='sugerida_leida',
                                motivo='El modelo la recomienda para este trabajo.',
                            ),
                        ],
                        incluye_repuestos=frase != HIDRAULICO,
                    )],
                )
                out = cotizar_por_servicio(frase, buscar=_buscar_casa, pedido=pedido)
                self.assertTrue(out['servicios'][0]['nombre'].startswith('Trabajo leído:'))
                self.assertGreater(out['mano_obra_clp'], 0)
                if frase != HIDRAULICO:
                    self.assertIn('Pieza leída', [r['nombre'] for r in out['repuestos']])
                    self.assertEqual(
                        _por_identidad(out['repuestos'])['sugerida_leida']['motivo_sugerencia'],
                        'El modelo la recomienda para este trabajo.',
                    )
                    self.assertEqual(
                        _por_identidad(out['repuestos'])['pieza_leida']['proveedor_nombre'],
                        'Casa Mock',
                    )

    def test_lo_que_no_se_entiende_no_sale_ok(self):
        out = cotizar_por_servicio('asdf qwerty sin sentido', buscar=_buscar_casa)
        self.assertEqual(out['servicios'], [])
        self.assertEqual(out['repuestos'], [])
        self.assertFalse(out['verificacion']['ok'])
        self.assertTrue(any(d['id'] == 'servicio-no-identificado' for d in out['dudas']))

    def test_un_modelo_desconocido_queda_como_duda(self):
        out = cotizar_por_servicio('del flibbert 2011 cambiar pastillas', buscar=_buscar_casa)
        self.assertEqual(out['servicios'][0]['vehiculo']['modelo'], 'Flibbert')
        self.assertTrue(any(d['id'] == 'vehiculo-no-reconocido' for d in out['dudas']))

    def test_el_aceite_elige_el_envase_mas_barato(self):
        out = cotizar_por_servicio(ACEITE, buscar=_buscar_casa)
        aceite = _por_identidad(out['repuestos'])['aceite_motor']
        self.assertEqual(aceite['litros'], 3.5)
        self.assertEqual(aceite['cantidad'], 1)
        self.assertEqual(aceite['precio_unitario_clp'], 24990)
        self.assertIn('4l', aceite['url_producto'])

    def test_la_mano_de_obra_se_completa_aunque_el_repuesto_ya_tenga_precio(self):
        out = completar_cotizacion_en_blanco(
            {
                'mano_obra_clp': 0,
                'servicios_lineas': [],
                'repuestos': [{
                    'nombre': 'Pastillas de freno delanteras',
                    'precio_unitario_clp': 24990,
                    'url_producto': 'https://www.casamock.cl/pastillas',
                    'proveedor_nombre': 'Casa Mock',
                }],
            },
            'pastillas del yaris 2016',
        )
        self.assertGreater(out['mano_obra_clp'], 0)
        self.assertEqual(out['repuestos'][0]['precio_unitario_clp'], 24990)

    def test_sin_buscador_inyectado_consulta_las_casas(self):
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.plan_por_servicio.buscar_lineas_en_casas',
            return_value={'pastillas de freno delanteras': {
                'precio_unitario_clp': 22222,
                'url_producto': 'https://www.ciper.cl/pastillas-yaris',
                'proveedor_nombre': 'Ciper',
                'nombre_producto': 'Pastillas delanteras Yaris',
            }},
        ) as casas:
            out = cotizar_por_servicio('pastillas del yaris 2016')
        casas.assert_called()
        linea = _por_identidad(out['repuestos'])['pastillas_freno']
        self.assertEqual(linea['precio_unitario_clp'], 22222)
        self.assertEqual(linea['proveedor_nombre'], 'Ciper')

    def test_la_duda_del_estimado_muestra_el_monto_con_margen(self):
        taller = SimpleNamespace(margen_ganancia_pct=30)
        out = cotizar_por_servicio('pastillas', taller=taller)
        texto = ' '.join(d['texto'] for d in out['dudas'])
        self.assertIn('32.000', texto)
        self.assertIn('41.600', texto)


class PushUnicaAgenteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_push_unica', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Push',
            telefono='900000089',
            estado_verificacion='aprobado',
        )

    def test_revision_y_borrador_dejan_una_sola_push(self):
        cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            servicio_nombre='Cambio de pastillas',
            token='tok-push-unica',
            repuestos=[{
                'nombre': 'Discos de freno delanteros',
                'origen': 'sugerencia',
                'estado_sugerencia': 'pendiente',
                'motivo_sugerencia': 'Si están bajo el mínimo.',
                'precio_unitario_clp': 11111,
            }],
            metadata={'dudas': [{'id': 'vehiculo', 'texto': 'confirmar', 'confirmada': False}]},
        )
        with patch(
            'mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay',
        ) as push:
            notificar_revision_al_taller(cot, taller_presente=False)
            notificar_cotizacion_borrador_agente(
                proveedor_user_id=self.user.id,
                cotizacion=cot,
                conversation_id=1,
            )
        self.assertEqual(push.call_count, 1)

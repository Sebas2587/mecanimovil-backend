"""El cotizador lee el servicio, no la frase literal del cliente."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.plan_por_servicio import (
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

"""Tres caminos de cotización: agente, IA del taller y edición manual asistida.

Lo pedido se cobra. El complemento queda pendiente hasta que el taller lo acepte.
"""
from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

_CACHE_LOCAL = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
}
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
    crear_cotizacion_borrador_desde_agente,
)
from mecanimovilapp.apps.agente_ia.services.orquestador import _cotizaciones_de_la_conversacion
from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CobroTaller, CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
    precio_unitario_desde_envase,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.completar_pedido import (
    completar_pedido_con_faena,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
    resumen_para_cliente,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import serializar_cotizacion_publica
from mecanimovilapp.apps.usuarios.models import Notificacion, Taller

User = get_user_model()

PEDIDO = 'kit de embrague, bomba de embrague y cambio de líquido de frenos'
PEDIDOS = ('Kit de embrague', 'Bomba de embrague', 'Líquido de frenos')
SUGERIDOS = ('Rodamiento de volante', 'Aceite de caja de cambios', 'Retén trasero de cigüeñal')

PLANTILLA_VIEJA = {
    'servicio_nombre': 'Cambio de embrague',
    'mano_obra_clp': 180000,
    'servicios_lineas': [{'nombre': 'Cambio de embrague', 'monto_clp': 180000}],
    'repuestos': [
        {'nombre': 'Kit de embrague', 'cantidad': 1, 'precio_unitario_clp': 89000},
        {'nombre': 'Rodamiento de volante', 'cantidad': 1, 'precio_unitario_clp': 12000},
        {'nombre': 'Aceite de caja', 'cantidad': 1, 'precio_unitario_clp': 32000},
        {'nombre': 'Retén trasero de cigüeñal', 'cantidad': 1, 'precio_unitario_clp': 7000},
    ],
}


def _por_nombre(repuestos):
    return {rep['nombre']: rep for rep in repuestos}


def _enriquecer_sin_red(repuestos, **_kwargs):
    return list(repuestos or [])


@override_settings(ASISTENTE_COTIZACION_IA_ENABLED=True)
class PedidoClutchLCKS17Tests(TestCase):
    def test_lo_pedido_entra_y_el_complemento_queda_pendiente(self):
        out = completar_pedido_con_faena(
            {
                **PLANTILLA_VIEJA,
                'descripcion_problema': PEDIDO,
            },
            servicio_nombre=PEDIDO,
        )
        lineas = _por_nombre(out['repuestos'])
        for nombre in PEDIDOS:
            self.assertEqual(lineas[nombre]['origen'], 'pedido')
            self.assertEqual(lineas[nombre]['estado_sugerencia'], 'aceptada')
        for nombre in SUGERIDOS:
            self.assertNotIn(nombre, lineas)
        faenas = [lin['nombre'] for lin in out['servicios_lineas']]
        self.assertIn('Cambio de embrague', faenas)
        self.assertIn('Cambio de bomba de embrague', faenas)
        self.assertIn('Cambio de líquido de frenos', faenas)
        # 89000 del kit + 180000 de la faena. Las sugerencias no se suman.
        self.assertEqual(out['costo_repuestos_clp'], 89000)
        self.assertEqual(out['total_clp'], 269000)
        ids = {d['id'] for d in out['dudas']}
        self.assertIn('kit-composicion', ids)
        self.assertIn('liquido-especificacion', ids)
        self.assertTrue(any(i.startswith('precio-') for i in ids))

    def test_los_tres_caminos_clasifican_lcks17_igual(self):
        """Agente, cotización IA y edición manual dejan lo pedido cobrable."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
            proponer_complementos,
        )

        generado = completar_pedido_con_faena(
            {**PLANTILLA_VIEJA, 'descripcion_problema': PEDIDO},
            servicio_nombre=PEDIDO,
        )
        # El agente conserva las líneas con origen; no reclasifica lo pedido.
        agente = [
            rep for rep in generado['repuestos']
            if rep.get('origen') in ('pedido', 'sugerencia')
        ]
        manual, dudas = proponer_complementos(
            [{
                'id': 'kit-1',
                'nombre': 'Kit de embrague',
                'cantidad': 1,
                'precio_unitario_clp': 89000,
            }],
            PEDIDO,
        )
        # Una bomba que quedó mal etiquetada se corrige al editar.
        corregido, _ = proponer_complementos(
            [{
                'id': 'bomba-vieja',
                'nombre': 'Bomba de embrague',
                'origen': 'sugerencia',
                'estado_sugerencia': 'pendiente',
                'motivo_sugerencia': 'El pedido nombra Bomba de embrague.',
                'cantidad': 1,
                'precio_unitario_clp': 28000,
            }],
            PEDIDO,
        )

        def clases(reps):
            return {
                rep['nombre']: (rep.get('origen'), rep.get('estado_sugerencia'))
                for rep in reps
            }

        esperadas = {nombre: ('pedido', 'aceptada') for nombre in PEDIDOS}
        for camino in (generado['repuestos'], agente, manual, corregido):
            vistos = clases(camino)
            for nombre, marca in esperadas.items():
                self.assertEqual(vistos[nombre], marca, nombre)
        self.assertEqual(
            {nombre: clases(generado['repuestos'])[nombre] for nombre in esperadas},
            {nombre: clases(manual)[nombre] for nombre in esperadas},
        )
        self.assertEqual(
            {nombre: clases(agente)[nombre] for nombre in esperadas},
            {nombre: clases(manual)[nombre] for nombre in esperadas},
        )
        ids = {duda['id'] for duda in dudas}
        self.assertIn('precio-bomba-de-embrague', ids)
        self.assertIn('precio-liquido-de-frenos', ids)
        bomba = next(rep for rep in corregido if rep['nombre'] == 'Bomba de embrague')
        self.assertEqual(bomba['origen'], 'pedido')
        self.assertEqual(bomba['motivo_sugerencia'], '')

    def test_aceite_de_caja_no_se_parte_por_litro(self):
        precio, nota = precio_unitario_desde_envase(
            'Aceite de caja de cambios',
            32000,
            'Valvulina 75W80 envase 4 litros',
        )
        self.assertEqual(precio, 32000)
        self.assertEqual(nota, '')
        por_litro, nota_motor = precio_unitario_desde_envase(
            'Aceite de motor',
            32000,
            'Bidón 4 litros 5W30',
        )
        self.assertEqual(por_litro, 8000)
        self.assertIn('litro', nota_motor)


@override_settings(ASISTENTE_COTIZACION_IA_ENABLED=True, CACHES=_CACHE_LOCAL)
class TresCaminosCotizacionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_pedido', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Pedido',
            telefono='900000031',
            estado_verificacion='aprobado',
        )
        self.otro = User.objects.create_user(username='taller_pedido_b', password='test123')
        Taller.objects.create(
            usuario=self.otro,
            nombre='Otro Taller Pedido',
            telefono='900000032',
            estado_verificacion='aprobado',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.ajeno = APIClient()
        self.ajeno.force_authenticate(user=self.otro)
        self.conversation = Conversation.objects.create(source_channel='WHATSAPP')
        self.conversation.participants.add(self.user)

    def _cot(self, **kwargs):
        datos = {
            'es_libre': True,
            'taller': self.taller,
            'creado_por': self.user,
            'estado': 'borrador',
            'cliente_nombre': 'Cliente LCKS17',
            'servicio_nombre': PEDIDO,
            'descripcion_problema': PEDIDO,
            'vehiculo_marca': 'Suzuki',
            'vehiculo_modelo': 'Celerio',
            'vehiculo_patente': 'LCKS17',
            'mano_obra_clp': 0,
            'token': 'tok-pedido-base',
        }
        datos.update(kwargs)
        return CotizacionCanal.objects.create(**datos)

    def test_agente_no_le_promete_al_cliente_lo_pendiente(self):
        contenido = completar_pedido_con_faena(
            {**PLANTILLA_VIEJA, 'descripcion_problema': PEDIDO},
            servicio_nombre=PEDIDO,
        )
        sesion = AgenteConversacionSesion.objects.create(
            conversation=self.conversation,
            taller=self.taller,
            estado=AgenteConversacionSesion.ESTADO_CAPTURANDO,
            habilitado_en_chat=True,
        )
        with (
            patch(
                'mecanimovilapp.apps.suscripciones.cuotas_services.verificar_y_consumir_cuota',
            ),
            patch(
                'mecanimovilapp.apps.agente_ia.services.cotizacion_borrador.generar_cotizacion_ia',
                return_value={
                    'disponible': True,
                    'contenido': contenido,
                    'contenido_ia': {},
                    'contexto': {
                        'vehiculo_marca': 'Suzuki',
                        'vehiculo_modelo': 'Celerio',
                        'vehiculo_patente': 'LCKS17',
                    },
                    'tokens_entrada': 0,
                    'tokens_salida': 0,
                    'modelo': 'test',
                },
            ),
            patch(
                'mecanimovilapp.apps.usuarios.tasks.send_expo_push_notification.delay',
            ),
            patch(
                'mecanimovilapp.apps.agente_ia.services.ws_broadcast.emitir_evento_ws_agente_ia',
            ),
        ):
            cot = crear_cotizacion_borrador_desde_agente(
                sesion=sesion,
                conversation=self.conversation,
                taller=self.taller,
                proveedor_user_id=self.user.id,
                datos={
                    'servicio_nombre': PEDIDO,
                    'cliente_nombre': 'Cliente LCKS17',
                    'vehiculo': {
                        'marca': 'Suzuki',
                        'modelo': 'Celerio',
                        'patente': 'LCKS17',
                        'anio': 2018,
                    },
                },
            )
        self.assertIsNotNone(cot)
        lineas = _por_nombre(cot.repuestos)
        self.assertEqual(lineas['Bomba de embrague']['origen'], 'pedido')
        self.assertNotIn('Rodamiento de volante', lineas)
        self.assertEqual(cot.total_clp, 269000)
        self.assertEqual(cot.metadata['revision_sugerencias']['estado'], 'sin_sugerencias')
        self.assertIn('kit-composicion', {d['id'] for d in cot.metadata['dudas']})
        texto = _cotizaciones_de_la_conversacion(self.conversation.id)
        for nombre in SUGERIDOS:
            self.assertNotIn(nombre, texto)
        self.assertIn('Kit de embrague', resumen_para_cliente(cot))
        for nombre in SUGERIDOS:
            self.assertNotIn(nombre, resumen_para_cliente(cot))

    def test_taller_pide_la_ia_y_recibe_el_mismo_reparto(self):
        with (
            patch(
                'mecanimovilapp.apps.suscripciones.cuotas_services.verificar_y_consumir_cuota',
            ),
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador._llamar_gemini',
                return_value=(PLANTILLA_VIEJA, {'tokens_entrada': 1, 'tokens_salida': 1, 'modelo': 'test'}, None),
            ),
            patch(
                'mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm.extraer_pedido_con_llm',
                side_effect=RuntimeError('sin red'),
            ),
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos.enriquecer_repuestos_cotizacion',
                side_effect=_enriquecer_sin_red,
            ),
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web.disparar_busqueda_web_cotizacion',
            ),
            patch(
                'mecanimovilapp.apps.agente_ia.services.ws_broadcast.emitir_evento_ws_agente_ia',
            ),
        ):
            resp = self.client.post(
                '/api/ordenes/cotizaciones-canal/generar-ia/',
                {
                    'cliente_nombre': 'Cliente LCKS17',
                    'servicio_nombre': PEDIDO,
                    'descripcion_problema': PEDIDO,
                    'vehiculo': {
                        'marca': 'Suzuki',
                        'modelo': 'Celerio',
                        'patente': 'LCKS17',
                        'anio': 2018,
                    },
                },
                format='json',
            )
        self.assertEqual(resp.status_code, 201, resp.content)
        cuerpo = resp.json()['cotizacion']
        lineas = _por_nombre(cuerpo['repuestos'])
        for nombre in PEDIDOS:
            self.assertEqual(lineas[nombre]['origen'], 'pedido', nombre)
            self.assertEqual(lineas[nombre]['estado_sugerencia'], 'aceptada', nombre)
        for nombre in SUGERIDOS:
            self.assertNotIn(nombre, lineas)
        self.assertEqual(cuerpo['revision_sugerencias']['estado'], 'sin_sugerencias')
        self.assertEqual(cuerpo['revision_sugerencias']['pendientes'], 0)
        self.assertTrue(cuerpo['dudas'])
        faenas = [lin['nombre'] for lin in cuerpo['mano_obra_lineas']]
        self.assertIn('Cambio de embrague', faenas)
        self.assertIn('Cambio de bomba de embrague', faenas)
        self.assertIn('Cambio de líquido de frenos', faenas)
        self.assertEqual(cuerpo['costo_repuestos_clp'], 89000)
        self.assertEqual(cuerpo['cobrado_total_repuestos_clp'], 89000)
        self.assertEqual(cuerpo['total_clp'], 89000 + cuerpo['mano_obra_clp'])

    def test_edicion_manual_propone_y_no_cobra_hasta_decidir(self):
        cot = self._cot(token='tok-manual-asistida', repuestos=[], total_clp=0)
        with (
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes.enriquecer_repuestos_cotizacion',
                side_effect=_enriquecer_sin_red,
            ),
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web.disparar_busqueda_web_cotizacion',
            ),
            patch(
                'mecanimovilapp.apps.agente_ia.services.ws_broadcast.emitir_evento_ws_agente_ia',
            ),
        ):
            alta = self.client.post(
                f'/api/ordenes/cotizaciones-canal/{cot.id}/cotizar-items/',
                {'nombres': ['Kit de embrague']},
                format='json',
            )
        self.assertEqual(alta.status_code, 200, alta.content)
        lineas = _por_nombre(alta.json()['cotizacion']['repuestos'])
        self.assertEqual(lineas['Kit de embrague']['origen'], 'pedido')
        self.assertEqual(lineas['Bomba de embrague']['origen'], 'pedido')
        self.assertEqual(lineas['Bomba de embrague']['estado_sugerencia'], 'aceptada')
        self.assertEqual(lineas['Bomba de embrague']['motivo_sugerencia'], '')
        self.assertEqual(lineas['Líquido de frenos']['origen'], 'pedido')
        self.assertNotIn('Aceite de caja de cambios', lineas)
        self.assertIn('kit-composicion', {d['id'] for d in alta.json()['cotizacion']['dudas']})
        dudas_alta = {d['id'] for d in alta.json()['cotizacion']['dudas']}
        self.assertIn('precio-bomba-de-embrague', dudas_alta)
        self.assertEqual(alta.json()['cotizacion']['total_clp'], 0)

        con_precio = []
        for rep in alta.json()['cotizacion']['repuestos']:
            fila = {
                'id': rep['id'],
                'nombre': rep['nombre'],
                'cantidad': 1,
                'precio_unitario_clp': rep['precio_unitario_clp'],
                'origen': rep['origen'],
                'estado_sugerencia': rep['estado_sugerencia'],
                'motivo_sugerencia': rep['motivo_sugerencia'],
            }
            if rep['nombre'] == 'Kit de embrague':
                fila['precio_unitario_clp'] = 45000
                fila['costo_estimado_clp'] = 30000
                fila['nombre_producto'] = 'Kit embrague disco prensa collarín, sin piloto'
            if rep['nombre'] == 'Bomba de embrague':
                fila['precio_unitario_clp'] = 28000
            con_precio.append(fila)
        with patch(
            'mecanimovilapp.apps.agente_ia.services.ws_broadcast.emitir_evento_ws_agente_ia',
        ):
            precios = self.client.patch(
                f'/api/ordenes/cotizaciones-canal/{cot.id}/',
                {'repuestos': con_precio},
                format='json',
            )
        self.assertEqual(precios.status_code, 200, precios.content)
        # La bomba se pidió: se cobra. El aceite sigue pendiente y no entra.
        self.assertEqual(precios.json()['total_clp'], 45000 + 28000)
        self.assertEqual(precios.json()['cobrado_total_repuestos_clp'], 45000 + 28000)
        self.assertEqual(
            _por_nombre(precios.json()['repuestos'])['Bomba de embrague']['origen'],
            'pedido',
        )

        lineas = _por_nombre(precios.json()['repuestos'])
        bomba_id = lineas['Bomba de embrague']['id']
        piloto_id = lineas['Rodamiento de volante']['id']
        self.assertEqual(lineas['Rodamiento de volante']['estado_sugerencia'], 'pendiente')
        rechaza_pedido = self.client.post(
            f'/api/ordenes/cotizaciones-canal/{cot.id}/sugerencias/',
            {'linea_id': bomba_id, 'accion': 'descartar'},
            format='json',
        )
        self.assertEqual(rechaza_pedido.status_code, 400, rechaza_pedido.content)

        with patch(
            'mecanimovilapp.apps.agente_ia.services.ws_broadcast.emitir_evento_ws_agente_ia',
        ):
            descarta = self.client.post(
                f'/api/ordenes/cotizaciones-canal/{cot.id}/sugerencias/',
                {'linea_id': piloto_id, 'accion': 'descartar'},
                format='json',
            )
        self.assertEqual(descarta.status_code, 200, descarta.content)
        cuerpo = descarta.json()['cotizacion']
        self.assertEqual(
            _por_nombre(cuerpo['repuestos'])['Rodamiento de volante']['estado_sugerencia'],
            'descartada',
        )
        self.assertEqual(cuerpo['total_clp'], 45000 + 28000)

        enviadas = [
            {
                'id': rep['id'],
                'nombre': rep['nombre'],
                'cantidad': rep['cantidad'],
                'precio_unitario_clp': rep['precio_unitario_clp'],
            }
            for rep in cuerpo['repuestos']
            if rep['estado_sugerencia'] != 'descartada'
        ]
        with patch(
            'mecanimovilapp.apps.agente_ia.services.ws_broadcast.emitir_evento_ws_agente_ia',
        ):
            edit = self.client.patch(
                f'/api/ordenes/cotizaciones-canal/{cot.id}/',
                {'repuestos': enviadas},
                format='json',
            )
        self.assertEqual(edit.status_code, 200, edit.content)
        nombres = [rep['nombre'] for rep in edit.json()['repuestos']]
        self.assertNotIn('Rodamiento de volante', nombres)
        self.assertEqual(
            _por_nombre(edit.json()['repuestos'])['Kit de embrague']['origen'],
            'pedido',
        )

        duda_id = edit.json()['dudas'][0]['id']
        confirma = self.client.post(
            f'/api/ordenes/cotizaciones-canal/{cot.id}/dudas/confirmar/',
            {'id': duda_id},
            format='json',
        )
        self.assertEqual(confirma.status_code, 200, confirma.content)
        confirmadas = {
            d['id']: d['confirmada'] for d in confirma.json()['cotizacion']['dudas']
        }
        self.assertTrue(confirmadas[duda_id])

    def test_el_cliente_solo_ve_lo_aceptado(self):
        cot = self._cot(
            token='tok-publico-sugerencias',
            estado='enviada',
            repuestos=[
                {
                    'id': 'kit',
                    'nombre': 'Kit de embrague',
                    'cantidad': 1,
                    'precio_unitario_clp': 89000,
                    'origen': 'pedido',
                    'estado_sugerencia': 'aceptada',
                },
                {
                    'id': 'piloto',
                    'nombre': 'Rodamiento de volante',
                    'cantidad': 1,
                    'precio_unitario_clp': 12000,
                    'origen': 'sugerencia',
                    'estado_sugerencia': 'pendiente',
                    'motivo_sugerencia': 'No viene en el kit.',
                },
            ],
            costo_repuestos_clp=89000,
            total_clp=89000,
        )
        publico = serializar_cotizacion_publica(cot)
        nombres = [rep['nombre'] for rep in publico['repuestos']]
        self.assertEqual(nombres, ['Kit de embrague'])
        self.assertNotIn('origen', publico['repuestos'][0])
        self.assertNotIn('motivo_sugerencia', publico['repuestos'][0])
        self.assertNotIn('estado_sugerencia', publico['repuestos'][0])

    def test_borrar_la_propia_es_un_paso_y_la_ajena_no_existe(self):
        cot = self._cot(token='tok-borrar', estado='enviada')
        resp = self.client.delete(f'/api/ordenes/cotizaciones-canal/{cot.id}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['modo'], 'oculta')
        self.assertEqual(resp.json()['estado'], 'cancelada')
        cot.refresh_from_db()
        self.assertEqual(cot.estado, 'cancelada')
        self.assertEqual(
            self.ajeno.delete(f'/api/ordenes/cotizaciones-canal/{cot.id}/').status_code,
            404,
        )

    def test_no_borra_si_hay_cita_activa_o_caja(self):
        cot = self._cot(token='tok-caja', estado='enviada')
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            creado_por=self.user,
            cotizacion_canal_origen=cot,
            fecha_servicio=date(2026, 11, 12),
            hora_servicio=time(10, 0),
            tipo_servicio='taller',
            estado='activa',
        )
        bloqueada = self.client.delete(f'/api/ordenes/cotizaciones-canal/{cot.id}/')
        self.assertEqual(bloqueada.status_code, 409, bloqueada.content)
        self.assertEqual(bloqueada.json()['codigo'], 'cotizacion_con_caja')
        cot.refresh_from_db()
        self.assertEqual(cot.estado, 'enviada')

        cita.estado = 'cerrada'
        cita.cerrada_en = timezone.now()
        cita.cobro_estado = 'anotado'
        cita.cobro_monto_clp = 10000
        cita.save(update_fields=['estado', 'cerrada_en', 'cobro_estado', 'cobro_monto_clp'])
        anotada = self.client.delete(f'/api/ordenes/cotizaciones-canal/{cot.id}/')
        self.assertEqual(anotada.status_code, 409)

        cita.cobro_estado = 'pendiente'
        cita.cobro_monto_clp = 0
        cita.save(update_fields=['cobro_estado', 'cobro_monto_clp'])
        CobroTaller.objects.create(
            taller=self.taller,
            ancla_tipo=CobroTaller.ANCLA_CITA,
            ancla_id=str(cita.id),
            origen=CobroTaller.ORIGEN_MANUAL,
            ref_externa='ref-caja-lcks17',
            tipo=CobroTaller.TIPO_ENTRADA,
            estado=CobroTaller.ESTADO_CONFIRMADO,
            monto_clp=10000,
            fecha_efectiva=timezone.now(),
            fecha_local=date(2026, 11, 12),
        )
        con_caja = self.client.delete(f'/api/ordenes/cotizaciones-canal/{cot.id}/')
        self.assertEqual(con_caja.status_code, 409, con_caja.content)
        cot.refresh_from_db()
        self.assertEqual(cot.estado, 'enviada')


class MensajeClienteSinPendientesTests(SimpleTestCase):
    """Teaser, metadata y resumen no nombran sugerencias pendientes ni descartadas."""

    def _cot(self):
        class Fake:
            id = 41
            servicio_nombre = 'kit de embrague, bomba de embrague y cambio de líquido de frenos'
            descripcion_problema = ''
            modalidad = 'taller'
            tipo_documento = 'cotizacion'
            vehiculo_marca = 'Suzuki'
            vehiculo_modelo = 'Celerio'
            vehiculo_anio = 2018
            vehiculo_cilindraje = ''
            vehiculo_patente = 'LCKS17'
            tipo_motor_label = ''
            mano_obra_clp = 180000
            costo_repuestos_clp = 89000
            total_clp = 269000
            descuento_clp = 0
            descuento_tipo = ''
            descuento_alcance = 'mano_obra'
            descuento_valor = 0
            duracion_minutos_estimada = 180
            url_publica = 'https://ejemplo.cl/c/lcks17'
            numero_publico = 'MM-000317'
            es_cotizacion_adicional = False
            cotizacion_original = None
            cita_origen = None
            advertencias = []
            metadata = {
                'servicios_lineas': [
                    {
                        'nombre': 'Cambio de embrague',
                        'monto_clp': 180000,
                        'origen': 'pedido',
                        'estado_sugerencia': 'aceptada',
                    },
                    {
                        'nombre': 'Cambio de rodamiento de volante',
                        'monto_clp': 15000,
                        'origen': 'sugerencia',
                        'estado_sugerencia': 'pendiente',
                    },
                ],
            }
            repuestos = [
                {
                    'nombre': 'Kit de embrague',
                    'cantidad': 1,
                    'precio_unitario_clp': 89000,
                    'origen': 'pedido',
                    'estado_sugerencia': 'aceptada',
                },
                {
                    'nombre': 'Rodamiento de volante',
                    'cantidad': 1,
                    'precio_unitario_clp': 12000,
                    'origen': 'sugerencia',
                    'estado_sugerencia': 'pendiente',
                    'motivo_sugerencia': 'No viene en el kit.',
                },
                {
                    'nombre': 'Aceite de caja de cambios',
                    'cantidad': 1,
                    'precio_unitario_clp': 32000,
                    'origen': 'sugerencia',
                    'estado_sugerencia': 'descartada',
                },
            ]

        return Fake()

    def test_teaser_metadata_y_resumen_omiten_lo_no_aceptado(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            formatear_resumen_cotizacion,
            formatear_teaser_cotizacion,
            metadata_cotizacion_mensaje,
        )

        cot = self._cot()
        teaser = formatear_teaser_cotizacion(cot, actualizada=True)
        self.assertIn('Incluye:', teaser)
        self.assertIn('Kit de embrague', teaser)
        self.assertIn('Cambio de embrague', teaser)
        self.assertNotIn('Rodamiento de volante', teaser)
        self.assertNotIn('Aceite de caja', teaser)
        self.assertNotIn('rodamiento de volante', teaser.lower())

        meta = metadata_cotizacion_mensaje(cot)
        nombres = [rep['nombre'] for rep in meta['repuestos']]
        self.assertEqual(nombres, ['Kit de embrague'])
        faenas = [lin['nombre'] for lin in meta['mano_obra_lineas']]
        self.assertEqual(faenas, ['Cambio de embrague'])

        resumen = formatear_resumen_cotizacion(cot)
        self.assertIn('Kit de embrague', resumen)
        self.assertNotIn('Rodamiento de volante', resumen)
        self.assertNotIn('Aceite de caja', resumen)
        self.assertNotIn('Cambio de rodamiento', resumen)

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.revision_sugerencias import (
            resumen_para_cliente,
        )

        texto_agente = resumen_para_cliente(cot)
        self.assertIn('Kit de embrague', texto_agente)
        self.assertNotIn('Rodamiento de volante', texto_agente)
        self.assertNotIn('Aceite de caja', texto_agente)


class AlertaAsumidaSinDuplicarTests(SimpleTestCase):
    def test_el_motivo_asumido_no_se_repite_en_alertas(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
            validar_repuesto,
        )

        linea = validar_repuesto({
            'nombre': 'Filtro de aire',
            'cantidad': 1,
            'precio_unitario_clp': 8990,
            'certeza': 'asumido',
            'comentario': 'Precio asumido',
        })
        self.assertEqual(linea['validacion_estado'], 'asumido')
        self.assertIn('No hay ficha de tienda', linea['validacion_motivo'])
        self.assertNotIn(linea['validacion_motivo'], linea['alertas'])

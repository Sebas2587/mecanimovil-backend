"""El chat del dueño arma el borrador de Cotizar y no da de alta un servicio."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from mecanimovilapp.apps.agente_ia.models import AgenteDuenoMensaje
from mecanimovilapp.apps.agente_ia.services.agente_dueno import responder_agente_dueno
from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.pipeline_comercial import _filas_cotizaciones_canal
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()

FRASE = (
    'Realiza una cotización para el cliente Carlos del chat de Facebook, '
    'cambio de embrague para Suzuki Swift 2015, patente HCBC63, '
    'a domicilio en la comuna de Quinta Normal.'
)


def _patente_suzuki(*_args, **_kwargs):
    return ({
        'marca_nombre': 'Suzuki',
        'modelo_nombre': 'Swift',
        'year': 2015,
        'color': 'Rojo',
        'motor': '1.2',
        'cilindraje': '1.2',
        'vin': 'VINHCBC63',
        'tipo_motor': 'GASOLINA',
        'patente': 'HCBC63',
    }, 200, None)


def _generada(*_args, **kwargs):
    veh = kwargs.get('vehiculo') or {}
    return {
        'disponible': True,
        'contenido': {
            'servicio_nombre': kwargs.get('servicio_nombre') or 'Cambio de embrague',
            'descripcion_problema': '',
            'repuestos': [{
                'nombre': 'Kit de embrague',
                'cantidad': 1,
                'precio_unitario_clp': 0,
            }],
            'mano_obra_clp': 90000,
            'costo_repuestos_clp': 0,
            'total_clp': 90000,
            'servicios_lineas': [{'nombre': 'Cambio de embrague', 'monto_clp': 90000}],
            'tipo_motor': 'GASOLINA',
            'tipo_motor_label': 'Gasolina',
            'duracion_minutos_estimada': 180,
            'advertencias': [],
        },
        'contenido_ia': {'origen': 'test'},
        'contexto': {
            'vehiculo_marca': veh.get('marca') or '',
            'vehiculo_modelo': veh.get('modelo') or '',
            'vehiculo_anio': veh.get('anio'),
            'vehiculo_patente': veh.get('patente') or '',
            'vehiculo_cilindraje': veh.get('cilindraje') or '',
            'tipo_motor': 'GASOLINA',
            'tipo_motor_label': 'Gasolina',
        },
        'error': None,
        'tokens_entrada': 1,
        'tokens_salida': 1,
        'modelo': 'test',
    }


class CotizacionDesdeChatDuenoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='dueno_cot', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Cotización',
            telefono='900000010',
            estado_verificacion='aprobado',
        )
        self.parches = [
            patch(
                'mecanimovilapp.apps.vehiculos.services.guest_patente_lookup.fetch_patente_normalized',
                side_effect=_patente_suzuki,
            ),
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador.generar_cotizacion_ia',
                side_effect=_generada,
            ),
            patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web.disparar_busqueda_web_cotizacion',
                return_value=False,
            ),
            patch(
                'mecanimovilapp.apps.agente_ia.services.orquestador._llamar_gemini_agente',
                return_value=(None, 'no debía llamar al modelo'),
            ),
        ]
        self.mocks = [p.start() for p in self.parches]
        self.addCleanup(lambda: [p.stop() for p in self.parches])

    def _decir(self, texto, hilo_id=None):
        return responder_agente_dueno(self.taller, texto, [], hilo_id, self.user)

    def test_la_frase_de_carlos_deja_borrador_sin_catalogo(self):
        respuesta = self._decir(FRASE)
        self.assertTrue(respuesta['ok'])
        self.assertNotIn('catálogo', respuesta['resumen'].lower())
        self.assertNotIn('catalogo', respuesta['resumen'].lower())
        self.mocks[3].assert_not_called()
        cotizacion = CotizacionCanal.objects.get()
        self.assertEqual(cotizacion.estado, 'borrador')
        self.assertTrue(cotizacion.es_libre)
        self.assertIsNone(cotizacion.conversation_id)
        self.assertEqual(cotizacion.servicio_nombre, 'Cambio de embrague')
        self.assertEqual(cotizacion.vehiculo_marca, 'Suzuki')
        self.assertEqual(cotizacion.vehiculo_modelo, 'Swift')
        self.assertEqual(cotizacion.vehiculo_anio, 2015)
        self.assertEqual(cotizacion.vehiculo_patente, 'HCBC63')
        self.assertEqual(cotizacion.vehiculo_vin, 'VINHCBC63')
        self.assertEqual(cotizacion.vehiculo_cilindraje, '1.2')
        self.assertEqual(cotizacion.metadata.get('vehiculo_color'), 'Rojo')
        self.assertEqual(cotizacion.modalidad, 'domicilio')
        self.assertIn('Quinta Normal', cotizacion.direccion_servicio)
        self.assertEqual(cotizacion.cliente_nombre, '')
        self.assertTrue(cotizacion.repuestos)
        self.assertTrue(cotizacion.token)
        self.assertTrue(cotizacion.url_publica)
        self.assertTrue(cotizacion.numero_publico)
        self.assertEqual(OfertaServicio.objects.filter(taller=self.taller).count(), 0)
        self.assertEqual(respuesta['enlace']['url'], cotizacion.url_publica)
        self.assertEqual(respuesta['enlace']['cotizacion_id'], cotizacion.id)
        mensaje = AgenteDuenoMensaje.objects.filter(hilo_id=respuesta['hilo_id'], rol='agente').latest('id')
        self.assertEqual(mensaje.vista['enlace']['url'], cotizacion.url_publica)
        self.assertIn('repuestos', respuesta['resumen'].lower())

    def test_si_la_patente_no_responde_el_borrador_igual_existe(self):
        self.mocks[0].side_effect = lambda *_a, **_k: (None, 503, 'servicio_externo')
        respuesta = self._decir(FRASE)
        cotizacion = CotizacionCanal.objects.get()
        self.assertEqual(cotizacion.estado, 'borrador')
        self.assertEqual(cotizacion.vehiculo_marca, 'Suzuki')
        self.assertEqual(cotizacion.vehiculo_modelo, 'Swift')
        self.assertEqual(cotizacion.vehiculo_patente, 'HCBC63')
        self.assertIn('No pude consultar la patente', respuesta['resumen'])

    def test_precio_dicho_antes_del_documento_es_la_mano_de_obra(self):
        primero = self._decir('Realiza una cotización de cambio de embrague')
        self.assertEqual(CotizacionCanal.objects.count(), 0)
        self.assertIn('auto', primero['resumen'].lower())
        self._decir('180000', primero['hilo_id'])
        self.assertEqual(CotizacionCanal.objects.count(), 0)
        self.assertEqual(OfertaServicio.objects.filter(taller=self.taller).count(), 0)
        self._decir('Suzuki Swift 2015 patente HCBC63', primero['hilo_id'])
        cotizacion = CotizacionCanal.objects.get()
        self.assertEqual(int(cotizacion.mano_obra_clp), 180000)
        self.assertEqual(OfertaServicio.objects.filter(taller=self.taller).count(), 0)

    def test_si_la_patente_no_coincide_pregunta_una_vez(self):
        self.mocks[0].side_effect = lambda *_a, **_k: ({
            'marca_nombre': 'Mazda',
            'modelo_nombre': '3',
            'year': 2014,
            'color': 'Gris',
            'vin': 'VINMAZDA',
            'cilindraje': '2.0',
            'tipo_motor': 'GASOLINA',
        }, 200, None)
        pregunta = self._decir(FRASE)
        self.assertEqual(CotizacionCanal.objects.count(), 0)
        self.assertIn('Mazda', pregunta['resumen'])
        self.assertIn('Suzuki', pregunta['resumen'])
        self._decir('la que dije', pregunta['hilo_id'])
        cotizacion = CotizacionCanal.objects.get()
        self.assertEqual(cotizacion.vehiculo_marca, 'Suzuki')
        self.assertEqual(cotizacion.vehiculo_anio, 2015)

    def test_despues_de_aprobar_pregunta_carlos_de_facebook(self):
        ct = ContentType.objects.get_for_model(Taller)
        conexion = ProviderChannelConnection.objects.create(
            content_type=ct,
            object_id=self.taller.id,
            usuario=self.user,
            channel='MESSENGER',
            enabled=True,
            status='conectada',
        )
        contacto = ExternalContact.objects.create(
            connection=conexion,
            channel='MESSENGER',
            external_id='psid-carlos',
            display_name='Carlos Pérez',
            phone='56911112222',
        )
        conversacion = Conversation.objects.create(
            type='OMNICHANNEL',
            source_channel='MESSENGER',
            external_contact=contacto,
        )
        conversacion.participants.add(self.user)
        borrador = self._decir(FRASE)
        respuesta = self._decir('está bien', borrador['hilo_id'])
        self.assertIn('Carlos', respuesta['resumen'])
        self.assertIn('Facebook', respuesta['resumen'])
        cotizacion = CotizacionCanal.objects.get()
        self.assertEqual(cotizacion.estado, 'borrador')
        self.assertEqual(cotizacion.cliente_nombre, '')
        self._decir('sí', borrador['hilo_id'])
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.cliente_nombre, 'Carlos Pérez')
        self.assertEqual(cotizacion.conversation_id, conversacion.id)
        self.assertFalse(cotizacion.es_libre)
        self.assertEqual(cotizacion.estado, 'borrador')

    def test_sin_carlos_ofrece_a_quien_ya_tiene_la_patente(self):
        CotizacionCanal.objects.create(
            taller=self.taller,
            es_libre=True,
            estado='enviada',
            cliente_nombre='Pedro Soto',
            cliente_telefono='+56987654321',
            vehiculo_patente='HCBC63',
            vehiculo_marca='Suzuki',
            vehiculo_modelo='Swift',
            servicio_nombre='Aceite',
            modalidad='taller',
        )
        borrador = self._decir(FRASE)
        respuesta = self._decir('está bien', borrador['hilo_id'])
        self.assertIn('Pedro Soto', respuesta['resumen'])
        self.assertEqual(respuesta['filas'][0]['id'].startswith('persona:'), True)

    def test_sin_contacto_pide_nombre_y_el_envio_espera_el_si(self):
        borrador = self._decir(FRASE)
        self._decir('está bien', borrador['hilo_id'])
        self._decir('María', borrador['hilo_id'])
        cotizacion = CotizacionCanal.objects.get(servicio_nombre='Cambio de embrague')
        self.assertEqual(cotizacion.cliente_nombre, 'María')
        self.assertEqual(cotizacion.estado, 'borrador')
        self.assertIn('no está en un canal', self._ultimo_resumen(borrador['hilo_id']).lower())
        envio = self._decir('Envíasela', borrador['hilo_id'])
        self.assertIn('calle', envio['resumen'].lower())
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, 'borrador')
        propuesta = self._decir('Av. Mapocho 120', borrador['hilo_id'])
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, 'borrador')
        self.assertIn('120', cotizacion.direccion_servicio)
        self.assertIn('Total', propuesta['resumen'])
        self.assertEqual(propuesta['confirmacion']['etiqueta'], 'Sí, enviar')
        self._decir('sí', borrador['hilo_id'])
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, 'enviada')

    def test_el_lead_de_hoy_usa_el_verbo_segun_el_precio(self):
        self._decir(FRASE)
        cotizacion = CotizacionCanal.objects.get()
        fila = next(
            item for item in _filas_cotizaciones_canal(self.taller)
            if item['cotizacion_id'] == cotizacion.id
        )
        self.assertFalse(fila['listo_para_enviar'])
        self.assertTrue(fila['pendientes_revision'])
        cotizacion.repuestos = [{
            'nombre': 'Kit de embrague',
            'cantidad': 1,
            'precio_unitario_clp': 80000,
            'certeza': 'confirmado',
        }]
        meta = dict(cotizacion.metadata or {})
        meta['listo_para_enviar'] = True
        meta['pendientes_revision'] = []
        cotizacion.metadata = meta
        cotizacion.costo_repuestos_clp = Decimal('80000')
        cotizacion.save()
        fila = next(
            item for item in _filas_cotizaciones_canal(self.taller)
            if item['cotizacion_id'] == cotizacion.id
        )
        self.assertTrue(fila['listo_para_enviar'])
        self.assertEqual(fila['pendientes_revision'], [])

    def test_alta_de_servicio_del_taller_no_arma_cotizacion(self):
        self.mocks[3].return_value = ({
            'decir': '¿Qué precio le ponemos al servicio del taller?',
            'haciendo': 'Reviso el catálogo',
            'vista': {'titulo': 'Servicio', 'resumen': '', 'filas': []},
            'accion': {'tipo': 'crear_servicio', 'listo': False, 'nombre': 'Cambio de embrague'},
        }, None)
        respuesta = self._decir('Deja el cambio de embrague como servicio del taller')
        self.assertEqual(CotizacionCanal.objects.count(), 0)
        self.assertEqual(OfertaServicio.objects.filter(taller=self.taller).count(), 0)
        self.assertTrue(respuesta['ok'])

    def _ultimo_resumen(self, hilo_id):
        return AgenteDuenoMensaje.objects.filter(hilo_id=hilo_id, rol='agente').latest('id').texto

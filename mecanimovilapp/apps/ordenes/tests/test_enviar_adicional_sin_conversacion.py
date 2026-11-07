"""Envío de adicional sin conversación publica link; con conversación va al canal."""
from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
    ENTREGA_APP,
    ENTREGA_LINK_PUBLICO,
)
from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CitaAgendaPersonalDetalle,
    CotizacionCanal,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import enviar_cotizacion_libre
from mecanimovilapp.apps.usuarios.models import MiembroTaller, Taller

User = get_user_model()


class EnviarAdicionalRoutingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner_envio_ad', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.owner,
            nombre='Taller Envío Adicional',
            telefono='900000010',
            estado_verificacion='aprobado',
        )
        self.principal = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.owner,
            estado='aceptada',
            modalidad='taller',
            cliente_nombre='Cliente Base',
            cliente_telefono='+56910000001',
            servicio_nombre='Servicio base',
            mano_obra_clp=30000,
            total_clp=30000,
            token='tok-base-envio-ad',
        )
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.principal,
            fecha_servicio=date(2030, 9, 1),
            hora_servicio=time(11, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            horario_por_confirmar=False,
            creado_por=self.owner,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=self.cita,
            cliente_nombre='Cliente Base',
            servicio_nombre='Servicio base',
            precio_referencia=30000,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def _adicional(self, **kwargs):
        defaults = {
            'es_libre': False,
            'conversation': None,
            'taller': self.taller,
            'creado_por': self.owner,
            'estado': 'borrador',
            'modalidad': 'taller',
            'cliente_nombre': 'Cliente Base',
            'cliente_telefono': '+56910000001',
            'servicio_nombre': 'Trabajo adicional',
            'motivo_servicio_adicional': 'Hallazgo en la visita',
            'es_cotizacion_adicional': True,
            'cotizacion_original': self.principal,
            'cita_origen': self.cita,
            'mano_obra_clp': 15000,
            'total_clp': 15000,
        }
        defaults.update(kwargs)
        return CotizacionCanal.objects.create(**defaults)

    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_adicional_sin_conversacion_publica_link_publico(self, mock_delay):
        adicional = self._adicional()
        self.assertFalse(adicional.es_libre)
        self.assertIsNone(adicional.conversation_id)
        citas_antes = CitaAgendaPersonal.objects.filter(taller=self.taller).count()
        duracion_antes = self.cita.duracion_minutos

        resp = self.client.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')

        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['entrega_via'], ENTREGA_LINK_PUBLICO)
        self.assertIsNone(data['message_id'])
        self.assertTrue(data['share_url'])
        self.assertEqual(data['cotizacion']['estado'], 'enviada')
        self.assertNotEqual(data['cotizacion']['estado'], 'aceptada')
        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'enviada')
        self.assertIsNone(adicional.aceptada_en)
        self.assertIsNone(adicional.message_envio_id)
        self.assertTrue(adicional.token)
        self.assertEqual((adicional.metadata or {}).get('entrega_canal'), ENTREGA_LINK_PUBLICO)
        self.assertEqual(CitaAgendaPersonal.objects.filter(taller=self.taller).count(), citas_antes)
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.duracion_minutos, duracion_antes)
        mock_delay.assert_not_called()
        self.assertEqual(Message.objects.count(), 0)

        publico = APIClient().get(f'/api/ordenes/cotizaciones-publicas/{adicional.token}/')
        self.assertEqual(publico.status_code, 200, publico.content)
        self.assertEqual(publico.json()['estado'], 'enviada')
        self.assertTrue(publico.json()['puede_responder'])
        self.assertTrue(publico.json()['es_trabajo_adicional'])
        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'enviada')

    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_reenvio_no_cambia_estado_ni_crea_mensaje(self, mock_delay):
        adicional = self._adicional()
        first = self.client.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')
        self.assertEqual(first.status_code, 200, first.content)
        adicional.refresh_from_db()
        token = adicional.token
        enviada_en = adicional.enviada_en

        second = self.client.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')

        self.assertEqual(second.status_code, 400, second.content)
        self.assertIn('ya fue enviada', str(second.json()))
        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'enviada')
        self.assertEqual(adicional.token, token)
        self.assertEqual(adicional.enviada_en, enviada_en)
        self.assertIsNone(adicional.aceptada_en)
        self.assertEqual(Message.objects.count(), 0)
        mock_delay.assert_not_called()

    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_adicional_con_conversacion_va_por_canal_app(self, mock_delay):
        conversation = Conversation.objects.create(
            type='OMNICHANNEL',
            source_channel='APP',
        )
        conversation.participants.add(self.owner)
        adicional = self._adicional(conversation=conversation)
        citas_antes = CitaAgendaPersonal.objects.filter(taller=self.taller).count()

        resp = self.client.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')

        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['entrega_via'], ENTREGA_APP)
        self.assertIsNotNone(data['message_id'])
        self.assertEqual(data['cotizacion']['estado'], 'enviada')
        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'enviada')
        self.assertIsNone(adicional.aceptada_en)
        self.assertEqual(adicional.message_envio_id, data['message_id'])
        message = Message.objects.get(pk=data['message_id'])
        self.assertEqual(message.conversation_id, conversation.id)
        self.assertEqual(message.direction, 'outbound')
        self.assertEqual(CitaAgendaPersonal.objects.filter(taller=self.taller).count(), citas_antes)
        mock_delay.assert_not_called()

        again = self.client.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')
        self.assertEqual(again.status_code, 400, again.content)
        self.assertEqual(Message.objects.filter(conversation=conversation).count(), 1)
        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'enviada')
        mock_delay.assert_not_called()

    def test_helper_rechaza_si_hay_conversacion(self):
        conversation = Conversation.objects.create(type='OMNICHANNEL', source_channel='APP')
        adicional = self._adicional(conversation=conversation)
        with self.assertRaises(ValueError) as ctx:
            enviar_cotizacion_libre(adicional)
        self.assertIn('enviar_cotizacion_canal', str(ctx.exception))
        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'borrador')

    def test_mecanico_no_envia_y_otro_taller_no_ve_el_adicional(self):
        adicional = self._adicional()
        mecanico_user = User.objects.create_user(username='mec_envio_ad', password='test123')
        MiembroTaller.objects.create(
            taller=self.taller,
            usuario=mecanico_user,
            rol='mecanico',
            nombre='Mecánico Envío',
            activo=True,
        )
        otro = User.objects.create_user(username='otro_envio_ad', password='test123')
        Taller.objects.create(
            usuario=otro,
            nombre='Otro Taller',
            telefono='900000011',
            estado_verificacion='aprobado',
        )

        mec = APIClient()
        mec.force_authenticate(user=mecanico_user)
        resp_mec = mec.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')
        self.assertEqual(resp_mec.status_code, 404, resp_mec.content)
        resp_mec_get = mec.get(f'/api/ordenes/cotizaciones-canal/{adicional.id}/')
        self.assertEqual(resp_mec_get.status_code, 404, resp_mec_get.content)

        ajeno = APIClient()
        ajeno.force_authenticate(user=otro)
        resp_ajeno = ajeno.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')
        self.assertEqual(resp_ajeno.status_code, 404, resp_ajeno.content)

        anon = APIClient()
        resp_anon = anon.post(f'/api/ordenes/cotizaciones-canal/{adicional.id}/enviar/')
        self.assertIn(resp_anon.status_code, (401, 403))

        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'borrador')
        self.assertIsNone(adicional.aceptada_en)

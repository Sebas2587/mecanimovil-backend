"""Tests de ventana de 24 h y plan de entrega de cotización."""
from datetime import date, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
    ENTREGA_LINK_PUBLICO,
    ENTREGA_SESION_META,
    ENTREGA_WHATSAPP_TEMPLATE,
    OutboundBlockedError,
    plan_entrega_cotizacion,
    validate_omnichannel_outbound,
)
from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class VentanaAtencionEntregaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_ventana', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Ventana',
            telefono='900000001',
            estado_verificacion='aprobado',
        )
        ct = ContentType.objects.get_for_model(Taller)
        self.connection = ProviderChannelConnection.objects.create(
            content_type=ct,
            object_id=self.taller.id,
            usuario=self.user,
            channel='WHATSAPP',
            enabled=True,
            status='conectada',
            phone_number_id='123456',
            access_token='token',
        )
        self.contact = ExternalContact.objects.create(
            connection=self.connection,
            channel='WHATSAPP',
            external_id='56988887777',
            display_name='Ana',
        )
        self.conversation = Conversation.objects.create(
            type='OMNICHANNEL',
            source_channel='WHATSAPP',
            external_contact=self.contact,
        )
        self.conversation.participants.add(self.user)

    def _inbound(self, hours_ago: float) -> Message:
        msg = Message.objects.create(
            conversation=self.conversation,
            content='Hola',
            direction='inbound',
        )
        Message.objects.filter(pk=msg.pk).update(
            timestamp=timezone.now() - timedelta(hours=hours_ago),
        )
        return msg

    def test_ventana_abierta_entrega_por_sesion(self):
        self._inbound(hours_ago=2)
        plan = plan_entrega_cotizacion(self.conversation)
        self.assertEqual(plan.via, ENTREGA_SESION_META)
        self.assertTrue(plan.should_send_meta)
        self.assertFalse(plan.use_template)
        validate_omnichannel_outbound(self.conversation)

    def test_ventana_cerrada_sin_plantilla_usa_link(self):
        self._inbound(hours_ago=25)
        plan = plan_entrega_cotizacion(self.conversation)
        self.assertEqual(plan.via, ENTREGA_LINK_PUBLICO)
        self.assertFalse(plan.should_send_meta)
        with self.assertRaises(OutboundBlockedError) as ctx:
            validate_omnichannel_outbound(self.conversation)
        self.assertEqual(ctx.exception.code, 'whatsapp_window_closed')

    @override_settings(WHATSAPP_TEMPLATE_COTIZACION='cotizacion_lista')
    def test_ventana_cerrada_sin_flag_ignora_plantilla(self):
        self._inbound(hours_ago=30)
        plan = plan_entrega_cotizacion(self.conversation)
        self.assertEqual(plan.via, ENTREGA_LINK_PUBLICO)
        self.assertFalse(plan.should_send_meta)
        self.assertFalse(plan.use_template)

    @override_settings(
        WHATSAPP_TEMPLATES_ENABLED=True,
        WHATSAPP_TEMPLATE_COTIZACION='cotizacion_lista',
    )
    def test_ventana_cerrada_con_plantilla_whatsapp(self):
        self._inbound(hours_ago=30)
        plan = plan_entrega_cotizacion(self.conversation)
        self.assertEqual(plan.via, ENTREGA_WHATSAPP_TEMPLATE)
        self.assertTrue(plan.should_send_meta)
        self.assertTrue(plan.use_template)

    def test_instagram_ventana_cerrada_solo_link(self):
        self.conversation.source_channel = 'INSTAGRAM'
        self.conversation.save(update_fields=['source_channel'])
        self.connection.channel = 'INSTAGRAM'
        self.connection.instagram_account_id = 'IG1'
        self.connection.save(update_fields=['channel', 'instagram_account_id'])
        self._inbound(hours_ago=26)
        plan = plan_entrega_cotizacion(self.conversation)
        self.assertEqual(plan.via, ENTREGA_LINK_PUBLICO)
        self.assertFalse(plan.should_send_meta)
        with self.assertRaises(OutboundBlockedError) as ctx:
            validate_omnichannel_outbound(self.conversation)
        self.assertEqual(ctx.exception.code, 'instagram_window_closed')

    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_cotizacion_ventana_cerrada_no_llama_meta(self, mock_delay):
        self._inbound(hours_ago=26)
        cot = CotizacionCanal.objects.create(
            conversation=self.conversation,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            cliente_nombre='Ana',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            servicio_nombre='Diagnóstico',
            mano_obra_clp=40000,
            total_clp=40000,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/ordenes/cotizaciones-canal/{cot.id}/enviar/')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['entrega_via'], ENTREGA_LINK_PUBLICO)
        self.assertTrue(data['share_url'])
        mock_delay.assert_not_called()
        cot.refresh_from_db()
        self.assertEqual(cot.estado, 'enviada')
        self.assertEqual((cot.metadata or {}).get('entrega_canal'), ENTREGA_LINK_PUBLICO)

    @override_settings(
        WHATSAPP_TEMPLATES_ENABLED=True,
        WHATSAPP_TEMPLATE_COTIZACION='cotizacion_lista',
    )
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_cotizacion_ventana_cerrada_usa_plantilla(self, mock_delay):
        self._inbound(hours_ago=26)
        cot = CotizacionCanal.objects.create(
            conversation=self.conversation,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            servicio_nombre='Cambio de aceite',
            mano_obra_clp=25000,
            total_clp=25000,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/ordenes/cotizaciones-canal/{cot.id}/enviar/')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['entrega_via'], ENTREGA_WHATSAPP_TEMPLATE)
        self.assertTrue(data['share_url'])
        mock_delay.assert_called_once()

    @override_settings(WHATSAPP_TEMPLATES_ENABLED=True)
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_aviso_ventana_abierta_pide_escribir(self, mock_delay):
        self._inbound(hours_ago=2)
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/chat/conversations/{self.conversation.id}/enviar-aviso/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'ventana_abierta')
        mock_delay.assert_not_called()

    @override_settings(WHATSAPP_TEMPLATE_COTIZACION='cotizacion_lista')
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_cotizacion_ventana_abierta_no_usa_plantilla(self, mock_delay):
        self._inbound(hours_ago=2)
        cot = CotizacionCanal.objects.create(
            conversation=self.conversation,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            servicio_nombre='Diagnóstico',
            mano_obra_clp=40000,
            total_clp=40000,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/ordenes/cotizaciones-canal/{cot.id}/enviar/')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['entrega_via'], ENTREGA_SESION_META)
        mock_delay.assert_called_once()
        cot.refresh_from_db()
        self.assertEqual((cot.metadata or {}).get('entrega_canal'), ENTREGA_SESION_META)
        message = Message.objects.get(pk=data['message_id'])
        self.assertFalse((message.channel_metadata or {}).get('whatsapp_template'))

    @override_settings(WHATSAPP_TEMPLATE_AVISO='aviso_taller')
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_aviso_deshabilitado_por_defecto(self, mock_delay):
        self._inbound(hours_ago=26)
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/chat/conversations/{self.conversation.id}/enviar-aviso/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'plantillas_deshabilitadas')
        mock_delay.assert_not_called()

    @override_settings(
        WHATSAPP_TEMPLATES_ENABLED=True,
        WHATSAPP_TEMPLATE_AVISO='aviso_taller',
    )
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_aviso_whatsapp_ventana_cerrada(self, mock_delay):
        self._inbound(hours_ago=26)
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/chat/conversations/{self.conversation.id}/enviar-aviso/')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['template_kind'], 'aviso')
        mock_delay.assert_called_once()

    @override_settings(
        WHATSAPP_TEMPLATES_ENABLED=True,
        WHATSAPP_TEMPLATE_AVISO='aviso_taller',
        WHATSAPP_TEMPLATE_CITA='cita_recordatorio',
    )
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_aviso_elige_cita_si_hay_visita(self, mock_delay):
        self._inbound(hours_ago=26)
        CitaAgendaPersonal.objects.create(
            taller=self.taller,
            conversation_origen=self.conversation,
            fecha_servicio=date(2030, 8, 22),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            horario_por_confirmar=False,
            creado_por=self.user,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/chat/conversations/{self.conversation.id}/enviar-aviso/')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['template_kind'], 'cita')
        mock_delay.assert_called_once()

    @override_settings(
        WHATSAPP_TEMPLATES_ENABLED=True,
        WHATSAPP_TEMPLATE_AVISO='aviso_taller',
        WHATSAPP_TEMPLATE_CITA='cita_recordatorio',
    )
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_aviso_elige_cita_si_horario_por_confirmar(self, mock_delay):
        self._inbound(hours_ago=26)
        CitaAgendaPersonal.objects.create(
            taller=self.taller,
            conversation_origen=self.conversation,
            fecha_servicio=date(2020, 1, 1),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            horario_por_confirmar=True,
            creado_por=self.user,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/chat/conversations/{self.conversation.id}/enviar-aviso/')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['template_kind'], 'cita')
        mock_delay.assert_called_once()

    @override_settings(WHATSAPP_TEMPLATES_ENABLED=True)
    @patch('mecanimovilapp.apps.omnichannel.tasks.send_meta_message.delay')
    def test_enviar_aviso_instagram_no_llama_meta(self, mock_delay):
        self.conversation.source_channel = 'INSTAGRAM'
        self.conversation.save(update_fields=['source_channel'])
        self.connection.channel = 'INSTAGRAM'
        self.connection.instagram_account_id = 'IG1'
        self.connection.save(update_fields=['channel', 'instagram_account_id'])
        self._inbound(hours_ago=26)
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post(f'/api/chat/conversations/{self.conversation.id}/enviar-aviso/')
        self.assertEqual(resp.status_code, 403)
        mock_delay.assert_not_called()

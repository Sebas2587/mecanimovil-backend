"""Tests omnicanal Meta."""
import hashlib
import hmac
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from mecanimovilapp.apps.omnichannel.utils import verify_meta_signature, channel_to_api_slug
from mecanimovilapp.apps.omnichannel.services.omnichannel_service import (
    OmnichannelService,
    is_meta_instagram_test_webhook,
)
from mecanimovilapp.apps.omnichannel.models import ProviderChannelConnection
from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.chat.models import Conversation, Message

User = get_user_model()


class MetaSignatureTests(SimpleTestCase):
    def test_verify_valid_signature(self):
        body = b'{"object":"whatsapp_business_account"}'
        sig = 'sha256=' + hmac.new(b'testsecret', body, hashlib.sha256).hexdigest()
        with patch('mecanimovilapp.apps.omnichannel.utils.meta_app_secret', return_value='testsecret'):
            self.assertTrue(verify_meta_signature(body, sig))

    def test_reject_invalid_signature(self):
        with patch('mecanimovilapp.apps.omnichannel.utils.meta_app_secret', return_value='testsecret'):
            self.assertFalse(verify_meta_signature(b'{}', 'sha256=bad'))


class FriendlyOAuthErrorTests(SimpleTestCase):
    def test_hides_technical_http_error(self):
        from mecanimovilapp.apps.omnichannel.utils import MetaOAuthExchangeError, friendly_oauth_error

        msg = friendly_oauth_error(MetaOAuthExchangeError(400, '{"error":"invalid_grant"}'))
        self.assertNotIn('http', msg)
        self.assertIn('expiró', msg)

    def test_hides_raw_exception_with_url(self):
        from mecanimovilapp.apps.omnichannel.utils import friendly_oauth_error

        msg = friendly_oauth_error(
            Exception('400 Client Error for url: https://graph.facebook.com/...&client_secret=secret')
        )
        self.assertNotIn('secret', msg)
        self.assertNotIn('graph.facebook', msg)


class WhatsAppConnectDiagnosticsTests(SimpleTestCase):
    def _client(self, **overrides):
        from unittest.mock import MagicMock

        client = MagicMock()
        client.granted_scopes.return_value = set()
        client.get_user_businesses.return_value = []
        client.get_granted_waba_ids.return_value = []
        client.get_whatsapp_business_accounts.return_value = []
        client.get_client_whatsapp_business_accounts.return_value = []
        client.get_phone_numbers.return_value = []
        for key, value in overrides.items():
            getattr(client, key).return_value = value
        return client

    def test_personal_facebook_sin_negocio(self):
        from mecanimovilapp.apps.omnichannel.services.whatsapp_connect_diagnostics import (
            diagnose_whatsapp_connection_gap,
        )

        diagnosis = diagnose_whatsapp_connection_gap(self._client(), 'token')
        self.assertEqual(diagnosis.error_code, 'facebook_sin_negocio')
        self.assertIn('Facebook personal', diagnosis.message)

    def test_negocio_sin_whatsapp_business(self):
        from mecanimovilapp.apps.omnichannel.services.whatsapp_connect_diagnostics import (
            diagnose_whatsapp_connection_gap,
        )

        client = self._client(get_user_businesses=[{'id': 'biz-1'}])
        diagnosis = diagnose_whatsapp_connection_gap(client, 'token')
        self.assertEqual(diagnosis.error_code, 'sin_whatsapp_business')
        self.assertIn('WhatsApp personal', diagnosis.message)

    def test_waba_sin_numero(self):
        from mecanimovilapp.apps.omnichannel.services.whatsapp_connect_diagnostics import (
            diagnose_whatsapp_connection_gap,
        )

        client = self._client(
            get_granted_waba_ids=['waba-1'],
            get_user_businesses=[{'id': 'biz-1'}],
        )
        diagnosis = diagnose_whatsapp_connection_gap(client, 'token')
        self.assertEqual(diagnosis.error_code, 'sin_numero_whatsapp')

    def test_scopes_sin_waba_ni_negocio(self):
        from mecanimovilapp.apps.omnichannel.services.whatsapp_connect_diagnostics import (
            diagnose_whatsapp_connection_gap,
        )

        client = self._client(
            granted_scopes={'whatsapp_business_management'},
        )
        diagnosis = diagnose_whatsapp_connection_gap(client, 'token')
        self.assertEqual(diagnosis.error_code, 'sin_permisos_admin')

    def test_numero_en_la_app_pide_vincular_el_telefono(self):
        from mecanimovilapp.apps.omnichannel.services.whatsapp_connect_diagnostics import (
            diagnose_phone_not_ready,
        )

        diagnosis = diagnose_phone_not_ready({
            'platform_type': 'ON_PREMISE',
            'is_on_biz_app': True,
            'code_verification_status': 'NOT_VERIFIED',
            'status': 'CONNECTED',
        })
        self.assertEqual(diagnosis.error_code, 'whatsapp_en_el_telefono')
        self.assertIn('app WhatsApp Business', diagnosis.message)
        self.assertIn('Cambiar número', diagnosis.instruction)


class EmbeddedConfigTests(SimpleTestCase):
    def test_build_embedded_config_requires_app_and_config_id(self):
        from mecanimovilapp.apps.omnichannel.utils import build_embedded_config_payload

        with patch('mecanimovilapp.apps.omnichannel.utils.meta_app_id', return_value='123'):
            with patch(
                'mecanimovilapp.apps.omnichannel.utils.meta_embedded_signup_config_id_for_channel',
                return_value='',
            ):
                self.assertIsNone(build_embedded_config_payload('WHATSAPP'))

        with patch('mecanimovilapp.apps.omnichannel.utils.meta_app_id', return_value='123'):
            with patch(
                'mecanimovilapp.apps.omnichannel.utils.meta_embedded_signup_config_id_for_channel',
                return_value='cfg-abc',
            ):
                payload = build_embedded_config_payload('WHATSAPP')
                self.assertTrue(payload['enabled'])
                self.assertEqual(payload['config_id'], 'cfg-abc')

    def test_oauth_whatsapp_pide_vincular_la_app_del_telefono(self):
        from urllib.parse import parse_qs, urlparse

        from mecanimovilapp.apps.omnichannel.utils import (
            build_embedded_signup_url,
            sdk_redirect_permitido,
        )

        with patch('mecanimovilapp.apps.omnichannel.utils.meta_app_id', return_value='123'):
            with patch(
                'mecanimovilapp.apps.omnichannel.utils.meta_oauth_redirect_uri',
                return_value='https://api.example/callback',
            ):
                with patch(
                    'mecanimovilapp.apps.omnichannel.utils.meta_embedded_signup_config_id_for_channel',
                    return_value='cfg-wa',
                ):
                    with patch(
                        'mecanimovilapp.apps.omnichannel.utils.meta_graph_version',
                        return_value='v21.0',
                    ):
                        url = build_embedded_signup_url('state-1', 'WHATSAPP')
        self.assertIn('/api/omnichannel/oauth/alta-whatsapp/', url)
        self.assertEqual(parse_qs(urlparse(url).query)['state'][0], 'state-1')
        with patch(
            'mecanimovilapp.apps.omnichannel.utils.meta_oauth_redirect_uri',
            return_value='https://api.example/api/omnichannel/oauth/callback/',
        ):
            self.assertTrue(sdk_redirect_permitido(
                'https://api.example/api/omnichannel/oauth/alta-whatsapp/?state=state-1',
            ))
            self.assertFalse(sdk_redirect_permitido('https://evil.example/alta-whatsapp/'))


class ChannelSlugTests(SimpleTestCase):
    def test_slugs(self):
        self.assertEqual(channel_to_api_slug('WHATSAPP'), 'whatsapp')
        self.assertEqual(channel_to_api_slug('APP'), 'app')


class MetaGraphGranularScopeTests(SimpleTestCase):
    def test_granted_waba_ids_from_debug_token(self):
        from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient

        client = MetaGraphClient()
        with patch.object(
            client,
            'debug_token',
            return_value={
                'granular_scopes': [
                    {'scope': 'whatsapp_business_management', 'target_ids': ['540742045781983']},
                ],
            },
        ):
            self.assertEqual(client.get_granted_waba_ids('token'), ['540742045781983'])

    def test_deprioritizes_wp_tel_waba(self):
        from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient

        real_score = MetaGraphClient._waba_priority_score('526378307216132', 'Mecanimovil', [])
        test_score = MetaGraphClient._waba_priority_score('2665080507196211', 'wp_tel', [])
        self.assertLess(real_score[0], test_score[0])


class OmnichannelServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_omni', password='pass')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Omni',
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
            display_identifier='+56911112222',
        )

    def test_ingest_inbound_creates_conversation(self):
        msg = OmnichannelService.ingest_inbound_message(
            self.connection,
            external_id='56999998888',
            text='Hola taller',
            external_message_id='wamid.TEST001',
            display_name='Juan Cliente',
            phone='+56999998888',
        )
        self.assertIsNotNone(msg)
        self.assertEqual(Conversation.objects.filter(source_channel='WHATSAPP').count(), 1)
        conv = Conversation.objects.first()
        self.assertEqual(conv.external_contact.display_name, 'Juan Cliente')
        self.assertEqual(msg.direction, 'inbound')

    def test_duplicate_external_message_ignored(self):
        OmnichannelService.ingest_inbound_message(
            self.connection,
            external_id='56999998888',
            text='Uno',
            external_message_id='wamid.DUP',
        )
        OmnichannelService.ingest_inbound_message(
            self.connection,
            external_id='56999998888',
            text='Dos',
            external_message_id='wamid.DUP',
        )
        self.assertEqual(Message.objects.filter(external_message_id='wamid.DUP').count(), 1)

    def test_parse_whatsapp_payload(self):
        body = {
            'object': 'whatsapp_business_account',
            'entry': [{
                'changes': [{
                    'value': {
                        'metadata': {'phone_number_id': '123456'},
                        'contacts': [{'profile': {'name': 'Ana'}}],
                        'messages': [{
                            'from': '56988887777',
                            'id': 'wamid.X',
                            'type': 'text',
                            'text': {'body': 'Consulta'},
                        }],
                    },
                }],
            }],
        }
        events = OmnichannelService.parse_whatsapp_payload(body)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['text'], 'Consulta')

    @patch('mecanimovilapp.apps.omnichannel.tasks.process_meta_webhook.delay')
    def test_webhook_view_queues_task(self, mock_delay):
        from django.test import Client
        body = b'{"object":"whatsapp_business_account","entry":[]}'
        with patch('mecanimovilapp.apps.omnichannel.views.omnichannel_enabled', return_value=True), \
             patch('mecanimovilapp.apps.omnichannel.views.verify_meta_signature', return_value=True):
            client = Client()
            resp = client.post(
                '/api/omnichannel/webhooks/meta/',
                data=body,
                content_type='application/json',
                HTTP_X_HUB_SIGNATURE_256='sha256=x',
            )
            self.assertEqual(resp.status_code, 200)
            mock_delay.assert_called_once()

    def test_resolve_instagram_by_page_or_ig_account_id(self):
        ct = ContentType.objects.get_for_model(Taller)
        ig_conn = ProviderChannelConnection.objects.create(
            content_type=ct,
            object_id=self.taller.id,
            usuario=self.user,
            channel='INSTAGRAM',
            enabled=True,
            status='conectada',
            page_id='PAGE123',
            instagram_account_id='IG456',
            access_token='token',
        )
        by_ig = OmnichannelService.resolve_connection_for_page('IG456', 'INSTAGRAM')
        by_page = OmnichannelService.resolve_connection_for_page('PAGE123', 'INSTAGRAM')
        self.assertEqual(by_ig.id, ig_conn.id)
        self.assertEqual(by_page.id, ig_conn.id)

    def test_process_instagram_webhook(self):
        ct = ContentType.objects.get_for_model(Taller)
        ProviderChannelConnection.objects.create(
            content_type=ct,
            object_id=self.taller.id,
            usuario=self.user,
            channel='INSTAGRAM',
            enabled=True,
            status='conectada',
            page_id='PAGE123',
            instagram_account_id='IG456',
            access_token='token',
        )
        body = {
            'object': 'instagram',
            'entry': [{
                'id': 'IG456',
                'messaging': [{
                    'sender': {'id': 'user789'},
                    'recipient': {'id': 'IG456'},
                    'timestamp': 1710000000,
                    'message': {'mid': 'mid.IG1', 'text': 'Hola IG'},
                }],
            }],
        }
        count = OmnichannelService.process_webhook_body(body)
        self.assertEqual(count, 1)
        self.assertEqual(Conversation.objects.filter(source_channel='INSTAGRAM').count(), 1)

    def test_meta_instagram_test_webhook_is_detected(self):
        self.assertTrue(
            is_meta_instagram_test_webhook('0', '23245', '12334'),
        )

    def test_process_instagram_webhook_meta_test_payload_ignored(self):
        body = {
            'object': 'instagram',
            'entry': [{
                'id': '0',
                'time': 1527459824,
                'changes': [{
                    'field': 'messages',
                    'value': {
                        'sender': {'id': '12334'},
                        'recipient': {'id': '23245'},
                        'timestamp': '1527459824',
                        'message': {'mid': 'random_mid', 'text': 'random_text'},
                    },
                }],
            }],
        }
        count = OmnichannelService.process_webhook_body(body)
        self.assertEqual(count, 0)

    def test_process_instagram_webhook_changes_format_with_real_recipient(self):
        ct = ContentType.objects.get_for_model(Taller)
        ProviderChannelConnection.objects.create(
            content_type=ct,
            object_id=self.taller.id,
            usuario=self.user,
            channel='INSTAGRAM',
            enabled=True,
            status='conectada',
            page_id='PAGE123',
            instagram_account_id='IG456',
            access_token='token',
        )
        body = {
            'object': 'instagram',
            'entry': [{
                'id': '0',
                'time': 1527459824,
                'changes': [{
                    'field': 'messages',
                    'value': {
                        'sender': {'id': 'user789'},
                        'recipient': {'id': 'IG456'},
                        'timestamp': '1527459824',
                        'message': {'mid': 'mid.IG2', 'text': 'Hola desde changes'},
                    },
                }],
            }],
        }
        count = OmnichannelService.process_webhook_body(body)
        self.assertEqual(count, 1)


class MetaSendRetryTests(SimpleTestCase):
    def test_reintenta_error_131000_y_5xx(self):
        from unittest.mock import MagicMock

        from mecanimovilapp.apps.omnichannel.tasks import _meta_reintenta

        resp_131000 = MagicMock()
        resp_131000.status_code = 400
        resp_131000.json.return_value = {'error': {'code': 131000, 'message': 'Something went wrong'}}
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.json.return_value = {}
        resp_perm = MagicMock()
        resp_perm.status_code = 400
        resp_perm.json.return_value = {'error': {'code': 131047, 'message': 're-engagement'}}

        self.assertTrue(_meta_reintenta(resp_131000))
        self.assertTrue(_meta_reintenta(resp_500))
        self.assertFalse(_meta_reintenta(resp_perm))


class RenovarTokenMetaTests(SimpleTestCase):
    def _conn(self, **kwargs):
        from datetime import timedelta
        from unittest.mock import MagicMock

        from django.utils import timezone

        conn = MagicMock()
        conn.access_token = 'viejo'
        conn.token_no_expira = False
        conn.token_expires_at = timezone.now() + timedelta(days=40)
        conn.channel = 'WHATSAPP'
        conn.id = 'abc'
        conn.status = 'conectada'
        for key, value in kwargs.items():
            setattr(conn, key, value)
        return conn

    def test_no_toca_un_permiso_que_aun_dura(self):
        from unittest.mock import MagicMock

        from mecanimovilapp.apps.omnichannel.services.token_meta import renovar_conexion

        conn = self._conn()
        client = MagicMock()
        self.assertEqual(renovar_conexion(conn, client), 'omitida')
        client.extender_token.assert_not_called()

    def test_renueva_cuando_faltan_menos_de_14_dias(self):
        from datetime import timedelta
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from django.utils import timezone

        from mecanimovilapp.apps.omnichannel.services.token_meta import renovar_conexion

        conn = self._conn(token_expires_at=timezone.now() + timedelta(days=5))
        client = MagicMock()
        client.extender_token.return_value = {'access_token': 'nuevo', 'expires_in': 5183944}
        client.clasificar_expiracion.return_value = SimpleNamespace(
            expires_at=timezone.now() + timedelta(days=60),
            never=False,
            known=True,
        )
        self.assertEqual(renovar_conexion(conn, client), 'renovada')
        self.assertEqual(conn.access_token, 'nuevo')
        conn.save.assert_called()

    def test_permiso_sin_vencimiento_no_se_renueva(self):
        from unittest.mock import MagicMock

        from mecanimovilapp.apps.omnichannel.services.token_meta import renovar_conexion

        conn = self._conn(token_no_expira=True)
        client = MagicMock()
        self.assertEqual(renovar_conexion(conn, client), 'omitida')
        client.extender_token.assert_not_called()

    def test_si_ya_vencio_y_meta_no_renueva_pide_conectar(self):
        from datetime import timedelta
        from unittest.mock import MagicMock

        from django.utils import timezone

        from mecanimovilapp.apps.omnichannel.services.token_meta import renovar_conexion

        conn = self._conn(token_expires_at=timezone.now() - timedelta(hours=1))
        client = MagicMock()
        client.extender_token.return_value = None
        self.assertEqual(renovar_conexion(conn, client), 'fallo')
        self.assertEqual(conn.status, 'error')
        self.assertIn('Conectar', conn.mensaje_estado)


class NumeroWhatsappListoTests(SimpleTestCase):
    def test_codigo_sin_verificacion_no_deja_mensajear(self):
        from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient

        client = MetaGraphClient()
        self.assertFalse(client.numero_listo_para_mensajeria({
            'code_verification_status': 'NOT_VERIFIED',
            'status': 'CONNECTED',
        }))
        self.assertTrue(client.numero_listo_para_mensajeria({
            'code_verification_status': 'VERIFIED',
            'status': 'CONNECTED',
        }))
        self.assertFalse(client.numero_listo_para_mensajeria({
            'code_verification_status': 'NOT_VERIFIED',
            'status': 'CONNECTED',
            'platform_type': 'ON_PREMISE',
            'is_on_biz_app': True,
        }))
        self.assertTrue(client.numero_listo_para_mensajeria({
            'code_verification_status': 'NOT_VERIFIED',
            'status': 'CONNECTED',
            'platform_type': 'CLOUD_API',
            'is_on_biz_app': True,
        }))
        self.assertFalse(client.numero_listo_para_mensajeria({
            'code_verification_status': 'NOT_VERIFIED',
            'status': 'DISCONNECTED',
        }))


class CoexistenciaTests(TestCase):
    """El taller sigue usando la app del teléfono y el chat lo refleja."""

    PHONE_ID = '777'

    def setUp(self):
        self.user = User.objects.create_user(username='taller_coex', password='pass')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Coex',
            telefono='900000003',
            estado_verificacion='aprobado',
        )
        self.conn = ProviderChannelConnection.objects.create(
            content_type=ContentType.objects.get_for_model(Taller),
            object_id=self.taller.id,
            usuario=self.user,
            channel='WHATSAPP',
            enabled=True,
            status='conectada',
            phone_number_id=self.PHONE_ID,
            access_token='token',
            display_identifier='+56 9 1111 2222',
            display_name='Taller Coex',
        )

    def _body(self, field, value):
        return {
            'object': 'whatsapp_business_account',
            'entry': [{'id': 'waba', 'changes': [{
                'field': field,
                'value': {
                    'messaging_product': 'whatsapp',
                    'metadata': {'display_phone_number': '56911112222', 'phone_number_id': self.PHONE_ID},
                    **value,
                },
            }]}],
        }

    def test_respuesta_desde_el_telefono_pausa_al_agente(self):
        from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion

        OmnichannelService.ingest_inbound_message(
            self.conn, external_id='56999998888', text='Hola', external_message_id='wamid.IN1',
        )
        conv = Conversation.objects.get(source_channel='WHATSAPP')
        AgenteConversacionSesion.objects.create(
            conversation=conv, taller=self.taller, habilitado_en_chat=True,
            estado=AgenteConversacionSesion.ESTADO_CAPTURANDO,
        )

        with patch('mecanimovilapp.apps.agente_ia.hooks.agente_ia_habilitado', return_value=True):
            OmnichannelService.process_webhook_body(self._body('smb_message_echoes', {
                'message_echoes': [{
                    'from': '56911112222', 'to': '56999998888', 'id': 'wamid.ECO1',
                    'timestamp': '1739230955', 'type': 'text', 'text': {'body': 'Te llamo'},
                }],
            }))

        eco = Message.objects.get(external_message_id='wamid.ECO1')
        self.assertEqual(eco.direction, 'outbound')
        self.assertEqual(eco.sender_id, self.user.id)
        self.assertEqual(eco.conversation_id, conv.id)
        self.assertEqual(eco.channel_metadata['origen'], 'app_whatsapp')
        sesion = AgenteConversacionSesion.objects.get(conversation=conv)
        self.assertTrue(sesion.pausado_por_taller)
        self.assertEqual(sesion.estado, AgenteConversacionSesion.ESTADO_PAUSADO)

        # El mismo eco repetido no duplica.
        OmnichannelService.process_webhook_body(self._body('smb_message_echoes', {
            'message_echoes': [{'from': '56911112222', 'to': '56999998888', 'id': 'wamid.ECO1',
                                'type': 'text', 'text': {'body': 'Te llamo'}}],
        }))
        self.assertEqual(Message.objects.filter(external_message_id='wamid.ECO1').count(), 1)

    def test_historial_compartido_queda_visible_y_ordenado(self):
        from mecanimovilapp.apps.omnichannel.services.omnichannel_service import (
            corte_bandeja,
            mensaje_visible_en_bandeja,
        )

        with patch('mecanimovilapp.apps.agente_ia.tasks.procesar_mensaje_entrante_task.delay') as agente:
            OmnichannelService.process_webhook_body(self._body('history', {
                'history': [{
                    'metadata': {'phase': 0, 'chunk_order': 1, 'progress': 100},
                    'threads': [{
                        'id': '56977776666',
                        'messages': [
                            {'from': '56911112222', 'id': 'wamid.H1', 'timestamp': '1700000000',
                             'type': 'text', 'text': {'body': 'Su auto está listo'},
                             'history_context': {'status': 'READ'}},
                            {'from': '56977776666', 'id': 'wamid.H2', 'timestamp': '1700000100',
                             'type': 'text', 'text': {'body': 'Gracias!'},
                             'history_context': {'status': 'READ'}},
                            {'from': '56911112222', 'id': 'wamid.H3', 'timestamp': '1700000200',
                             'type': 'media_placeholder', 'history_context': {'status': 'PLAYED'}},
                        ],
                    }],
                }],
            }))
        agente.assert_not_called()

        conv = Conversation.objects.get(source_channel='WHATSAPP')
        self.assertEqual(conv.external_contact.external_id, '56977776666')
        msgs = list(conv.messages.order_by('timestamp'))
        self.assertEqual([m.external_message_id for m in msgs], ['wamid.H1', 'wamid.H2', 'wamid.H3'])
        self.assertEqual([m.direction for m in msgs], ['outbound', 'inbound', 'outbound'])
        self.assertEqual(msgs[0].timestamp.year, 2023)
        self.assertTrue(all(m.is_read for m in msgs))
        corte = corte_bandeja(self.conn)
        self.assertTrue(all(mensaje_visible_en_bandeja(m, corte) for m in msgs))

    def test_agenda_del_telefono_pone_nombre_a_contactos_con_chat(self):
        OmnichannelService.ingest_inbound_message(
            self.conn, external_id='56999998888', text='Hola', external_message_id='wamid.IN2',
        )
        OmnichannelService.process_webhook_body(self._body('smb_app_state_sync', {
            'state_sync': [
                {'type': 'contact', 'action': 'add',
                 'contact': {'full_name': 'Pedro Cliente', 'first_name': 'Pedro', 'phone_number': '+56999998888'}},
                {'type': 'contact', 'action': 'add',
                 'contact': {'full_name': 'Sin Chat', 'first_name': 'Sin', 'phone_number': '+56900000000'}},
            ],
        }))
        contacto = Conversation.objects.get(source_channel='WHATSAPP').external_contact
        self.assertEqual(contacto.display_name, 'Pedro Cliente')
        self.assertEqual(Conversation.objects.filter(source_channel='WHATSAPP').count(), 1)

    def test_al_vincular_la_app_se_pide_agenda_e_historial(self):
        from unittest.mock import MagicMock

        from mecanimovilapp.apps.omnichannel.services.meta_oauth import _sincronizar_app_del_telefono

        client = MagicMock()
        _sincronizar_app_del_telefono(client, self.conn, {'is_on_biz_app': True, 'platform_type': 'CLOUD_API'})
        tipos = [c.args[2] for c in client.solicitar_sincronizacion_app.call_args_list]
        self.assertEqual(tipos, ['smb_app_state_sync', 'history'])

        client.reset_mock()
        _sincronizar_app_del_telefono(client, self.conn, {'is_on_biz_app': False, 'platform_type': 'CLOUD_API'})
        client.solicitar_sincronizacion_app.assert_not_called()


class CambioNumeroWhatsappTests(TestCase):
    NUEVO = {
        'id': '999',
        'display_phone_number': '+56 9 4482 9287',
        'verified_name': 'Taller Omni',
        'code_verification_status': 'VERIFIED',
    }

    def setUp(self):
        self.user = User.objects.create_user(username='taller_cambio', password='pass')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Cambio',
            telefono='900000002',
            estado_verificacion='aprobado',
        )
        self.conn = ProviderChannelConnection.objects.create(
            content_type=ContentType.objects.get_for_model(Taller),
            object_id=self.taller.id,
            usuario=self.user,
            channel='WHATSAPP',
            enabled=True,
            status='conectada',
            phone_number_id='111',
            waba_id='waba-1',
            access_token='token-viejo',
            display_identifier='+56911112222',
            oauth_state='state-cambio',
            alta_modo='numero_nuevo',
            numero_solicitado='56944829287',
        )

    def _client(self, phone_states, registro_ok=True):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient

        real = MetaGraphClient()
        client = MagicMock()
        client.exchange_code.return_value = {'access_token': 'token-nuevo'}
        client.extender_token_si_vence_pronto.side_effect = lambda token: token
        client.clasificar_expiracion.return_value = SimpleNamespace(
            expires_at=None, never=True, known=True,
        )
        client.resolve_whatsapp_from_waba_ids.return_value = {
            'waba_id': 'waba-1',
            'phone_number_id': '999',
            'display_identifier': '+56 9 4482 9287',
            'display_name': 'Taller Omni',
        }
        client.get_granted_waba_ids.return_value = ['waba-1']
        client.get_phone_number_by_id.side_effect = phone_states
        client.numero_listo_para_mensajeria.side_effect = real.numero_listo_para_mensajeria
        client.registrar_numero.return_value = registro_ok
        return client

    def _completar(self, client):
        from mecanimovilapp.apps.omnichannel.services.meta_oauth import complete_meta_oauth_connection

        with patch(
            'mecanimovilapp.apps.omnichannel.services.meta_oauth.MetaGraphClient',
            return_value=client,
        ):
            return complete_meta_oauth_connection(self.conn, 'code')

    def test_numero_nuevo_se_registra_y_los_chats_siguen(self):
        OmnichannelService.ingest_inbound_message(
            self.conn,
            external_id='56999998888',
            text='Hola',
            external_message_id='wamid.ANTES',
        )
        pendiente = {**self.NUEVO, 'status': 'PENDING', 'platform_type': 'NOT_APPLICABLE'}
        listo = {**self.NUEVO, 'status': 'CONNECTED', 'platform_type': 'CLOUD_API'}
        client = self._client([pendiente, listo])

        result = self._completar(client)

        self.assertTrue(result.success)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.phone_number_id, '999')
        self.assertEqual(self.conn.status, 'conectada')
        self.assertEqual(len(self.conn.registro_pin), 6)
        client.registrar_numero.assert_called_once_with('999', 'token-nuevo', self.conn.registro_pin)
        _, kwargs = client.resolve_whatsapp_from_waba_ids.call_args
        self.assertEqual(kwargs['preferred_display_phone'], '56944829287')

        self.assertIsNone(OmnichannelService.resolve_connection_for_whatsapp('111'))
        self.assertEqual(OmnichannelService.resolve_connection_for_whatsapp('999'), self.conn)
        OmnichannelService.ingest_inbound_message(
            self.conn,
            external_id='56999998888',
            text='Sigo aquí',
            external_message_id='wamid.DESPUES',
        )
        self.assertEqual(Conversation.objects.filter(source_channel='WHATSAPP').count(), 1)

    def test_si_el_nuevo_falla_el_anterior_sigue_conectado(self):
        en_app = {
            **self.NUEVO,
            'status': 'DISCONNECTED',
            'platform_type': 'ON_PREMISE',
            'is_on_biz_app': True,
            'code_verification_status': 'NOT_VERIFIED',
        }
        client = self._client([en_app])

        result = self._completar(client)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'whatsapp_en_el_telefono')
        client.registrar_numero.assert_not_called()
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.status, 'conectada')
        self.assertTrue(self.conn.enabled)
        self.assertEqual(self.conn.phone_number_id, '111')
        self.assertEqual(self.conn.access_token, 'token-viejo')
        self.assertIsNone(self.conn.oauth_state)
        self.assertIn('+56911112222 sigue conectado', self.conn.mensaje_estado)

    def test_numero_que_facebook_no_compartio(self):
        client = self._client([])
        client.resolve_whatsapp_from_waba_ids.return_value = None
        client.resolve_whatsapp_assets.return_value = None

        result = self._completar(client)

        self.assertEqual(result.error_code, 'numero_no_encontrado')
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.phone_number_id, '111')

    def test_alta_numero_nuevo_no_pide_la_app_del_telefono(self):
        from mecanimovilapp.apps.omnichannel.services.meta_oauth import build_whatsapp_alta_html

        kwargs = dict(
            app_id='123', config_id='cfg', graph_version='v21.0',
            state='s', callback_url='https://api.example/cb/',
        )
        nuevo = build_whatsapp_alta_html(**kwargs, modo='numero_nuevo', numero='+56944829287').content.decode()
        app = build_whatsapp_alta_html(**kwargs, modo='app_whatsapp').content.decode()
        self.assertNotIn('whatsapp_business_app_onboarding', nuevo)
        self.assertIn('+56944829287', nuevo)
        self.assertIn('whatsapp_business_app_onboarding', app)

"""Tests omnicanal Meta."""
import hashlib
import hmac
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from mecanimovilapp.apps.omnichannel.utils import verify_meta_signature, channel_to_api_slug
from mecanimovilapp.apps.omnichannel.services.omnichannel_service import OmnichannelService
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

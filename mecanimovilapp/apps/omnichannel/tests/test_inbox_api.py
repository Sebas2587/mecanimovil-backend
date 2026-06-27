import hashlib
import hmac
from unittest.mock import patch

from django.test import SimpleTestCase

from mecanimovilapp.apps.omnichannel.utils import verify_meta_signature, channel_to_api_slug


class InboxUtilTests(SimpleTestCase):
    def test_channel_slug(self):
        self.assertEqual(channel_to_api_slug('MESSENGER'), 'messenger')

    def test_signature_roundtrip(self):
        body = b'{"test":true}'
        secret = 'mysecret'
        sig = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with patch('mecanimovilapp.apps.omnichannel.utils.meta_app_secret', return_value=secret):
            self.assertTrue(verify_meta_signature(body, sig))

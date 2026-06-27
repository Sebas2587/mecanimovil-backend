#!/usr/bin/env python3
"""Verificación automatizada parcial del módulo omnicanal (sin PostGIS)."""
import hashlib
import hmac
import sys
from unittest.mock import patch


def test_utils():
    from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug, verify_meta_signature

    assert channel_to_api_slug('WHATSAPP') == 'whatsapp'
    assert channel_to_api_slug('INSTAGRAM') == 'instagram'
    body = b'{"ok":true}'
    sig = 'sha256=' + hmac.new(b'secret', body, hashlib.sha256).hexdigest()
    with patch('mecanimovilapp.apps.omnichannel.utils.meta_app_secret', return_value='secret'):
        assert verify_meta_signature(body, sig)
        assert not verify_meta_signature(body, 'sha256=bad')
    print('✓ utils (signature + channel slug)')


def main():
    try:
        test_utils()
    except Exception as exc:
        print(f'✗ {exc}', file=sys.stderr)
        sys.exit(1)
    print('\nVerificación automatizada OK (utils).')
    print('Pendiente manual Meta Dashboard: V1-V11 — ver openspec/changes/omnichannel-meta-messaging/tasks.md')
    print('Pendiente CI/PostGIS: Django TestCase completo (V12)')


if __name__ == '__main__':
    main()

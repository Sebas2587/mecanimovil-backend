"""Cliente HTTP para Meta Graph API."""
import logging
import re
from typing import Any

import requests

from mecanimovilapp.apps.omnichannel.utils import meta_app_secret, meta_graph_version

logger = logging.getLogger(__name__)


def normalize_phone(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'\D', '', value)


class MetaGraphClient:
    BASE = 'https://graph.facebook.com'

    def __init__(self, access_token: str | None = None):
        self.access_token = access_token

    def _url(self, path: str) -> str:
        return f'{self.BASE}/{meta_graph_version()}/{path.lstrip("/")}'

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        from decouple import config
        app_id = config('META_APP_ID', default='')
        secret = meta_app_secret()
        resp = requests.get(
            self._url('oauth/access_token'),
            params={
                'client_id': app_id,
                'client_secret': secret,
                'redirect_uri': redirect_uri,
                'code': code,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_me_accounts(self, access_token: str) -> list[dict]:
        resp = requests.get(
            self._url('me/accounts'),
            params={'access_token': access_token},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get('data', [])

    def get_user_businesses(self, access_token: str) -> list[dict]:
        resp = requests.get(
            self._url('me/businesses'),
            params={'access_token': access_token},
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.warning('Business list fetch failed: %s', resp.text)
            return []
        return resp.json().get('data', [])

    def get_whatsapp_business_accounts(self, business_id: str, access_token: str) -> list[dict]:
        resp = requests.get(
            self._url(f'{business_id}/owned_whatsapp_business_accounts'),
            params={'access_token': access_token},
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.warning('WABA fetch failed: %s', resp.text)
            return []
        return resp.json().get('data', [])

    def get_phone_numbers(self, waba_id: str, access_token: str) -> list[dict]:
        resp = requests.get(
            self._url(f'{waba_id}/phone_numbers'),
            params={'access_token': access_token},
            timeout=30,
        )
        if resp.status_code >= 400:
            return []
        return resp.json().get('data', [])

    def subscribe_page_webhooks(
        self,
        page_id: str,
        access_token: str,
        *,
        fields: str = 'messages,messaging_postbacks',
    ) -> dict:
        """Vincula la app a la Page y suscribe campos de webhook (Messenger/IG)."""
        resp = requests.post(
            self._url(f'{page_id}/subscribed_apps'),
            params={
                'subscribed_fields': fields,
                'access_token': access_token,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.warning('Page webhook subscribe failed (%s): %s', page_id, resp.text)
            resp.raise_for_status()
        return resp.json()

    def subscribe_waba_webhooks(self, waba_id: str, access_token: str) -> dict:
        """Vincula la app al WABA para recibir webhooks de WhatsApp."""
        resp = requests.post(
            self._url(f'{waba_id}/subscribed_apps'),
            params={'access_token': access_token},
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.warning('WABA webhook subscribe failed (%s): %s', waba_id, resp.text)
            resp.raise_for_status()
        return resp.json()

    def resolve_whatsapp_assets(
        self,
        access_token: str,
        *,
        preferred_display_phone: str | None = None,
        business_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Resuelve WABA + phone_number_id desde businesses del usuario."""
        target = normalize_phone(preferred_display_phone)
        business_ids: list[str] = []
        if business_id:
            business_ids.append(business_id)
        business_ids.extend(b['id'] for b in self.get_user_businesses(access_token) if b.get('id'))

        seen: set[str] = set()
        for bid in business_ids:
            if bid in seen:
                continue
            seen.add(bid)
            for waba in self.get_whatsapp_business_accounts(bid, access_token):
                waba_id = waba.get('id')
                if not waba_id:
                    continue
                phones = self.get_phone_numbers(waba_id, access_token)
                if not phones:
                    continue
                if target:
                    for phone in phones:
                        if normalize_phone(phone.get('display_phone_number')) == target:
                            return {
                                'meta_business_id': bid,
                                'waba_id': waba_id,
                                'phone_number_id': phone.get('id'),
                                'display_identifier': phone.get('display_phone_number'),
                                'display_name': phone.get('verified_name') or waba.get('name'),
                            }
                else:
                    phone = phones[0]
                    return {
                        'meta_business_id': bid,
                        'waba_id': waba_id,
                        'phone_number_id': phone.get('id'),
                        'display_identifier': phone.get('display_phone_number'),
                        'display_name': phone.get('verified_name') or waba.get('name'),
                    }
        return None

    def get_instagram_account(self, page_id: str, access_token: str) -> dict | None:
        resp = requests.get(
            self._url(page_id),
            params={
                'fields': 'instagram_business_account{id,username,name}',
                'access_token': access_token,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data.get('instagram_business_account')

    def send_whatsapp_text(self, phone_number_id: str, to_wa_id: str, text: str, token: str):
        return requests.post(
            self._url(f'{phone_number_id}/messages'),
            json={
                'messaging_product': 'whatsapp',
                'to': to_wa_id,
                'type': 'text',
                'text': {'body': text},
            },
            params={'access_token': token},
            timeout=30,
        )

    def send_page_message(self, page_id: str, recipient_id: str, text: str, token: str):
        return requests.post(
            self._url(f'{page_id}/messages'),
            json={
                'recipient': {'id': recipient_id},
                'message': {'text': text},
                'messaging_type': 'RESPONSE',
            },
            params={'access_token': token},
            timeout=30,
        )

    def send_instagram_message(self, instagram_account_id: str, recipient_id: str, text: str, token: str):
        return requests.post(
            self._url(f'{instagram_account_id}/messages'),
            json={
                'recipient': {'id': recipient_id},
                'message': {'text': text},
            },
            params={'access_token': token},
            timeout=30,
        )

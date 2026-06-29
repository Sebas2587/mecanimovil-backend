"""Cliente HTTP para Meta Graph API."""
import logging
import re
from typing import Any

import requests

from mecanimovilapp.apps.omnichannel.utils import meta_app_secret, meta_graph_version, MetaOAuthExchangeError

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
        if resp.status_code >= 400:
            logger.warning(
                'OAuth token exchange failed: status=%s body=%s',
                resp.status_code,
                resp.text[:400],
            )
            raise MetaOAuthExchangeError(resp.status_code, resp.text)
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

    def get_waba_profile(self, waba_id: str, access_token: str) -> dict:
        resp = requests.get(
            self._url(waba_id),
            params={'access_token': access_token, 'fields': 'id,name'},
            timeout=30,
        )
        if resp.status_code >= 400:
            return {'id': waba_id}
        return resp.json() or {'id': waba_id}

    @staticmethod
    def _waba_priority_score(waba_id: str, waba_name: str, phones: list[dict]) -> tuple[int, int]:
        """Menor score = mejor candidato. Deprioriza cuentas de prueba Meta (wp_tel)."""
        name = (waba_name or '').lower()
        if name.startswith('wp_tel') or 'test' in name:
            return (2, len(phones))
        verified = sum(1 for p in phones if p.get('verified_name'))
        return (0 if phones else 1, -verified)

    def _sort_waba_candidates(self, waba_ids: list[str], access_token: str) -> list[str]:
        scored: list[tuple[tuple[int, int], str]] = []
        for waba_id in waba_ids:
            if not waba_id:
                continue
            profile = self.get_waba_profile(waba_id, access_token)
            phones = self.get_phone_numbers(waba_id, access_token)
            score = self._waba_priority_score(waba_id, profile.get('name', ''), phones)
            scored.append((score, waba_id))
        scored.sort(key=lambda item: item[0])
        return [waba_id for _, waba_id in scored]

    def get_phone_numbers(self, waba_id: str, access_token: str) -> list[dict]:
        resp = requests.get(
            self._url(f'{waba_id}/phone_numbers'),
            params={
                'access_token': access_token,
                'fields': 'id,display_phone_number,verified_name,quality_rating',
            },
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json().get('data', [])
            if data:
                return data
            logger.warning(
                'WABA %s phone_numbers edge vacío (200): %s',
                waba_id,
                resp.text[:500],
            )
        else:
            logger.warning(
                'WABA %s phone_numbers edge error (%s): %s',
                waba_id,
                resp.status_code,
                resp.text[:500],
            )

        resp2 = requests.get(
            self._url(waba_id),
            params={
                'access_token': access_token,
                'fields': 'id,name,phone_numbers{id,display_phone_number,verified_name}',
            },
            timeout=30,
        )
        if resp2.status_code == 200:
            nested = (resp2.json().get('phone_numbers') or {}).get('data', [])
            if nested:
                return nested
            logger.warning(
                'WABA %s nested phone_numbers vacío: %s',
                waba_id,
                resp2.text[:500],
            )
        else:
            logger.warning(
                'WABA %s nested fields error (%s): %s',
                waba_id,
                resp2.status_code,
                resp2.text[:500],
            )
        return []

    def get_phone_number_by_id(self, phone_number_id: str, access_token: str) -> dict | None:
        resp = requests.get(
            self._url(phone_number_id),
            params={
                'access_token': access_token,
                'fields': 'id,display_phone_number,verified_name',
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.warning(
                'phone_number_id %s lookup failed (%s): %s',
                phone_number_id,
                resp.status_code,
                resp.text[:500],
            )
            return None
        return resp.json()

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

    def get_app_access_token(self) -> str:
        from decouple import config
        app_id = config('META_APP_ID', default='')
        secret = meta_app_secret()
        return f'{app_id}|{secret}'

    def debug_token(self, input_token: str) -> dict[str, Any]:
        resp = requests.get(
            self._url('debug_token'),
            params={
                'input_token': input_token,
                'access_token': self.get_app_access_token(),
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.warning('debug_token failed: %s', resp.text)
            return {}
        return resp.json().get('data', {}) or {}

    def get_granted_waba_ids(self, access_token: str) -> list[str]:
        """WABAs que el usuario seleccionó en el diálogo OAuth (granular scopes)."""
        data = self.debug_token(access_token)
        waba_ids: list[str] = []
        for scope_entry in data.get('granular_scopes') or []:
            scope = scope_entry.get('scope') or ''
            if scope in ('whatsapp_business_management', 'whatsapp_business_messaging'):
                waba_ids.extend(scope_entry.get('target_ids') or [])
        return list(dict.fromkeys(waba_ids))

    def get_client_whatsapp_business_accounts(
        self, business_id: str, access_token: str
    ) -> list[dict]:
        resp = requests.get(
            self._url(f'{business_id}/client_whatsapp_business_accounts'),
            params={'access_token': access_token},
            timeout=30,
        )
        if resp.status_code >= 400:
            return []
        return resp.json().get('data', [])

    def resolve_whatsapp_from_waba_ids(
        self,
        waba_ids: list[str],
        access_token: str,
        *,
        preferred_display_phone: str | None = None,
        meta_business_id: str | None = None,
    ) -> dict[str, Any] | None:
        target = normalize_phone(preferred_display_phone)
        ordered_ids = self._sort_waba_candidates(waba_ids, access_token)
        for waba_id in ordered_ids:
            if not waba_id:
                continue
            phones = self.get_phone_numbers(waba_id, access_token)
            if not phones:
                logger.warning('WABA %s sin phone_numbers visibles para este token', waba_id)
                continue
            if target:
                for phone in phones:
                    if normalize_phone(phone.get('display_phone_number')) == target:
                        return {
                            'meta_business_id': meta_business_id,
                            'waba_id': waba_id,
                            'phone_number_id': phone.get('id'),
                            'display_identifier': phone.get('display_phone_number'),
                            'display_name': phone.get('verified_name'),
                        }
            else:
                phone = phones[0]
                return {
                    'meta_business_id': meta_business_id,
                    'waba_id': waba_id,
                    'phone_number_id': phone.get('id'),
                    'display_identifier': phone.get('display_phone_number'),
                    'display_name': phone.get('verified_name'),
                }
        return None

    def resolve_whatsapp_assets(
        self,
        access_token: str,
        *,
        preferred_display_phone: str | None = None,
        business_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Resuelve WABA + phone_number_id desde OAuth granular scopes o businesses."""
        granted = self.get_granted_waba_ids(access_token)
        if granted:
            logger.info('WABA ids from OAuth granular scopes: %s', granted)
            result = self.resolve_whatsapp_from_waba_ids(
                self._sort_waba_candidates(granted, access_token),
                access_token,
                preferred_display_phone=preferred_display_phone,
                meta_business_id=business_id,
            )
            if result:
                return result

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
            waba_sources = (
                self.get_whatsapp_business_accounts(bid, access_token)
                + self.get_client_whatsapp_business_accounts(bid, access_token)
            )
            for waba in waba_sources:
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

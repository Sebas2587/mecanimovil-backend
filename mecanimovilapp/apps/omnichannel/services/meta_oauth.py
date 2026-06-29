"""Completar conexiones Meta OAuth / Embedded Signup."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from django.http import HttpResponse

from mecanimovilapp.apps.omnichannel.models import ProviderChannelConnection
from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient
from mecanimovilapp.apps.omnichannel.utils import friendly_oauth_error, meta_oauth_redirect_uri

logger = logging.getLogger(__name__)


@dataclass
class MetaOAuthSessionData:
    phone_number_id: str | None = None
    waba_id: str | None = None
    business_id: str | None = None
    shared_waba_ids: list[str] = field(default_factory=list)


@dataclass
class MetaOAuthCompletionResult:
    success: bool
    message: str
    instruction: str = ''
    needs_phone_number_id: bool = False
    waba_id: str | None = None
    channel: str | None = None


def complete_meta_oauth_connection(
    conn: ProviderChannelConnection,
    code: str,
    session: MetaOAuthSessionData | None = None,
) -> MetaOAuthCompletionResult:
    session = session or MetaOAuthSessionData()
    client = MetaGraphClient()

    try:
        token_data = client.exchange_code(code, meta_oauth_redirect_uri())
        access_token = token_data.get('access_token')
        if not access_token:
            conn.status = 'error'
            conn.mensaje_estado = 'No se recibió access token de Meta.'
            conn.save(update_fields=['status', 'mensaje_estado', 'updated_at'])
            return MetaOAuthCompletionResult(
                success=False,
                message=conn.mensaje_estado,
                instruction='Vuelve a la app e intenta conectar de nuevo.',
            )

        user_token = access_token
        update_fields: dict[str, Any] = {'access_token': user_token}

        if conn.channel in ('MESSENGER', 'INSTAGRAM'):
            pages = client.get_me_accounts(user_token)
            if not pages:
                conn.status = 'error'
                conn.mensaje_estado = (
                    'No encontramos una Página de Facebook vinculada. '
                    'Crea o vincula una Página en Meta Business Suite e intenta de nuevo.'
                )
                conn.save(update_fields=['status', 'mensaje_estado', 'updated_at'])
                return MetaOAuthCompletionResult(
                    success=False,
                    message=conn.mensaje_estado,
                    instruction='Vuelve a la app Mecanimovil Proveedores.',
                )

            page = pages[0]
            update_fields['page_id'] = page.get('id')
            update_fields['display_name'] = page.get('name')
            page_token = page.get('access_token') or user_token
            update_fields['access_token'] = page_token

            if conn.channel == 'INSTAGRAM':
                ig = client.get_instagram_account(page.get('id'), page_token)
                if ig:
                    update_fields['instagram_account_id'] = ig.get('id')
                    update_fields['display_identifier'] = ig.get('username') or ig.get('name')
                else:
                    conn.status = 'error'
                    conn.mensaje_estado = (
                        'Tu Página no tiene Instagram Business vinculado. '
                        'Vincúlalo en Meta Business Suite e intenta de nuevo.'
                    )
                    conn.save(update_fields=['status', 'mensaje_estado', 'updated_at'])
                    return MetaOAuthCompletionResult(
                        success=False,
                        message=conn.mensaje_estado,
                        instruction='Vuelve a la app Mecanimovil Proveedores.',
                    )
            elif conn.channel == 'MESSENGER':
                update_fields['display_identifier'] = page.get('name')

        if conn.channel == 'WHATSAPP':
            update_fields['access_token'] = user_token
            business_id = session.business_id or conn.meta_business_id
            phone_number_id = session.phone_number_id
            waba_id = session.waba_id
            shared_waba_ids = list(session.shared_waba_ids)

            if phone_number_id:
                update_fields['phone_number_id'] = phone_number_id
            if waba_id:
                update_fields['waba_id'] = waba_id
            if business_id:
                update_fields['meta_business_id'] = business_id

            if not update_fields.get('phone_number_id'):
                candidate_waba_ids = [wid for wid in shared_waba_ids if wid]
                if waba_id and waba_id not in candidate_waba_ids:
                    candidate_waba_ids.insert(0, waba_id)
                if not candidate_waba_ids:
                    candidate_waba_ids = client.get_granted_waba_ids(user_token)

                if candidate_waba_ids:
                    wa_assets = client.resolve_whatsapp_from_waba_ids(
                        candidate_waba_ids,
                        user_token,
                        meta_business_id=business_id,
                    )
                    if wa_assets:
                        update_fields.update({k: v for k, v in wa_assets.items() if v is not None})

            if not update_fields.get('phone_number_id'):
                wa_assets = client.resolve_whatsapp_assets(
                    user_token,
                    business_id=business_id,
                )
                if wa_assets:
                    update_fields.update(wa_assets)

            if not update_fields.get('phone_number_id'):
                granted = client.get_granted_waba_ids(user_token)
                if granted:
                    conn.waba_id = granted[0]
                conn.access_token = user_token
                conn.status = 'error'
                conn.mensaje_estado = (
                    'No pudimos vincular tu WhatsApp automáticamente. '
                    'Pulsa Conectar e intenta de nuevo.'
                )
                conn.save()
                return MetaOAuthCompletionResult(
                    success=False,
                    message=conn.mensaje_estado,
                    instruction='Vuelve a la app y pulsa Conectar otra vez.',
                    needs_phone_number_id=False,
                    waba_id=conn.waba_id,
                    channel=conn.channel.lower(),
                )

            waba_for_sub = update_fields.get('waba_id')
            if waba_for_sub:
                try:
                    client.subscribe_waba_webhooks(waba_for_sub, user_token)
                except Exception as sub_exc:
                    logger.warning('WABA webhook subscribe after OAuth failed: %s', sub_exc)

        page_id = update_fields.get('page_id')
        page_token = update_fields.get('access_token')
        if page_id and page_token and conn.channel in ('MESSENGER', 'INSTAGRAM'):
            try:
                client.subscribe_page_webhooks(page_id, page_token)
            except Exception as sub_exc:
                logger.warning('Page webhook subscribe after OAuth failed: %s', sub_exc)

        conn.mark_connected(enabled=True, **update_fields)
        return MetaOAuthCompletionResult(
            success=True,
            message='Canal conectado correctamente.',
            instruction='Vuelve a la app Mecanimovil Proveedores.',
            channel=conn.channel.lower(),
        )
    except Exception as exc:
        logger.exception('Meta OAuth completion failed: %s', exc)
        friendly = friendly_oauth_error(exc)
        conn.status = 'error'
        conn.mensaje_estado = friendly
        conn.save(update_fields=['status', 'mensaje_estado', 'updated_at'])
        return MetaOAuthCompletionResult(
            success=False,
            message=friendly,
            instruction='Vuelve a la app Mecanimovil Proveedores e intenta de nuevo.',
        )


def build_oauth_callback_html(
    *,
    success: bool,
    title: str,
    message: str,
    instruction: str = '',
) -> HttpResponse:
    color = '#0052FF' if success else '#CF202F'
    icon = '✓' if success else '!'
    safe_instruction = instruction or 'Cierra esta ventana y vuelve a Mecanimovil Proveedores.'
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Mecanimovil</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #F5F7FA;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .card {{
      background: #fff;
      border-radius: 16px;
      padding: 32px 28px;
      max-width: 420px;
      width: 100%;
      text-align: center;
      box-shadow: 0 8px 32px rgba(10, 11, 13, 0.08);
    }}
    .icon {{
      width: 56px; height: 56px; border-radius: 50%;
      background: {color}18; color: {color};
      display: flex; align-items: center; justify-content: center;
      font-size: 28px; font-weight: 700; margin: 0 auto 16px;
    }}
    h1 {{ color: #0A0B0D; font-size: 20px; margin-bottom: 8px; }}
    p {{ color: #5B616E; font-size: 14px; line-height: 1.5; margin-bottom: 16px; }}
    .hint {{ background: #F5F7FA; border-radius: 10px; padding: 12px; font-size: 13px; color: #5B616E; }}
    button {{
      margin-top: 20px; background: {color}; color: #fff; border: none;
      border-radius: 10px; padding: 14px 24px; font-size: 15px; font-weight: 600; cursor: pointer;
    }}
  </style>
  <script>
    function notifyOpener(payload) {{
      try {{
        if (window.opener && !window.opener.closed) {{
          window.opener.postMessage(payload, window.location.origin);
        }}
      }} catch (e) {{}}
    }}
    notifyOpener({{
      type: 'mecanimovil:meta-oauth',
      success: {'true' if success else 'false'},
      message: {repr(message)}
    }});
    function cerrar() {{
      try {{ window.close(); }} catch (e) {{}}
    }}
  </script>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    <p>{message}</p>
    <div class="hint">{safe_instruction}</div>
    <button type="button" onclick="cerrar()">Cerrar y volver a la app</button>
  </div>
</body>
</html>"""
    status = 200 if success else 400
    return HttpResponse(html, content_type='text/html; charset=utf-8', status=status)

"""Clasifica por qué falló conectar WhatsApp tras el login de Facebook."""
from __future__ import annotations

from dataclasses import dataclass

WHATSAPP_CONNECT_COPY = {
    'facebook_sin_negocio': {
        'message': (
            'La cuenta de Facebook con la que entraste no administra un negocio en Meta. '
            'Usa el Facebook dueño del taller (el de Meta Business Suite), no un Facebook personal.'
        ),
        'instruction': (
            'Cierra la sesión de Facebook en el navegador, entra con la cuenta administradora '
            'y pulsa Conectar otra vez.'
        ),
    },
    'sin_whatsapp_business': {
        'message': (
            'Este Facebook no tiene un WhatsApp Business asociado. '
            'Un número de WhatsApp personal no se puede conectar a Mecanimovil.'
        ),
        'instruction': (
            'Crea o vincula WhatsApp Business en Meta Business Suite con el Facebook del taller '
            'y vuelve a pulsar Conectar.'
        ),
    },
    'sin_numero_whatsapp': {
        'message': (
            'Encontramos una cuenta WhatsApp Business, pero no un número listo para conectar.'
        ),
        'instruction': (
            'Completa la verificación del número en Meta Business Suite y vuelve a intentar.'
        ),
    },
    'sin_permisos_admin': {
        'message': (
            'Tu usuario de Facebook no es administrador de WhatsApp Business del taller, '
            'o no autorizaste esa cuenta en el diálogo de Meta.'
        ),
        'instruction': (
            'Pídele al dueño que te agregue como administrador o entra con esa cuenta y '
            'acepta compartir WhatsApp Business.'
        ),
    },
    'codigo_expirado': {
        'message': (
            'La autorización expiró o ya fue usada.'
        ),
        'instruction': (
            'Cierra el navegador, vuelve a la app y pulsa Conectar otra vez.'
        ),
    },
    'generico': {
        'message': 'No pudimos vincular tu WhatsApp.',
        'instruction': 'Pulsa Conectar e intenta de nuevo. Si se repite, contacta a soporte.',
    },
}


@dataclass(frozen=True)
class WhatsAppConnectDiagnosis:
    error_code: str
    message: str
    instruction: str


def copy_for_error(error_code: str) -> WhatsAppConnectDiagnosis:
    payload = WHATSAPP_CONNECT_COPY.get(error_code) or WHATSAPP_CONNECT_COPY['generico']
    return WhatsAppConnectDiagnosis(
        error_code=error_code if error_code in WHATSAPP_CONNECT_COPY else 'generico',
        message=payload['message'],
        instruction=payload['instruction'],
    )


def diagnose_whatsapp_connection_gap(client, access_token: str) -> WhatsAppConnectDiagnosis:
    """Infiere la causa con el token ya emitido (sin Phone Number ID)."""
    scopes = set(client.granted_scopes(access_token) or [])
    businesses = client.get_user_businesses(access_token) or []
    granted_wabas = list(client.get_granted_waba_ids(access_token) or [])

    waba_ids: list[str] = []
    for wid in granted_wabas:
        if wid and wid not in waba_ids:
            waba_ids.append(wid)

    for biz in businesses:
        bid = (biz or {}).get('id')
        if not bid:
            continue
        owned = client.get_whatsapp_business_accounts(bid, access_token) or []
        shared = client.get_client_whatsapp_business_accounts(bid, access_token) or []
        for waba in [*owned, *shared]:
            wid = (waba or {}).get('id')
            if wid and wid not in waba_ids:
                waba_ids.append(wid)

    phones_found = False
    for wid in waba_ids:
        phones = client.get_phone_numbers(wid, access_token) or []
        if phones:
            phones_found = True
            break

    wa_scopes = scopes.intersection({
        'whatsapp_business_management',
        'whatsapp_business_messaging',
    })

    if waba_ids and not phones_found:
        return copy_for_error('sin_numero_whatsapp')
    if waba_ids:
        return copy_for_error('sin_numero_whatsapp')
    if businesses and not waba_ids:
        return copy_for_error('sin_whatsapp_business')
    if wa_scopes and not businesses and not waba_ids:
        return copy_for_error('sin_permisos_admin')
    if not businesses:
        return copy_for_error('facebook_sin_negocio')
    return copy_for_error('sin_whatsapp_business')

"""Plantillas Utility de WhatsApp (fuera de la ventana de 24 h)."""
from __future__ import annotations

from django.conf import settings


KIND_COTIZACION = 'cotizacion'
KIND_CITA = 'cita'
KIND_AVISO = 'aviso'


def _texto(valor: str, fallback: str = '-') -> str:
    cleaned = ' '.join((valor or '').split())[:512]
    return cleaned or fallback


def _idioma() -> str:
    return (getattr(settings, 'WHATSAPP_TEMPLATE_LANG', '') or 'es').strip() or 'es'


def template_nombre(kind: str) -> str:
    if kind == KIND_CITA:
        return (getattr(settings, 'WHATSAPP_TEMPLATE_CITA', '') or '').strip()
    if kind == KIND_AVISO:
        return (getattr(settings, 'WHATSAPP_TEMPLATE_AVISO', '') or '').strip()
    return (getattr(settings, 'WHATSAPP_TEMPLATE_COTIZACION', '') or '').strip()


def _payload(kind: str, body_texts: list[str], extra_components: list[dict] | None = None) -> dict:
    components: list[dict] = [
        {
            'type': 'body',
            'parameters': [{'type': 'text', 'text': _texto(t)} for t in body_texts],
        },
    ]
    if extra_components:
        components.extend(extra_components)
    return {
        'kind': kind,
        'name': template_nombre(kind),
        'language': _idioma(),
        'components': components,
    }


def payload_cotizacion(*, taller: str, servicio: str, total: str, url: str, token: str = '') -> dict:
    extras: list[dict] = []
    if getattr(settings, 'WHATSAPP_TEMPLATE_COTIZACION_URL_BUTTON', False) and token:
        extras.append({
            'type': 'button',
            'sub_type': 'url',
            'index': '0',
            'parameters': [{'type': 'text', 'text': _texto(token)}],
        })
    return _payload(
        KIND_COTIZACION,
        [_texto(taller, 'Tu taller'), _texto(servicio, 'tu servicio'), total, url or '—'],
        extras,
    )


def payload_cita(*, taller: str, slot: str) -> dict:
    return _payload(KIND_CITA, [_texto(taller, 'Tu taller'), _texto(slot, 'horario por confirmar')])


def payload_aviso(*, taller: str) -> dict:
    return _payload(KIND_AVISO, [_texto(taller, 'Tu taller')])


def payload_desde_metadata(meta: dict) -> dict | None:
    """Lee plantilla embebida en channel_metadata del mensaje."""
    if not meta.get('whatsapp_template'):
        return None
    name = (meta.get('template_name') or '').strip()
    components = meta.get('template_components')
    if name and isinstance(components, list):
        return {
            'kind': meta.get('template_kind') or KIND_COTIZACION,
            'name': name,
            'language': (meta.get('template_language') or _idioma()).strip() or 'es',
            'components': components,
        }
    return None

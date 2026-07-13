"""Helpers para sincronizar dirección física del taller (texto + geo)."""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional


def parse_chile_address_components(
    direccion_completa: str,
    extras: Optional[Mapping[str, Any]] = None,
) -> dict:
    """
    Parsea un string de dirección Chile a campos de TallerDireccion.
    Acepta extras (calle, numero, comuna, ciudad, region) del request.
    """
    extras = extras or {}
    direccion_completa = (direccion_completa or '').strip()
    calle = str(extras.get('calle') or '').strip()
    numero = str(extras.get('numero') or '').strip()
    comuna = str(extras.get('comuna') or '').strip()
    ciudad = str(extras.get('ciudad') or '').strip()
    region = str(extras.get('region') or '').strip()
    codigo_postal = str(extras.get('codigo_postal') or '').strip()
    detalles = str(extras.get('detalles_adicionales') or '').strip()

    if direccion_completa and (not calle or not comuna):
        partes = [p.strip() for p in direccion_completa.split(',') if p.strip()]
        if partes:
            calle_numero = partes[0]
            numero_match = re.search(r'(\d+[A-Za-z]?)', calle_numero)
            if numero_match and not numero:
                numero = numero_match.group(1)
                calle = calle or calle_numero.replace(numero, '', 1).strip(' ,')
            else:
                calle = calle or calle_numero
            # Quitar "Chile" final típico de Nominatim / Google
            if partes and partes[-1].lower() == 'chile':
                partes = partes[:-1]
            if len(partes) > 1 and not comuna:
                comuna = partes[1]
            if len(partes) > 2 and not ciudad:
                ciudad = partes[2]
            elif len(partes) == 2 and not ciudad:
                # "Calle 123, Santiago" → comuna=ciudad=Santiago
                ciudad = comuna
            if len(partes) > 3 and not region:
                region = partes[3]
            elif not region:
                region = 'Chile'

    # Fallbacks mínimos para no fallar constraints NOT NULL del modelo
    if not calle and direccion_completa:
        calle = direccion_completa[:255]
    if not numero:
        numero = 's/n'
    if not comuna:
        comuna = ciudad or 'Sin comuna'
    if not ciudad:
        ciudad = comuna or 'Sin ciudad'
    if not region:
        region = 'Chile'

    return {
        'calle': calle[:255],
        'numero': numero[:20],
        'comuna': comuna[:100],
        'ciudad': ciudad[:100],
        'region': region[:100],
        'codigo_postal': codigo_postal[:10] or None,
        'detalles_adicionales': detalles or None,
    }


def upsert_taller_direccion_fisica(taller, direccion_text: str, extras: Optional[Mapping[str, Any]] = None):
    """
    Crea o actualiza TallerDireccion para que la app usuarios muestre la dirección.
    """
    from .models import TallerDireccion

    text = (direccion_text or '').strip()
    if not text and not extras:
        return None

    data = parse_chile_address_components(text, extras)
    if not any([data.get('calle'), data.get('comuna'), data.get('ciudad')]):
        return None

    direccion_fisica, created = TallerDireccion.objects.get_or_create(
        taller=taller,
        defaults=data,
    )
    if not created:
        for key, value in data.items():
            if value:
                setattr(direccion_fisica, key, value)
        direccion_fisica.save()
    return direccion_fisica

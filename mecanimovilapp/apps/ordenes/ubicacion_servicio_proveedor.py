"""
Ubicación del servicio según modalidad: taller (dirección del local) vs mecánico a domicilio.
"""
from __future__ import annotations

from typing import Any

from django.contrib.gis.geos import Point

_SKIP_NUMERO = frozenset({'s/n', 'sn', 's/n.', '-', '0', 'null', 'undefined', ''})


def _clean_dir_part(raw) -> str:
    s = str(raw or '').strip()
    if not s:
        return ''
    lower = s.lower()
    if lower.startswith('provincia de '):
        return ''
    if lower.startswith('región ') or lower.startswith('region '):
        return ''
    if lower == 'chile':
        return ''
    return s


def texto_direccion_taller(taller) -> str | None:
    """Calle N°, comuna, ciudad — sin s/n ni provincia/región."""
    if not taller:
        return None
    try:
        direccion = getattr(taller, 'direccion_fisica', None)
        if direccion:
            calle = _clean_dir_part(getattr(direccion, 'calle', None))
            numero_raw = str(getattr(direccion, 'numero', None) or '').strip()
            numero = '' if numero_raw.lower() in _SKIP_NUMERO else numero_raw
            comuna = _clean_dir_part(getattr(direccion, 'comuna', None))
            ciudad = _clean_dir_part(getattr(direccion, 'ciudad', None))
            street = ' '.join(p for p in (calle, numero) if p).strip()
            parts: list[str] = []
            if street:
                parts.append(street)
            for part in (comuna, ciudad):
                if not part:
                    continue
                if any(part.lower() == p.lower() or part.lower() in p.lower() for p in parts):
                    continue
                parts.append(part)
            if parts:
                return ', '.join(parts)

            completa = _clean_dir_part(getattr(direccion, 'direccion_completa', None) or '')
            if completa:
                segments = [
                    p for p in (
                        _clean_dir_part(seg)
                        for seg in completa.split(',')
                    )
                    if p and p.lower() not in _SKIP_NUMERO
                ]
                if segments:
                    return ', '.join(segments)
    except Exception:
        pass
    return None


def punto_ubicacion_taller(taller) -> Point | None:
    if not taller:
        return None
    ubic = getattr(taller, 'ubicacion', None)
    if ubic is None:
        return None
    try:
        return Point(float(ubic.x), float(ubic.y), srid=4326)
    except (TypeError, ValueError):
        return None


def modalidad_servicio_dict(tipo_proveedor: str | None) -> dict[str, Any] | None:
    if tipo_proveedor == 'taller':
        return {
            'tipo': 'taller',
            'label': 'En taller',
            'a_domicilio': False,
        }
    if tipo_proveedor == 'mecanico':
        return {
            'tipo': 'mecanico',
            'label': 'A domicilio',
            'a_domicilio': True,
        }
    return None


def resolve_miembro_taller_efectivo(solicitud, oferta=None):
    """Técnico asignado en oferta o preferido por el cliente al agendar."""
    if oferta is None:
        oferta = getattr(solicitud, 'oferta_seleccionada', None)
    if oferta is not None:
        asignado = getattr(oferta, 'miembro_taller_asignado', None)
        if asignado is not None:
            return asignado
    return getattr(solicitud, 'miembro_taller_preferido', None)


def _inferir_modalidad_ambas(solicitud, taller=None) -> str:
    """Cuando el técnico atiende en ambas modalidades, inferir por datos guardados."""
    if getattr(solicitud, 'direccion_usuario_id', None):
        return 'mecanico'
    texto = (getattr(solicitud, 'direccion_servicio_texto', None) or '').strip()
    if taller and texto:
        texto_taller = (texto_direccion_taller(taller) or '').strip()
        if texto_taller and texto != texto_taller:
            return 'mecanico'
    return 'taller'


def resolve_tipo_proveedor_servicio_efectivo(solicitud, oferta=None) -> str | None:
    """
    Modalidad efectiva del servicio: técnico del taller (en_taller / a_domicilio)
    o tipo legacy de la oferta (taller / mecanico).
    """
    if oferta is None:
        oferta = getattr(solicitud, 'oferta_seleccionada', None)

    tipo_oferta = getattr(oferta, 'tipo_proveedor', None) if oferta else None
    if tipo_oferta == 'mecanico':
        return 'mecanico'

    miembro = resolve_miembro_taller_efectivo(solicitud, oferta)
    if miembro is not None:
        mt = miembro.modalidad_tecnico
        if mt == 'a_domicilio':
            return 'mecanico'
        if mt == 'en_taller':
            return 'taller'
        if mt == 'ambas':
            taller = None
            if oferta is not None and tipo_oferta == 'taller':
                proveedor = getattr(oferta, 'proveedor', None)
                taller = getattr(proveedor, 'taller', None) if proveedor else None
            return _inferir_modalidad_ambas(solicitud, taller)

    return tipo_oferta


def servicio_catalogo_es_a_domicilio(miembro_preferido, payload: dict) -> bool:
    """True si la confirmación de catálogo debe usar ubicación del cliente."""
    if miembro_preferido is None:
        return False
    mt = miembro_preferido.modalidad_tecnico
    if mt == 'a_domicilio':
        return True
    if mt == 'en_taller':
        return False
    if mt == 'ambas':
        if payload.get('direccion_usuario'):
            return True
        lat = payload.get('lat')
        lng = payload.get('lng')
        direccion = (payload.get('direccion_servicio_texto') or '').strip()
        if lat is not None and lng is not None and direccion:
            return True
    return False


def direccion_servicio_texto_para_solicitud(
    *,
    direccion_guardada: str,
    tipo_proveedor: str | None,
    taller=None,
) -> str:
    """Texto a mostrar en detalle/listado; prioriza dirección del taller si aplica."""
    if tipo_proveedor == 'taller' and taller:
        texto_taller = texto_direccion_taller(taller)
        if texto_taller:
            return texto_taller
    return (direccion_guardada or '').strip() or 'Ubicación no especificada'

"""Lee el texto como lo escribe el taller y separa faena de pieza.

El taller mete todo en un campo: "Servicio para cambio de bujias, cambio de
bobinas, cambio de bateria y revision electromecánica". "Cambio de bujías" es
la mano de obra; el repuesto se llama "Bujías". Una revisión no trae pieza.
"""
from __future__ import annotations

import re
import unicodedata

_VERBO_PIEZA = re.compile(
    r'^(?:cambio|reemplazo|recambio|instalaci[oó]n|montaje|colocaci[oó]n)\s+(?:de\s+)?(.+)$',
    re.IGNORECASE,
)
_SOLO_MANO = re.compile(
    r'^(?:revisi[oó]n|diagn[oó]stico|inspecci[oó]n|escaneo|scanner|chequeo|'
    r'alineaci[oó]n|balanceo|rectificado|limpieza|regulaci[oó]n|ajuste|'
    r'mantenci[oó]n)\b',
    re.IGNORECASE,
)
_ACENTOS = {
    'bujia': 'bujía',
    'bujias': 'bujías',
    'bateria': 'batería',
    'baterias': 'baterías',
    'revision': 'revisión',
    'diagnostico': 'diagnóstico',
    'electromecanica': 'electromecánica',
    'electromecanico': 'electromecánico',
    'alineacion': 'alineación',
    'inspeccion': 'inspección',
    'instalacion': 'instalación',
    'colocacion': 'colocación',
    'mantencion': 'mantención',
    'transmision': 'transmisión',
    'distribucion': 'distribución',
    'suspension': 'suspensión',
    'inyeccion': 'inyección',
    'mecanica': 'mecánica',
    'mecanico': 'mecánico',
    'electrica': 'eléctrica',
    'electrico': 'eléctrico',
    'direccion': 'dirección',
}


def _fold(texto: str) -> str:
    raw = unicodedata.normalize('NFD', texto or '')
    return ''.join(ch for ch in raw if unicodedata.category(ch) != 'Mn').lower()


def _titulo(texto: str) -> str:
    palabras = []
    for palabra in (texto or '').split():
        palabras.append(_ACENTOS.get(_fold(palabra), palabra))
    if not palabras:
        return ''
    palabras[0] = palabras[0][:1].upper() + palabras[0][1:]
    return ' '.join(palabras)


def _stem(token: str) -> str:
    t = _fold(token)
    if len(t) > 4 and t.endswith('es'):
        return t[:-2]
    if len(t) > 3 and t.endswith('s'):
        return t[:-1]
    return t


def misma_pieza(a: str, b: str) -> bool:
    ta = {_stem(t) for t in re.findall(r'[a-záéíóúñ]+', _fold(a)) if len(t) > 2}
    tb = {_stem(t) for t in re.findall(r'[a-záéíóúñ]+', _fold(b)) if len(t) > 2}
    if not ta or not tb:
        return False
    return bool(ta & tb)


def es_solo_mano(texto: str) -> bool:
    return bool(_SOLO_MANO.match((texto or '').strip()))


def nombre_pieza(texto: str) -> str:
    """Si el taller nombró la faena, devuelve solo la pieza. Si no hay pieza, ''."""
    limpio = (texto or '').strip()
    if not limpio or es_solo_mano(limpio):
        return ''
    match = _VERBO_PIEZA.match(limpio)
    if not match:
        return ''
    return _titulo(match.group(1).strip())


def interpretar_pedido_taller(texto: str) -> dict[str, list[str]]:
    """Separa el campo del taller en líneas de mano de obra y nombres de pieza."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
        _split_servicios,
    )

    mano: list[str] = []
    piezas: list[str] = []
    chunks = [c.strip() for c in _split_servicios(texto) if c.strip()]
    lista = len(chunks) > 1
    for frase in chunks:
        if es_solo_mano(frase):
            mano.append(_titulo(frase))
            continue
        pieza = nombre_pieza(frase)
        if pieza:
            mano.append(_titulo(frase))
            if not any(misma_pieza(pieza, previa) for previa in piezas):
                piezas.append(pieza)
            continue
        if lista:
            piezas.append(_titulo(frase))
            continue
        mano.append(_titulo(frase))
    return {'mano_obra': mano, 'repuestos': piezas}


def aplicar_lectura_taller(
    repuestos: list[dict],
    servicios_lineas,
    mano_obra: int,
    *,
    pedido: str,
) -> tuple[list[dict], list[dict], int]:
    """Corrige nombres de pieza y arma la mano de obra que el taller escribió."""
    interp = interpretar_pedido_taller(pedido)
    limpios: list[dict] = []
    for rep in repuestos or []:
        if not isinstance(rep, dict):
            continue
        nombre = str(rep.get('nombre') or '').strip()
        if es_solo_mano(nombre):
            continue
        pieza = nombre_pieza(nombre)
        if pieza:
            rep = dict(rep)
            rep['nombre'] = pieza
            nombre = pieza
        if any(misma_pieza(nombre, str(prev.get('nombre') or '')) for prev in limpios):
            continue
        limpios.append(rep)
    for pieza in interp['repuestos']:
        if any(misma_pieza(pieza, str(prev.get('nombre') or '')) for prev in limpios):
            continue
        limpios.append({
            'id': f'pieza-{len(limpios) + 1}',
            'nombre': pieza,
            'cantidad': 1,
            'precio_unitario_clp': 0,
            'precio_estimado': True,
        })

    lineas_in = [lin for lin in (servicios_lineas or []) if isinstance(lin, dict)]
    if lineas_in:
        lineas = lineas_in
    else:
        nombres = interp['mano_obra'] or ['Mano de obra']
        if len(nombres) == 1:
            lineas = [{'nombre': nombres[0], 'monto_clp': max(0, int(mano_obra or 0))}]
        else:
            lineas = [{'nombre': nombre, 'monto_clp': 0} for nombre in nombres]
    return limpios[:12], lineas, int(mano_obra or 0)


def bloque_para_prompt(texto: str) -> str:
    interp = interpretar_pedido_taller(texto)
    if not interp['mano_obra'] and not interp['repuestos']:
        return ''
    lineas = ['Así está escrito este pedido (respétalo; no renombres la faena como pieza):']
    if interp['mano_obra']:
        lineas.append(
            'Mano de obra: ' + '; '.join(interp['mano_obra'])
        )
    if interp['repuestos']:
        lineas.append(
            'Repuestos (nombre de la pieza, sin "cambio de"): ' + '; '.join(interp['repuestos'])
        )
    else:
        lineas.append('Repuestos: ninguno. No inventes una pieza para la revisión o el diagnóstico.')
    return '\n'.join(lineas)

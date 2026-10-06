"""Piensa el pedido antes de buscar precios.

El taller escribe en lenguaje natural. Este paso decide el trabajo, las piezas
de ESE auto y qué no se debe confundir. La búsqueda solo corre después, y una
pieza escasa o mal clasificada no sigue consultando tiendas.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_TIMEOUT_RAZON = (4, 12)


def planificar(
    servicio: str,
    vehiculo: dict[str, Any] | None = None,
    *,
    descripcion: str = '',
    usar_llm: bool = True,
) -> dict[str, Any]:
    """Plan de piezas. El determinista manda en los nombres; el LLM explica y afina."""
    base = _plan_determinista(servicio, descripcion, vehiculo or {})
    if not usar_llm:
        return base
    llm = _plan_llm(servicio, descripcion, vehiculo or {}, base)
    if not llm:
        return base
    return _fusionar(base, llm)


def consulta_de(plan: dict[str, Any], nombre: str) -> str:
    pieza = _pieza(plan, nombre)
    return str(pieza.get('consulta') or '').strip()


def es_escasa(plan: dict[str, Any], nombre: str) -> bool:
    return bool(_pieza(plan, nombre).get('escasa'))


def _pieza(plan: dict[str, Any], nombre: str) -> dict[str, Any]:
    from .enriquecer_repuestos import _clave_fuzzy

    clave = _clave_fuzzy(nombre)
    for pieza in plan.get('piezas') or []:
        if not isinstance(pieza, dict):
            continue
        if _clave_fuzzy(str(pieza.get('nombre') or '')) == clave:
            return pieza
    return {}


def _plan_determinista(servicio: str, descripcion: str, veh: dict[str, Any]) -> dict[str, Any]:
    texto = ' '.join(p for p in (servicio, descripcion) if p).strip()
    auto = _auto(veh)
    if _es_embrague(texto):
        return _plan_embrague(texto, auto, veh)
    return _plan_desde_frases(texto, auto, veh)


def _plan_embrague(texto: str, auto: str, veh: dict[str, Any]) -> dict[str, Any]:
    pide_piola = _menciona_piola(texto)
    piezas = [
        _item(
            'Kit de embrague',
            f'kit embrague {auto}',
            'Disco, prensa y rodamiento de empuje de este auto. No es la piola ni una prensa suelta.',
            escasa=False,
        ),
        _item(
            'Rodamiento de volante',
            f'rodamiento piloto {auto}',
            'Es el rulemán piloto. Un rodamiento de rueda o un volante bimasa no sirven.',
            escasa=True,
        ),
        _item(
            'Aceite de caja de cambios',
            f'aceite caja cambios {auto}',
            'El llenado de la caja de este auto, no el aceite de motor.',
            escasa=False,
        ),
        _item(
            'Retén trasero de cigüeñal',
            f'reten cigueñal {auto}',
            'Queda a la vista al bajar la caja. En autos chicos a veces no hay ficha publicada.',
            escasa=True,
            sugerida=True,
        ),
    ]
    if pide_piola:
        piezas.insert(1, _item(
            'Piola de embrague',
            f'piola embrague {auto}',
            'Cable de este auto. No es el kit.',
            escasa=False,
        ))
    razon = (
        f'{auto} : cambio de embrague en un solo trabajo. '
        'El kit es disco, prensa y rodamiento de empuje. '
        'El rodamiento de volante es el piloto, no un rodamiento genérico de la marca. '
    )
    if pide_piola:
        razon += 'La piola va en su propia línea porque este pedido la nombra y no viene dentro del kit. '
    razon += 'Si una tienda no publica la pieza para este modelo, la línea queda sin precio y con la fuente de lo que sí apareció.'
    return {
        'trabajo': 'cambio_embrague',
        'faena': 'Cambio de embrague',
        'razonamiento': razon.strip(),
        'piezas': piezas,
    }


def _plan_desde_frases(texto: str, auto: str, veh: dict[str, Any]) -> dict[str, Any]:
    from .separar_pedido_taller import interpretar_pedido_taller

    interp = interpretar_pedido_taller(texto or 'Servicio mecánico')
    piezas = []
    for nombre in interp.get('repuestos') or []:
        piezas.append(_item(
            nombre,
            f'{nombre} {auto}'.strip(),
            f'Pieza para {auto}. Solo entra una ficha de esta pieza y este modelo.',
            escasa=_parece_escasa(nombre),
        ))
    faenas = interp.get('mano_obra') or ['Mano de obra']
    return {
        'trabajo': 'pedido_taller',
        'faena': faenas[0],
        'razonamiento': (
            f'{auto}: {", ".join(faenas)}. '
            'Cada repuesto se busca por su nombre y este modelo. '
            'Si la ficha es otra pieza, se deja de buscar y se dice qué apareció.'
        ),
        'piezas': piezas,
    }


def _plan_llm(
    servicio: str,
    descripcion: str,
    veh: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any] | None:
    from .generador import (
        _parse_json,
        _url_generate_content,
        generation_config_gemini,
        modelos_gemini_cotizacion,
        texto_candidato_gemini,
    )

    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    modelos = modelos_gemini_cotizacion()
    if not api_key or not modelos:
        return None
    nombres = ', '.join(p['nombre'] for p in base.get('piezas') or [])
    auto = _auto(veh)
    prompt = f"""Piensa el pedido de un taller en Chile antes de buscar repuestos.
No busques precios. Razona el trabajo para ESTE auto y responde solo JSON.

Auto: {auto}
Motor: {veh.get('tipo_motor') or ''} {veh.get('cilindraje') or ''}
Pedido del taller: {servicio}
Detalle: {descripcion or 'sin detalle'}
Piezas que el sistema ya separó (no las renombres ni las juntes): {nombres or 'ninguna'}

Reglas:
- Un kit de embrague no es la piola, ni una prensa, ni un rodamiento de rueda.
- Rodamiento de volante = rodamiento piloto. No es volante bimasa ni "rodamiento Suzuki" genérico.
- Si la pieza es difícil de encontrar para este modelo, escasa=true.
- consulta es la frase exacta para una tienda chilena: pieza + marca + modelo + año.

{{
  "razonamiento": "2 a 4 frases de por qué estas piezas y no otras",
  "piezas": [{{"nombre": "igual al de la lista", "consulta": "...", "escasa": false}}]
}}"""
    modelo = modelos[0]
    cfg = generation_config_gemini(
        temperature=0.2,
        max_output=1200,
        response_json=True,
        thinking=True,
    )
    if isinstance(cfg.get('thinkingConfig'), dict):
        cfg['thinkingConfig'] = {'thinkingLevel': 'low'}
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': cfg,
    }
    try:
        resp = requests.post(
            _url_generate_content(modelo, api_key),
            json=payload,
            timeout=_TIMEOUT_RAZON,
        )
    except requests.RequestException as exc:
        logger.info('razonar_pedido: sin LLM (%s); sigue el plan del trabajo', exc)
        return None
    if resp.status_code != 200:
        logger.info('razonar_pedido: Gemini %s; sigue el plan del trabajo', resp.status_code)
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    texto = texto_candidato_gemini(body) or ''
    data = _parse_json(texto)
    if not isinstance(data, dict):
        data = _json_suelto(texto)
    return data if isinstance(data, dict) else None


def _fusionar(base: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    """El LLM puede explicar y marcar escasez. No puede cambiar la pieza."""
    out = dict(base)
    razon = str(llm.get('razonamiento') or '').strip()
    if razon:
        out['razonamiento'] = razon[:500]
    extras = {
        _norm(str(p.get('nombre') or '')): p
        for p in (llm.get('piezas') or [])
        if isinstance(p, dict)
    }
    piezas = []
    for pieza in base.get('piezas') or []:
        item = dict(pieza)
        otro = extras.get(_norm(item['nombre']))
        if isinstance(otro, dict):
            consulta = str(otro.get('consulta') or '').strip()
            if consulta and _consulta_respeta_pieza(item['nombre'], consulta):
                item['consulta'] = consulta[:180]
            if otro.get('escasa') is True:
                item['escasa'] = True
        piezas.append(item)
    out['piezas'] = piezas
    return out


def _consulta_respeta_pieza(nombre: str, consulta: str) -> bool:
    n = _norm(nombre)
    c = _norm(consulta)
    if 'kit' in n and 'kit' not in c:
        return False
    if 'piola' in n and 'piola' not in c and 'cable' not in c:
        return False
    if 'piloto' in n or 'volante' in n:
        return 'piloto' in c
    if 'reten' in n or 'ciguenal' in n:
        return 'reten' in c or 'ciguenal' in c
    if 'aceite' in n and 'caja' in n:
        return 'aceite' in c and ('caja' in c or 'transmision' in c)
    return True


def _item(
    nombre: str,
    consulta: str,
    porque: str,
    *,
    escasa: bool,
    sugerida: bool = False,
) -> dict[str, Any]:
    return {
        'nombre': nombre,
        'consulta': re.sub(r'\s+', ' ', consulta).strip()[:180],
        'porque': porque,
        'escasa': escasa,
        'sugerida': sugerida,
    }


def _auto(veh: dict[str, Any]) -> str:
    partes = [
        str(veh.get('marca') or '').strip(),
        str(veh.get('modelo') or '').strip(),
        str(veh.get('anio') or '').strip(),
    ]
    cc = str(veh.get('cilindraje') or '').strip()
    if cc:
        partes.append(cc)
    return ' '.join(p for p in partes if p) or 'este auto'


def _es_embrague(texto: str) -> bool:
    n = _norm(texto)
    return 'embrague' in n or 'clutch' in n


def _menciona_piola(texto: str) -> bool:
    n = _norm(texto)
    return 'piola' in n or 'guaya' in n or ('cable' in n and ('embrague' in n or 'clutch' in n))


def _parece_escasa(nombre: str) -> bool:
    n = _norm(nombre)
    return any(k in n for k in ('reten', 'ciguenal', 'piloto', 'bimasa', 'computador', 'ecu'))


def _norm(texto: str) -> str:
    plano = unicodedata.normalize('NFD', texto or '')
    plano = ''.join(ch for ch in plano if unicodedata.category(ch) != 'Mn')
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', plano.lower())).strip()


def _json_suelto(texto: str) -> dict[str, Any] | None:
    inicio = texto.find('{')
    fin = texto.rfind('}')
    if inicio < 0 or fin <= inicio:
        return None
    try:
        data = json.loads(texto[inicio:fin + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None

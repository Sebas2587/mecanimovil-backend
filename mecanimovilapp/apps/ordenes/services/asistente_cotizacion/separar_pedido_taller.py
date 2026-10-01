"""Lee el texto como lo escribe el taller y separa faena de pieza.

"Cambio de bujías y bobinas" es un solo trabajo: esas piezas se cambian juntas
y la mano de obra va en un solo precio. "Y también limpieza de cuerpo de
aceleración" es otro servicio, no un repuesto. "Cambio de bujías" es la faena;
el repuesto se llama "Bujías". Una revisión o una limpieza no trae pieza.
"""
from __future__ import annotations

import re
import unicodedata

_VERBO_PIEZA = re.compile(
    r'^(?:cambio|reemplazo|recambio|instalaci[oó]n|montaje|colocaci[oó]n|'
    r'cambiar|reemplazar|instalar|colocar)\s+(?:de\s+)?(.+)$',
    re.IGNORECASE,
)
_SOLO_MANO = re.compile(
    r'^(?:revisi[oó]n|diagn[oó]stico|inspecci[oó]n|escaneo|scanner|chequeo|'
    r'alineaci[oó]n|balanceo|rectificado|limpieza|regulaci[oó]n|ajuste|'
    r'mantenci[oó]n|reparaci[oó]n|'
    r'revisar|diagnosticar|inspeccionar|limpiar|alinear|rectificar|reparar|mantener)\b',
    re.IGNORECASE,
)
_PREFIJO_SOLO_MANO = re.compile(
    r'^(?:revisi[oó]n|diagn[oó]stico|inspecci[oó]n|escaneo|scanner|chequeo|'
    r'alineaci[oó]n|balanceo|rectificado|limpieza|regulaci[oó]n|ajuste|'
    r'mantenci[oó]n|reparaci[oó]n|'
    r'revisar|diagnosticar|inspeccionar|limpiar|alinear|rectificar|reparar|mantener)'
    r'\s+(?:de\s+|del\s+)?(?:el\s+|la\s+|los\s+|las\s+)?',
    re.IGNORECASE,
)
_CONECTOR_INICIAL = re.compile(
    r'^(?:y\s+)?(?:tambi[eé]n|adem[aá]s)\s+',
    re.IGNORECASE,
)
_LADO = re.compile(
    r'^(?:delanter[oa]s?|traser[oa]s?|izquierd[oa]s?|derech[oa]s?|'
    r'superiores?|inferiores?)$',
    re.IGNORECASE,
)
_VERBO_EN_TEXTO = re.compile(
    r'\b(?:cambio|reemplazo|recambio|instalaci[oó]n|montaje|colocaci[oó]n|'
    r'revisi[oó]n|diagn[oó]stico|inspecci[oó]n|escaneo|scanner|chequeo|'
    r'alineaci[oó]n|balanceo|rectificado|limpieza|regulaci[oó]n|ajuste|'
    r'mantenci[oó]n|reparaci[oó]n|servicio|'
    r'limpiar|cambiar|reemplazar|revisar|diagnosticar|inspeccionar|'
    r'alinear|rectificar|reparar|instalar|colocar|mantener|'
    r'tambi[eé]n|adem[aá]s)\b',
    re.IGNORECASE,
)
_INFINITIVO = {
    'limpiar': 'Limpieza',
    'cambiar': 'Cambio',
    'reemplazar': 'Reemplazo',
    'revisar': 'Revisión',
    'diagnosticar': 'Diagnóstico',
    'inspeccionar': 'Inspección',
    'alinear': 'Alineación',
    'rectificar': 'Rectificado',
    'reparar': 'Reparación',
    'instalar': 'Instalación',
    'colocar': 'Colocación',
    'mantener': 'Mantención',
}
_VERBOS_TOKEN = {
    'cambio', 'reemplazo', 'recambio', 'instalacion', 'montaje', 'colocacion',
    'revision', 'diagnostico', 'inspeccion', 'escaneo', 'scanner', 'chequeo',
    'alineacion', 'balanceo', 'rectificado', 'limpieza', 'regulacion', 'ajuste',
    'mantencion', 'reparacion', 'servicio',
    'limpiar', 'cambiar', 'reemplazar', 'revisar', 'diagnosticar', 'inspeccionar',
    'alinear', 'rectificar', 'reparar', 'instalar', 'colocar', 'mantener',
}
_STOP = {'de', 'del', 'la', 'el', 'los', 'las', 'un', 'una', 'para', 'con', 'en', 'al', 'por'}
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
    'aceleracion': 'aceleración',
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


def _tokens(texto: str) -> set[str]:
    return {
        _stem(t)
        for t in re.findall(r'[a-z]+', _fold(texto))
        if len(t) > 2 and t not in _STOP
    }


def misma_pieza(a: str, b: str) -> bool:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return False
    return bool(ta & tb)


def _mismo_objeto(a: str, b: str) -> bool:
    """El nombre de la pieza es el objeto de la faena, no solo una palabra suelta."""
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


def es_solo_mano(texto: str) -> bool:
    return bool(_SOLO_MANO.match((texto or '').strip()))


def _sin_conector(texto: str) -> str:
    return _CONECTOR_INICIAL.sub('', (texto or '').strip()).strip()


def _titulo_faena(texto: str) -> str:
    limpio = _sin_conector(texto)
    palabras = limpio.split()
    if not palabras:
        return ''
    cabeza = _fold(palabras[0])
    if cabeza not in _INFINITIVO:
        return _titulo(limpio)
    resto = limpio.split(None, 1)[1] if len(palabras) > 1 else ''
    resto = re.sub(r'^(?:el|la|los|las|de|del)\s+', '', resto, flags=re.IGNORECASE).strip()
    if not resto:
        return _INFINITIVO[cabeza]
    if resto.lower().startswith('de '):
        return _titulo(f'{_INFINITIVO[cabeza]} {resto}')
    return _titulo(f'{_INFINITIVO[cabeza]} de {resto}')


def _es_conjunta(texto: str) -> bool:
    match = _VERBO_PIEZA.match((texto or '').strip())
    if not match:
        return False
    return bool(re.search(r'\s+y\s+', match.group(1), flags=re.IGNORECASE))


def _objeto_solo_mano(texto: str) -> str:
    return _PREFIJO_SOLO_MANO.sub('', (texto or '').strip()).strip()


def piezas_de_faena(texto: str) -> list[str]:
    """Piezas que se compran para esta faena. Vacío si el trabajo no lleva repuesto."""
    limpio = (texto or '').strip()
    if not limpio or es_solo_mano(limpio):
        return []
    match = _VERBO_PIEZA.match(limpio)
    if not match:
        return []
    objeto = match.group(1).strip()
    trozos = [t.strip() for t in re.split(r'\s+y\s+|,\s*', objeto, flags=re.IGNORECASE) if t.strip()]
    if len(trozos) <= 1:
        return [_titulo(objeto)] if objeto else []
    cabeza = ''
    out: list[str] = []
    for trozo in trozos:
        palabras = trozo.split()
        if len(palabras) == 1 and _LADO.match(palabras[0]) and cabeza:
            out.append(_titulo(f'{cabeza} {trozo}'))
            continue
        cabeza = next((w for w in palabras if _fold(w) not in _STOP), '')
        out.append(_titulo(trozo))
    return out


def nombre_pieza(texto: str) -> str:
    """Si el taller nombró la faena, devuelve solo la pieza. Si no hay pieza, ''."""
    piezas = piezas_de_faena(texto)
    if len(piezas) == 1:
        return piezas[0]
    return ''


def texto_pedido_taller(servicio: str, descripcion: str = '') -> str:
    """Junta el nombre del servicio y el detalle cuando el detalle trae otro trabajo."""
    servicio = (servicio or '').strip()
    descripcion = (descripcion or '').strip()
    if not descripcion:
        return servicio
    if _fold(descripcion) and _fold(descripcion) in _fold(servicio):
        return servicio
    if not _VERBO_EN_TEXTO.search(descripcion):
        return servicio
    if not servicio:
        return descripcion
    return f'{servicio} | {descripcion}'


def interpretar_pedido_taller(texto: str) -> dict[str, list[str]]:
    """Separa el campo del taller en líneas de mano de obra y nombres de pieza."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
        _split_servicios,
    )

    mano: list[str] = []
    piezas: list[str] = []
    conjuntas: list[str] = []
    chunks = [c.strip() for c in _split_servicios(texto) if c.strip()]
    lista = len(chunks) > 1
    for frase in chunks:
        frase = _sin_conector(frase)
        if not frase:
            continue
        titulo = _titulo_faena(frase)
        if es_solo_mano(frase) or es_solo_mano(titulo):
            mano.append(titulo)
            continue
        nombres = piezas_de_faena(titulo) or piezas_de_faena(frase)
        if nombres:
            mano.append(titulo)
            if _es_conjunta(titulo) or _es_conjunta(frase):
                conjuntas.append(titulo)
            for pieza in nombres:
                if not any(misma_pieza(pieza, previa) for previa in piezas):
                    piezas.append(pieza)
            continue
        if lista:
            piezas.append(titulo)
            continue
        mano.append(titulo)
    return {'mano_obra': mano, 'repuestos': piezas, 'conjuntas': conjuntas}


def _verbo(texto: str) -> str:
    palabras = _fold(texto).split()
    return palabras[0] if palabras else ''


def _tokens_distintivos(texto: str) -> set[str]:
    todos = _tokens(texto)
    sin_verbo = {t for t in todos if t not in _VERBOS_TOKEN}
    return sin_verbo or todos


def _linea_de_faena(faena: str, linea: str) -> bool:
    tf = _tokens_distintivos(faena)
    tl = _tokens_distintivos(linea)
    if not tf or not tl:
        return False
    if tl <= tf:
        return True
    verbo_faena = _verbo(faena)
    if verbo_faena and verbo_faena == _verbo(linea) and tl <= (tf | {verbo_faena}):
        return True
    return False


def _monto(valor) -> int:
    if valor is None or valor == '':
        return 0
    if isinstance(valor, bool):
        return 0
    if isinstance(valor, (int, float)):
        return max(0, int(valor))
    texto = str(valor).strip().replace('$', '').replace(' ', '')
    if re.fullmatch(r'\d{1,3}(\.\d{3})+', texto):
        texto = texto.replace('.', '')
    texto = texto.replace(',', '')
    try:
        return max(0, int(float(texto)))
    except (TypeError, ValueError):
        return 0


def _lineas_mano(nombres: list[str], lineas_in: list[dict], mano_obra: int) -> tuple[list[dict], int]:
    if not nombres:
        if lineas_in:
            return lineas_in, mano_obra
        return [{'nombre': 'Mano de obra', 'monto_clp': max(0, int(mano_obra or 0))}], mano_obra
    if not lineas_in:
        if len(nombres) == 1:
            return [{'nombre': nombres[0], 'monto_clp': max(0, int(mano_obra or 0))}], mano_obra
        return [{'nombre': nombre, 'monto_clp': 0} for nombre in nombres], mano_obra

    usadas: set[int] = set()
    out: list[dict] = []
    for nombre in nombres:
        monto = 0
        for i, lin in enumerate(lineas_in):
            if i in usadas:
                continue
            if not _linea_de_faena(nombre, str(lin.get('nombre') or '')):
                continue
            monto += _monto(lin.get('monto_clp'))
            usadas.add(i)
        out.append({'nombre': nombre, 'monto_clp': monto})
    suma = sum(lin['monto_clp'] for lin in out)
    total = int(mano_obra or 0)
    if suma > 0 and total > suma:
        ceros = [i for i, lin in enumerate(out) if lin['monto_clp'] == 0]
        if ceros:
            resto = total - suma
            base, extra = divmod(resto, len(ceros))
            for j, i in enumerate(ceros):
                out[i]['monto_clp'] = base + (extra if j == 0 else 0)
            suma = total
    if suma > 0:
        mano_obra = suma
    return out, int(mano_obra or 0)


def _es_objeto_de_servicio(nombre: str, objetos: list[str]) -> bool:
    limpio = _sin_conector(nombre)
    if es_solo_mano(limpio):
        return True
    for objeto in objetos:
        if objeto and _mismo_objeto(limpio, objeto):
            return True
    return False


def aplicar_lectura_taller(
    repuestos: list[dict],
    servicios_lineas,
    mano_obra: int,
    *,
    pedido: str,
) -> tuple[list[dict], list[dict], int]:
    """Corrige nombres de pieza y arma la mano de obra que el taller escribió."""
    interp = interpretar_pedido_taller(pedido)
    objetos_solo = [
        _objeto_solo_mano(nombre)
        for nombre in interp['mano_obra']
        if es_solo_mano(nombre)
    ]
    limpios: list[dict] = []
    for rep in repuestos or []:
        if not isinstance(rep, dict):
            continue
        nombre = _sin_conector(str(rep.get('nombre') or '').strip())
        if not nombre or _es_objeto_de_servicio(nombre, objetos_solo):
            continue
        piezas = piezas_de_faena(nombre)
        if len(piezas) > 1:
            for pieza in piezas:
                if _es_objeto_de_servicio(pieza, objetos_solo):
                    continue
                if any(misma_pieza(pieza, str(prev.get('nombre') or '')) for prev in limpios):
                    continue
                item = dict(rep)
                item['nombre'] = pieza
                item['precio_unitario_clp'] = 0
                limpios.append(item)
            continue
        if len(piezas) == 1:
            rep = dict(rep)
            rep['nombre'] = piezas[0]
            nombre = piezas[0]
        if _es_objeto_de_servicio(nombre, objetos_solo):
            continue
        if any(misma_pieza(nombre, str(prev.get('nombre') or '')) for prev in limpios):
            continue
        limpios.append(rep)
    for pieza in interp['repuestos']:
        if _es_objeto_de_servicio(pieza, objetos_solo):
            continue
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
    lineas, mano_obra = _lineas_mano(interp['mano_obra'], lineas_in, int(mano_obra or 0))
    return limpios[:12], lineas, int(mano_obra or 0)


def bloque_para_prompt(texto: str, descripcion: str = '') -> str:
    interp = interpretar_pedido_taller(texto_pedido_taller(texto, descripcion))
    if not interp['mano_obra'] and not interp['repuestos']:
        return ''
    conjuntas = set(interp.get('conjuntas') or [])
    lineas = ['Así está escrito este pedido (respétalo; no renombres la faena como pieza):']
    if interp['mano_obra']:
        bits = []
        for nombre in interp['mano_obra']:
            if nombre in conjuntas:
                bits.append(f'{nombre} (un solo monto; no la partas en varias líneas)')
            else:
                bits.append(nombre)
        lineas.append('Mano de obra: ' + '; '.join(bits))
    solos = [nombre for nombre in interp['mano_obra'] if es_solo_mano(nombre)]
    if interp['repuestos']:
        lineas.append(
            'Repuestos (nombre de la pieza, sin "cambio de"): ' + '; '.join(interp['repuestos'])
        )
    else:
        lineas.append('Repuestos: ninguno. No inventes una pieza para la revisión o el diagnóstico.')
    if solos:
        lineas.append(
            'Estos trabajos son solo mano de obra, no repuestos: ' + '; '.join(solos)
        )
    if conjuntas:
        lineas.append(
            'Si varias piezas van en la misma faena, cobra esa mano de obra una sola vez.'
        )
    return '\n'.join(lineas)

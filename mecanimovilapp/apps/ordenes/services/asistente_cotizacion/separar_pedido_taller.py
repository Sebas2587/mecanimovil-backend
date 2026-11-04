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
    r'^(?:y\s+)?(?:tambi[eé]n|adem[aá]s)\s+|^y\s+',
    re.IGNORECASE,
)
# "embrague" no identifica la pieza: la piola y el kit comparten esa palabra
# y no son el mismo repuesto. El distintivo (piola, volante, aire) sí separa.
_GENERICOS_PIEZA = {
    'embrague', 'clutch', 'freno', 'frenos', 'filtro', 'filtros',
    'aceite', 'cambio', 'completo', 'servicio', 'kit', 'juego', 'set',
    'repuesto', 'repuestos',
}
_DISTINTIVOS_PIEZA = {
    'piola', 'cable', 'guaya', 'volante', 'piloto', 'empuje', 'collarin',
    'prensa', 'plato', 'disco', 'caja', 'motor', 'aire', 'polen',
    'gasolina', 'bencina', 'reten', 'sello', 'ciguenal', 'bimasa',
    'bombin', 'hidraulico', 'delantero', 'trasero', 'izquierdo', 'derecho',
}
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
    """La misma pieza, no solo la misma familia.

    "Piola de embrague" y "Kit de embrague" comparten "embrague" y son
    repuestos distintos. "Bujías" y "cambio de bujías" sí son la misma.
    """
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return False
    # El filtro de aire y el de aceite comparten «filtro» y no son la misma pieza.
    if ('aire' in ta) != ('aire' in tb) and ('filtro' in ta or 'filtro' in tb):
        return False
    # «Aceite» y «Filtro de aceite» se compran juntos y no son la misma línea.
    # «Aceite de motor con filtro» sí sigue siendo el aceite.
    fa = _fold(a)
    fb = _fold(b)

    def _filtro_pieza(texto: str) -> bool:
        return 'filtro' in texto and 'con filtro' not in texto

    def _aceite_sin_filtro(texto: str) -> bool:
        return 'aceite' in texto and 'filtro' not in texto

    if (_filtro_pieza(fa) and _aceite_sin_filtro(fb)) or (_filtro_pieza(fb) and _aceite_sin_filtro(fa)):
        return False
    distintivos_a = ta & _DISTINTIVOS_PIEZA
    distintivos_b = tb & _DISTINTIVOS_PIEZA
    if distintivos_a and distintivos_b and distintivos_a.isdisjoint(distintivos_b):
        return False
    nucleo_a = ta - _GENERICOS_PIEZA
    nucleo_b = tb - _GENERICOS_PIEZA
    if nucleo_a and nucleo_b:
        return bool(nucleo_a & nucleo_b)
    if not nucleo_a and not nucleo_b:
        return bool(ta & tb)
    # «Aceite» es el mismo repuesto que «Aceite de motor», no una tercera línea.
    if _aceite_sin_filtro(fa) and _aceite_sin_filtro(fb) and (ta <= tb or tb <= ta):
        return True
    return False


def _mismo_objeto(a: str, b: str) -> bool:
    """El nombre de la pieza es el objeto de la faena, no solo una palabra suelta."""
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


_RE_PARTE_COMPRABLE = re.compile(
    r'(pastillas?(?:\s+de\s+freno)?(?:\s+(?:delanter[oa]s?|traser[oa]s?))?|'
    r'discos?(?:\s+de\s+freno)?(?:\s+(?:delanter[oa]s?|traser[oa]s?))?|'
    r'buj[ií]as?|bobinas?|bater[ií]as?|'
    r'filtro\s+de\s+(?:aceite|aire|polen|habit[aá]culo|cabina|combustible|bencina|gasolina)|'
    r'aceite(?:\s+de\s+motor)?|'
    r'amortiguadores?)',
    re.IGNORECASE,
)


def _objeto_comprable(texto: str) -> str:
    """La pieza que nombra una mantención. Vacío si el trabajo no lleva repuesto."""
    resto = _objeto_solo_mano(texto)
    hallado = _RE_PARTE_COMPRABLE.search(resto)
    if not hallado:
        return ''
    return hallado.group(1).strip()


def es_solo_mano(texto: str) -> bool:
    """Revisión o limpieza sin pieza. «Mantención con pastillas» sí compra la pieza."""
    limpio = (texto or '').strip()
    if not _SOLO_MANO.match(limpio):
        return False
    return not _objeto_comprable(limpio)


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
    if not limpio:
        return []
    if _SOLO_MANO.match(limpio):
        objeto = _objeto_comprable(limpio)
        return [_titulo(objeto)] if objeto else []
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
        _FILTRO_HABITACULO_RE,
        _split_servicios,
    )

    mano: list[str] = []
    piezas: list[str] = []
    conjuntas: list[str] = []
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
        _SEP_OTRO_SERVICIO_RE,
    )

    # «también rodamiento de volante» es una pieza del trabajo, no otra faena.
    # El verbo se hereda solo dentro de la lista inicial («cambio de A, B y C»).
    segmentos = _SEP_OTRO_SERVICIO_RE.split(texto) or [texto]
    chunks: list[str] = []
    hereda_verbo: list[bool] = []
    for i, segmento in enumerate(segmentos):
        for frase in _split_servicios(segmento):
            if not frase.strip():
                continue
            chunks.append(frase.strip())
            hereda_verbo.append(i == 0)
    lista = len(chunks) > 1
    verbo_lista = ''
    for frase, puede_heredar in zip(chunks, hereda_verbo):
        frase = _sin_conector(frase)
        if not frase:
            continue
        # «Cambio de pastillas, aceite y filtro, bujías»: el verbo abre toda la lista.
        if lista and puede_heredar and verbo_lista and not _VERBO_PIEZA.match(frase) and not es_solo_mano(frase):
            frase = f'{verbo_lista} {frase}'.strip()
        titulo = _titulo_faena(frase)
        abierto = _VERBO_PIEZA.match(frase)
        if abierto:
            verbo_lista = frase[:abierto.start(1)].strip()
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
        if lista and _FILTRO_HABITACULO_RE.match(frase):
            # "y filtro de aire" ya se partió de la faena anterior. Sin verbo
            # quedaba solo como repuesto y el taller no veía la mano de obra.
            mano.append(_titulo(f'Cambio de {frase}'))
            if not any(misma_pieza(titulo, previa) for previa in piezas):
                piezas.append(titulo)
            continue
        if lista:
            piezas.append(titulo)
            continue
        mano.append(titulo)
    return {
        'mano_obra': _dedupe_faenas(mano),
        'repuestos': piezas,
        'conjuntas': conjuntas,
    }


def _misma_faena(a: str, b: str) -> bool:
    """El mismo trabajo aunque uno diga mantención y el otro cambio.

    El filtro de aire no es el de aceite. Bujías y bobinas juntas no se
    tragan un cambio de bujías pedido aparte.
    """
    ta = _tokens_distintivos(a)
    tb = _tokens_distintivos(b)
    if not ta or not tb:
        return False
    if ('aire' in ta) != ('aire' in tb):
        return False
    if ('polen' in ta) != ('polen' in tb):
        return False
    if ta == tb:
        return True
    menor, mayor = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not menor <= mayor:
        return False
    extra = mayor - menor
    if extra & {'bujia', 'bobina', 'bateria', 'pastilla', 'disco', 'amortiguador', 'correa'}:
        return False
    if menor <= {'filtro', 'freno'} and extra:
        return False
    return True


def _dedupe_faenas(nombres: list[str]) -> list[str]:
    """Una línea por trabajo. La primera redacción se queda; la repetición no."""
    out: list[str] = []
    for nombre in nombres:
        if any(_misma_faena(nombre, previa) for previa in out):
            continue
        out.append(nombre)
    return out


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


# Sin tarifa del taller y sin faenas cotizadas por el modelo, una hora de taller.
_HORA_TALLER_FALLBACK = 15_000


def _mediana(valores: list[int]) -> int:
    ordered = sorted(v for v in valores if v > 0)
    if not ordered:
        return 0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2))


def _minutos_faena(nombre: str) -> int:
    from mecanimovilapp.apps.agente_ia.services.duracion_trabajo import duracion_familia_desde_texto
    from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import (
        DURACION_DEFAULT_MINUTOS,
    )

    return duracion_familia_desde_texto(nombre) or DURACION_DEFAULT_MINUTOS


def _tarifa_hora_taller(taller) -> int:
    """La hora configurada del taller, si existe. Cero si no está."""
    if taller is None:
        return 0
    fuentes = [taller]
    config = getattr(taller, 'agente_config', None)
    if config is not None:
        fuentes.append(config)
    for fuente in fuentes:
        for campo in ('tarifa_hora_clp', 'valor_hora_clp', 'precio_hora_clp'):
            try:
                valor = int(getattr(fuente, campo, 0) or 0)
            except (TypeError, ValueError):
                valor = 0
            if valor > 0:
                return valor
    return 0


def _tarifa_servicio(taller, nombre: str, *, marca: str, modelo: str, tipo_motor: str) -> int:
    if taller is None or not getattr(taller, 'pk', None):
        return 0
    try:
        from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
            buscar_oferta_exacta,
            precio_publico_oferta,
        )

        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        if oferta is None:
            return 0
        precio, _ = precio_publico_oferta(oferta, con_repuestos=False)
        return precio if precio > 0 else 0
    except Exception:
        return 0


def completar_montos_mano(
    lineas: list[dict],
    *,
    taller=None,
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
) -> tuple[list[dict], int]:
    """Cada faena pedida cobra. La suma manda; un total del modelo no la recorta.

    Orden: tarifa del servicio, hora configurada × horas estándar, estimado del
    modelo para esa faena, y si el modelo no la cotizó, las horas estándar a la
    mediana de lo que sí cotizó (o $15.000/h si no cotizó ninguna).
    """
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        monto_linea_mo,
    )

    hora = _tarifa_hora_taller(taller)
    preparados: list[tuple[dict, int, int, bool]] = []
    tarifas_hora_modelo: list[int] = []
    for lin in lineas or []:
        if not isinstance(lin, dict):
            continue
        row = dict(lin)
        nombre = str(row.get('nombre') or '').strip()
        minutos = _minutos_faena(nombre) if nombre else 60
        actual = monto_linea_mo(row)
        desde_catalogo = bool(row.get('precio_desde_catalogo')) and actual > 0
        tarifa = 0 if desde_catalogo else _tarifa_servicio(
            taller, nombre, marca=marca, modelo=modelo, tipo_motor=tipo_motor,
        )
        if desde_catalogo:
            monto = actual
            faltaba = False
        elif tarifa > 0:
            monto = tarifa
            faltaba = False
        elif hora > 0:
            monto = max(1, int(round(hora * minutos / 60)))
            faltaba = False
        elif actual > 0:
            monto = actual
            faltaba = False
            if minutos > 0:
                tarifas_hora_modelo.append(int(round(actual * 60 / minutos)))
        else:
            monto = 0
            faltaba = True
        preparados.append((row, monto, minutos, faltaba))

    hora_recalc = _mediana(tarifas_hora_modelo) or _HORA_TALLER_FALLBACK
    out: list[dict] = []
    for row, monto, minutos, faltaba in preparados:
        if faltaba:
            monto = max(1, int(round(hora_recalc * minutos / 60)))
        row['monto_clp'] = monto
        row['precio_mano_obra_clp'] = monto
        out.append(row)
    return out, sum(int(lin['monto_clp']) for lin in out)


def _lineas_mano(
    nombres: list[str],
    lineas_in: list[dict],
    mano_obra: int,
    *,
    taller=None,
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
) -> tuple[list[dict], int]:
    if not nombres:
        if lineas_in:
            lineas, total = completar_montos_mano(
                lineas_in, taller=taller, marca=marca, modelo=modelo, tipo_motor=tipo_motor,
            )
            return lineas, total or int(mano_obra or 0)
        return [{'nombre': 'Mano de obra', 'monto_clp': max(0, int(mano_obra or 0))}], mano_obra
    if not lineas_in and len(nombres) == 1:
        return [{'nombre': nombres[0], 'monto_clp': max(0, int(mano_obra or 0))}], mano_obra

    usadas: set[int] = set()
    out: list[dict] = []
    for nombre in nombres:
        monto = 0
        ya_sumadas: list[str] = []
        for i, lin in enumerate(lineas_in or []):
            if i in usadas:
                continue
            linea_nombre = str(lin.get('nombre') or '')
            if not _linea_de_faena(nombre, linea_nombre):
                continue
            # La misma faena dicha dos veces (mantención y cambio) no se suma.
            # Bujías y bobinas sí: son piezas distintas de un solo trabajo.
            if any(_misma_faena(linea_nombre, previa) for previa in ya_sumadas):
                usadas.add(i)
                continue
            monto += _monto(lin.get('monto_clp') or lin.get('precio_mano_obra_clp'))
            usadas.add(i)
            ya_sumadas.append(linea_nombre)
        out.append({'nombre': nombre, 'monto_clp': monto})
    lineas, total = completar_montos_mano(
        out, taller=taller, marca=marca, modelo=modelo, tipo_motor=tipo_motor,
    )
    return lineas, total


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
    taller=None,
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
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
    lineas, mano_obra = _lineas_mano(
        interp['mano_obra'],
        lineas_in,
        int(mano_obra or 0),
        taller=taller,
        marca=marca,
        modelo=modelo,
        tipo_motor=tipo_motor,
    )
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

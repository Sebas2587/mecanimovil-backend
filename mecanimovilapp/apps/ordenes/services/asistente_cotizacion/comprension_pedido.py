"""Identidad de cada ítem del pedido.

Dos piezas son la misma solo si comparten identidad. Compartir una palabra
(embrague, frenos) no las une. La taxonomía es el apoyo; la comparación es
por id. Un texto del modelo se acepta solo si cumple el schema.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field, ValidationError

ROL_REPUESTO = 'repuesto'
ROL_MANO = 'mano_obra'
ROL_INSUMO = 'insumo'

# Marcadores distintivos, del más específico al más corto. No incluyen la
# palabra suelta «embrague» ni «frenos»: esas no identifican una pieza.
_IDENTIDADES: tuple[dict[str, Any], ...] = (
    {
        'id': 'cilindro_receptor_embrague',
        'rol': ROL_REPUESTO,
        'nombre': 'Cilindro de embrague',
        'marcadores': (
            'cilindro receptor', 'cilindro esclavo', 'bombin de embrague',
            'bombin embrague', 'bombin', 'cilindro de embrague', 'cilindro embrague',
        ),
    },
    {
        'id': 'bomba_embrague',
        'rol': ROL_REPUESTO,
        'nombre': 'Bomba de embrague',
        'marcadores': (
            'cilindro maestro', 'bomba de embrague', 'bomba embrague', 'bomba de clutch',
        ),
    },
    {
        'id': 'kit_embrague',
        'rol': ROL_REPUESTO,
        'nombre': 'Kit de embrague',
        'marcadores': (
            'kit de embrague', 'kit embrague', 'embrague completo', 'kit de clutch', 'kit clutch',
        ),
    },
    {
        'id': 'flexible_embrague',
        'rol': ROL_REPUESTO,
        'nombre': 'Flexible de embrague',
        'marcadores': ('flexible de embrague', 'flexible embrague', 'manguera de embrague'),
    },
    {
        'id': 'horquilla_embrague',
        'rol': ROL_REPUESTO,
        'nombre': 'Horquilla de embrague',
        'marcadores': ('horquilla de embrague', 'horquilla embrague', 'horquilla'),
    },
    {
        'id': 'piola_embrague',
        'rol': ROL_REPUESTO,
        'nombre': 'Piola de embrague',
        'marcadores': ('piola de embrague', 'piola embrague', 'piola', 'guaya', 'cable de embrague'),
    },
    {
        'id': 'rodamiento_piloto',
        'rol': ROL_REPUESTO,
        'nombre': 'Rodamiento de volante',
        'marcadores': (
            'rodamiento de volante', 'rodamiento volante', 'rodamiento piloto',
            'rodamiento de piloto', 'ruleman piloto', 'ruleman', 'piloto',
        ),
    },
    {
        'id': 'rodamiento_empuje',
        'rol': ROL_REPUESTO,
        'nombre': 'Rodamiento de empuje',
        'marcadores': ('rodamiento de empuje', 'crapodina', 'collarin'),
    },
    {
        'id': 'reten_ciguenal',
        'rol': ROL_REPUESTO,
        'nombre': 'Retén trasero de cigüeñal',
        'marcadores': ('reten trasero', 'reten de ciguenal', 'reten ciguenal', 'reten'),
    },
    {
        'id': 'liquido_frenos',
        'rol': ROL_INSUMO,
        'nombre': 'Líquido de frenos',
        'marcadores': ('liquido de frenos', 'liquido de embrague', 'liquido frenos', 'dot3', 'dot4', 'dot 4'),
    },
    {
        'id': 'aceite_caja',
        'rol': ROL_INSUMO,
        'nombre': 'Aceite de caja de cambios',
        'marcadores': (
            'aceite de caja', 'aceite caja', 'aceite de transmision',
            'aceite transmision', 'valvulina',
        ),
    },
    {
        'id': 'pastillas_freno',
        'rol': ROL_REPUESTO,
        'nombre': 'Pastillas de freno',
        'marcadores': ('pastilla',),
    },
    {
        'id': 'balatas_freno',
        'rol': ROL_REPUESTO,
        'nombre': 'Balatas de freno',
        'marcadores': ('balata', 'zapata'),
    },
    {
        'id': 'discos_freno',
        'rol': ROL_REPUESTO,
        'nombre': 'Discos de freno',
        'marcadores': (
            'discos de freno', 'disco de freno', 'discos freno', 'disco freno',
            'discos delanteros', 'discos traseros', 'disco delantero', 'disco trasero',
        ),
    },
    {
        'id': 'tambores_freno',
        'rol': ROL_REPUESTO,
        'nombre': 'Tambores de freno',
        'marcadores': ('tambor de freno', 'tambor freno', 'tambor'),
    },
    {
        'id': 'bombin_rueda',
        'rol': ROL_REPUESTO,
        'nombre': 'Bombín de rueda',
        'marcadores': (
            'bombin de freno', 'bombin de rueda', 'bombin freno',
            'cilindro de rueda', 'cilindro rueda',
        ),
    },
    {
        'id': 'cilindro_maestro_freno',
        'rol': ROL_REPUESTO,
        'nombre': 'Cilindro maestro de freno',
        'marcadores': (
            'cilindro maestro de freno', 'cilindro maestro freno', 'bomba de freno',
        ),
    },
    {
        'id': 'flexible_freno',
        'rol': ROL_REPUESTO,
        'nombre': 'Flexible de freno',
        'marcadores': ('flexible de freno', 'flexible freno', 'manguera de freno'),
    },
)

_POR_ID = {fila['id']: fila for fila in _IDENTIDADES}
_POR_NOMBRE = {fila['nombre']: fila for fila in _IDENTIDADES}

# Referencia de vehículo para compatibilidad y especificaciones. No es un precio.
_FICHAS = (
    {
        'marca': 'renault',
        'modelo': 'oroch',
        'motor': '1.6',
        'aceite_caja': {
            'especificacion': '75W-80',
            'litros': '2.5',
            'origen': 'Referencia de caja manual Renault 1.6. Confirmar litros en la varilla.',
        },
        'liquido_frenos': {'especificacion': 'DOT4', 'litros': '1'},
    },
)

_FAENA = {
    'kit_embrague': 'Cambio de embrague',
    'bomba_embrague': 'Cambio de bomba de embrague',
    'cilindro_receptor_embrague': 'Cambio de cilindro de embrague',
    'piola_embrague': 'Cambio de piola de embrague',
    'liquido_frenos': 'Cambio de líquido de frenos',
    'aceite_caja': 'Cambio de aceite de caja',
}


class ItemComprendido(BaseModel):
    identidad: str
    rol: str
    nombre: str
    texto_original: str = ''
    sistema: str = ''
    especificacion: str = ''
    cantidad: str = ''
    unidad: str = ''
    confianza: float | None = None

    def modelo(self) -> dict[str, Any]:
        return self.model_dump()


class ComprensionSchema(BaseModel):
    """Contrato de la salida estructurada. Una identidad por ítem."""

    items: list[ItemComprendido] = Field(default_factory=list)
    faenas: list[str] = Field(default_factory=list)
    dudas: list[dict[str, Any]] = Field(default_factory=list)
    fluidos: dict[str, Any] = Field(default_factory=dict)


# Un marcador de una sola palabra nombra varias piezas. Solo vale dentro
# del sistema. «Bombín de freno» no es el cilindro de embrague.
_MARCADORES_CORTOS = frozenset({
    'bombin', 'cilindro maestro', 'piola', 'horquilla', 'ruleman',
    'reten', 'piloto', 'guaya',
})
_OTRO_SISTEMA = (
    'freno', 'suspension', 'amortiguador', 'rueda', 'puerta', 'acelerador',
    'direccion', 'automatico', 'cruceta', 'bieleta', 'rotula',
)
_IDENTIDADES_EMBRAGUE = frozenset({
    'kit_embrague', 'bomba_embrague', 'cilindro_receptor_embrague',
    'flexible_embrague', 'horquilla_embrague', 'piola_embrague',
    'rodamiento_piloto', 'rodamiento_empuje', 'reten_ciguenal',
})
UMBRAL_CONFIANZA = 0.6


def norm(texto: str) -> str:
    plano = unicodedata.normalize('NFD', str(texto or ''))
    plano = ''.join(ch for ch in plano if unicodedata.category(ch) != 'Mn')
    plano = plano.lower().replace('embrage', 'embrague')
    plano = re.sub(r'[^a-z0-9]+', ' ', plano)
    return re.sub(r'\s+', ' ', plano).strip()


def _sistema_de(n: str) -> str:
    if 'embrague' in n or 'clutch' in n:
        return 'embrague'
    if 'freno' in n:
        return 'frenos'
    if any(pieza in n for pieza in _OTRO_SISTEMA):
        return 'otro'
    return ''


def _expandir(n: str) -> str:
    """Abreviaturas de taller. «cm» y «bba» solo como palabra."""
    n = re.sub(r'\bbba\b', 'bomba', n)
    n = re.sub(r'\bcil rec\b', 'cilindro receptor', n)
    n = re.sub(r'\bcm\b', 'cilindro maestro', n)
    return n


def _sistema_del_trozo(n: str, etiqueta: str = '') -> str:
    """El calificador de este tramo gana sobre una palabra de otro tramo."""
    local_embrague = 'embrague' in n or 'clutch' in n
    local_freno = 'freno' in n or ('rueda' in n and not local_embrague)
    local_otro = any(
        pieza in n for pieza in ('puerta', 'acelerador', 'suspension', 'automatico', 'direccion')
    )
    if local_freno and not local_embrague:
        return 'frenos'
    if local_otro and not local_embrague:
        return 'otro'
    if local_embrague or etiqueta == 'embrague':
        return 'embrague'
    if etiqueta == 'frenos':
        return 'frenos'
    if etiqueta == 'otro':
        return 'otro'
    return ''


_TALLOS_PIEZA = (
    'reten', 'kit', 'bomba', 'cilindro', 'bombin', 'pastilla', 'disco',
    'tambor', 'zapata', 'balata', 'flexible', 'horquilla', 'piola',
    'ruleman', 'piloto', 'collarin', 'crapodina', 'guaya', 'bba',
)
_RE_ETIQUETA = re.compile(
    r'(frenos?|embrague|clutch|suspensi[oó]n|direcci[oó]n)\s*:',
    re.IGNORECASE,
)
_CALIFICADORES = (
    ('delanter', 'delanteras'),
    ('traser', 'traseras'),
    ('izquierd', 'izquierdo'),
    ('derech', 'derecho'),
)


def _calificadores(n: str) -> tuple[str, ...]:
    marcas = [token for token, _etiq in _CALIFICADORES if token in n]
    marcas.extend(
        extra for extra in ('rueda', 'ciguenal', 'puerta', 'acelerador') if extra in n
    )
    return tuple(marcas)


def _nombre_con_calificadores(nombre: str, n: str) -> str:
    plural = any(pieza in norm(nombre) for pieza in ('pastilla', 'balata', 'disco', 'tambor'))
    etiquetas = {
        'delanter': 'delanteras' if plural else 'delantero',
        'traser': 'traseras' if plural else 'trasero',
        'izquierd': 'izquierdo',
        'derech': 'derecho',
    }
    extra = [
        etiquetas[token] for token in etiquetas
        if token in n and token not in norm(nombre)
    ]
    if not extra:
        return nombre
    return f"{nombre} {' '.join(extra)}".strip()


def _lados_con_pieza(cuerpo: str) -> bool:
    lados = re.split(r'\s+y\s+', cuerpo, flags=re.IGNORECASE)
    if len(lados) < 2:
        return False
    return all(any(tallo in norm(lado) for tallo in _TALLOS_PIEZA) for lado in lados)


def _tramos(texto: str) -> list[tuple[str, str]]:
    """Cada etiqueta de sistema cubre solo el texto que le sigue."""
    plano = str(texto or '')
    marcas = list(_RE_ETIQUETA.finditer(plano))
    if not marcas:
        return [(plano, '')]
    tramos: list[tuple[str, str]] = []
    if marcas[0].start() > 0:
        previo = plano[:marcas[0].start()].strip(' .')
        if previo:
            tramos.append((previo, ''))
    for i, marca in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(plano)
        etiqueta = norm(marca.group(1))
        if etiqueta.startswith('freno'):
            sistema = 'frenos'
        elif etiqueta in ('embrague', 'clutch'):
            sistema = 'embrague'
        else:
            sistema = 'otro'
        cuerpo = plano[marca.end():fin].strip(' .')
        if cuerpo:
            tramos.append((cuerpo, sistema))
    return tramos or [(plano, '')]


def _marcador_permitido(marca: str, n: str, sistema: str) -> bool:
    if _sistema_de(n) in ('frenos', 'otro') and sistema != 'embrague':
        return marca not in _MARCADORES_CORTOS and 'embrague' not in marca and 'clutch' not in marca
    if marca in _MARCADORES_CORTOS:
        return sistema == 'embrague' or 'embrague' in n or 'clutch' in n
    return True


def _es_solo_el_kit(n: str) -> bool:
    if 'sistema' in n or 'embrague' not in n and 'clutch' not in n:
        return False
    ruido = {
        'de', 'del', 'la', 'el', 'y', 'cambio', 'cambios', 'repuesto', 'repuestos',
        'embrague', 'clutch', 'kit',
    }
    resto = [t for t in n.split() if t not in ruido and not t.isdigit()]
    return not resto


def _texto_con_sistema(texto: str, sistema: str) -> str:
    n = norm(texto)
    if sistema == 'embrague' and 'embrague' not in n and 'clutch' not in n:
        return f'{n} embrague'.strip()
    return n


def identidades_en(texto: str, sistema_heredado: str = '') -> list[str]:
    """Todas las piezas de la frase. El sistema se hereda solo dentro del tramo."""
    n = _expandir(norm(texto))
    if not n or 'sistema' in n and not _sistema_de(n):
        return []
    sistema = _sistema_del_trozo(n, sistema_heredado)
    if (
        sistema not in ('frenos', 'otro')
        and 'freno' not in n
        and 'rueda' not in n
        and re.search(r'\bkit\b', n)
        and ('bomba' in n or 'receptor' in n)
    ):
        sistema = 'embrague'
    visto = _texto_con_sistema(n, sistema) if sistema == 'embrague' else n
    encontradas: list[str] = []

    def _sumar(ident: str) -> None:
        if ident and ident not in encontradas:
            encontradas.append(ident)

    if ('disco' in visto or 'prensa' in visto or 'plato' in visto) and (
        'empuje' in visto or 'collarin' in visto or 'rodamiento' in visto
    ):
        _sumar('kit_embrague')
    if sistema == 'embrague' or 'embrague' in visto or 'clutch' in visto:
        if re.search(r'\bkit\b', visto) or _es_solo_el_kit(visto):
            _sumar('kit_embrague')
        if re.search(r'\bbomba\b', visto):
            _sumar('bomba_embrague')
        if 'maestro' in visto and 'bombin' not in visto and 'receptor' not in visto and 'esclavo' not in visto:
            _sumar('bomba_embrague')
        if (
            'bombin' in visto
            or 'receptor' in visto
            or 'esclavo' in visto
            or ('cilindro' in visto and 'maestro' not in visto)
        ):
            _sumar('cilindro_receptor_embrague')
        if 'crapodina' in visto or (
            'collarin' in visto and 'kit_embrague' not in encontradas
        ) or ('rodamiento de empuje' in visto and 'kit_embrague' not in encontradas):
            _sumar('rodamiento_empuje')
    for fila in _IDENTIDADES:
        for marca in fila['marcadores']:
            if marca not in visto:
                continue
            if not _marcador_permitido(marca, visto, sistema):
                continue
            _sumar(fila['id'])
            break
    if 'kit_embrague' in encontradas:
        encontradas = [ident for ident in encontradas if ident != 'rodamiento_empuje']
    return encontradas


def identidad_de(texto: str) -> str:
    """Id de la pieza, o vacío si el texto no nombra una sola pieza concreta."""
    if es_sistema(texto):
        return ''
    encontradas = identidades_en(texto)
    if len(encontradas) == 1:
        return encontradas[0]
    return ''


def nombre_de(identidad: str) -> str:
    fila = _POR_ID.get(identidad)
    return fila['nombre'] if fila else ''


def rol_de(identidad: str) -> str:
    fila = _POR_ID.get(identidad)
    return fila['rol'] if fila else ''


def es_sistema(texto: str) -> bool:
    """Un sistema no es un repuesto. «Sistema hidráulico de frenos…» no se cotiza como pieza."""
    n = norm(texto)
    if 'sistema' not in n:
        return False
    concreto = identidad_de_sin_sistema(n)
    return not concreto


def identidad_de_sin_sistema(n: str) -> str:
    encontradas = [ident for ident in identidades_en(n) if ident != 'kit_embrague']
    if len(encontradas) == 1:
        return encontradas[0]
    return ''


def identidades_distintas(linea: str, ficha: str) -> bool:
    """True solo cuando las dos frases nombran piezas distintas."""
    a = identidad_de(linea)
    b = identidad_de(ficha)
    return bool(a and b and a != b)


def composicion_de_kit(titulo: str) -> dict[str, bool] | None:
    """Lo que la ficha declara. None si no hay ficha o no se puede leer."""
    n = norm(titulo)
    if not n:
        return None
    if 'kit' not in n and 'embrague' not in n and 'clutch' not in n:
        return None
    partes = {
        'disco': 'disco' in n,
        'prensa': 'prensa' in n or 'plato' in n,
        'empuje': any(p in n for p in ('collarin', 'empuje', 'rodamiento')),
        'piloto': 'piloto' in n or 'ruleman' in n,
    }
    if not any(partes.values()):
        return None
    return partes


def kit_incluye_rodamiento(titulo: str) -> bool | None:
    """True si la ficha trae el rodamiento. None si no se puede confirmar."""
    partes = composicion_de_kit(titulo)
    if partes is None:
        return None
    return bool(partes['empuje'] or partes['piloto'])


def kit_pide_piloto_aparte(titulo: str) -> bool:
    """Solo si la ficha dice que el piloto no viene."""
    n = norm(titulo)
    if not n:
        return False
    return 'sin piloto' in n or 'no incluye piloto' in n or 'no trae piloto' in n


def ficha_vehiculo(vehiculo: dict | None) -> dict[str, Any] | None:
    if not isinstance(vehiculo, dict):
        return None
    marca = norm(str(vehiculo.get('marca') or ''))
    modelo = norm(str(vehiculo.get('modelo') or ''))
    for ficha in _FICHAS:
        if ficha['marca'] in marca and ficha['modelo'] in modelo:
            return ficha
    return None


def _fluido_confiable(fluidos: dict | None, ident: str) -> dict[str, Any] | None:
    if not isinstance(fluidos, dict):
        return None
    fluido = fluidos.get(ident)
    if not isinstance(fluido, dict):
        return None
    try:
        confianza = float(fluido.get('confianza') if fluido.get('confianza') is not None else 0)
    except (TypeError, ValueError):
        confianza = 0
    if confianza < UMBRAL_CONFIANZA or not str(fluido.get('especificacion') or '').strip():
        return None
    return fluido


def anotar_especificacion(
    rep: dict,
    vehiculo: dict | None,
    fluidos: dict | None = None,
) -> None:
    """Aceite y líquido salen con la spec del vehículo. La tabla local es el respaldo."""
    if not isinstance(rep, dict):
        return
    ident = str(rep.get('identidad') or '') or identidad_de(str(rep.get('nombre') or ''))
    if ident:
        rep['identidad'] = ident
        rep['rol'] = rol_de(ident) or rep.get('rol') or ''
    if ident not in ('aceite_caja', 'liquido_frenos'):
        return
    if str(rep.get('especificacion') or '').strip() and rep.get('especificacion_origen') == 'llm':
        return
    fluido = _fluido_confiable(fluidos, ident)
    if fluido:
        litros = str(fluido.get('litros') or '').strip()
        spec = str(fluido['especificacion']).strip()
        rep['especificacion'] = f'{spec} · {litros} L' if litros else spec
        rep['especificacion_origen'] = 'llm'
        if litros:
            rep['cantidad_texto'] = f'{litros} L'
        return
    ficha = ficha_vehiculo(vehiculo)
    if not ficha:
        return
    if ident == 'aceite_caja':
        aceite = ficha['aceite_caja']
        rep['especificacion'] = f"{aceite['especificacion']} · {aceite['litros']} L"
        rep['comentario'] = aceite['origen']
        rep['cantidad_texto'] = f"{aceite['litros']} L"
        rep['especificacion_origen'] = 'ficha'
    elif ident == 'liquido_frenos':
        rep['especificacion'] = ficha['liquido_frenos']['especificacion']
        rep['especificacion_origen'] = 'ficha'


def faenas_de(texto: str, identidades: list[str]) -> list[str]:
    n = norm(texto)
    titulos: list[str] = []
    for ident in identidades:
        titulo = _FAENA.get(ident)
        if titulo and titulo not in titulos:
            titulos.append(titulo)
    if ('purg' in n or 'sistema hidraulico' in n) and 'Purga del sistema hidráulico' not in titulos:
        titulos.append('Purga del sistema hidráulico')
    return titulos


_RUIDO_VEHICULO = {
    'renault', 'oroch', 'suzuki', 'toyota', 'hyundai', 'kia', 'chevrolet',
    'nissan', 'ford', 'volkswagen', 'mazda', 'peugeot', 'citroen', 'fiat',
    'honda', 'mitsubishi', 'chery', 'jeep', 'bmw', 'mercedes', 'audi',
    'volvo', 'subaru', 'patente', 'motor', 'ano', 'anio', 'modelo', 'marca',
    'bencina', 'diesel', 'gasolina', 'manual', 'automatico', 'mecanico',
}
_SOLO_FAENA = {
    'purgar', 'purga', 'revisar', 'revision', 'diagnostico', 'diagnosticar',
    'de', 'del', 'el', 'la', 'y', 'sistema',
}


def _es_preambulo(texto: str) -> bool:
    """Marca, modelo, año o patente. No es una pieza."""
    n = norm(texto)
    if not n:
        return True
    utiles = []
    for token in n.split():
        if token in _RUIDO_VEHICULO or token.isdigit() or re.fullmatch(r'[a-z]{2,4}\d{2,4}', token):
            continue
        utiles.append(token)
    return not utiles


def piezas_del_pedido(texto: str) -> list[dict[str, str]]:
    """Ítems atómicos. El sistema es el del tramo, no el de todo el texto.

    Cada mención queda como línea o como duda. Dos menciones de la misma
    identidad con calificadores distintos no se funden.
    """
    vistos: list[tuple[str, tuple[str, ...]]] = []
    libres: list[str] = []
    items: list[dict[str, str]] = []
    for cuerpo, etiqueta in _tramos(texto):
        sistema_tramo = _sistema_del_trozo(_expandir(norm(cuerpo)), etiqueta)
        partir_y = sistema_tramo == 'embrague' or _lados_con_pieza(cuerpo)
        for trozo in _trozos(cuerpo, partir_y=partir_y):
            if es_sistema(trozo) or _es_preambulo(trozo):
                continue
            sistema = _sistema_del_trozo(_expandir(norm(trozo)), sistema_tramo or etiqueta)
            encontradas = identidades_en(trozo, sistema_heredado=sistema)
            if 'reten_ciguenal' in encontradas and 'reten' not in norm(trozo) and sistema != 'embrague':
                encontradas = [ident for ident in encontradas if ident != 'reten_ciguenal']
            if not encontradas:
                n = norm(trozo)
                if not n or all(token in _SOLO_FAENA for token in n.split()):
                    continue
                if re.match(
                    r'^(cambio|revision|servicio|diagnostico|mantenimiento|mantencion)\b',
                    n,
                ):
                    continue
                if n in libres:
                    continue
                libres.append(n)
                items.append({
                    'identidad': 'sin_clasificar',
                    'rol': 'duda',
                    'nombre': trozo.strip(),
                    'texto_original': trozo.strip(),
                    'sistema': sistema,
                })
                continue
            califs = _calificadores(norm(trozo))
            for ident in encontradas:
                clave = (ident, califs)
                if clave in vistos:
                    continue
                vistos.append(clave)
                items.append({
                    'identidad': ident,
                    'rol': rol_de(ident),
                    'nombre': _nombre_con_calificadores(nombre_de(ident), norm(trozo)),
                    'texto_original': trozo.strip(),
                    'sistema': 'embrague' if ident in _IDENTIDADES_EMBRAGUE else (
                        'frenos' if ident.endswith('_freno') or ident in (
                            'bombin_rueda', 'cilindro_maestro_freno', 'pastillas_freno',
                            'balatas_freno', 'discos_freno', 'tambores_freno', 'flexible_freno',
                        ) else sistema
                    ),
                })
    return items


def validar_comprension(payload: dict | None) -> dict[str, Any]:
    """Schema estricto. Vacío, inválido o con una identidad desconocida no pasa."""
    if not isinstance(payload, dict) or not payload.get('items'):
        raise ValueError('comprension vacia')
    try:
        data = ComprensionSchema.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    vistos: set[str] = set()
    permitidas = set(_POR_ID) | {'sin_clasificar', 'otra'}
    roles = {ROL_REPUESTO, ROL_MANO, ROL_INSUMO, 'duda', 'sistema', 'mano_obra'}
    for item in data.items:
        if item.identidad not in permitidas:
            raise ValueError(f'identidad desconocida: {item.identidad}')
        if item.rol not in roles:
            raise ValueError(f'rol desconocido: {item.rol}')
        if item.identidad in ('sin_clasificar', 'otra'):
            continue
        if item.identidad in vistos:
            raise ValueError(f'identidad repetida: {item.identidad}')
        vistos.add(item.identidad)
    return data.model_dump()


def _duda_pieza(nombre: str, texto: str) -> dict[str, Any]:
    return {
        'id': f"pieza-{norm(nombre).replace(' ', '-')}"[:48],
        'texto': texto,
        'confirmada': False,
    }


def _confianza_baja(item: dict) -> bool:
    if 'confianza' not in item or item.get('confianza') is None:
        return False
    try:
        return float(item.get('confianza')) < UMBRAL_CONFIANZA
    except (TypeError, ValueError):
        return True


def _reconciliar_llm(texto: str, vehiculo: dict | None, validado: dict[str, Any]) -> dict[str, Any]:
    """La taxonomía valida al modelo. Si se contradicen, la pieza queda en duda."""
    items: list[dict[str, Any]] = []
    dudas = [duda for duda in (validado.get('dudas') or []) if isinstance(duda, dict)]
    fluidos = validado.get('fluidos') if isinstance(validado.get('fluidos'), dict) else {}
    for crudo in validado.get('items') or []:
        if not isinstance(crudo, dict):
            continue
        item = dict(crudo)
        frase = str(item.get('texto_original') or item.get('nombre') or '')
        ident_llm = str(item.get('identidad') or '')
        rol = str(item.get('rol') or '')
        if item.get('confianza') is None:
            item['confianza'] = 0.7
        if rol in ('duda', 'sistema', 'mano_obra') or ident_llm in ('', 'sin_clasificar'):
            if rol == 'sistema' or es_sistema(frase):
                dudas.append({
                    'id': 'sistema-no-repuesto',
                    'texto': 'Una frase de sistema no es un repuesto. Quedó como mano de obra o como duda.',
                    'confirmada': False,
                })
            else:
                dudas.append(_duda_pieza(
                    frase or item.get('nombre') or 'pieza',
                    f"No clasifiqué «{frase or item.get('nombre')}». Quedó como duda, no como otra pieza.",
                ))
            continue
        if ident_llm == 'otra':
            if _confianza_baja(item):
                dudas.append(_duda_pieza(
                    frase or item.get('nombre') or 'pieza',
                    (
                        f"La lectura de «{frase or item.get('nombre')}» no tiene confianza suficiente. "
                        'Quedó como duda visible, no se cotizó.'
                    ),
                ))
                continue
            if rol not in ('repuesto', 'insumo', ''):
                dudas.append(_duda_pieza(
                    frase or item.get('nombre') or 'pieza',
                    f"No clasifiqué «{frase or item.get('nombre')}». Quedó como duda, no como otra pieza.",
                ))
                continue
            sistema_item = str(item.get('sistema') or '') or _sistema_del_trozo(_expandir(norm(frase)), '')
            local = [
                ident for ident in identidades_en(frase, sistema_heredado=sistema_item)
                if not (sistema_item in ('frenos', 'otro') and ident in _IDENTIDADES_EMBRAGUE)
            ]
            nombre_llm = str(item.get('nombre') or frase).strip() or frase
            if (
                sistema_item
                and sistema_item not in ('', 'otro')
                and sistema_item not in norm(nombre_llm)
            ):
                nombre_llm = f'{nombre_llm} de {sistema_item}'
            if len(local) == 1:
                ident = local[0]
                item['nombre'] = _nombre_con_calificadores(nombre_de(ident) or nombre_llm, norm(frase))
            else:
                item['nombre'] = nombre_llm
            slug = norm(str(item['nombre'])).replace(' ', '-')[:40] or 'pieza'
            item['identidad'] = f"otra:{norm(sistema_item) or 'otro'}:{slug}"
            item['rol'] = ROL_REPUESTO if rol != 'insumo' else ROL_INSUMO
            item['sistema'] = sistema_item or 'otro'
            items.append(item)
            continue
        if _confianza_baja(item):
            dudas.append(_duda_pieza(
                frase or item.get('nombre') or ident_llm,
                f"La lectura de «{frase or item.get('nombre')}» no tiene confianza suficiente. Quedó como duda.",
            ))
            continue
        local = identidades_en(frase, sistema_heredado=_sistema_de(norm(texto)))
        if local and ident_llm not in local:
            dudas.append(_duda_pieza(
                frase or item.get('nombre') or ident_llm,
                (
                    f"La lectura y la taxonomía no coinciden en «{frase or item.get('nombre')}». "
                    'Quedó como duda, no como otra pieza.'
                ),
            ))
            continue
        if not local and _sistema_de(norm(frase)) in ('frenos', 'otro') and ident_llm in _IDENTIDADES_EMBRAGUE:
            dudas.append(_duda_pieza(
                frase,
                f"«{frase}» nombra otro sistema. No lo pasé a una pieza de embrague.",
            ))
            continue
        item['identidad'] = ident_llm
        item['rol'] = rol_de(ident_llm) or rol
        item['nombre'] = nombre_de(ident_llm) or item.get('nombre') or frase
        items.append(item)
    if any(es_sistema(trozo) for trozo in _trozos(texto)) and not any(
        duda.get('id') == 'sistema-no-repuesto' for duda in dudas
    ):
        dudas.append({
            'id': 'sistema-no-repuesto',
            'texto': 'Una frase de sistema no es un repuesto. Quedó como mano de obra o como duda.',
            'confirmada': False,
        })
    for item in items:
        anotar_especificacion(item, vehiculo, fluidos)
    return {
        'items': items,
        'faenas': faenas_de(texto, [item['identidad'] for item in items]),
        'dudas': dudas,
        'fluidos': fluidos,
    }


def _desde_taxonomia(texto: str, vehiculo: dict | None, aviso: str = '') -> dict[str, Any]:
    items = piezas_del_pedido(texto)
    if vehiculo:
        for item in items:
            anotar_especificacion(item, vehiculo)
    dudas = []
    if aviso:
        dudas.append({
            'id': 'lectura-no-usable',
            'texto': aviso,
            'confirmada': False,
        })
    if any(es_sistema(trozo) for trozo in _trozos(texto)):
        dudas.append({
            'id': 'sistema-no-repuesto',
            'texto': 'Una frase de sistema no es un repuesto. Quedó como mano de obra o como duda.',
            'confirmada': False,
        })
    for item in items:
        if item.get('identidad') != 'sin_clasificar':
            continue
        dudas.append(_duda_pieza(
            str(item.get('nombre') or ''),
            (
                f"No clasifiqué «{item.get('nombre')}». Quedó como duda: "
                'no se cobra y no se unió con otra pieza.'
            ),
        ))
    return {
        'items': items,
        'faenas': faenas_de(texto, [item['identidad'] for item in items if item['identidad'] != 'sin_clasificar']),
        'dudas': dudas,
        'fluidos': {},
    }


def comprender_pedido(texto: str, vehiculo: dict | None = None, respuesta_llm: dict | None = None) -> dict[str, Any]:
    """Lee el pedido. El modelo se valida; si no sirve, queda la taxonomía y una duda."""
    if respuesta_llm is not None:
        try:
            validado = validar_comprension(respuesta_llm)
        except ValueError:
            return _desde_taxonomia(
                texto,
                vehiculo,
                'La lectura del pedido vino vacía o inválida. No la usé para nombrar otra pieza.',
            )
        return _reconciliar_llm(texto, vehiculo, validado)
    return _desde_taxonomia(texto, vehiculo)


def _volcar(valor: Any) -> Any:
    if hasattr(valor, 'model_dump'):
        return valor.model_dump()
    return valor


def comprension_desde_pedido(pedido) -> dict[str, Any]:
    """La extracción que ya hace el generador, validada con el schema.

    No llama al modelo. Si esa llamada ya trajo ítems, se reconcilian con la
    taxonomía. Si no, la taxonomía lee los nombres.
    """
    nombres = []
    for rep in getattr(pedido, 'repuestos_mencionados', None) or []:
        nombre = str(getattr(rep, 'nombre', '') or '').strip()
        if nombre:
            nombres.append(nombre)
    for servicio in getattr(pedido, 'servicios', None) or []:
        nombre = str(getattr(servicio, 'nombre', '') or '').strip()
        if nombre:
            nombres.append(nombre)
    items_llm = list(getattr(pedido, 'items', None) or [])
    if items_llm:
        fluidos = getattr(pedido, 'fluidos', None) or {}
        if hasattr(fluidos, 'items'):
            fluidos = {llave: _volcar(valor) for llave, valor in fluidos.items()}
        elif isinstance(fluidos, dict):
            fluidos = {llave: _volcar(valor) for llave, valor in fluidos.items()}
        else:
            fluidos = {}
        return comprender_pedido(
            ', '.join(nombres),
            respuesta_llm={
                'items': [_volcar(item) for item in items_llm],
                'fluidos': fluidos,
                'faenas': [],
                'dudas': [],
            },
        )
    return comprender_pedido(', '.join(nombres))


def _ident_para_ficha(rep: dict) -> str:
    """Dos «otra» o la misma pieza con otro calificador no son la misma ficha."""
    if not isinstance(rep, dict):
        return ''
    guardada = str(rep.get('identidad') or '')
    if guardada.startswith('otra:'):
        return guardada
    nombre = str(rep.get('nombre') or rep.get('nombre_producto') or '')
    base = identidad_de(nombre)
    if not base and guardada not in ('', 'sin_clasificar', 'otra'):
        base = guardada
    if not base:
        return ''
    cal = _calificadores(norm(nombre))
    if cal:
        return f'{base}|{"+".join(cal)}'
    return base


def separar_precios_copiados(repuestos: list) -> list[dict]:
    """La misma ficha no puede cotizar dos piezas distintas."""
    grupos: dict[str, list] = {}
    for rep in repuestos or []:
        if not isinstance(rep, dict):
            continue
        url = str(rep.get('url_producto') or rep.get('url_referencia') or '').strip()
        if url:
            grupos.setdefault(url, []).append(rep)
    dudas = []
    for url, grupo in grupos.items():
        identidades = [_ident_para_ficha(rep) for rep in grupo]
        distintas = {ident for ident in identidades if ident}
        if len(distintas) < 2:
            continue
        titulo = ' '.join(str(rep.get('nombre_producto') or '') for rep in grupo)
        de_la_ficha = _ident_para_ficha({'nombre': titulo, 'nombre_producto': titulo})
        titulo_n = norm(titulo)
        for rep, ident in zip(grupo, identidades):
            if str(ident).startswith('otra:'):
                nombre = norm(str(rep.get('nombre') or ''))
                ruido = {'de', 'del', 'la', 'el', 'y', 'freno', 'frenos', 'para'}
                tokens = [token for token in nombre.split() if token not in ruido]
                if tokens and all(token in titulo_n for token in tokens):
                    continue
            elif de_la_ficha and ident == de_la_ficha:
                continue
            rep['precio_unitario_clp'] = 0
            rep['url_producto'] = ''
            rep['url_referencia'] = ''
            rep['nombre_producto'] = ''
            rep['precio_estimado'] = False
            dudas.append({
                'id': f"precio-copiado-{norm(str(rep.get('nombre') or 'pieza')).replace(' ', '-')}"[:80],
                'texto': (
                    f"El precio de {rep.get('nombre')} venía de la misma ficha que otra pieza. "
                    'Se quitó para no cobrar el kit como si fuera la bomba o el cilindro.'
                ),
                'confirmada': False,
            })
    return dudas


def _trozos(texto: str, partir_y: bool = False) -> list[str]:
    plano = str(texto or '')
    if partir_y:
        plano = re.sub(r'\s+y\s+', ', ', plano, flags=re.IGNORECASE)
    return [trozo.strip() for trozo in re.split(r'[,;]', plano) if trozo.strip()]

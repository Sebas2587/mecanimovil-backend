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
    """Todas las piezas de la frase. El sistema de la enumeración se hereda."""
    n = norm(texto)
    if not n or 'sistema' in n and not _sistema_de(n):
        return []
    propio = _sistema_de(n)
    if propio in ('frenos', 'otro'):
        sistema = ''
    else:
        sistema = propio or sistema_heredado
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
    """Ítems atómicos del texto. El sistema de la frase se hereda en la enumeración.

    Lo que no entra en la taxonomía queda sin clasificar. No se cobra: la duda
    lo guarda. No se fusiona con otra pieza.
    """
    ntexto = norm(texto)
    sistema = _sistema_de(ntexto)
    vistos: list[str] = []
    libres: list[str] = []
    items: list[dict[str, str]] = []
    for trozo in _trozos(texto, partir_y=sistema == 'embrague'):
        if es_sistema(trozo) or _es_preambulo(trozo):
            continue
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
        for ident in encontradas:
            if ident in vistos:
                continue
            vistos.append(ident)
            items.append({
                'identidad': ident,
                'rol': rol_de(ident),
                'nombre': nombre_de(ident),
                'texto_original': trozo.strip(),
                'sistema': 'embrague' if ident in _IDENTIDADES_EMBRAGUE else sistema,
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
        if rol in ('duda', 'sistema', 'mano_obra') or ident_llm in ('', 'otra', 'sin_clasificar'):
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
        identidades = [identidad_de(str(rep.get('nombre') or '')) for rep in grupo]
        distintas = {ident for ident in identidades if ident}
        if len(distintas) < 2:
            continue
        titulo = ' '.join(str(rep.get('nombre_producto') or '') for rep in grupo)
        de_la_ficha = identidad_de(titulo)
        for rep, ident in zip(grupo, identidades):
            if de_la_ficha and ident == de_la_ficha:
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

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
    especificacion: str = ''
    cantidad: str = ''
    unidad: str = ''

    def modelo(self) -> dict[str, Any]:
        return self.model_dump()


class ComprensionSchema(BaseModel):
    """Contrato de la salida estructurada. Una identidad por ítem."""

    items: list[ItemComprendido] = Field(default_factory=list)
    faenas: list[str] = Field(default_factory=list)
    dudas: list[dict[str, Any]] = Field(default_factory=list)


def norm(texto: str) -> str:
    plano = unicodedata.normalize('NFD', str(texto or ''))
    plano = ''.join(ch for ch in plano if unicodedata.category(ch) != 'Mn')
    plano = re.sub(r'[^a-z0-9]+', ' ', plano.lower())
    return re.sub(r'\s+', ' ', plano).strip()


def _es_solo_el_kit(n: str) -> bool:
    if 'sistema' in n or 'embrague' not in n and 'clutch' not in n:
        return False
    ruido = {
        'de', 'del', 'la', 'el', 'y', 'cambio', 'cambios', 'repuesto', 'repuestos',
        'embrague', 'clutch', 'kit',
    }
    resto = [t for t in n.split() if t not in ruido and not t.isdigit()]
    return not resto


def identidad_de(texto: str) -> str:
    """Id de la pieza, o vacío si el texto no nombra una pieza concreta."""
    if es_sistema(texto):
        return ''
    n = norm(texto)
    if not n:
        return ''
    mejor = ''
    largo = 0
    for fila in _IDENTIDADES:
        for marca in fila['marcadores']:
            if marca in n and len(marca) > largo:
                mejor = fila['id']
                largo = len(marca)
    if mejor:
        return mejor
    # Solo «embrague» o «cambio de embrague», sin otro sustantivo, es el kit.
    # «Flexible de embrague» no cae aquí: ya tiene identidad propia.
    if _es_solo_el_kit(n):
        return 'kit_embrague'
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
    mejor = ''
    largo = 0
    for fila in _IDENTIDADES:
        if fila['id'] == 'kit_embrague':
            continue
        for marca in fila['marcadores']:
            if marca in n and len(marca) > largo:
                mejor = fila['id']
                largo = len(marca)
    return mejor


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


def anotar_especificacion(rep: dict, vehiculo: dict | None) -> None:
    """Aceite y líquido salen con la spec del vehículo. No inventa un precio."""
    if not isinstance(rep, dict):
        return
    ficha = ficha_vehiculo(vehiculo)
    ident = identidad_de(str(rep.get('nombre') or ''))
    if ident:
        rep['identidad'] = ident
        rep['rol'] = rol_de(ident)
    if not ficha:
        return
    if ident == 'aceite_caja':
        aceite = ficha['aceite_caja']
        rep['especificacion'] = f"{aceite['especificacion']} · {aceite['litros']} L"
        rep['comentario'] = aceite['origen']
        rep['cantidad_texto'] = f"{aceite['litros']} L"
    elif ident == 'liquido_frenos':
        rep['especificacion'] = ficha['liquido_frenos']['especificacion']


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
    """Ítems atómicos del texto. Cada uno con su identidad.

    Lo que no entra en la taxonomía queda como pieza sin clasificar.
    No se tira y no se fusiona con el kit.
    """
    vistos: list[str] = []
    libres: list[str] = []
    items: list[dict[str, str]] = []
    for trozo in _trozos(texto):
        if es_sistema(trozo) or _es_preambulo(trozo):
            continue
        ident = identidad_de(trozo)
        if ident == 'reten_ciguenal' and 'reten' not in norm(trozo):
            continue
        if not ident:
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
                'rol': ROL_REPUESTO,
                'nombre': trozo.strip(),
            })
            continue
        if ident in vistos:
            continue
        vistos.append(ident)
        items.append({
            'identidad': ident,
            'rol': rol_de(ident),
            'nombre': nombre_de(ident),
        })
    return items


def validar_comprension(payload: dict | None) -> dict[str, Any]:
    """Schema. Una identidad desconocida o repetida no pasa."""
    try:
        data = ComprensionSchema.model_validate(payload or {})
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    vistos: set[str] = set()
    for item in data.items:
        if item.identidad not in _POR_ID and item.identidad != 'sin_clasificar':
            raise ValueError(f'identidad desconocida: {item.identidad}')
        if item.identidad == 'sin_clasificar':
            continue
        if item.identidad in vistos:
            raise ValueError(f'identidad repetida: {item.identidad}')
        vistos.add(item.identidad)
        if item.rol not in (ROL_REPUESTO, ROL_MANO, ROL_INSUMO, 'duda'):
            raise ValueError(f'rol desconocido: {item.rol}')
    return data.model_dump()


def comprender_pedido(texto: str, vehiculo: dict | None = None, respuesta_llm: dict | None = None) -> dict[str, Any]:
    """Lee el pedido. Si hay salida de modelo, tiene que validar; si no, la taxonomía."""
    if respuesta_llm is not None:
        validado = validar_comprension(respuesta_llm)
        return validado
    items = piezas_del_pedido(texto)
    if vehiculo:
        for item in items:
            anotar_especificacion(item, vehiculo)
    dudas = []
    if any(es_sistema(trozo) for trozo in _trozos(texto)):
        dudas.append({
            'id': 'sistema-no-repuesto',
            'texto': 'Una frase de sistema no es un repuesto. Quedó como mano de obra o como duda.',
            'confirmada': False,
        })
    for item in items:
        if item.get('identidad') != 'sin_clasificar':
            continue
        dudas.append({
            'id': f"pieza-{norm(item.get('nombre') or '').replace(' ', '-')}"[:48],
            'texto': (
                f"No clasifiqué «{item.get('nombre')}». Quedó como pieza aparte: "
                'no se descartó ni se unió con otra.'
            ),
            'confirmada': False,
        })
    return {
        'items': items,
        'faenas': faenas_de(texto, [item['identidad'] for item in items]),
        'dudas': dudas,
    }


def comprension_desde_pedido(pedido) -> dict[str, Any]:
    """La extracción que ya hace el generador, validada con el schema.

    No llama al modelo. Toma PedidoExtraido (la llamada existente
    extraer_pedido_con_llm) y lo pasa por validar_comprension.
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
    base = comprender_pedido(', '.join(nombres))
    return validar_comprension(base)


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


def _trozos(texto: str) -> list[str]:
    plano = str(texto or '')
    plano = re.sub(r'\s+y\s+', ', ', plano, flags=re.IGNORECASE)
    return [trozo.strip() for trozo in re.split(r'[,;]', plano) if trozo.strip()]

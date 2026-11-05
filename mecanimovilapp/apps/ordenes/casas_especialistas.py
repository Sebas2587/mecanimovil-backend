"""Casas de repuestos reales, con local en Santiago cuando está publicado.

Los datos salen de los sitios de cada casa (sucursales, contacto, marcas).
No se inventa una dirección, un teléfono ni un precio.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# fisica False = vendedor solo en línea. None = no confirmamos local.
# catalogo_online = hay fichas públicas con precio que se pueden buscar.

PERFILES: list[dict[str, Any]] = [
    {
        'nombre': 'Indra',
        'alias': 'indra repuestos',
        'dominio': 'indra.cl',
        'sitio': 'https://indra.cl/',
        'telefono': '+56 2 2783 8300',
        # Casa matriz: partió en Fiat y sumó estas marcas. El sitio público
        # no tiene fichas con precio (sucursales y «cotiza con nosotros»).
        'marcas': ['fiat', 'alfa romeo', 'lancia', 'volkswagen', 'audi', 'seat', 'skoda', 'chery'],
        'fisica': True,
        'catalogo_online': False,
        'sucursales': [
            {'direccion': 'Lira 664', 'comuna': 'Santiago'},
            {'direccion': 'Avenida Brasil 28', 'comuna': 'Santiago'},
            {'direccion': 'Av. Vicuña Mackenna 8580', 'comuna': 'La Florida'},
            {'direccion': 'Maipú 236', 'comuna': 'Maipú'},
            {'direccion': 'Maipú 220-233', 'comuna': 'Concepción'},
        ],
    },
    {
        'nombre': 'Adriazola',
        'alias': 'adriazola repuestos',
        'dominio': 'adriazolarepuestos.com',
        'sitio': 'https://www.adriazolarepuestos.com/',
        'telefono': '+56 2 2350 3300',
        'marcas': ['peugeot', 'citroen', 'renault', 'chevrolet', 'opel', 'ds'],
        'fisica': True,
        'catalogo_online': True,
        'sucursales': [
            {
                'direccion': 'Diez de Julio 391',
                'comuna': 'Santiago',
                'marcas': ['peugeot', 'renault', 'citroen'],
            },
            {
                'direccion': 'Brasil 32',
                'comuna': 'Santiago',
                'marcas': ['peugeot', 'renault', 'citroen', 'opel', 'chevrolet'],
            },
            {
                'direccion': 'Gran Avenida 7765',
                'comuna': 'La Cisterna',
                'marcas': ['peugeot', 'renault', 'citroen', 'opel', 'chevrolet'],
            },
        ],
    },
    {
        'nombre': 'Comauto',
        'alias': 'comauto',
        'dominio': 'comauto.cl',
        'sitio': 'https://comauto.cl/',
        'telefono': '+56 2 2510 4040',
        'marcas': ['peugeot', 'renault', 'citroen'],
        'fisica': True,
        # El sitio pide cotizar. No publica el precio de la ficha.
        'catalogo_online': False,
        'sucursales': [
            {'direccion': 'Av. 10 de Julio 370', 'comuna': 'Santiago'},
        ],
    },
    {
        'nombre': 'Casa Citroën',
        'alias': 'casa citroen',
        'dominio': 'casacitroen.cl',
        'sitio': 'https://www.casacitroen.cl/',
        'telefono': '+56 2 2510 4020',
        'marcas': ['citroen'],
        'fisica': True,
        'catalogo_online': False,
        'sucursales': [
            {'direccion': 'Av. 10 de Julio 380', 'comuna': 'Santiago'},
        ],
    },
    {
        'nombre': 'Vimae',
        'alias': 'repuestos vimae',
        'dominio': 'vimae.cl',
        'sitio': 'https://vimae.cl/',
        'telefono': '+56 9 5126 6674',
        'marcas': [
            'chevrolet', 'isuzu', 'opel', 'kia', 'hyundai', 'mitsubishi',
            'mazda', 'maxus', 'mg',
        ],
        'fisica': True,
        'catalogo_online': False,
        'sucursales': [
            {
                'direccion': 'Av. 10 de Julio 618',
                'comuna': 'Santiago',
                'marcas': ['chevrolet', 'isuzu', 'opel'],
            },
            {
                'direccion': 'Av. 10 de Julio 636',
                'comuna': 'Santiago',
                'marcas': ['maxus', 'mg'],
            },
            {
                'direccion': 'Av. 10 de Julio 648',
                'comuna': 'Santiago',
                'marcas': ['kia', 'hyundai', 'mitsubishi', 'mazda'],
            },
        ],
    },
    {
        'nombre': 'Ciper',
        'alias': 'ciper',
        'dominio': 'ciper.cl',
        'sitio': 'https://www.ciper.cl/',
        'telefono': '',
        # Seis tiendas; el sitio publica Avenida Brasil (Santiago) sin numeración.
        'marcas': [
            'nissan', 'chevrolet', 'kia', 'hyundai', 'toyota', 'suzuki',
            'mitsubishi', 'ssangyong', 'isuzu', 'mahindra',
        ],
        'fisica': True,
        'catalogo_online': True,
        'sucursales': [
            {'direccion': 'Avenida Brasil', 'comuna': 'Santiago'},
        ],
    },
    # Ya estaban en la búsqueda. No les invento sucursal.
    {
        'nombre': 'Suzukistore20',
        'alias': 'suzukistore20',
        'dominio': '',
        'sitio': '',
        'telefono': '',
        'marcas': ['suzuki'],
        'fisica': False,
        'catalogo_online': False,
        'sucursales': [],
    },
    {
        'nombre': 'Miktares',
        'alias': 'miktares',
        'dominio': '',
        'sitio': '',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': False,
        'sucursales': [],
    },
    {
        'nombre': 'Frenos Vergara',
        'alias': 'frenos vergara',
        'dominio': 'frenosvergara.shop',
        'sitio': 'https://frenosvergara.shop/',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': True,
        'sucursales': [],
    },
    {
        'nombre': 'Mundo Repuestos',
        'alias': 'mundo repuestos',
        'dominio': 'mundorepuestos.cl',
        'sitio': 'https://www.mundorepuestos.cl/',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': True,
        'sucursales': [],
    },
    {
        'nombre': 'Repuestos Sergio Escobar',
        'alias': 'sergio escobar',
        'dominio': 'sergioescobar.cl',
        'sitio': 'https://repuestos.sergioescobar.cl/',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': True,
        'sucursales': [],
    },
    {
        'nombre': 'Repuestos Ank',
        'alias': 'repuestos ank',
        'dominio': 'repuestosank.cl',
        'sitio': '',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': True,
        'sucursales': [],
    },
    {
        'nombre': 'Emasa',
        'alias': 'emasa',
        'dominio': 'emasa.cl',
        'sitio': '',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': True,
        'sucursales': [],
    },
    {
        'nombre': 'Todo Embragues',
        'alias': 'todo embragues',
        'dominio': 'todoembragues.cl',
        'sitio': '',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': True,
        'sucursales': [],
    },
    {
        'nombre': 'Casa del Embrague',
        'alias': 'casa del embrague',
        'dominio': 'casadelembrague.cl',
        'sitio': '',
        'telefono': '',
        'marcas': [],
        'fisica': None,
        'catalogo_online': True,
        'sucursales': [],
    },
]


def _norm(texto: str) -> str:
    t = unicodedata.normalize('NFD', str(texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', t).strip()


def es_etiqueta_historial(nombre: str) -> bool:
    """El historial es un precio, no una casa de repuestos."""
    return _norm(nombre) in {'historial del taller', 'historial', 'historial taller'}


def _compacto(texto: str) -> str:
    return re.sub(r'[^a-z0-9]', '', _norm(texto))


def _host(url_o_dominio: str) -> str:
    texto = str(url_o_dominio or '').strip().lower()
    if '://' in texto:
        texto = texto.split('://', 1)[1]
    texto = texto.split('/', 1)[0].split(':', 1)[0]
    return texto[4:] if texto.startswith('www.') else texto


def perfiles_para_settings() -> list[dict[str, Any]]:
    """La lista que ya consumía la búsqueda, más el perfil."""
    out = []
    for perfil in PERFILES:
        out.append({
            'nombre': perfil['nombre'],
            'alias': perfil['alias'],
            'dominio': perfil['dominio'],
            'marcas': list(perfil['marcas']),
            'fisica': perfil['fisica'],
            'catalogo_online': perfil['catalogo_online'],
            'telefono': perfil['telefono'],
            'sitio': perfil['sitio'],
            'sucursales': list(perfil['sucursales']),
        })
    return out


def _marca_calza(marca: str, marcas: list[str]) -> bool:
    m = _norm(marca)
    if not m or not marcas:
        return False
    for item in marcas:
        mk = _norm(item)
        if mk and (mk in m or m in mk):
            return True
    return False


def perfil_de(nombre: str = '', url: str = '') -> dict[str, Any] | None:
    host = _host(url or nombre)
    compacto = _compacto(nombre)
    for perfil in PERFILES:
        dom = _host(perfil.get('dominio') or '')
        if dom and host and (host == dom or host.endswith('.' + dom) or dom in host):
            return perfil
        if compacto and compacto == _compacto(perfil.get('nombre') or ''):
            return perfil
        alias = _compacto(perfil.get('alias') or '')
        if compacto and alias and (compacto == alias or compacto.startswith(alias)):
            return perfil
    return None


def es_fisica(nombre: str = '', url: str = '') -> bool:
    perfil = perfil_de(nombre, url)
    return bool(perfil and perfil.get('fisica') is True)


def es_solo_en_linea(nombre: str = '', url: str = '') -> bool:
    perfil = perfil_de(nombre, url)
    if perfil is not None and perfil.get('fisica') is False:
        return True
    host = _host(url)
    compacto = _compacto(nombre)
    if 'mercadolibre' in host or 'mercadolibre' in compacto:
        return True
    generalistas = (
        'lider.cl', 'sodimac.cl', 'falabella.com', 'easy.cl', 'paris.cl',
        'ripley.cl', 'construmart.cl',
    )
    return any(host == d or host.endswith('.' + d) for d in generalistas)


def especialistas_de_marca(marca: str) -> list[dict[str, Any]]:
    return [
        perfil for perfil in PERFILES
        if perfil.get('fisica') is True and _marca_calza(marca, perfil.get('marcas') or [])
    ]


def especialista_de_la_ficha(nombre: str, url: str, marca: str) -> dict[str, Any] | None:
    """La ficha es de la especialista solo si el enlace es de su sitio."""
    url = str(url or '').strip()
    if not url:
        return None
    perfil = perfil_de('', url)
    if not perfil or perfil.get('fisica') is not True:
        return None
    if nombre:
        otro = perfil_de(nombre, '')
        if otro and _host(str(otro.get('dominio') or '')) != _host(str(perfil.get('dominio') or '')):
            return None
    if not _marca_calza(marca, perfil.get('marcas') or []):
        return None
    return perfil


def marca_visible(marca: str) -> str:
    palabras = [p for p in str(marca or '').split() if p]
    if not palabras:
        return 'la marca'
    return ' '.join(p[:1].upper() + p[1:].lower() for p in palabras)


def _pesos(monto: int) -> str:
    return '$' + f'{int(monto):,}'.replace(',', '.')


def sucursal_para(perfil: dict[str, Any], marca: str = '', comuna_taller: str = '') -> dict[str, Any]:
    sucursales = list(perfil.get('sucursales') or [])
    if not sucursales:
        return {}

    def _sirve(sucursal: dict[str, Any]) -> bool:
        marcas = sucursal.get('marcas') or []
        if marcas and marca and not _marca_calza(marca, marcas):
            return False
        return True

    candidatas = [s for s in sucursales if _sirve(s)] or sucursales
    texto = _norm(comuna_taller)
    if texto:
        especificas: list[dict[str, Any]] = []
        generica: dict[str, Any] | None = None
        for sucursal in sorted(
            candidatas,
            key=lambda s: len(_norm(s.get('comuna') or '')),
            reverse=True,
        ):
            comuna = _norm(sucursal.get('comuna') or '')
            if not comuna or (comuna != texto and comuna not in texto):
                continue
            if comuna == 'santiago':
                # Lira y Brasil comparten comuna. Quedarse con la última
                # imprimía Avenida Brasil 28 cuando el texto solo dice Santiago.
                if generica is None:
                    generica = sucursal
            else:
                especificas.append(sucursal)
        if especificas:
            return especificas[0]
        if generica is not None:
            return generica
    for sucursal in candidatas:
        if _norm(sucursal.get('comuna') or '') != 'concepcion':
            return sucursal
    return candidatas[0]


def texto_sucursal(sucursal: dict[str, Any] | None) -> str:
    if not sucursal:
        return ''
    return ', '.join(
        parte for parte in (
            str(sucursal.get('direccion') or '').strip(),
            str(sucursal.get('comuna') or '').strip(),
        ) if parte
    )


def nota_especialista(nombre: str, marca: str, *, cubre_todo: bool, a_consultar: bool) -> str:
    casa = str(nombre or '').strip() or 'La casa'
    auto = marca_visible(marca)
    if cubre_todo and not a_consultar:
        return f'{casa}: especialista {auto}, tiene todos los repuestos de esta cotización.'
    if a_consultar:
        return nota_consulta_especialista(casa, auto)
    return f'{casa}: especialista {auto}, mejor precio encontrado.'


def nota_consulta_especialista(
    nombre: str,
    marca: str,
    *,
    tienda: str = '',
    precio: int = 0,
) -> str:
    """Sin ficha no hay stock verificado. La referencia es la de esta línea."""
    casa = str(nombre or '').strip() or 'La casa'
    auto = marca_visible(marca)
    base = f'{casa} (especialista {auto}): consulta disponibilidad y precio.'
    casa_ref = str(tienda or '').strip()
    try:
        monto = int(precio or 0)
    except (TypeError, ValueError):
        monto = 0
    if not casa_ref or monto <= 0:
        return base
    return f'{base} Referencia: {casa_ref} {_pesos(monto)}.'


def nota_solo_en_linea(nombre: str) -> str:
    casa = str(nombre or '').strip() or 'Tienda'
    return f'{casa} (solo en línea): no hay casa física con esta pieza.'


def prioridad_candidato(url: str, titulo: str, marca: str) -> tuple[int, int, int]:
    """Más chico = mejor. Solo entre fichas que ya pasaron las compuertas.

    Especialista física de la marca, original/OEM, casa física, desconocida, solo en línea.
    """
    perfil = especialista_de_la_ficha('', url, marca)
    especialista = 0 if perfil else 1
    texto = _norm(titulo)
    oem = 0 if especialista == 0 and any(
        token in texto for token in ('original', 'oem', 'genuino')
    ) else 1
    if perfil or es_fisica('', url):
        fisica = 0
    elif es_solo_en_linea('', url):
        fisica = 2
    else:
        fisica = 1
    return (especialista, oem, fisica)

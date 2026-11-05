"""PDF de orden de compra de repuestos para llevar a la casa.

Documento del taller: identidad, vehículo y una tabla por casa. Sin mano de
obra y sin el precio que ve el cliente. Un monto solo se imprime como
referencia de otra tienda, nunca como si la casa lo hubiera cotizado cuando
la línea está a consultar.
"""
from __future__ import annotations

import os
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from django.utils import timezone
from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

_FONT_DIR = Path(__file__).resolve().parent.parent / 'fonts'
_FONT_REG = _FONT_DIR / 'DejaVuSans.ttf'
_FONT_BOLD = _FONT_DIR / 'DejaVuSans-Bold.ttf'

INK = (32, 32, 32)
MUTED = (98, 98, 98)
LINE = (214, 214, 214)
HEADER_BG = (244, 244, 244)
PAPER = (255, 255, 255)
SOFT = (255, 241, 246)
MAGENTA = (253, 43, 123)
LINK = (12, 84, 128)
WHITE = (255, 255, 255)

MARGIN = 14.0
PAGE_W = 210.0
PAGE_H = 297.0
CONTENT_BOTTOM = 279.0
CONTENT_W = PAGE_W - 2 * MARGIN
COLS = (10.0, 50.0, 48.0, 14.0, 60.0)  # #, repuesto, especificación, cant., referencia
HEADERS = ('#', 'Repuesto', 'Especificación', 'Cant.', 'Referencia')
_MESES = (
    'ene', 'feb', 'mar', 'abr', 'may', 'jun',
    'jul', 'ago', 'sep', 'oct', 'nov', 'dic',
)
_PIE = 'No incluye mano de obra ni el valor cobrado al cliente.'


def _pesos(monto: int) -> str:
    return '$' + f'{int(monto):,}'.replace(',', '.')


def _txt(valor: Any) -> str:
    return ' '.join(str(valor or '').split())


def _fecha(cuando: date) -> str:
    return f'{cuando.day} {_MESES[cuando.month - 1]} {cuando.year}'


class _OrdenPdf(FPDF):
    def __init__(self):
        super().__init__(format='A4', unit='mm')
        self.add_font('DejaVu', '', str(_FONT_REG))
        self.add_font('DejaVu', 'B', str(_FONT_BOLD))
        self.set_auto_page_break(auto=False)
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.alias_nb_pages()

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(MARGIN, self.get_y(), PAGE_W - MARGIN, self.get_y())
        self.set_y(-12)
        self.set_font('DejaVu', '', 8)
        self.set_text_color(*MUTED)
        self.cell(CONTENT_W - 22, 8, _PIE)
        self.cell(22, 8, f'{self.page_no()} / {{nb}}', align='R')


def _linea_es_historial(rep: dict) -> bool:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        _linea_es_historial as _es,
    )

    return _es(rep)


def _casa_grupo(rep: dict, marca: str) -> str:
    from mecanimovilapp.apps.ordenes.casas_especialistas import (
        es_etiqueta_historial,
        especialistas_de_marca,
    )

    casa = _txt(rep.get('casa_repuesto_nombre'))
    proveedor = _txt(rep.get('proveedor_nombre'))
    if casa and not es_etiqueta_historial(casa):
        return casa
    if proveedor and not es_etiqueta_historial(proveedor) and not _linea_es_historial(rep):
        return proveedor
    perfiles = especialistas_de_marca(marca) if marca else []
    if perfiles:
        return str(perfiles[0].get('nombre') or '')
    if proveedor and not es_etiqueta_historial(proveedor):
        return proveedor
    return 'Casa por confirmar'


def _grupos(repuestos: list[dict], marca: str = '') -> list[tuple[str, list[dict]]]:
    orden: list[str] = []
    grupos: dict[str, list[dict]] = {}
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        nombre = _txt(rep.get('nombre'))
        if not nombre:
            continue
        casa = _casa_grupo(rep, marca) or 'Casa por confirmar'
        if casa not in grupos:
            orden.append(casa)
            grupos[casa] = []
        grupos[casa].append(rep)
    return [(casa, grupos[casa]) for casa in orden]


def _monto_historial(rep: dict) -> int:
    for campo in ('precio_referencia_clp', 'precio_unitario_clp'):
        try:
            monto = int(rep.get(campo) or 0)
        except (TypeError, ValueError):
            monto = 0
        if monto > 0:
            return monto
    return 0


def _contexto(cotizacion) -> dict[str, Any]:
    tipo = ' '.join(
        parte for parte in (
            str(getattr(cotizacion, 'tipo_motor', '') or ''),
            str(getattr(cotizacion, 'tipo_motor_label', '') or ''),
        ) if parte
    )
    return {
        'modelo': str(getattr(cotizacion, 'vehiculo_modelo', '') or ''),
        'anio': getattr(cotizacion, 'vehiculo_anio', None),
        'tipo_motor': tipo,
        'cilindraje': getattr(cotizacion, 'vehiculo_cilindraje', '') or '',
    }


def _referencia(rep: dict, cotizacion) -> dict[str, Any]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        _referencia_consulta,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
        validar_repuesto,
    )

    ctx = _contexto(cotizacion)
    ctx['marca'] = str(getattr(cotizacion, 'vehiculo_marca', '') or '')
    ficha = validar_repuesto(rep, **ctx)
    # Sin página de producto, el PDF igual puede nombrar la tienda de la referencia.
    # Una ficha descartada no se vuelve a imprimir.
    if (
        ficha.get('validacion_estado') != 'sin_referencia_valida'
        and not ficha.get('tienda_referencia')
        and rep.get('precio_a_consultar')
        and not _linea_es_historial(rep)
    ):
        tienda, precio = _referencia_consulta(rep, **_contexto(cotizacion))
        if tienda and precio > 0:
            ficha['tienda_referencia'] = tienda
            ficha['precio_verificado_clp'] = int(precio)
            ficha['url_referencia'] = ''
    return ficha


def _lineas_referencia(rep: dict, ficha: dict) -> list[tuple[str, str]]:
    """Texto de la columna y URL clicable, si hay ficha."""
    url = _txt(ficha.get('url_referencia'))
    tienda = _txt(ficha.get('tienda_referencia'))
    try:
        precio = int(ficha.get('precio_verificado_clp') or 0)
    except (TypeError, ValueError):
        precio = 0
    if _linea_es_historial(rep):
        monto = _monto_historial(rep)
        lineas = [('A consultar', '')]
        if monto > 0:
            lineas.append((f'historial del taller {_pesos(monto)}', ''))
        casa = _txt(ficha.get('casa_sugerida'))
        if casa:
            lineas.append((f'no verificado en {casa}', ''))
        return lineas
    aviso = ''
    casa = _txt(ficha.get('casa_sugerida'))
    if casa and tienda and casa.casefold() != tienda.casefold():
        aviso = f'no verificado en {casa}'
    if rep.get('precio_a_consultar'):
        lineas = [('A consultar', '')]
        if tienda and precio > 0:
            lineas.append((f'{tienda} {_pesos(precio)}', ''))
        if aviso:
            lineas.append((aviso, ''))
        if url:
            lineas.append(('Ver ficha', url))
        return lineas
    if tienda and precio > 0:
        lineas = [(f'{tienda} {_pesos(precio)}', '')]
        if aviso:
            lineas.append((aviso, ''))
        if url:
            lineas.append(('Ver ficha', url))
        return lineas
    try:
        monto = int(rep.get('precio_unitario_clp') or 0)
    except (TypeError, ValueError):
        monto = 0
    if monto > 0:
        return [(f'Referencia {_pesos(monto)}', '')]
    return [('A consultar', '')]


def _sucursal_para_pdf(cotizacion, casa: str, muestra: dict) -> tuple[str, str]:
    """La sucursal sigue la dirección actual del taller, no la que quedó guardada."""
    from mecanimovilapp.apps.ordenes.casas_especialistas import (
        perfil_de,
        sucursal_para,
        texto_sucursal,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
        _lugar_del_taller,
    )

    guardada = _txt(muestra.get('casa_sucursal'))
    telefono = _txt(muestra.get('casa_telefono'))
    lugar = _lugar_del_taller(getattr(cotizacion, 'taller', None))
    perfil = perfil_de(casa) if lugar else None
    if not perfil:
        return guardada, telefono
    sucursal = sucursal_para(
        perfil,
        str(getattr(cotizacion, 'vehiculo_marca', '') or ''),
        lugar,
    )
    texto = texto_sucursal(sucursal)
    if texto:
        return texto, str(perfil.get('telefono') or telefono)
    return guardada, telefono


def _horario(casa: str, lineas: list[dict]) -> str:
    from mecanimovilapp.apps.ordenes.casas_especialistas import perfil_de

    for rep in lineas:
        texto = _txt(rep.get('casa_horario') or rep.get('horario'))
        if texto:
            return texto
    perfil = perfil_de(casa)
    if not perfil:
        return ''
    return _txt(perfil.get('horario'))


def _es_especialista(casa: str, marca: str) -> bool:
    from mecanimovilapp.apps.ordenes.casas_especialistas import (
        _norm,
        especialistas_de_marca,
    )

    nombre = _norm(casa)
    return any(_norm(str(perfil.get('nombre') or '')) == nombre for perfil in especialistas_de_marca(marca))


def _leer_logo(foto) -> str | BytesIO | None:
    if not foto:
        return None
    try:
        path = getattr(foto, 'path', None)
        if path and os.path.isfile(path):
            return path
        if hasattr(foto, 'read'):
            data = foto.read()
            try:
                foto.seek(0)
            except Exception:
                pass
            if data:
                buf = BytesIO(data)
                buf.seek(0)
                return buf
    except Exception:
        return None
    return None


_DIRECCION_VACIA = frozenset({
    '',
    'chile',
    's/n',
    'sn',
    'sin comuna',
    'sin ciudad',
    'sin numero',
    'sin número',
})


def _norm_parte(texto: str) -> str:
    return ' '.join(str(texto or '').casefold().split())


def _contiene_numero(texto: str, numero: str) -> bool:
    if not numero:
        return False
    return re.search(
        rf'(?<!\d){re.escape(numero)}(?!\d)',
        texto,
        flags=re.IGNORECASE,
    ) is not None


def _direccion_encabezado(*fuentes: str, numero: str = '', extras: tuple[str, ...] = ()) -> str:
    """Calle, número, comuna y ciudad, sin repetir un trozo."""
    vistos: set[str] = set()
    trozos: list[str] = []
    numero_limpio = ' '.join(str(numero or '').split())
    numero_clave = _norm_parte(numero_limpio)

    def agregar(valor: str, *, es_numero: bool = False) -> None:
        texto = ' '.join(str(valor or '').split())
        clave = _norm_parte(texto)
        if not clave or clave in _DIRECCION_VACIA or clave in vistos:
            return
        if es_numero and any(_contiene_numero(pieza, texto) for pieza in trozos):
            vistos.add(clave)
            return
        vistos.add(clave)
        trozos.append(texto)

    for fuente in fuentes:
        for trozo in str(fuente or '').split(','):
            agregar(trozo)
    if numero_clave not in _DIRECCION_VACIA:
        agregar(numero_limpio, es_numero=True)
    for extra in extras:
        agregar(extra)
    if not trozos:
        return ''

    calle = trozos[0]
    resto: list[str] = []
    numero_puesto = (
        numero_clave not in _DIRECCION_VACIA and (
            _norm_parte(calle) == numero_clave or _contiene_numero(calle, numero_limpio)
        )
    )
    for trozo in trozos[1:]:
        if numero_clave not in _DIRECCION_VACIA and not numero_puesto and _norm_parte(trozo) == numero_clave:
            calle = f'{calle} {trozo}'.strip()
            numero_puesto = True
            continue
        resto.append(trozo)
    return ', '.join([calle, *resto])


def _identidad(cotizacion) -> dict[str, Any]:
    taller = getattr(cotizacion, 'taller', None)
    nombre = _txt(getattr(taller, 'nombre', '')) or 'Taller'
    telefono = _txt(getattr(taller, 'telefono', ''))
    rut = _txt(getattr(taller, 'rut', ''))
    usuario = getattr(taller, 'usuario', None)
    email = _txt(getattr(usuario, 'email', '')) if usuario is not None else ''
    direccion = ''
    fisica = None
    try:
        fisica = getattr(taller, 'direccion_fisica', None)
    except Exception:
        fisica = None
    if fisica is not None:
        direccion = _direccion_encabezado(
            _txt(getattr(fisica, 'calle', '')),
            numero=_txt(getattr(fisica, 'numero', '')),
            extras=(
                _txt(getattr(fisica, 'comuna', '')),
                _txt(getattr(fisica, 'ciudad', '')),
                _txt(getattr(fisica, 'region', '')),
            ),
        )
    if not direccion and usuario is not None:
        direccion = _direccion_encabezado(_txt(getattr(usuario, 'direccion', '')))
    folio = _txt(getattr(cotizacion, 'numero_publico', ''))
    if not folio and getattr(cotizacion, 'pk', None):
        folio = str(cotizacion.pk)
    return {
        'nombre': nombre,
        'telefono': telefono,
        'rut': rut,
        'email': email,
        'direccion': direccion,
        'logo': _leer_logo(getattr(taller, 'foto_perfil', None)),
        'folio': folio,
    }


def _iniciales(nombre: str) -> str:
    partes = [p for p in nombre.split() if p]
    if not partes:
        return 'T'
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][:1] + partes[1][:1]).upper()


def _font(pdf: _OrdenPdf, size: float, *, bold: bool = False, color=INK) -> None:
    pdf.set_font('DejaVu', 'B' if bold else '', size)
    pdf.set_text_color(*color)


def _envuelve(pdf: _OrdenPdf, w: float, text: str, size: float, *, bold: bool = False) -> list[str]:
    _font(pdf, size, bold=bold)
    lineas = pdf.multi_cell(
        w, 4, text or ' ',
        dry_run=True,
        output=MethodReturnValue.LINES,
        align='L',
        new_x=XPos.RIGHT,
        new_y=YPos.TOP,
    )
    return [ln for ln in (lineas or []) if str(ln).strip()] or ['']


def _salta(pdf: _OrdenPdf, alto: float) -> None:
    if pdf.get_y() + alto <= CONTENT_BOTTOM:
        return
    pdf.add_page()
    pdf.set_y(MARGIN)


def _logo_o_iniciales(pdf: _OrdenPdf, x: float, y: float, identidad: dict) -> None:
    lado = 16.0
    logo = identidad.get('logo')
    dibujado = False
    if logo:
        try:
            pdf.image(logo, x=x, y=y, w=lado, h=lado)
            dibujado = True
        except Exception:
            dibujado = False
    if not dibujado:
        pdf.set_fill_color(*SOFT)
        pdf.rect(x, y, lado, lado, style='F')
        _font(pdf, 9, bold=True, color=MAGENTA)
        pdf.set_xy(x, y + 5.2)
        pdf.cell(lado, 5, _iniciales(identidad['nombre']), align='C')
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, lado, lado)


def _draw_identidad(pdf: _OrdenPdf, identidad: dict, cuando: date) -> None:
    y = pdf.get_y()
    pdf.set_fill_color(*MAGENTA)
    pdf.rect(MARGIN, y, CONTENT_W, 1.6, style='F')
    y += 4
    _logo_o_iniciales(pdf, MARGIN, y, identidad)
    texto_x = MARGIN + 20
    texto_w = 98
    _font(pdf, 13, bold=True)
    pdf.set_xy(texto_x, y)
    pdf.multi_cell(texto_w, 6, identidad['nombre'], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    meta = []
    if identidad['direccion']:
        meta.append(identidad['direccion'])
    contacto = ' · '.join(parte for parte in (identidad['telefono'], identidad['email']) if parte)
    if contacto:
        meta.append(contacto)
    if identidad['rut']:
        meta.append(f'RUT {identidad["rut"]}')
    _font(pdf, 8, color=MUTED)
    for linea in meta:
        pdf.set_x(texto_x)
        pdf.multi_cell(texto_w, 4, linea, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    alto_izq = max(16, pdf.get_y() - y)
    der_x = MARGIN + 118
    der_w = CONTENT_W - 118
    _font(pdf, 8, color=MUTED)
    pdf.set_xy(der_x, y + 1)
    pdf.multi_cell(der_w, 4, _fecha(cuando), align='R')
    if identidad['folio']:
        pdf.set_x(der_x)
        pdf.multi_cell(der_w, 4, f'Nº {identidad["folio"]}', align='R')
    pdf.set_y(max(pdf.get_y(), y + alto_izq) + 3)
    _font(pdf, 14, bold=True)
    pdf.set_x(MARGIN)
    pdf.cell(CONTENT_W, 7, 'Orden de compra de repuestos', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    y_rule = pdf.get_y()
    pdf.line(MARGIN, y_rule, PAGE_W - MARGIN, y_rule)
    pdf.set_y(y_rule + 4)


def _draw_vehiculo(pdf: _OrdenPdf, cotizacion) -> None:
    patente = _txt(getattr(cotizacion, 'vehiculo_patente', '')) or 'Sin patente'
    auto = ' '.join(
        parte for parte in (
            _txt(getattr(cotizacion, 'vehiculo_marca', '')),
            _txt(getattr(cotizacion, 'vehiculo_modelo', '')),
            _txt(getattr(cotizacion, 'vehiculo_anio', '')),
        ) if parte
    ) or 'Sin marca ni modelo'
    motor = ' '.join(
        parte for parte in (
            _txt(getattr(cotizacion, 'vehiculo_cilindraje', '')),
            _txt(getattr(cotizacion, 'tipo_motor_label', '') or getattr(cotizacion, 'tipo_motor', '')),
        ) if parte
    ) or 'Sin dato'
    vin = _txt(getattr(cotizacion, 'vehiculo_vin', '')) or 'Sin VIN'
    celdas = (
        ('Patente', patente),
        ('Vehículo', auto),
        ('Motor', motor),
        ('VIN', vin),
    )
    ancho = CONTENT_W / 4
    envueltas = [
        _envuelve(pdf, ancho - 4, valor, 8, bold=True)
        for _, valor in celdas
    ]
    alto = 8 + max(len(lineas) for lineas in envueltas) * 3.8
    _salta(pdf, alto + 2)
    y = pdf.get_y()
    pdf.set_fill_color(*HEADER_BG)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.rect(MARGIN, y, CONTENT_W, alto, style='FD')
    for i, ((etiqueta, _), lineas) in enumerate(zip(celdas, envueltas)):
        x = MARGIN + i * ancho
        if i:
            pdf.line(x, y, x, y + alto)
        _font(pdf, 7, bold=True, color=MUTED)
        pdf.set_xy(x + 2, y + 2)
        pdf.cell(ancho - 4, 3.5, etiqueta.upper())
        for n, linea in enumerate(lineas):
            _font(pdf, 8, bold=True)
            pdf.set_xy(x + 2, y + 7 + n * 3.8)
            pdf.cell(ancho - 4, 3.8, linea)
    pdf.set_y(y + alto + 6)


def _draw_tabla_header(pdf: _OrdenPdf) -> None:
    _salta(pdf, 8)
    y = pdf.get_y()
    pdf.set_fill_color(*HEADER_BG)
    pdf.set_draw_color(*LINE)
    pdf.rect(MARGIN, y, CONTENT_W, 7, style='FD')
    x = MARGIN
    _font(pdf, 7.5, bold=True, color=MUTED)
    for ancho, titulo in zip(COLS, HEADERS):
        align = 'C' if titulo in ('#', 'Cant.') else 'L'
        pdf.set_xy(x + 1, y + 1.6)
        pdf.cell(ancho - 2, 4, titulo, align=align)
        x += ancho
    pdf.set_y(y + 7)


def _spec(rep: dict) -> str:
    return ' · '.join(
        parte for parte in (
            _txt(rep.get('especificacion')),
            _txt(rep.get('marca_repuesto')),
            _txt(rep.get('calidad')),
            _txt(rep.get('codigo_parte')),
        ) if parte
    )


def _alto_fila(pdf: _OrdenPdf, rep: dict, ficha: dict, numero: int) -> tuple[float, list, list, list]:
    nombre = _envuelve(pdf, COLS[1] - 3, _txt(rep.get('nombre')), 9, bold=True)
    spec = _envuelve(pdf, COLS[2] - 3, _spec(rep) or '—', 8)
    refs = _lineas_referencia(rep, ficha)
    n = max(len(nombre), len(spec), len(refs), 1)
    return 3 + n * 4.2, nombre, spec, refs


def _draw_fila(pdf: _OrdenPdf, rep: dict, ficha: dict, numero: int) -> None:
    alto, nombre, spec, refs = _alto_fila(pdf, rep, ficha, numero)
    if pdf.get_y() + alto > CONTENT_BOTTOM:
        pdf.add_page()
        pdf.set_y(MARGIN)
        _draw_tabla_header(pdf)
    y = pdf.get_y()
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.15)
    pdf.rect(MARGIN, y, CONTENT_W, alto)
    x = MARGIN
    for ancho in COLS[:-1]:
        x += ancho
        pdf.line(x, y, x, y + alto)
    _font(pdf, 8, color=MUTED)
    pdf.set_xy(MARGIN, y + 1.6)
    pdf.cell(COLS[0], 4, str(numero), align='C')
    for i, linea in enumerate(nombre):
        _font(pdf, 9, bold=True)
        pdf.set_xy(MARGIN + COLS[0] + 1.5, y + 1.4 + i * 4.2)
        pdf.cell(COLS[1] - 3, 4.2, linea)
    for i, linea in enumerate(spec):
        _font(pdf, 8, color=MUTED)
        pdf.set_xy(MARGIN + COLS[0] + COLS[1] + 1.5, y + 1.4 + i * 4.2)
        pdf.cell(COLS[2] - 3, 4.2, linea)
    try:
        cantidad = int(rep.get('cantidad') or 1)
    except (TypeError, ValueError):
        cantidad = 1
    _font(pdf, 9)
    pdf.set_xy(MARGIN + sum(COLS[:3]), y + 1.6)
    pdf.cell(COLS[3], 4, str(cantidad), align='C')
    ref_x = MARGIN + sum(COLS[:4]) + 1.5
    for i, (texto, url) in enumerate(refs):
        es_link = bool(url) and texto == 'Ver ficha'
        _font(pdf, 8, bold=es_link, color=LINK if es_link else INK)
        pdf.set_xy(ref_x, y + 1.4 + i * 4.2)
        pdf.cell(COLS[4] - 3, 4.2, texto, link=url if es_link else '')
    pdf.set_y(y + alto)


def _draw_casa(pdf: _OrdenPdf, item: dict, cotizacion, marca: str) -> None:
    casa = item['casa']
    lineas = item['lineas']
    meta = ' · '.join(parte for parte in (item.get('sucursal'), item.get('telefono'), item.get('horario')) if parte)
    badge = ''
    if _es_especialista(casa, marca):
        from mecanimovilapp.apps.ordenes.casas_especialistas import marca_visible

        badge = f'Especialista {marca_visible(marca)}'
    _salta(pdf, 22)
    y = pdf.get_y()
    _font(pdf, 12, bold=True)
    pdf.set_xy(MARGIN, y)
    pdf.cell(pdf.get_string_width(casa) + 1, 6, casa)
    if badge:
        ancho = pdf.get_string_width(badge) + 4
        x = pdf.get_x() + 2
        pdf.set_fill_color(*SOFT)
        pdf.rect(x, y + 0.6, ancho, 5, style='F')
        _font(pdf, 7.5, bold=True, color=MAGENTA)
        pdf.set_xy(x, y + 1.1)
        pdf.cell(ancho, 4, badge, align='C')
    pdf.set_y(y + 7)
    if meta:
        _font(pdf, 8, color=MUTED)
        pdf.set_x(MARGIN)
        pdf.multi_cell(CONTENT_W, 4, meta)
        pdf.ln(1)
    _draw_tabla_header(pdf)
    for i, rep in enumerate(lineas, start=1):
        ficha = _referencia(rep, cotizacion)
        _draw_fila(pdf, rep, ficha, i)
    pdf.ln(5)


def _emitir(cotizacion) -> list[dict]:
    from mecanimovilapp.apps.ordenes.casas_especialistas import perfil_de

    marca = _txt(getattr(cotizacion, 'vehiculo_marca', ''))
    grupos = _grupos(list(getattr(cotizacion, 'repuestos', None) or []), marca)
    emitidos: list[dict] = []
    for casa, lineas in grupos:
        muestra = next((r for r in lineas if _txt(r.get('casa_sucursal') or r.get('casa_telefono'))), lineas[0])
        sucursal, telefono = _sucursal_para_pdf(cotizacion, casa, muestra)
        horario = _horario(casa, lineas)
        previo = next(
            (item for item in emitidos if sucursal and item['sucursal'].casefold() == sucursal.casefold()),
            None,
        )
        if previo is not None:
            if perfil_de(casa) and not perfil_de(previo['casa']):
                previo['casa'] = casa
                previo['telefono'] = telefono or previo['telefono']
            if horario and not previo.get('horario'):
                previo['horario'] = horario
            previo['lineas'].extend(lineas)
            continue
        emitidos.append({
            'casa': casa,
            'lineas': list(lineas),
            'sucursal': sucursal,
            'telefono': telefono,
            'horario': horario,
        })
    return emitidos


def generar_pdf_orden_compra(cotizacion) -> bytes:
    cuando = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
    pdf = _OrdenPdf()
    pdf.add_page()
    pdf.set_y(MARGIN)
    identidad = _identidad(cotizacion)
    _draw_identidad(pdf, identidad, cuando)
    _draw_vehiculo(pdf, cotizacion)
    marca = _txt(getattr(cotizacion, 'vehiculo_marca', ''))
    emitidos = _emitir(cotizacion)
    if not emitidos:
        _font(pdf, 10, color=MUTED)
        pdf.set_x(MARGIN)
        pdf.multi_cell(CONTENT_W, 5, 'Esta cotización no tiene repuestos.')
    for item in emitidos:
        _draw_casa(pdf, item, cotizacion, marca)
    return bytes(pdf.output())

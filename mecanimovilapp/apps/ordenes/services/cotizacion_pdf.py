"""PDF on-demand de cotización pública (fpdf2).

Replica la jerarquía visual de CotizacionPublicaScreen: canvas, cards,
folio, badges, líneas con wrap y totales. Sin Chromium.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import requests
from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

logger = logging.getLogger(__name__)

_FONT_DIR = Path(__file__).resolve().parent.parent / 'fonts'
_FONT_REG = _FONT_DIR / 'DejaVuSans.ttf'
_FONT_BOLD = _FONT_DIR / 'DejaVuSans-Bold.ttf'

# Tokens Mecanimovil (usuarios / Tinder palette).
INK = (59, 59, 59)
MUTED = (117, 117, 117)
HINT = (184, 184, 184)
CANVAS = (249, 249, 249)
PAPER = (255, 255, 255)
TONAL = (243, 243, 243)
BORDER = (232, 232, 232)
MAGENTA = (253, 43, 123)
SOFT = (255, 240, 245)
SELECTION_TEXT = (194, 24, 91)
PILL_OK_BG = (255, 238, 244)
WARNING_BG = (255, 248, 230)
WHITE = (255, 255, 255)

ACCENT_POOL = (
    MAGENTA,
    (255, 113, 88),
    (99, 102, 241),
    (14, 165, 233),
)

ESTADO_META = {
    'enviada': ('Pendiente de respuesta', False),
    'aceptada': ('Aceptada', True),
    'rechazada': ('Rechazada', False),
    'expirada': ('Expirada', False),
    'cancelada': ('Cancelada', False),
}

MESES = (
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
)

MARGIN = 18.0
PAGE_W = 210.0
PAGE_H = 297.0
FOOTER_H = 12.0
CONTENT_BOTTOM = PAGE_H - FOOTER_H
GAP = 3.2
PAD = 5.0
RADIUS = 2.6
AVATAR = 14.0


def _txt(value: Any) -> str:
    if value is None:
        return ''
    return str(value).replace('\r\n', '\n').replace('\r', '\n')


def _clp(value: Any) -> str:
    n = int(round(float(value or 0)))
    formatted = f'{n:,}'.replace(',', '.')
    return f'${formatted}'


def _fecha_larga(iso: str | None) -> str:
    if not iso:
        return ''
    try:
        from datetime import datetime

        raw = str(iso).replace('Z', '+00:00')
        dt = datetime.fromisoformat(raw)
        return f'{dt.day} de {MESES[dt.month - 1]} de {dt.year}'
    except (TypeError, ValueError, IndexError):
        return str(iso)[:10]


def _fecha_corta(iso: str | None) -> str:
    if not iso:
        return ''
    try:
        from datetime import datetime

        raw = str(iso).replace('Z', '+00:00')
        dt = datetime.fromisoformat(raw)
        meses = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')
        return f'{dt.day} {meses[dt.month - 1]} {dt.year}'
    except (TypeError, ValueError, IndexError):
        return str(iso)[:10]


def _duracion(minutos: int | None) -> str:
    if not minutos:
        return ''
    m = int(minutos)
    if m >= 60:
        horas = round(m / 60 * 2) / 2
        if horas == int(horas):
            return f'{int(horas)} h est.'
        return f'{horas} h est.'
    return f'{m} min est.'


def _accent(nombre: str) -> tuple[int, int, int]:
    h = 0
    for ch in nombre or 'Taller':
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return ACCENT_POOL[h % len(ACCENT_POOL)]


def _initials(nombre: str) -> str:
    parts = [p for p in str(nombre or 'T').strip().split() if p]
    if len(parts) >= 2:
        return f'{parts[0][0]}{parts[1][0]}'.upper()
    return (parts[0][:2] if parts else 'T').upper()


def _lineas(data: dict) -> list[dict]:
    rows: list[dict] = []
    mo = int(data.get('mano_obra_clp') or 0)
    if mo > 0 or (data.get('servicio_nombre') or '').strip():
        rows.append({
            'nombre': 'Mano de obra',
            'tipo': 'Mano de obra',
            'qty': 1,
            'unit_label': '',
            'unitario': mo,
            'subtotal': mo,
            'meta': '',
        })
    for rep in data.get('repuestos') or []:
        if not isinstance(rep, dict):
            continue
        qty = int(rep.get('cantidad') or 1) or 1
        unit = int(rep.get('precio_unitario_clp') or 0)
        marca = (rep.get('marca_repuesto') or '').strip()
        comentario = (rep.get('comentario') or '').strip()
        meta = ' · '.join(p for p in (marca, comentario) if p)
        rows.append({
            'nombre': (rep.get('nombre') or 'Repuesto').strip(),
            'tipo': 'Repuesto',
            'qty': qty,
            'unit_label': 'und',
            'unitario': unit,
            'subtotal': unit * qty,
            'meta': meta,
        })
    return rows


def _logo_stream(url: str | None) -> io.BytesIO | None:
    if not url:
        return None
    try:
        res = requests.get(url, timeout=4)
        if res.status_code != 200 or not res.content:
            return None
        raw = res.content
    except Exception:
        logger.debug('No se pudo descargar logo del taller para PDF', exc_info=True)
        return None
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert('RGB')
        w, h = img.size
        side = min(w, h)
        img = img.crop((
            (w - side) // 2,
            (h - side) // 2,
            (w - side) // 2 + side,
            (h - side) // 2 + side,
        ))
        img = img.resize((320, 320), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=90)
        buf.seek(0)
        return buf
    except Exception:
        logger.debug('No se pudo normalizar logo del taller para PDF', exc_info=True)
        return io.BytesIO(raw)


class DocumentoPDF(FPDF):
    def __init__(self, folio: str):
        super().__init__(format='A4', unit='mm')
        self.folio = folio
        self.set_auto_page_break(auto=False)
        self.set_page_background(CANVAS)
        self.add_font('DejaVu', '', str(_FONT_REG))
        self.add_font('DejaVu', 'B', str(_FONT_BOLD))

    def header(self):
        if self.page_no() == 1:
            self.set_fill_color(*SOFT)
            self.rect(0, 0, PAGE_W, 46, 'F')

    def footer(self):
        self.set_y(-12)
        self.set_font('DejaVu', '', 8)
        self.set_text_color(*MUTED)
        self.set_char_spacing(0.35)
        label = f'EMITIDA EN MECANIMOVIL  ·  #{self.folio}'
        self.cell(0, 5, label, align='C')
        self.set_char_spacing(0)


def _font(pdf: DocumentoPDF, size: float, *, bold: bool = False, color=INK):
    pdf.set_font('DejaVu', 'B' if bold else '', size)
    pdf.set_text_color(*color)


def _content_w() -> float:
    return PAGE_W - 2 * MARGIN


def _ensure(pdf: DocumentoPDF, height: float):
    if pdf.get_y() + height > CONTENT_BOTTOM:
        pdf.add_page()
        pdf.set_y(MARGIN)


def _measure(pdf: DocumentoPDF, width: float, text: str, line_h: float, size: float, *, bold=False) -> float:
    text = _txt(text).strip()
    if not text:
        return 0.0
    _font(pdf, size, bold=bold)
    lines = pdf.multi_cell(
        width,
        line_h,
        text,
        dry_run=True,
        output=MethodReturnValue.LINES,
        align='L',
    )
    return max(line_h, len(lines) * line_h)


def _text(
    pdf: DocumentoPDF,
    x: float,
    y: float,
    width: float,
    text: str,
    line_h: float,
    size: float,
    *,
    bold=False,
    color=INK,
    align='L',
) -> float:
    text = _txt(text)
    if not text:
        return y
    pdf.set_xy(x, y)
    _font(pdf, size, bold=bold, color=color)
    pdf.multi_cell(
        width,
        line_h,
        text,
        align=align,
        new_x=XPos.LEFT,
        new_y=YPos.NEXT,
    )
    return pdf.get_y()


def _eyebrow(pdf: DocumentoPDF, x: float, y: float, width: float, text: str, *, align='L') -> float:
    pdf.set_xy(x, y)
    _font(pdf, 7, bold=True, color=MUTED)
    pdf.set_char_spacing(0.45)
    pdf.cell(width, 3.6, _txt(text).upper(), align=align, new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_char_spacing(0)
    return pdf.get_y()


def _card(pdf: DocumentoPDF, x: float, y: float, w: float, h: float, fill=PAPER):
    pdf.set_fill_color(*fill)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, w, h, style='DF', round_corners=True, corner_radius=RADIUS)


def _badge(pdf: DocumentoPDF, x: float, y: float, label: str, bg, fg) -> float:
    label = _txt(label)
    _font(pdf, 7, bold=True, color=fg)
    width = pdf.get_string_width(label) + 4.2
    height = 4.4
    pdf.set_fill_color(*bg)
    pdf.rect(x, y, width, height, style='F', round_corners=True, corner_radius=1.1)
    pdf.set_xy(x, y + 0.55)
    pdf.cell(width, 3.3, label, align='C')
    return width


def _rule(pdf: DocumentoPDF, x: float, y: float, w: float):
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.18)
    pdf.line(x, y, x + w, y)


def _avatar(pdf: DocumentoPDF, x: float, y: float, taller: dict, logo: io.BytesIO | None):
    nombre = (taller.get('nombre') or 'Taller').strip()
    accent = _accent(nombre)
    if logo:
        try:
            with pdf.elliptic_clip(x, y, AVATAR, AVATAR):
                pdf.image(logo, x=x, y=y, w=AVATAR, h=AVATAR)
        except Exception:
            logo = None
    if not logo:
        soft = tuple(int(c * 0.12 + 255 * 0.88) for c in accent)
        pdf.set_fill_color(*soft)
        pdf.ellipse(x, y, AVATAR, AVATAR, style='F')
        _font(pdf, 7.5, bold=True, color=accent)
        pdf.set_xy(x, y + 4.3)
        pdf.cell(AVATAR, 5, _initials(nombre), align='C')
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.55)
    pdf.ellipse(x, y, AVATAR, AVATAR, style='D')
    if taller.get('verificado'):
        d = 4.2
        vx = x + AVATAR - d + 0.4
        vy = y + AVATAR - d + 0.4
        pdf.set_fill_color(*MAGENTA)
        pdf.ellipse(vx, vy, d, d, style='F')
        _font(pdf, 6, bold=True, color=WHITE)
        pdf.set_xy(vx, vy + 0.25)
        pdf.cell(d, 3.6, '✓', align='C')


def _draw_header(pdf: DocumentoPDF, data: dict, taller: dict, logo: io.BytesIO | None) -> None:
    cw = _content_w()
    x0 = MARGIN
    inner_w = cw - 2 * PAD
    meta_w = 58.0
    left_w = inner_w - meta_w - 5
    copy_x = x0 + PAD + AVATAR + 3.5
    copy_w = left_w - AVATAR - 3.5
    nombre = (taller.get('nombre') or 'Taller').strip()
    folio = data.get('numero_publico') or ''
    estado = data.get('estado') or ''
    estado_label, estado_ok = ESTADO_META.get(estado, (estado, False))
    emitida = _fecha_corta(data.get('enviada_en'))
    vigente = _fecha_corta(data.get('fecha_expiracion_publica'))
    contactos = []
    direccion = _txt(taller.get('direccion')).strip()
    telefono = _txt(taller.get('telefono')).strip()
    email = _txt(taller.get('email')).strip()
    if direccion:
        contactos.append(direccion)
    linea_contacto = '  ·  '.join(p for p in (telefono, email) if p)
    if linea_contacto:
        contactos.append(linea_contacto)

    name_h = _measure(pdf, copy_w, nombre, 5.6, 13, bold=True)
    left_h = 4.0 + name_h
    rating = float(taller.get('calificacion_promedio') or 0)
    if rating > 0:
        left_h += 4.4
    meta_h = 0.0
    if folio:
        meta_h += 6.8
    if estado_label:
        meta_h += 5.8
    if emitida:
        meta_h += 4.6
    if vigente:
        meta_h += 4.6
    top_h = max(AVATAR, left_h, meta_h)
    contact_h = 0.0
    if contactos:
        contact_h = 2.6
        for line in contactos:
            contact_h += _measure(pdf, inner_w, line, 4.2, 8)
    height = PAD + top_h + contact_h + PAD
    _ensure(pdf, height + 1)
    y0 = pdf.get_y()
    _card(pdf, x0, y0, cw, height)

    _avatar(pdf, x0 + PAD, y0 + PAD, taller, logo)
    y = _eyebrow(pdf, copy_x, y0 + PAD, copy_w, 'Cotización de')
    _text(pdf, copy_x, y, copy_w, nombre, 5.6, 13, bold=True)
    if rating > 0:
        _text(pdf, copy_x, pdf.get_y() + 0.2, copy_w, f'★  {rating:.1f}', 4.2, 8, color=INK)

    meta_x = x0 + PAD + inner_w - meta_w
    my = y0 + PAD
    if folio:
        _font(pdf, 8.5, bold=True)
        bw = min(meta_w, pdf.get_string_width(f'#{folio}') + 5.5)
        pdf.set_fill_color(*TONAL)
        pdf.rect(meta_x + meta_w - bw, my, bw, 6.0, style='F', round_corners=True, corner_radius=1.2)
        pdf.set_xy(meta_x + meta_w - bw, my + 0.9)
        pdf.cell(bw, 4.1, f'#{folio}', align='C')
        my += 6.8
    if estado_label:
        bg, fg = (PILL_OK_BG, MAGENTA) if estado_ok else (TONAL, MUTED)
        _font(pdf, 7, bold=True, color=fg)
        bw = min(meta_w, pdf.get_string_width(estado_label) + 5)
        pdf.set_fill_color(*bg)
        pdf.rect(meta_x + meta_w - bw, my, bw, 5.0, style='F', round_corners=True, corner_radius=1.1)
        pdf.set_xy(meta_x + meta_w - bw, my + 0.6)
        pdf.cell(bw, 3.7, estado_label, align='C')
        my += 5.8
    if emitida:
        my = _text(pdf, meta_x, my, meta_w, f'Emitida: {emitida}', 4.2, 8, color=MUTED, align='R')
    if vigente:
        _text(pdf, meta_x, my, meta_w, f'Válida: {vigente}', 4.2, 8, color=MUTED, align='R')

    if contactos:
        cy = y0 + PAD + top_h + 0.8
        _rule(pdf, x0 + PAD, cy, inner_w)
        cy += 1.6
        for line in contactos:
            cy = _text(pdf, x0 + PAD, cy, inner_w, line, 4.2, 8, color=MUTED)

    pdf.set_y(y0 + height + GAP)


def _draw_facts(pdf: DocumentoPDF, data: dict, cliente: dict) -> None:
    cw = _content_w()
    x0 = MARGIN
    inner_w = cw - 2 * PAD
    col_w = (inner_w - 6) / 2
    veh = ' '.join(
        str(p) for p in (
            data.get('vehiculo_marca'),
            data.get('vehiculo_modelo'),
            data.get('vehiculo_anio'),
        ) if p
    )
    if data.get('vehiculo_patente'):
        veh = f"{veh} · {data['vehiculo_patente']}".strip(' ·')
    modalidad = 'A domicilio' if data.get('modalidad') == 'domicilio' else 'En taller'
    extras = ' · '.join(
        p for p in (
            modalidad,
            _duracion(data.get('duracion_minutos_estimada')),
            data.get('tipo_motor_label'),
            data.get('vehiculo_cilindraje'),
        ) if p
    )
    cli_name = (cliente.get('nombre') or data.get('cliente_nombre') or '').strip()
    cli_tel = (cliente.get('telefono') or '').strip()
    cli_dir = (cliente.get('direccion') or '').strip()
    if data.get('modalidad') == 'domicilio' and data.get('direccion_servicio'):
        cli_dir = cli_dir or str(data.get('direccion_servicio'))

    left_body = _measure(pdf, col_w, cli_name, 5.2, 11.5, bold=True)
    left_body += _measure(pdf, col_w, cli_tel, 4.2, 8) if cli_tel else 0
    left_body += _measure(pdf, col_w, cli_dir, 4.2, 8) if cli_dir else 0
    right_body = _measure(pdf, col_w, veh or 'Tu vehículo', 5.2, 11.5, bold=True)
    right_body += _measure(pdf, col_w, extras, 4.2, 8)
    if data.get('modalidad') == 'domicilio' and data.get('direccion_servicio'):
        right_body += _measure(pdf, col_w, data.get('direccion_servicio'), 4.6, 8.5)
    height = PAD + 3.6 + max(left_body, right_body) + PAD
    _ensure(pdf, height + 1)
    y0 = pdf.get_y()
    _card(pdf, x0, y0, cw, height, fill=TONAL)

    lx = x0 + PAD
    rx = lx + col_w + 6
    if cli_name:
        y = _eyebrow(pdf, lx, y0 + PAD, col_w, 'Cliente')
        y = _text(pdf, lx, y, col_w, cli_name, 5.2, 11.5, bold=True)
        if cli_tel:
            y = _text(pdf, lx, y, col_w, cli_tel, 4.2, 8, color=INK)
        if cli_dir:
            _text(pdf, lx, y, col_w, cli_dir, 4.2, 8, color=MUTED)
    y = _eyebrow(pdf, rx, y0 + PAD, col_w, 'Vehículo')
    y = _text(pdf, rx, y, col_w, veh or 'Tu vehículo', 5.2, 11.5, bold=True)
    y = _text(pdf, rx, y, col_w, extras, 4.2, 8, color=MUTED)
    if data.get('modalidad') == 'domicilio' and data.get('direccion_servicio'):
        _text(pdf, rx, y, col_w, data['direccion_servicio'], 4.2, 8, color=MUTED)
    pdf.set_y(y0 + height + GAP)


def _draw_paper(pdf: DocumentoPDF, eyebrow: str, title: str | None, body: str) -> None:
    body = _txt(body).strip()
    if not body:
        return
    cw = _content_w()
    x0 = MARGIN
    inner_w = cw - 2 * PAD
    title_h = _measure(pdf, inner_w, title or '', 5.2, 11, bold=True) if title else 0
    body_h = _measure(pdf, inner_w, body, 4.6, 9)
    height = PAD + 3.6 + title_h + (2.0 if title else 0) + body_h + PAD
    _ensure(pdf, min(height, 80) + 1)
    y0 = pdf.get_y()
    if pdf.get_y() + height > CONTENT_BOTTOM:
        _card(pdf, x0, y0, cw, CONTENT_BOTTOM - y0)
        y = _eyebrow(pdf, x0 + PAD, y0 + PAD, inner_w, eyebrow)
        if title:
            y = _text(pdf, x0 + PAD, y, inner_w, title, 5.2, 11, bold=True)
            y += 1.0
            _rule(pdf, x0 + PAD, y, inner_w)
            y += 1.8
        _text(pdf, x0 + PAD, y, inner_w, body, 4.6, 9)
        pdf.add_page()
        pdf.set_y(MARGIN)
        return
    _card(pdf, x0, y0, cw, height)
    y = _eyebrow(pdf, x0 + PAD, y0 + PAD, inner_w, eyebrow)
    if title:
        y = _text(pdf, x0 + PAD, y, inner_w, title, 5.2, 11, bold=True)
        y += 0.8
        _rule(pdf, x0 + PAD, y, inner_w)
        y += 1.6
    _text(pdf, x0 + PAD, y, inner_w, body, 4.6, 9)
    pdf.set_y(y0 + height + GAP)


def _draw_hero(pdf: DocumentoPDF, data: dict) -> None:
    if not data.get('es_trabajo_adicional'):
        return
    princ = (data.get('servicio_principal') or {}).get('nombre') or 'Servicio en curso'
    motivo = _txt(data.get('motivo_servicio_adicional') or '').strip()
    body = (
        f'Este trabajo se propone durante tu servicio en curso'
        f'{": " + princ if princ else "."}'
    )
    if motivo:
        body = f'{body}\n\n{motivo}'
    _draw_paper(pdf, 'Durante tu servicio', princ, body)


def _row_height(pdf: DocumentoPDF, row: dict, desc_w: float) -> float:
    name_h = _measure(pdf, desc_w, row['nombre'], 4.6, 9.5, bold=True)
    meta_h = _measure(pdf, desc_w, row['meta'], 3.8, 7.5) if row['meta'] else 0
    qty_h = 4.0
    return max(11.0, name_h + meta_h + qty_h + 2.2)


def _draw_lineas(pdf: DocumentoPDF, rows: list[dict], data: dict | None = None) -> None:
    if not rows:
        return
    cw = _content_w()
    x0 = MARGIN
    inner_w = cw - 2 * PAD
    amt_w = 26.0
    desc_w = inner_w - (amt_w * 2) - 6
    titulo = ((data or {}).get('servicio_nombre') or '').strip() or 'Detalle'
    subtitulo = ((data or {}).get('descripcion_problema') or '').strip()
    notas = ((data or {}).get('notas_cotizacion') or '').strip()
    if subtitulo and subtitulo in notas:
        subtitulo = ''
    titulo_h = _measure(pdf, inner_w, titulo, 5.0, 11, bold=True)
    sub_h = _measure(pdf, inner_w, subtitulo, 4.2, 8) if subtitulo else 0
    header_h = PAD + 3.6 + titulo_h + sub_h + 1.6 + 3.8
    row_heights = [_row_height(pdf, row, desc_w) for row in rows]
    total_h = header_h + sum(row_heights) + PAD
    _ensure(pdf, min(total_h, 32))
    y0 = pdf.get_y()
    fits = y0 + total_h <= CONTENT_BOTTOM
    if fits:
        _card(pdf, x0, y0, cw, total_h)
    else:
        _card(pdf, x0, y0, cw, CONTENT_BOTTOM - y0)

    y = _eyebrow(pdf, x0 + PAD, y0 + PAD, inner_w, 'Detalle')
    y = _text(pdf, x0 + PAD, y, inner_w, titulo, 5.0, 11, bold=True)
    if subtitulo:
        y = _text(pdf, x0 + PAD, y, inner_w, subtitulo, 4.2, 8, color=MUTED)
    y += 0.6
    _rule(pdf, x0 + PAD, y, inner_w)
    y += 1.2
    _font(pdf, 6.5, bold=True, color=MUTED)
    pdf.set_char_spacing(0.4)
    pdf.set_xy(x0 + PAD, y)
    pdf.cell(desc_w, 3.6, 'DESCRIPCIÓN')
    pdf.set_xy(x0 + PAD + desc_w, y)
    pdf.cell(amt_w, 3.6, 'UNITARIO', align='R')
    pdf.set_xy(x0 + PAD + desc_w + amt_w, y)
    pdf.cell(amt_w + 6, 3.6, 'SUBTOTAL', align='R')
    pdf.set_char_spacing(0)
    y += 4.4

    for idx, row in enumerate(rows):
        rh = row_heights[idx]
        if y + rh > CONTENT_BOTTOM - 2:
            pdf.add_page()
            y0 = MARGIN
            remain = sum(row_heights[idx:]) + PAD + 8
            _card(pdf, x0, y0, cw, min(remain, CONTENT_BOTTOM - y0))
            y = y0 + PAD
        if idx:
            _rule(pdf, x0 + PAD, y, inner_w)
            y += 1.2
        name_h = _measure(pdf, desc_w, row['nombre'], 4.6, 9.5, bold=True)
        _text(pdf, x0 + PAD, y, desc_w, row['nombre'], 4.6, 9.5, bold=True)
        is_mo = row['tipo'] != 'Repuesto'
        badge_bg, badge_fg = (SOFT, SELECTION_TEXT) if is_mo else (TONAL, MUTED)
        cy = y + name_h + 0.2
        badge_w = _badge(pdf, x0 + PAD, cy, row['tipo'], badge_bg, badge_fg)
        qty = f"{row['qty']} {row['unit_label']}".strip()
        _text(
            pdf,
            x0 + PAD + badge_w + 2,
            cy + 0.2,
            desc_w - badge_w - 2,
            f"{qty} × {_clp(row['unitario'])}",
            3.8,
            7.5,
            color=MUTED,
        )
        cy += 4.4
        if row['meta']:
            _text(pdf, x0 + PAD, cy, desc_w, row['meta'], 3.8, 7.5, color=MUTED)
        mid_y = y + 0.4
        _text(
            pdf, x0 + PAD + desc_w, mid_y, amt_w,
            _clp(row['unitario']), 4.6, 8.5, color=MUTED, align='R',
        )
        _text(
            pdf, x0 + PAD + desc_w + amt_w, mid_y, amt_w + 6,
            _clp(row['subtotal']), 4.6, 10, bold=True, align='R',
        )
        y += rh

    pdf.set_y(y + GAP)


def _draw_bottom(pdf: DocumentoPDF, data: dict) -> None:
    cw = _content_w()
    x0 = MARGIN
    total = int(data.get('total_clp') or 0)
    neto = int(round(total / 1.19)) if total else 0
    iva = total - neto
    vigente = _fecha_larga(data.get('fecha_expiracion_publica'))
    politicas = (data.get('politicas_cotizacion') or '').strip()
    if not politicas:
        from mecanimovilapp.apps.usuarios.legal_constants import POLITICAS_COTIZACION_FALLBACK
        politicas = POLITICAS_COTIZACION_FALLBACK
    note_parts = []
    if vigente:
        note_parts.append(f'Esta cotización es válida hasta el {vigente}.')
    if politicas:
        note_parts.append(politicas)
    note_parts.append(
        'Los precios de línea ya incluyen IVA. El desglose neto/IVA es informativo.'
    )
    if data.get('es_trabajo_adicional') or data.get('pago_directo_taller'):
        note_parts.append(
            'El pago de mano de obra y repuestos se coordina directo con el taller. '
            'Mecanimovil no cobra este trabajo.'
        )
    note = '\n\n'.join(note_parts)

    totals_w = 70.0
    gap = 4.0
    note_w = cw - totals_w - gap
    lines = []
    if int(data.get('costo_repuestos_clp') or 0) > 0:
        lines.append(('Repuestos', _clp(data.get('costo_repuestos_clp')), False))
    lines.append(('Mano de obra', _clp(data.get('mano_obra_clp')), False))
    desc = int(data.get('descuento_clp') or 0)
    if desc <= 0:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            descuento_visible_clp,
        )
        desc = descuento_visible_clp(
            costo_repuestos_clp=int(data.get('costo_repuestos_clp') or 0),
            mano_obra_clp=int(data.get('mano_obra_clp') or 0),
            total_clp=total,
            descuento_clp=desc,
        )
    if desc > 0:
        etiqueta = (data.get('descuento_etiqueta') or 'Descuento').strip() or 'Descuento'
        lines.append((etiqueta, f'-{_clp(desc)}', False))
    lines.append(('Neto', _clp(neto), False))
    lines.append(('IVA 19%', _clp(iva), False))
    totals_h = PAD + len(lines) * 4.8 + 1.6 + 7.2 + PAD
    note_h = 0.0
    if note:
        note_h = PAD + 3.6 + _measure(pdf, note_w - 2 * PAD, note, 4.4, 8.5) + PAD
    height = max(totals_h, note_h or 0)
    _ensure(pdf, height + 1)
    y0 = pdf.get_y()

    if note:
        _card(pdf, x0, y0, note_w, max(note_h, height), fill=WARNING_BG)
        y = _eyebrow(pdf, x0 + PAD, y0 + PAD, note_w - 2 * PAD, 'Validez')
        _text(pdf, x0 + PAD, y, note_w - 2 * PAD, note, 4.4, 8.5)

    tx = x0 + (note_w + gap if note else 0)
    tw = totals_w if note else cw
    _card(pdf, tx, y0, tw, height)
    y = y0 + PAD
    label_w = tw - 2 * PAD - 28
    for label, value, _strong in lines:
        _text(pdf, tx + PAD, y, label_w, label, 4.4, 8, color=MUTED)
        _text(pdf, tx + PAD + label_w, y, 28, value, 4.4, 8, color=MUTED, align='R')
        y += 4.8
    y += 0.4
    _rule(pdf, tx + PAD, y, tw - 2 * PAD)
    y += 1.6
    _text(pdf, tx + PAD, y, label_w, 'Total a pagar', 5.6, 10.5, bold=True)
    _text(pdf, tx + PAD + label_w, y, 28, _clp(total), 5.6, 12, bold=True, color=MAGENTA, align='R')
    pdf.set_y(y0 + height + GAP)


def _draw_signed(pdf: DocumentoPDF, data: dict) -> None:
    if data.get('estado') != 'aceptada':
        return
    msg = 'El taller coordinará el horario contigo.'
    if data.get('es_trabajo_adicional'):
        msg = 'El taller puede continuar este trabajo adicional.'
    cw = _content_w()
    h = 10
    if pdf.get_y() + h > CONTENT_BOTTOM:
        return
    y = pdf.get_y()
    _rule(pdf, MARGIN, y, cw)
    y = _text(pdf, MARGIN, y + 1.2, cw, 'Cotización aceptada', 4.6, 9.5, bold=True)
    _text(pdf, MARGIN, y, cw, msg, 4.0, 8, color=MUTED)


def generar_pdf_desde_payload(data: dict) -> bytes:
    folio = (data.get('numero_publico') or 'MM-000000').strip()
    taller = data.get('taller') or {}
    cliente = data.get('cliente') or {}
    pdf = DocumentoPDF(folio)
    pdf.add_page()
    pdf.set_y(MARGIN)

    logo = _logo_stream(taller.get('foto_perfil'))
    _draw_header(pdf, data, taller, logo)
    _draw_facts(pdf, data, cliente)
    if data.get('actualizada_por_taller'):
        _draw_paper(
            pdf,
            'Actualización',
            'El taller actualizó esta cotización',
            'Revisa el desglose. Si el total cambió y aún puedes responder, acepta o rechaza de nuevo.',
        )
    _draw_hero(pdf, data)
    _draw_lineas(pdf, _lineas(data), data)
    notas = (data.get('notas_cotizacion') or '').strip()
    if notas:
        _draw_paper(pdf, 'Notas de cotización', None, notas)
    _draw_bottom(pdf, data)
    _draw_signed(pdf, data)
    return bytes(pdf.output())


def generar_pdf_cotizacion_publica(cotizacion, request=None) -> bytes:
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
        asegurar_numero_publico,
        serializar_cotizacion_publica,
    )

    asegurar_numero_publico(cotizacion)
    data = serializar_cotizacion_publica(cotizacion, request)
    if not data.get('numero_publico'):
        data['numero_publico'] = formatear_fallback(cotizacion)
    return generar_pdf_desde_payload(data)


def formatear_fallback(cotizacion) -> str:
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import formatear_numero_publico

    return formatear_numero_publico(cotizacion.pk)

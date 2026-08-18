"""PDF on-demand de cotización pública (fpdf2, sin Chromium)."""
from __future__ import annotations

import io
import logging
from typing import Any

import requests

from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    asegurar_numero_publico,
    serializar_cotizacion_publica,
)

logger = logging.getLogger(__name__)

ESTADO_LABEL = {
    'enviada': 'Pendiente de respuesta',
    'aceptada': 'Aceptada',
    'rechazada': 'Rechazada',
    'expirada': 'Expirada',
    'cancelada': 'Cancelada',
}


def _txt(value: Any) -> str:
    if value is None:
        return ''
    raw = str(value)
    return raw.encode('cp1252', 'replace').decode('cp1252')


def _clp(value: Any) -> str:
    n = int(round(float(value or 0)))
    formatted = f'{n:,}'.replace(',', '.')
    return f'${formatted}'


def _fecha_corta(iso: str | None) -> str:
    if not iso:
        return ''
    try:
        from datetime import datetime

        raw = str(iso).replace('Z', '+00:00')
        dt = datetime.fromisoformat(raw)
        return dt.strftime('%d-%m-%Y')
    except (TypeError, ValueError):
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


def _lineas(data: dict) -> list[dict]:
    rows: list[dict] = []
    mo = int(data.get('mano_obra_clp') or 0)
    nombre = (data.get('servicio_nombre') or '').strip()
    if mo > 0 or nombre:
        rows.append({
            'nombre': nombre or 'Servicio',
            'tipo': 'Servicio',
            'qty': 1,
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
            'unitario': unit,
            'subtotal': unit * qty,
            'meta': meta,
        })
    return rows


def _logo_bytes(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        res = requests.get(url, timeout=4)
        if res.status_code == 200 and res.content:
            return res.content
    except Exception:
        logger.debug('No se pudo descargar logo del taller para PDF', exc_info=True)
    return None


def generar_pdf_cotizacion_publica(cotizacion: CotizacionCanal, request=None) -> bytes:
    from fpdf import FPDF

    asegurar_numero_publico(cotizacion)
    data = serializar_cotizacion_publica(cotizacion, request)
    folio = data.get('numero_publico') or formatear_fallback(cotizacion)
    taller = data.get('taller') or {}
    cliente = data.get('cliente') or {}

    pdf = FPDF(format='A4')
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.core_fonts_encoding = 'cp1252'

    logo = _logo_bytes(taller.get('foto_perfil'))
    if logo:
        try:
            pdf.image(io.BytesIO(logo), x=12, y=12, w=18, h=18)
        except Exception:
            logo = None

    left = 34 if logo else 12
    pdf.set_xy(left, 12)
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 8, _txt(taller.get('nombre') or 'Taller'), ln=1)
    pdf.set_x(left)
    pdf.set_font('Helvetica', '', 9)
    contacto = '  ·  '.join(
        p for p in (
            taller.get('direccion'),
            taller.get('telefono'),
            taller.get('email'),
        ) if p
    )
    if contacto:
        pdf.multi_cell(0, 5, _txt(contacto))

    pdf.set_xy(140, 12)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(58, 6, _txt(f'#{folio}'), ln=1, align='R')
    pdf.set_x(140)
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(58, 5, _txt(ESTADO_LABEL.get(data.get('estado'), data.get('estado') or '')), ln=1, align='R')
    emitida = _fecha_corta(data.get('enviada_en'))
    vigente = _fecha_corta(data.get('fecha_expiracion_publica'))
    if emitida:
        pdf.set_x(140)
        pdf.cell(58, 5, _txt(f'Emitida: {emitida}'), ln=1, align='R')
    if vigente:
        pdf.set_x(140)
        pdf.cell(58, 5, _txt(f'Valida hasta: {vigente}'), ln=1, align='R')

    pdf.ln(8)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y())
    pdf.ln(4)

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(90, 6, _txt('Cliente'), ln=0)
    pdf.cell(90, 6, _txt('Vehiculo'), ln=1)
    pdf.set_font('Helvetica', '', 9)
    y0 = pdf.get_y()
    cli_lines = [
        cliente.get('nombre') or data.get('cliente_nombre') or '',
        cliente.get('telefono') or '',
        cliente.get('direccion') or '',
    ]
    pdf.multi_cell(90, 5, _txt('\n'.join(p for p in cli_lines if p) or '—'))
    y1 = pdf.get_y()
    pdf.set_xy(102, y0)
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
    extras = [modalidad, _duracion(data.get('duracion_minutos_estimada'))]
    pdf.multi_cell(90, 5, _txt('\n'.join(p for p in [veh, *extras] if p)))
    pdf.set_y(max(y1, pdf.get_y()) + 3)

    if data.get('es_trabajo_adicional'):
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, _txt('Trabajo adicional'), ln=1)
        pdf.set_font('Helvetica', '', 9)
        princ = (data.get('servicio_principal') or {}).get('nombre')
        if princ:
            pdf.multi_cell(0, 5, _txt(f'Durante: {princ}'))
        if data.get('motivo_servicio_adicional'):
            pdf.multi_cell(0, 5, _txt(data['motivo_servicio_adicional']))
        pdf.ln(2)

    desc = (data.get('descripcion_problema') or '').strip()
    notas = (data.get('notas_cotizacion') or '').strip()
    if desc and desc not in notas:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, _txt('Sobre el servicio'), ln=1)
        pdf.set_font('Helvetica', '', 9)
        pdf.multi_cell(0, 5, _txt(desc))
        pdf.ln(2)

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, _txt('Detalle'), ln=1)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(243, 243, 243)
    pdf.cell(88, 6, _txt('Descripcion'), border=0, fill=True)
    pdf.cell(24, 6, _txt('Tipo'), border=0, fill=True)
    pdf.cell(16, 6, _txt('Cant.'), border=0, fill=True, align='R')
    pdf.cell(30, 6, _txt('Unitario'), border=0, fill=True, align='R')
    pdf.cell(28, 6, _txt('Subtotal'), border=0, fill=True, align='R', ln=1)
    pdf.set_font('Helvetica', '', 8)
    for row in _lineas(data):
        nombre = row['nombre']
        if row['meta']:
            nombre = f"{nombre} ({row['meta']})"
        pdf.cell(88, 6, _txt(nombre)[:52])
        pdf.cell(24, 6, _txt(row['tipo']))
        pdf.cell(16, 6, str(row['qty']), align='R')
        pdf.cell(30, 6, _clp(row['unitario']), align='R')
        pdf.cell(28, 6, _clp(row['subtotal']), align='R', ln=1)

    if notas:
        pdf.ln(3)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, _txt('Notas de cotizacion'), ln=1)
        pdf.set_font('Helvetica', '', 9)
        pdf.multi_cell(0, 5, _txt(notas))

    total = int(data.get('total_clp') or 0)
    neto = int(round(total / 1.19)) if total else 0
    iva = total - neto
    pdf.ln(4)
    pdf.set_font('Helvetica', '', 9)
    if int(data.get('costo_repuestos_clp') or 0) > 0:
        pdf.cell(158, 6, _txt('Repuestos'), align='R')
        pdf.cell(28, 6, _clp(data.get('costo_repuestos_clp')), align='R', ln=1)
    pdf.cell(158, 6, _txt('Mano de obra'), align='R')
    pdf.cell(28, 6, _clp(data.get('mano_obra_clp')), align='R', ln=1)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(158, 8, _txt('Total a pagar (IVA incl.)'), align='R')
    pdf.cell(28, 8, _clp(total), align='R', ln=1)
    pdf.set_font('Helvetica', '', 8)
    pdf.cell(158, 5, _txt('Neto (informativo)'), align='R')
    pdf.cell(28, 5, _clp(neto), align='R', ln=1)
    pdf.cell(158, 5, _txt('IVA 19% (informativo)'), align='R')
    pdf.cell(28, 5, _clp(iva), align='R', ln=1)

    if vigente:
        pdf.ln(3)
        pdf.set_font('Helvetica', '', 8)
        pdf.multi_cell(
            0,
            4,
            _txt(
                f'Esta cotizacion es valida hasta el {vigente}. '
                'Los precios de repuestos pueden variar si cambia disponibilidad o marca. '
                'Los precios de linea ya incluyen IVA.'
            ),
        )

    pdf.ln(6)
    pdf.set_font('Helvetica', '', 8)
    pdf.cell(0, 5, _txt(f'Emitida en Mecanimovil  ·  #{folio}'), ln=1)

    return bytes(pdf.output())


def formatear_fallback(cotizacion: CotizacionCanal) -> str:
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import formatear_numero_publico

    return formatear_numero_publico(cotizacion.pk)

"""PDF de orden de compra de repuestos para llevar a la casa.

Sin mano de obra y sin el precio que ve el cliente. Un monto solo se imprime
como referencia de otra tienda, nunca como si la casa lo hubiera cotizado
cuando la línea está a consultar.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from django.utils import timezone
from fpdf import FPDF
from fpdf.enums import XPos, YPos

_FONT_DIR = Path(__file__).resolve().parent.parent / 'fonts'
_FONT_REG = _FONT_DIR / 'DejaVuSans.ttf'
_FONT_BOLD = _FONT_DIR / 'DejaVuSans-Bold.ttf'


def _pesos(monto: int) -> str:
    return '$' + f'{int(monto):,}'.replace(',', '.')


def _txt(valor: Any) -> str:
    return ' '.join(str(valor or '').split())


class _OrdenPdf(FPDF):
    def __init__(self):
        super().__init__(format='A4')
        self.add_font('DejaVu', '', str(_FONT_REG))
        self.add_font('DejaVu', 'B', str(_FONT_BOLD))
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(14, 14, 14)

    def _parrafo(self, texto: str, *, bold: bool = False, size: int = 10) -> None:
        self.set_font('DejaVu', 'B' if bold else '', size)
        self.multi_cell(0, 5.5, texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _grupos(repuestos: list[dict]) -> list[tuple[str, list[dict]]]:
    orden: list[str] = []
    grupos: dict[str, list[dict]] = {}
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        nombre = _txt(rep.get('nombre'))
        if not nombre:
            continue
        casa = _txt(rep.get('casa_repuesto_nombre') or rep.get('proveedor_nombre')) or 'Casa por confirmar'
        if casa not in grupos:
            orden.append(casa)
            grupos[casa] = []
        grupos[casa].append(rep)
    return [(casa, grupos[casa]) for casa in orden]


def _precio_linea(rep: dict) -> str:
    if rep.get('precio_a_consultar'):
        ref_tienda = _txt(rep.get('referencia_tienda'))
        try:
            ref = int(rep.get('precio_referencia_clp') or 0)
        except (TypeError, ValueError):
            ref = 0
        if ref_tienda and ref > 0:
            return f'A consultar. Referencia en {ref_tienda}: {_pesos(ref)} (no es el precio de esta casa).'
        return 'A consultar'
    try:
        monto = int(rep.get('precio_unitario_clp') or 0)
    except (TypeError, ValueError):
        monto = 0
    if monto <= 0:
        return 'A consultar'
    return f'Referencia {_pesos(monto)}'


def generar_pdf_orden_compra(cotizacion) -> bytes:
    taller = getattr(cotizacion, 'taller', None)
    nombre_taller = _txt(getattr(taller, 'nombre', '') or '') or 'Taller'
    cuando = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
    motor = ' '.join(
        parte for parte in (
            _txt(getattr(cotizacion, 'vehiculo_cilindraje', '')),
            _txt(getattr(cotizacion, 'tipo_motor_label', '') or getattr(cotizacion, 'tipo_motor', '')),
        ) if parte
    )
    auto = ' '.join(
        parte for parte in (
            _txt(getattr(cotizacion, 'vehiculo_marca', '')),
            _txt(getattr(cotizacion, 'vehiculo_modelo', '')),
            _txt(getattr(cotizacion, 'vehiculo_anio', '')),
        ) if parte
    )
    pdf = _OrdenPdf()
    pdf.add_page()
    pdf._parrafo('Orden de compra de repuestos', bold=True, size=16)
    pdf._parrafo(nombre_taller, bold=True, size=12)
    pdf._parrafo(cuando.strftime('%d-%m-%Y'))
    pdf.ln(2)
    pdf._parrafo('Vehículo', bold=True, size=12)
    patente = _txt(getattr(cotizacion, 'vehiculo_patente', '')) or 'Sin patente'
    vin = _txt(getattr(cotizacion, 'vehiculo_vin', '')) or 'Sin VIN'
    pdf._parrafo(f'Patente {patente}')
    pdf._parrafo(auto or 'Sin marca ni modelo')
    pdf._parrafo(f'Motor {motor}' if motor else 'Motor sin dato')
    pdf._parrafo(f'VIN {vin}')
    pdf.ln(2)

    grupos = _grupos(list(getattr(cotizacion, 'repuestos', None) or []))
    if not grupos:
        pdf._parrafo('Esta cotización no tiene repuestos.')
    for casa, lineas in grupos:
        pdf._parrafo(casa, bold=True, size=12)
        muestra = next((r for r in lineas if _txt(r.get('casa_sucursal') or r.get('casa_telefono'))), lineas[0])
        sucursal = _txt(muestra.get('casa_sucursal'))
        telefono = _txt(muestra.get('casa_telefono'))
        if sucursal:
            pdf._parrafo(sucursal)
        if telefono:
            pdf._parrafo(f'Teléfono {telefono}')
        for rep in lineas:
            try:
                cantidad = int(rep.get('cantidad') or 1)
            except (TypeError, ValueError):
                cantidad = 1
            titulo = _txt(rep.get('nombre'))
            pdf._parrafo(f'{cantidad} × {titulo}', bold=True)
            spec = ' · '.join(
                parte for parte in (
                    _txt(rep.get('especificacion')),
                    _txt(rep.get('marca_repuesto')),
                    _txt(rep.get('calidad')),
                    _txt(rep.get('codigo_parte')),
                ) if parte
            )
            if spec:
                pdf._parrafo(spec, size=9)
            pdf._parrafo(_precio_linea(rep), size=9)
        pdf.ln(1)

    pdf.ln(2)
    pdf._parrafo(
        'Precios de referencia para comprar el repuesto. No incluye mano de obra ni el valor que se cobra al cliente.',
        size=9,
    )
    return bytes(pdf.output())

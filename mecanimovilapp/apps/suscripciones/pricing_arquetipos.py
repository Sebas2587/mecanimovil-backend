"""
Arquetipos de ticket de servicio (Chile) para calibrar créditos y planes.

La idea: cada arquetipo tiene un ticket de mercado de referencia y una fracción
objetivo (0–1) del ticket que queremos representar con el costo en créditos de
**una postulación** (créditos × precio bruto por crédito).

El precio bruto del crédito es lo que ve/paga el proveedor en Mercado Pago; la
liquidación neta tras comisión MP + IVA se estima con `mercado_pago_pricing`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Dict, Iterable, List

from mecanimovilapp.apps.suscripciones.mercado_pago_pricing import retencion_efectiva_sobre_bruto


@dataclass(frozen=True)
class ArquetipoServicio:
    id: str
    nombre: str
    ticket_referencia_clp: Decimal
    fraccion_captura_objetivo: Decimal

    def clp_objetivo_por_postulacion(self) -> Decimal:
        return (self.ticket_referencia_clp * self.fraccion_captura_objetivo).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )


# Fracciones calibradas para que, con ~$520 bruto/crédito (≈ $500 neto tras MP),
# los créditos sugeridos queden en bandas 8 / 14 / 22 / 25 (tope por postulación en script).
ARQUETIPOS_DEFAULT: List[ArquetipoServicio] = [
    ArquetipoServicio(
        id='basico',
        nombre='Servicio liviano / diagnóstico básico',
        ticket_referencia_clp=Decimal('40000'),
        fraccion_captura_objetivo=Decimal('0.1039'),
    ),
    ArquetipoServicio(
        id='medio',
        nombre='Servicio medio (mantención, frenos, aceite…)',
        ticket_referencia_clp=Decimal('80000'),
        fraccion_captura_objetivo=Decimal('0.09095'),
    ),
    ArquetipoServicio(
        id='alto',
        nombre='Servicio alto (mayor complejidad o ticket)',
        ticket_referencia_clp=Decimal('120000'),
        fraccion_captura_objetivo=Decimal('0.09528'),
    ),
    ArquetipoServicio(
        id='premium',
        nombre='Servicio premium / ticket muy alto',
        ticket_referencia_clp=Decimal('200000'),
        fraccion_captura_objetivo=Decimal('0.064965'),
    ),
]


def arquetipos_por_id() -> Dict[str, ArquetipoServicio]:
    return {a.id: a for a in ARQUETIPOS_DEFAULT}


def precio_neto_credito_desde_bruto(precio_credito_bruto: Decimal) -> Decimal:
    r = retencion_efectiva_sobre_bruto()
    return (precio_credito_bruto * (Decimal('1') - r)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def liquidez_neta_monto_bruto_mp(monto_bruto: Decimal) -> Decimal:
    r = retencion_efectiva_sobre_bruto()
    return (monto_bruto * (Decimal('1') - r)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def creditos_sugeridos_para_ticket(
    ticket_clp: Decimal,
    fraccion_sobre_ticket: Decimal,
    precio_credito_bruto: Decimal,
    *,
    min_creditos: int = 1,
    max_creditos: int = 99,
) -> int:
    if ticket_clp <= 0 or fraccion_sobre_ticket < 0 or precio_credito_bruto <= 0:
        return min_creditos
    objetivo_clp = (ticket_clp * fraccion_sobre_ticket).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    n = (objetivo_clp / precio_credito_bruto).to_integral_value(rounding=ROUND_CEILING)
    c = max(min_creditos, int(n))
    return min(c, max_creditos)


def fraccion_ticket_efectiva_bruta(
    ticket_clp: Decimal,
    creditos: int,
    precio_credito_bruto: Decimal,
) -> Decimal:
    if ticket_clp <= 0:
        return Decimal('0')
    return ((Decimal(creditos) * precio_credito_bruto) / ticket_clp).quantize(
        Decimal('0.0001'), rounding=ROUND_HALF_UP
    )


def precio_bruto_credito_desde_ticket_y_creditos(
    ticket_clp: Decimal,
    fraccion_sobre_ticket: Decimal,
    creditos: int,
) -> Decimal:
    if creditos < 1:
        raise ValueError('creditos debe ser >= 1')
    objetivo = ticket_clp * fraccion_sobre_ticket
    return (objetivo / Decimal(creditos)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def filas_simulacion(
    precio_credito_bruto: Decimal,
    arquetipos: Iterable[ArquetipoServicio],
    *,
    min_creditos: int = 1,
    max_creditos: int = 99,
) -> List[dict]:
    p_neto = precio_neto_credito_desde_bruto(precio_credito_bruto)
    rows: List[dict] = []
    for a in arquetipos:
        c = creditos_sugeridos_para_ticket(
            a.ticket_referencia_clp,
            a.fraccion_captura_objetivo,
            precio_credito_bruto,
            min_creditos=min_creditos,
            max_creditos=max_creditos,
        )
        rows.append(
            {
                'id': a.id,
                'nombre': a.nombre,
                'ticket_clp': a.ticket_referencia_clp,
                'fraccion_objetivo': a.fraccion_captura_objetivo,
                'clp_objetivo_postulacion': a.clp_objetivo_por_postulacion(),
                'creditos_sugeridos': c,
                'clp_bruto_postulacion': Decimal(c) * precio_credito_bruto,
                'clp_neto_postulacion_aprox': Decimal(c) * p_neto,
                'fraccion_ticket_bruta_efectiva': fraccion_ticket_efectiva_bruta(
                    a.ticket_referencia_clp, c, precio_credito_bruto
                ),
            }
        )
    return rows


def creditos_mensuales_sugeridos_plan(
    postulaciones_mes: int,
    precio_credito_bruto: Decimal,
    arquetipo: ArquetipoServicio,
    *,
    min_creditos: int = 1,
    max_creditos: int = 99,
) -> int:
    c = creditos_sugeridos_para_ticket(
        arquetipo.ticket_referencia_clp,
        arquetipo.fraccion_captura_objetivo,
        precio_credito_bruto,
        min_creditos=min_creditos,
        max_creditos=max_creditos,
    )
    return int(c * postulaciones_mes)


# Mapeo servicio (nombre exacto en BD) → id de arquetipo (ajustar si cambian nombres).
SERVICIO_A_ARQUETIPO: Dict[str, str] = {
    'Lavado a domicilio': 'basico',
    'Cambio de ampolletas': 'basico',
    'Cambio de batería': 'basico',
    'Cambio de filtro habitáculo': 'basico',
    'Cambio de filtro de aire': 'basico',
    'Revisión técnica': 'basico',
    'Servicio escáner automotriz': 'basico',
    'Cambio de pastillas de frenos y rectificado': 'medio',
    'Cambio de pastillas y discos de freno': 'medio',
    'Cambio de pastillas de frenos': 'medio',
    'Cambio de bujías': 'medio',
    'Cambio aceite motor y filtro': 'medio',
    'Cambio de aceite motor': 'medio',
    'Revisión precompra': 'medio',
    'Diagnóstico electromecánico': 'alto',
    'Diagnóstico mecánico': 'alto',
    'Mantenimiento por kilometraje': 'premium',
}


def creditos_requeridos_por_servicio_desde_arquetipos(
    precio_credito_bruto: Decimal,
    *,
    max_creditos: int = 25,
) -> Dict[str, int]:
    """
    Devuelve nombre_servicio → créditos requeridos según arquetipo y precio bruto vigente.
    """
    by_id = arquetipos_por_id()
    out: Dict[str, int] = {}
    for nombre, aid in SERVICIO_A_ARQUETIPO.items():
        arq = by_id[aid]
        out[nombre] = creditos_sugeridos_para_ticket(
            arq.ticket_referencia_clp,
            arq.fraccion_captura_objetivo,
            precio_credito_bruto,
            min_creditos=1,
            max_creditos=max_creditos,
        )
    return out

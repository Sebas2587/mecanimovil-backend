"""Reglas de conversación según calificación acumulada del lead."""
from __future__ import annotations

from mecanimovilapp.apps.agente_ia.models import LeadCalificacion


def _etiqueta_categoria(categoria: str) -> str:
    labels = dict(LeadCalificacion.CATEGORIA_CHOICES)
    return labels.get(categoria, categoria or 'sin calificar')


def construir_bloque_calificacion_lead(
    *,
    categoria: str = '',
    score: int = 0,
) -> str:
    """Sección del prompt con categoría acumulada y reglas por tipo de lead."""
    cat = (categoria or LeadCalificacion.CATEGORIA_SIN_CALIFICAR).strip()
    if cat == LeadCalificacion.CATEGORIA_SIN_CALIFICAR and score <= 0:
        return ''

    lineas = [
        f'Calificación acumulada de este lead: {_etiqueta_categoria(cat)} (score {int(score or 0)}).',
        'Ajusta tu ritmo comercial según esta calificación (además de la señal del turno actual):',
    ]

    if cat in (
        LeadCalificacion.CATEGORIA_LISTO_AGENDAR,
        LeadCalificacion.CATEGORIA_INTERESADO,
    ):
        lineas.append(
            '- Lead calificado: puedes ser más directo cerrando cotización o coordinación cuando el cliente '
            'lo pida. Si ya tiene patente + teléfono + problema claro, prioriza avanzar al borrador.'
        )
    elif cat in (
        LeadCalificacion.CATEGORIA_CURIOSO,
        LeadCalificacion.CATEGORIA_SIN_PRESUPUESTO,
        LeadCalificacion.CATEGORIA_COMPARANDO,
    ):
        lineas.append(
            '- Lead de baja disposición comercial: refuerza NO insistir — quédate en asesoría técnica. '
            'PROHIBIDO empujar cotización, teléfono o agenda en cada turno. Solo retoma si ESTE mensaje '
            'muestra señal clara de avance (pide precio, confirma cotizar, da datos para avanzar).'
        )
    elif cat == LeadCalificacion.CATEGORIA_NO_AUTOMOTRIZ:
        lineas.append(
            '- Lead fuera de tema automotriz: no insistas comercialmente; escala a humano si persiste.'
        )
    else:
        lineas.append(
            '- Lead aún sin calificar claramente: sigue el ritmo natural del turno; no asumas intención de compra.'
        )

    return '\n'.join(lineas)


def prioridad_escalamiento_por_lead(categoria: str) -> str:
    """alta | normal — para notificaciones al taller."""
    cat = (categoria or '').strip()
    if cat == LeadCalificacion.CATEGORIA_LISTO_AGENDAR:
        return 'alta'
    if cat == LeadCalificacion.CATEGORIA_INTERESADO:
        return 'alta'
    return 'normal'

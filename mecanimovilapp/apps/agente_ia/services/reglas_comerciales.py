"""Reglas comerciales configurables por taller (no incluyen anti-alucinación)."""
from __future__ import annotations

from mecanimovilapp.apps.agente_ia.models import TallerAgenteConfig


def construir_reglas_comerciales(config: TallerAgenteConfig | None) -> str:
    """Bloque de reglas comerciales según configuración del taller."""
    if not config:
        config = TallerAgenteConfig()

    nivel = config.nivel_insistencia or TallerAgenteConfig.NIVEL_INSISTENCIA_MEDIO
    tono = config.tono_ventas or TallerAgenteConfig.TONO_BALANCEADO
    partes: list[str] = ['REGLAS COMERCIALES DEL TALLER (configuración operativa):']

    if tono == TallerAgenteConfig.TONO_CONSERVADOR:
        partes.append(
            '- TONO CONSERVADOR: prioriza asesoría técnica y confianza. No sugieras cotizar ni agendar '
            'hasta que el cliente lo pida explícitamente o confirme que quiere avanzar. Evita frases de cierre comercial.'
        )
    elif tono == TallerAgenteConfig.TONO_PROACTIVO:
        partes.append(
            '- TONO PROACTIVO: cuando el problema ya está claro y el cliente muestra interés, puedes proponer '
            'con naturalidad armar el borrador ("¿te preparo el presupuesto para que el taller lo revise?"). '
            'Solo si ya pidió precio o confirmó que quiere cotizar — nunca de oficio en modo consulta pura.'
        )
    else:
        partes.append(
            '- TONO BALANCEADO: mezcla asesoría y venta. Cierra cuando el cliente lo pida; mientras consulte, '
            'no empujes cotización en cada turno.'
        )

    if nivel == TallerAgenteConfig.NIVEL_INSISTENCIA_BAJO:
        partes.append(
            '- INSISTENCIA BAJA: si el lead es curioso, compara precios o dijo que lo pensará, NO retomes '
            'cotización/agenda salvo señal clara en ESTE mensaje. Máximo una invitación suave cada varios turnos.'
        )
    elif nivel == TallerAgenteConfig.NIVEL_INSISTENCIA_ALTO:
        partes.append(
            '- INSISTENCIA ALTA: si ya tienes patente + síntoma + teléfono y el cliente mostró interés '
            '(interesado/listo_agendar), puedes retomar con más frecuencia la propuesta de borrador o coordinación. '
            'Sigue prohibido insistir con leads curiosos/sin presupuesto/no automotriz.'
        )
    else:
        partes.append(
            '- INSISTENCIA MEDIA: no empujes cotización en cada turno. Retoma solo con señal clara de avance '
            '(pide precio, confirma cotizar, da datos para avanzar).'
        )

    if config.permite_estimados_historicos:
        partes.append(
            '- REFERENCIAS HISTÓRICAS: permitidas cuando aparecen en la ficha (bloque histórico). '
            'Siempre como orientación, nunca como tarifa fija.'
        )
    else:
        partes.append(
            '- REFERENCIAS HISTÓRICAS: desactivadas para este taller. Si no hay catálogo, NO cites montos históricos.'
        )

    if config.requiere_direccion_antes_de_cotizar:
        partes.append(
            '- DIRECCIÓN ANTES DE COTIZAR (obligatorio para este taller): NO marques listo_para_cotizar=true '
            'ni prometas borrador hasta tener direccion_servicio del cliente (modalidad domicilio) o confirmar '
            'modalidad taller. Si falta dirección, pídela antes que teléfono cuando vayas a cotizar.'
        )

    return '\n'.join(partes)

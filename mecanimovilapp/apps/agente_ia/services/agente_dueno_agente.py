"""El modelo elige la herramienta. Si no responde, las tareas conocidas igual corren."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HERRAMIENTAS = {
    'clientes_esperando',
    'cotizar_pendientes',
    'resumen_cotizaciones',
    'detalle_cotizaciones',
    'crear_servicio',
}


def es_otra_tarea(texto: str) -> bool:
    return _herramienta_directa(texto) is not None


def atender_tarea(taller, hilo, texto: str, user) -> dict | None:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_tareas import estudiar_lead

    elegido = _id_lead(texto)
    if elegido:
        return estudiar_lead(taller, user, elegido)
    pendiente = hilo.accion_pendiente if isinstance(hilo.accion_pendiente, dict) else {}
    if pendiente.get('tipo') == 'tarea_agente':
        return _continuar(taller, user, texto, pendiente)
    herramienta = _herramienta_directa(texto)
    if herramienta is None and _puede_planear(plano(texto)):
        herramienta = _planear(texto)
    if herramienta is None:
        return None
    return _correr(taller, user, texto, herramienta, {})


def _continuar(taller, user, texto: str, pendiente: dict) -> dict | None:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_tareas import (
        cerrar_servicio,
        cotizar_pendientes,
        detalle_cotizaciones,
    )

    p = plano(texto)
    herramienta = pendiente.get('herramienta')
    if herramienta == 'estudiar_lead' and _pide_armar(p):
        return cotizar_pendientes(taller, user, list(pendiente.get('clientes') or []))
    if herramienta == 'crear_servicio':
        return cerrar_servicio(taller, texto, pendiente)
    if herramienta == 'resumen_cotizaciones' and re.search(
        r'aprobad|rechaz|borrador|plazo|vencid|expir',
        p,
    ):
        return detalle_cotizaciones(taller, texto, str(pendiente.get('periodo') or 'semana'))
    if herramienta == 'clientes_esperando' and _herramienta_directa(texto) == 'cotizar_pendientes':
        return cotizar_pendientes(taller, user, list(pendiente.get('clientes') or []))
    directa = _herramienta_directa(texto)
    if directa:
        return _correr(taller, user, texto, directa, pendiente)
    return None


def _correr(taller, user, texto: str, herramienta: str, pendiente: dict) -> dict | None:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_tareas import (
        cotizar_pendientes,
        detalle_cotizaciones,
        empezar_servicio,
        resumen_cotizaciones,
        turno_clientes_esperando,
    )

    if herramienta == 'clientes_esperando':
        return turno_clientes_esperando(taller, user)
    if herramienta == 'cotizar_pendientes':
        return cotizar_pendientes(taller, user, list(pendiente.get('clientes') or []))
    if herramienta == 'resumen_cotizaciones':
        return resumen_cotizaciones(taller, texto)
    if herramienta == 'detalle_cotizaciones':
        return detalle_cotizaciones(taller, texto, str(pendiente.get('periodo') or 'semana'))
    if herramienta == 'crear_servicio':
        return empezar_servicio(taller, texto)
    return None


def _herramienta_directa(texto: str) -> str | None:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    if re.search(r'\b(pendientes|cotizaciones de los clientes|las cotizaciones pendientes)\b', p) and re.search(
        r'\b(realiza|realizar|realices|cotiza|cotizar|arma|haz)\b',
        p,
    ):
        return 'cotizar_pendientes'
    if re.search(r'\b(cuantas|cuantos)\b', p) and 'cotiz' in p and re.search(r'\b(semana|mes|enviad)\b', p):
        return 'resumen_cotizaciones'
    if re.search(r'\b(crea|crear|crees|da de alta)\b', p) and re.search(r'\bservicio\b', p):
        return 'crear_servicio'
    return None


def _id_lead(texto: str) -> int | None:
    hallado = re.search(r'\blead:(\d+)\b', texto or '')
    if not hallado:
        return None
    return int(hallado.group(1))


def _pide_armar(p: str) -> bool:
    return bool(re.match(r'^(si|dale|confirmo|ok|okay|de acuerdo|hazlo|adelante|claro|listo)\b', p) or re.search(
        r'\b(cotiza|cotizalo|armalo|armar|hazla)\b',
        p,
    ))


def _puede_planear(p: str) -> bool:
    return bool(re.search(r'\b(cotiz|cliente|servicio|repuesto|enviad|aprobad|presupuesto)\b', p))


def _planear(texto: str) -> str | None:
    from mecanimovilapp.apps.agente_ia.services.orquestador import _llamar_gemini_agente

    decision, _error = _llamar_gemini_agente(
        'Eres el coordinador del taller. Elige una herramienta y no inventes datos.\n'
        'Herramientas: clientes_esperando, cotizar_pendientes, resumen_cotizaciones, '
        'detalle_cotizaciones, crear_servicio.\n'
        'Responde solo JSON: {"herramienta":"nombre"}\n'
        f'Mensaje:\n{texto}'
    )
    if not isinstance(decision, dict):
        return None
    nombre = str(decision.get('herramienta') or '')
    if nombre in _HERRAMIENTAS:
        return nombre
    return None

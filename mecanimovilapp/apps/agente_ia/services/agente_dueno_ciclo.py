"""El modelo elige una herramienta, observa el taller y recién ahí responde."""
from __future__ import annotations

import json
import re

from django.core.cache import cache

_MEMORIA = 12
_PASOS = 3


def ciclo_agente(taller, hilo, texto: str, user, historial: list[dict]) -> dict | None:
    from mecanimovilapp.apps.agente_ia.services.orquestador import _llamar_gemini_agente

    observaciones = []
    for _ in range(_PASOS):
        decision, _error = _llamar_gemini_agente(_prompt(
            getattr(taller, 'nombre', '') or 'Taller',
            texto,
            historial,
            observaciones,
            _leer_memoria(taller.id),
        ))
        if not isinstance(decision, dict):
            break
        nombre = str(decision.get('herramienta') or '').strip()
        if nombre:
            turno = _correr(taller, hilo, texto, user, nombre, decision.get('argumentos'))
            if turno is None:
                observaciones.append({'herramienta': nombre, 'observacion': 'Esa herramienta no existe.'})
                continue
            _anotar(taller.id, nombre, turno.get('resumen') or '')
            return turno
        decir = str(decision.get('decir') or '').strip()
        if not decir:
            break
        if _inventa_datos(decir, decision.get('vista')):
            observaciones.append({
                'herramienta': 'rechazo',
                'observacion': 'No afirmes clientes ni totales sin una herramienta.',
            })
            continue
        from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno

        return _turno(
            haciendo=str(decision.get('haciendo') or 'Respondo')[:180],
            titulo=str(decision.get('titulo') or 'Agente del taller')[:80],
            resumen=decir[:2000],
            ancla='keep',
        )
    return _por_si_invento(taller, user, texto)


def _correr(taller, hilo, texto, user, nombre: str, argumentos) -> dict | None:
    del user, argumentos
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_tareas import (
        cotizar_pendientes,
        detalle_cotizaciones,
        empezar_servicio,
        resumen_actividad,
        resumen_cotizaciones,
        turno_clientes_esperando,
    )

    if nombre == 'clientes_esperando':
        return turno_clientes_esperando(taller, user)
    if nombre == 'cotizar_pendientes':
        pendiente = hilo.accion_pendiente if isinstance(hilo.accion_pendiente, dict) else {}
        return cotizar_pendientes(taller, user, list(pendiente.get('clientes') or []))
    if nombre == 'resumen_cotizaciones':
        return resumen_cotizaciones(taller, texto)
    if nombre == 'actividad_taller':
        return resumen_actividad(taller)
    if nombre == 'detalle_cotizaciones':
        return detalle_cotizaciones(taller, texto, 'semana')
    if nombre == 'crear_servicio':
        return empezar_servicio(taller, texto)
    if nombre == 'agenda_hoy':
        from django.utils import timezone

        from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _responder_hoy

        return _responder_hoy(taller, timezone.localdate(), [])
    return None


def _por_si_invento(taller, user, texto: str) -> dict | None:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_tareas import (
        resumen_actividad,
        turno_clientes_esperando,
    )

    p = plano(texto)
    if re.search(r'cliente|usuario|quien|pendiente|cotiz|potencial|escrib', p):
        return turno_clientes_esperando(taller, user)
    if re.search(r'realiz|todo el tiempo|enviad', p):
        return resumen_actividad(taller)
    return None


def _inventa_datos(decir: str, vista) -> bool:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(decir)
    if 'alta demanda' in p or 'lo mas pedido' in p:
        return True
    if re.search(r'\b\d+\s+clientes\b', p):
        return True
    filas = []
    if isinstance(vista, dict) and isinstance(vista.get('filas'), list):
        filas = vista['filas']
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        fila_id = str(fila.get('id') or '')
        if fila_id.startswith(('lead:', 'cotizacion:', 'chat:', 'oferta:')):
            continue
        if fila.get('titulo') or fila.get('detalle'):
            return True
    return False


def _prompt(taller: str, texto: str, historial: list[dict], observaciones: list[dict], memoria: list[str]) -> str:
    return (
        'Eres el agente del dueño de un taller mecánico. '
        'No inventes clientes, patentes, totales ni demandas. '
        'Si la respuesta depende del taller, llama una herramienta y usa solo lo que ella devuelva. '
        'Puedes hacer una pregunta breve solo si no hace falta mirar datos.\n'
        'Herramientas: '
        'clientes_esperando (quién escribió hoy o ayer, pidió un servicio, mandó patente y no tiene cotización enviada), '
        'cotizar_pendientes (arma los borradores de esa lista), '
        'resumen_cotizaciones (enviadas de esta semana o este mes), '
        'actividad_taller (servicios completados y cotizaciones enviadas en todo el tiempo), '
        'detalle_cotizaciones (aprobadas, borrador, rechazadas o fuera de plazo), '
        'crear_servicio (alta de un servicio del taller), '
        'agenda_hoy (citas de hoy).\n'
        'Responde solo JSON: '
        '{"herramienta":"nombre"} '
        'o {"decir":"pregunta o cierre que no afirma datos del taller","haciendo":"","titulo":""}.\n'
        f'Taller: {taller}\n'
        f'Hechos ya consultados:\n{json.dumps(memoria, ensure_ascii=False)}\n'
        f'Historial:\n{json.dumps(historial[-8:], ensure_ascii=False)}\n'
        f'Observaciones de este turno:\n{json.dumps(observaciones, ensure_ascii=False)}\n'
        f'Mensaje:\n{texto}'
    )


def _leer_memoria(taller_id: int) -> list[str]:
    guardado = cache.get(f'agente-dueno-memoria:{taller_id}') or []
    if not isinstance(guardado, list):
        return []
    return [str(item) for item in guardado[-_MEMORIA:]]


def _anotar(taller_id: int, herramienta: str, resumen: str) -> None:
    hecho = f'{herramienta}: {(resumen or "").strip()[:180]}'
    if not hecho.strip(':'):
        return
    previa = _leer_memoria(taller_id)
    previa.append(hecho)
    cache.set(f'agente-dueno-memoria:{taller_id}', previa[-_MEMORIA:], 60 * 60 * 24 * 30)

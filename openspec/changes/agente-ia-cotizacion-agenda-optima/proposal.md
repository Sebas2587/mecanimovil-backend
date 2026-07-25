# agente-ia-cotizacion-agenda-optima

## Why

El agente IA conversacional ya captura leads y arma borradores, pero el taller aún debe abrir cada cotización para saber si está lista, Messenger/IG no disparaban agendamiento automático al marcar aceptada, y la agenda ignoraba especialidad del servicio y preguntaba día/hora en lugar de proponer el mejor slot.

## What Changes

- **Readiness gate:** `evaluar_listo_para_enviar()` determinístico en metadata del borrador (`listo_para_enviar`, `pendientes_revision`).
- **Notificaciones:** push diferenciado "lista para enviar" vs "con pendientes".
- **Pipeline comercial:** filas de borradores agente IA con campos de readiness; orden prioriza listas.
- **Unificación aceptación:** `crear_cita_desde_cotizacion_aceptada()` + `marcar-aceptada` dispara `on_cotizacion_respondida` → agendamiento IA en todos los canales.
- **Agenda óptima:** slots filtrados por `oferta_servicio_id`/especialidad; asignación de mecánico con fallback; propuesta proactiva del slot más próximo.

## Scope (out)

- Refactor del orquestador en prompts multi-fase.
- Recordatorios / no-show.
- Nuevos modelos de datos.

## Requirements

- REQ-AGENTE-READINESS: borrador agente IA SHALL persistir checklist de envío en metadata.
- REQ-AGENTE-ACEPTAR-UNIFICADO: cualquier vía de aceptación SHALL crear cita placeholder y encolar agendamiento IA si hay conversación.
- REQ-AGENTE-AGENDA-ESPECIALIDAD: agendamiento conversacional SHALL respetar especialidad del servicio cotizado con fallback.
- REQ-AGENTE-AGENDA-PROPUESTA: post-aceptación SHALL proponer el slot más próximo disponible antes de pedir día/hora abierto.

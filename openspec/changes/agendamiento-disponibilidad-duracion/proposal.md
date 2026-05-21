# Agendamiento por duración y ventanas libres

## Why
Los proveedores necesitan definir cuánto dura cada servicio y que los usuarios vean horarios reales cuando el mecánico ya tiene citas el mismo día.

## What Changes
- `OfertaServicio`: `duracion_minima_minutos`, `duracion_maxima_minutos`
- Servicio `disponibilidad_proveedor`: intervalos ocupados + ventanas libres + slots
- API: `disponibilidad_con_duracion/`, `dias_disponibles_agenda/` en taller y mecánico
- App usuarios: `CalendarioProveedorScreen`, flujo post-selección de proveedor
- App proveedor: rango de duración en `crear-servicio`

## Requirements
- REQ-DURACION-OFERTA: el proveedor SHALL configurar min/max minutos por oferta
- REQ-VENTANAS-LIBRES: slots SHALL respetar citas activas con duración máxima de cada servicio agendado
- REQ-CALENDARIO-USUARIO: tras elegir proveedor compatible, el usuario SHALL elegir fecha/hora desde agenda real

## Documentación actualizada (2026-05-21)
- Spec canónica: `openspec/specs/agendamiento-disponibilidad/spec.md`
- Fix 500 + JSON slots: `openspec/changes/agendamiento-calendario-api-resilience/`
- Cliente (agendaContext): `mecanimovil-usuarios/openspec/changes/agendamiento-calendario-contexto-unificado/`

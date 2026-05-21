# API agenda — resiliencia y fix 500 (implementado)

**Estado:** Implementado (2026-05-21)  
**Commit:** `d990e85`

## Why
`GET .../disponibilidad_con_duracion/?oferta_servicio_id=96` devolvía 500 cuando
`duracion_rango_oferta` trataba `servicio.duracion_estimada_base` (DurationField/timedelta)
como `time`. El calendario desde perfil quedaba vacío aunque el contexto de navegación fuera correcto.

## What Changes
- `_time_to_minutes` acepta `timedelta` y `time`.
- `_slots_json_safe` antes de responder.
- try/except en acciones `disponibilidad_con_duracion` (taller y mecánico).

## Spec canónica
`openspec/specs/agendamiento-disponibilidad/spec.md`

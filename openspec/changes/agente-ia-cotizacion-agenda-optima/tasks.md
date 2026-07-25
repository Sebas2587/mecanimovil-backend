# Tasks — agente-ia-cotizacion-agenda-optima

## Workstream A — Readiness
- [x] `evaluar_listo_para_enviar()` en `cotizacion_borrador.py`
- [x] Persistir `listo_para_enviar` / `pendientes_revision` en metadata
- [x] Notificaciones push diferenciadas
- [x] Serializer + pipeline comercial con campos y orden

## Workstream B — Aceptación unificada
- [x] `crear_cita_desde_cotizacion_aceptada()` extraído
- [x] `marcar-aceptada` crea cita + `on_cotizacion_respondida`

## Workstream C — Agenda óptima
- [x] Categorías desde `servicios_lineas` / `oferta_servicio_id`
- [x] `disponibilidad_con_duracion(requiere_especialidad=True)` con fallback
- [x] `resolver_miembro_cita_personal(categorias_requeridas=...)` con fallback
- [x] `_mejor_slot_proximo()` + mensaje proactivo en `iniciar_agendamiento`

## Verificación
- [ ] Borrador sin patente → `listo_para_enviar=false` + pendientes
- [ ] Borrador catálogo completo → `listo_para_enviar=true`
- [ ] `POST marcar-aceptada` → cita + task agendamiento
- [ ] Aceptación WA/link → mismo flujo de propuesta de slot

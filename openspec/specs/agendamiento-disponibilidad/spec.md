# agendamiento-disponibilidad Specification

## Purpose
Cálculo de ventanas libres y slots de agenda según `HorarioProveedor` real, citas existentes
(`SolicitudServicio`) y duración de la `OfertaServicio` solicitada.

**Implementación:** `mecanimovilapp/apps/usuarios/services/disponibilidad_proveedor.py`  
**Vistas:** `TallerViewSet` / `MecanicoDomicilioViewSet` → `disponibilidad_con_duracion`, `dias_disponibles_agenda`, `horarios_semanales`

**Cliente (contexto navegación):** `mecanimovil-usuarios/openspec/changes/agendamiento-calendario-contexto-unificado/design.md`

## Requirements

### REQ-DURACION-OFERTA
El cálculo de slots **SHALL** usar `duracion_minima_minutos` / `duracion_maxima_minutos` de `OfertaServicio`.
Si faltan, puede usar `duracion_estimada` (TimeField) o `servicio.duracion_estimada_base` (DurationField → minutos).

#### Scenario: Oferta con duracion_estimada_base en servicio
- GIVEN `oferta_servicio_id` válido para el proveedor
- AND el servicio tiene `duracion_estimada_base` como `DurationField`
- WHEN se llama `disponibilidad_con_duracion`
- THEN responde 200 con slots (no 500)

### REQ-VENTANAS-LIBRES
Los slots **SHALL** respetar citas en estados `pendiente`, `confirmado`, `en_proceso`, `aceptada_por_proveedor`,
usando la duración máxima de cada cita.

### REQ-HORARIO-REAL-BD
`horarios_semanales` **SHALL** devolver solo registros `HorarioProveedor` persistidos.
Sin filas → lista vacía `[]` (no horario sintético por defecto).

### REQ-OFERTA-PROVEEDOR
Con `oferta_servicio_id`, la oferta **SHALL** filtrarse por el mismo `taller` o `mecanico` del path.
Si no pertenece, se usa duración por defecto (60 min) y se registra warning en logs.

### REQ-API-RESILIENTE
`disponibilidad_con_duracion` **SHALL NOT** responder 500 por errores de cálculo; en fallo devuelve 200 con
`proveedor_disponible: false` y `slots_disponibles: []`.

### REQ-SLOTS-JSON
La respuesta **SHALL** serializar slots solo con campos string: `hora`, `hora_fin_estimada`, `disponible`
(sin objetos `time` internos).

## Endpoints

| Método | Path | Query |
|--------|------|-------|
| GET | `/api/usuarios/talleres/{id}/horarios_semanales/` | — |
| GET | `/api/usuarios/mecanicos-domicilio/{id}/horarios_semanales/` | — |
| GET | `.../dias_disponibles_agenda/` | `oferta_servicio_id`, `dias` (1-30) |
| GET | `.../disponibilidad_con_duracion/` | `fecha` (YYYY-MM-DD), `oferta_servicio_id` |

## Commits de referencia
- `d990e85` — fix 500, timedelta, slots JSON-safe, try/except vistas
- `8e745a9` — agenda solo HorarioProveedor real
- `37ecca9` — dias_disponibles_agenda sin 500

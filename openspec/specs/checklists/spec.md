# checklists Specification

## Purpose
TBD - created by archiving change checklist-inteligente-salud. Update Purpose after archive.
## Requirements
### Requirement: Intención del checklist por servicio

Cada `ChecklistTemplate` **SHALL** declarar un `tipo_intencion_default`
(`REPARACION` | `INSPECCION` | `PRECOMPRA` | `MIXTO`) que indica la
semántica del checklist sobre el vehículo.

#### Scenario: Servicio de diagnóstico configurado como inspección

- GIVEN un `Servicio` llamado `Diagnóstico mecánico`
- WHEN se ejecuta `populate_checklists_por_servicio`
- THEN su `ChecklistTemplate` queda con `tipo_intencion_default='INSPECCION'`
- AND ningún `ChecklistItemTemplate` tiene `tipo_actualizacion='REEMPLAZA'`

#### Scenario: Servicio de cambio de aceite configurado como reparación

- GIVEN un `Servicio` llamado `Cambio aceite motor y filtro`
- WHEN se ejecuta `populate_checklists_por_servicio`
- THEN su `ChecklistTemplate` queda con `tipo_intencion_default='REPARACION'`
- AND el ítem "Aceite Motor Reemplazado" tiene `tipo_actualizacion='REEMPLAZA'` y `componente_salud_asociado` apuntando a `ComponenteSalud(slug='oil')`

### Requirement: Asociación explícita ítem ↔ componente de salud

Cada `ChecklistItemTemplate` cuya respuesta afecte la salud del vehículo **SHALL** tener FK explícita `componente_salud_asociado → vehiculos.ComponenteSalud` y un `tipo_actualizacion` (`REEMPLAZA` | `INSPECCIONA` | `INFORMATIVO`). El `mapeo_componentes` por substring queda prohibido.

#### Scenario: Ítem sin componente asociado no afecta salud

- GIVEN un `ChecklistItemTemplate` con `componente_salud_asociado=null`
- WHEN se completa el checklist y se ejecuta `actualizar_salud_desde_checklist`
- THEN la respuesta a ese ítem no actualiza ningún `ComponenteSaludVehiculo`

#### Scenario: Ítem con tipo_actualizacion=INFORMATIVO no afecta salud

- GIVEN un `ChecklistItemTemplate` con `tipo_actualizacion='INFORMATIVO'`
- WHEN se completa el checklist
- THEN la respuesta queda registrada pero `ComponenteSaludVehiculo.salud_porcentaje` no se modifica

### Requirement: Input COMPONENT_HEALTH para inspecciones

El catálogo `ChecklistItemCatalog` **SHALL** soportar el tipo de pregunta
`COMPONENT_HEALTH` (slider 0–100) para que el técnico declare el porcentaje
de vida útil restante de un componente durante una inspección.

#### Scenario: Técnico declara pastillas al 70%

- GIVEN un ítem `Vida útil — Pastillas de freno` con `tipo_pregunta='COMPONENT_HEALTH'` y `componente_salud_asociado=ComponenteSalud(slug='brakes')`
- WHEN el técnico guarda la respuesta con `respuesta_numero=70`
- AND completa el checklist
- THEN `ComponenteSaludVehiculo.salud_porcentaje == 70.0`
- AND `ComponenteSaludVehiculo.salud_anclada_pct == 70.0`
- AND `ComponenteSaludVehiculo.historial_fuente == 'CHECKLIST'`
- AND `ComponenteSaludVehiculo.nivel_alerta == 'ATENCION'`

#### Scenario: SELECT cualitativo mapea a porcentaje

- GIVEN un ítem `Estado Pastillas de Frenos` con `tipo_pregunta='SELECT'` y `componente_salud_asociado=ComponenteSalud(slug='brakes')`
- WHEN el técnico responde `'Bueno'` y completa el checklist
- THEN `ComponenteSaludVehiculo.salud_porcentaje == 80.0`
- AND `ComponenteSaludVehiculo.historial_fuente == 'CHECKLIST'`

### Requirement: Snapshot de salud actual durante el checklist

El backend **SHALL** exponer
`GET /api/checklists/instances/{id}/salud-snapshot/` que devuelve, por cada
ítem del template con `componente_salud_asociado`, la salud actual del
componente para el vehículo de la orden.

#### Scenario: Snapshot incluye salud actual por componente

- GIVEN un `ChecklistInstance` cuya orden tiene `vehiculo` con `ComponenteSaludVehiculo(componente=brakes, salud_porcentaje=60.0, nivel_alerta='ATENCION')`
- WHEN el proveedor hace `GET /api/checklists/instances/{id}/salud-snapshot/`
- THEN la respuesta incluye `items[].salud_actual=60.0` para el ítem vinculado a `brakes`
- AND `items[].nivel_alerta_actual='ATENCION'`

#### Scenario: Componente sin registro retorna salud_actual=null

- GIVEN un `ChecklistInstance` cuyo vehículo aún no tiene `ComponenteSaludVehiculo` para el componente vinculado
- WHEN se consulta el snapshot
- THEN `items[].salud_actual` es `null`

### Requirement: Preview de impacto antes de finalizar

El backend **SHALL** exponer
`POST /api/checklists/instances/{id}/preview-impacto/` que calcula sin
persistir el diff entre la salud actual y la proyectada por las respuestas
guardadas hasta el momento.

#### Scenario: Preview muestra diff por componente

- GIVEN un `ChecklistInstance` con respuestas guardadas (no finalizado)
- WHEN el proveedor hace `POST /api/checklists/instances/{id}/preview-impacto/`
- THEN la respuesta incluye `diff[]` con `salud_actual`, `salud_nueva`, `delta`, `tipo_actualizacion`
- AND incluye `salud_general_actual` y `salud_general_estimada`
- AND ningún registro de `ComponenteSaludVehiculo` o `EstadoSaludVehiculo` se modifica

### Requirement: Templates sincronizados en cada deploy

`populate_checklists_por_servicio` **SHALL** ejecutarse durante el build de
Render para mantener `ChecklistTemplate` y `ChecklistItemTemplate` alineados
con el catálogo de servicios. La operación es idempotente.

#### Scenario: Build de Render sincroniza templates

- GIVEN un push a `main` con cambios en el populate
- WHEN Render ejecuta `build.sh`
- THEN `python manage.py populate_checklists_por_servicio` corre antes de `collectstatic`
- AND el comando termina con código 0
- AND ejecutar el comando dos veces seguidas no crea duplicados


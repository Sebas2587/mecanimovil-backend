# checklists Specification (delta — checklist-inteligente-v2)

## ADDED Requirements

### Requirement: Bulk creation de ChecklistItemTemplate desde catálogo por categoría

El backend **SHALL** exponer `POST /api/checklists/templates/{id}/bulk-add-items/` que,
dado `categoria`, `componente_ids[]` y `tipo_evaluacion`, cree o actualice en una sola
operación todos los `ChecklistItemTemplate` necesarios con `tipo_actualizacion` y
`componente_salud_asociado` pre-cableados.

Los valores de `tipo_evaluacion` **SHALL** mapear de la siguiente forma:
- `rapida` → 1 ítem SELECT por componente, `tipo_actualizacion=INSPECCIONA`
- `completa` → 1 ítem SELECT + 1 ítem COMPONENT_HEALTH por componente, `tipo_actualizacion=INSPECCIONA`
- `reemplazo` → 1 ítem BOOLEAN por componente, `tipo_actualizacion=REEMPLAZA`

#### Scenario: Admin crea items en bulk para sistema de frenos

- GIVEN un `ChecklistTemplate` para `Diagnóstico mecánico` con 0 ítems de frenos
- WHEN el admin envía `POST .../bulk-add-items/` con
  `{"categoria": "SISTEMA_FRENOS", "componente_ids": [1, 2], "tipo_evaluacion": "completa"}`
- THEN se crean 4 `ChecklistItemTemplate` (2 SELECT + 2 COMPONENT_HEALTH)
- AND cada uno tiene `componente_salud_asociado` apuntando al `ComponenteSalud` correspondiente
- AND la respuesta incluye `items_creados: 4`, `items_existentes: 0`

#### Scenario: Idempotencia en bulk-add-items

- GIVEN un `ChecklistTemplate` que ya tiene 4 ítems de frenos creados previamente
- WHEN el admin ejecuta el mismo `POST .../bulk-add-items/` dos veces
- THEN la segunda ejecución retorna `items_creados: 0`, `items_existentes: 4`
- AND no se crean ítems duplicados en la base de datos

### Requirement: Política de prioridad explícita en actualización de salud

Cuando múltiples `ChecklistItemTemplate` del mismo checklist mapean al mismo
`ComponenteSalud`, `actualizar_salud_desde_checklist` y `preview-impacto`
**SHALL** seleccionar el candidato con mayor prioridad según:

```
PRIORIDAD_TIPO_ACTUALIZACION: REEMPLAZA=0 > INSPECCIONA=1 > INFORMATIVO=99
PRIORIDAD_TIPO_PREGUNTA:      COMPONENT_HEALTH=0 > SELECT=1 > RATING=2
```

Empate en prioridad se resuelve por `orden_visual` ascendente (primera declaración gana).

El comportamiento de `preview-impacto` y `actualizar_salud_desde_checklist`
**SHALL** ser idéntico para el mismo conjunto de respuestas.

#### Scenario: COMPONENT_HEALTH prevalece sobre SELECT para el mismo componente

- GIVEN un template con dos ítems mapeados a `ComponenteSalud(slug='brakes')`:
  - Ítem A: `tipo_pregunta=SELECT`, `orden_visual=1`, respuesta `'Bueno'` (→ 80%)
  - Ítem B: `tipo_pregunta=COMPONENT_HEALTH`, `orden_visual=2`, respuesta `65`
- WHEN se completa el checklist
- THEN `ComponenteSaludVehiculo.salud_porcentaje == 65.0` (Ítem B ganó por tipo_pregunta)

#### Scenario: REEMPLAZA prevalece sobre INSPECCIONA para el mismo componente

- GIVEN un template con dos ítems para `ComponenteSalud(slug='oil')`:
  - Ítem A: `tipo_actualizacion=INSPECCIONA`, `tipo_pregunta=SELECT`, respuesta `'Regular'` (→ 60%)
  - Ítem B: `tipo_actualizacion=REEMPLAZA`, `tipo_pregunta=BOOLEAN`, respuesta `True`
- WHEN se completa el checklist
- THEN `ComponenteSaludVehiculo.salud_porcentaje == 100.0` (REEMPLAZA ganó)

#### Scenario: BOOLEAN REEMPLAZA con respuesta False no afecta salud

- GIVEN un ítem `Aceite Motor Reemplazado` con `tipo_actualizacion=REEMPLAZA`, `tipo_pregunta=BOOLEAN`
- WHEN el técnico guarda `respuesta_booleana=False` y completa el checklist
- THEN `ComponenteSaludVehiculo.salud_porcentaje` NO se modifica
- AND el ítem se trata como `INFORMATIVO` para esa respuesta

### Requirement: Recomendaciones ML post-checklist

El backend **SHALL** exponer `GET /api/checklists/instances/{id}/recomendaciones/`
que retorne recomendaciones de servicios y mantenimientos generadas automáticamente
al completarse el checklist, disponibles para el proveedor y el cliente dueño.

Las recomendaciones **SHALL** generarse asíncronamente via Celery al mismo tiempo que
`actualizar_salud_desde_checklist`, cachearse en Redis con TTL 24h, y categorizarse
en `URGENTE`, `ATENCION` o `PROACTIVA`.

El endpoint **SHALL** retornar 400 si el checklist no está en estado `COMPLETADO`.

El endpoint **SHALL** retornar 403 si el usuario autenticado no es el proveedor de la
orden ni el cliente dueño.

#### Scenario: Técnico puede ver recomendaciones post-checklist completado

- GIVEN un `ChecklistInstance` en estado `COMPLETADO` cuya orden pertenece a un taller
- WHEN un usuario del taller hace `GET /api/checklists/instances/{id}/recomendaciones/`
- THEN la respuesta es 200 con `recomendaciones[]`, `componentes_actualizados[]`,
  `salud_general_antes` y `salud_general_despues`

#### Scenario: Cliente puede ver recomendaciones del checklist de su orden

- GIVEN un `ChecklistInstance` en estado `COMPLETADO` cuya orden pertenece al cliente autenticado
- WHEN el cliente hace `GET /api/checklists/instances/{id}/recomendaciones/`
- THEN la respuesta es 200 con `recomendaciones[]` que incluyen `servicios_sugeridos`

#### Scenario: Checklist no completado retorna 400

- GIVEN un `ChecklistInstance` en estado `EN_PROGRESO` o `PENDIENTE_FIRMA_CLIENTE`
- WHEN cualquier usuario autenticado consulta el endpoint
- THEN la respuesta es 400 con mensaje sobre estado incorrecto

#### Scenario: Recomendación URGENTE por desgaste acelerado

- GIVEN un `EventoSaludVehiculo` reciente con `salud_porcentaje=75` para `brakes`
  registrado hace 15 días con `tipo_evento=INSPECCION_DECLARADA`
- AND un checklist completado que actualiza `brakes` a 60% (bajó 15pp en 15 días)
- WHEN `generar_recomendaciones_checklist` corre
- THEN se genera una recomendación con `prioridad=URGENTE` y `fuente=ANOMALIA`
- AND `razon` contiene referencia al desgaste acelerado detectado

### Requirement: Inline admin expone campos de salud

`ChecklistItemTemplateInline` en Django Admin **SHALL** mostrar los campos
`tipo_actualizacion` y `componente_salud_asociado` para que los administradores
puedan configurar la semántica de salud sin ejecutar el comando de populate.

#### Scenario: Admin edita tipo_actualizacion desde el inline

- GIVEN un `ChecklistTemplate` abierto en Django Admin
- WHEN el admin edita un `ChecklistItemTemplate` desde el inline
- THEN puede ver y modificar `tipo_actualizacion` (desplegable REEMPLAZA/INSPECCIONA/INFORMATIVO)
- AND puede ver y modificar `componente_salud_asociado` (foreign key a ComponenteSalud)

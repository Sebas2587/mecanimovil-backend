# Diseño técnico

## Contexto

El sistema actual asume implícitamente que todo checklist completado es un
"servicio realizado" (reemplazo). Esa simplificación rompe la precisión del
motor de salud cuando el usuario contrata una **inspección/diagnóstico**:
las pastillas, frenos, batería, etc. quedan registradas como recién
reemplazadas aunque el técnico solo las haya revisado.

Necesitamos:

1. Que el catálogo de checklist sea expresivo (cada ítem declara su
   intención sobre la salud del vehículo).
2. Que el motor de salud entienda dos puntos cardinales: "componente
   reemplazado" (curva reinicia) y "componente inspeccionado" (curva se
   ancla en el porcentaje declarado y decae desde ahí).
3. Que el técnico vea, mientras llena el checklist, en qué estado está cada
   componente y cuál será el impacto al finalizar.

## Goals

- Que un servicio tipo `Diagnóstico mecánico` permita al técnico declarar
  "pastillas al 70%", "aceite al 35%", etc. y la métrica del usuario se
  actualice exactamente a esos valores.
- Que un servicio tipo `Cambio de aceite motor y filtro` siga reseteando los
  componentes reemplazados a 100% pero también admita que ese mismo
  checklist incluya 1–2 ítems de inspección (ej. "estado pastillas") sin
  romper la lógica.
- Que el `mapeo_componentes` por substring desaparezca: la asociación
  `ChecklistItemTemplate ↔ ComponenteSalud` debe ser una FK explícita.
- Que en cada deploy a Render los templates queden sincronizados con la lista
  oficial de servicios (vía `populate_checklists_por_servicio` idempotente).

## Non-goals

- No cambiamos el modelo `Servicio` ni introducimos un campo `tipo` global a
  nivel de servicio (la "intención" vive en el template del checklist).
- No reemplazamos las reglas Weibull (`ReglaMantenimientoGenerica`/
  `Especifica`); el ancla solo desplaza el origen de la curva.
- No tocamos el flujo de `PRECOMPRA` (sigue saltándose el recálculo de
  salud y certificando el vehículo en `signals.py`).

## Decisión: granularidad por ítem (no por template)

Razón: hay servicios mixtos comunes. `Mantenimiento por kilometraje`
incluye reemplazos (aceite, filtro) **y** revisiones (correa, frenos,
fluidos). Forzar todo el template a una sola intención obligaría a partir
templates artificialmente. La granularidad por ítem (`tipo_actualizacion`)
con fallback al `tipo_intencion_default` del template cubre todos los casos
con un solo código path.

## Decisión: input híbrido `COMPONENT_HEALTH` + `SELECT`

Razón: el `SELECT` ya existente con opciones `Excelente/Bueno/Regular/Malo/
Crítico` se mantiene para evaluaciones cualitativas de sistemas completos
(ej. "Estado del Sistema Eléctrico"). Para evaluación cuantitativa de un
componente con regla Weibull (pastillas, aceite, batería, etc.) introducimos
`COMPONENT_HEALTH` (slider 0–100, paso 5). Ambos producen un float; la lógica
de `INSPECCIONA` los unifica.

## Algoritmo de ancla Weibull

`HealthEngine` calcula salud desde un km base (`km_ultimo_servicio`) usando
Weibull con η (`vida_util_proyectada`) y β. Cuando un técnico declara que
un componente está al 70% durante una inspección:

```
eta              = 50_000 km            # vida útil del componente
salud_declarada  = 70 %                 # 30 % consumido
km_consumido_inf = eta * (1 - 0.70)     # 15_000 km
km_base_efectivo = km_actual_vehiculo - km_consumido_inf
```

Persistimos `salud_anclada_pct=70` en `ComponenteSaludVehiculo`. En cada
recálculo posterior:

```
delta_km = km_actual_vehiculo - km_base_efectivo
salud    = HealthEngine._weibull(delta_km, eta, beta)
```

Esto garantiza que:
- Si el vehículo no se mueve: salud sigue siendo 70%.
- Si el vehículo recorre +5 000 km: salud cae proporcionalmente.
- Si el componente se reemplaza después: `salud_anclada_pct=None`,
  `historial_fuente='CHECKLIST'`, salud reinicia a 100% y el ancla deja de
  aplicar.

## Esquema de datos

```mermaid
erDiagram
    ChecklistTemplate ||--o{ ChecklistItemTemplate : items
    ChecklistItemTemplate }o--|| ChecklistItemCatalog : usa
    ChecklistItemTemplate }o--o| ComponenteSalud : actualiza
    ChecklistInstance }o--|| ChecklistTemplate : sigue
    ChecklistInstance ||--o{ ChecklistItemResponse : respuestas
    ComponenteSalud ||--o{ ComponenteSaludVehiculo : por_vehiculo
    ChecklistTemplate {
      string tipo_intencion_default "REPARACION|INSPECCION|PRECOMPRA|MIXTO"
    }
    ChecklistItemTemplate {
      string tipo_actualizacion "REEMPLAZA|INSPECCIONA|INFORMATIVO"
      fk componente_salud_asociado
    }
    ChecklistItemCatalog {
      string tipo_pregunta "+COMPONENT_HEALTH"
    }
    ComponenteSaludVehiculo {
      float salud_porcentaje
      float salud_anclada_pct "nuevo"
      string historial_fuente "CHECKLIST cuando viene del slider"
    }
```

## Endpoints nuevos

### `GET /api/checklists/instances/{id}/salud-snapshot/`

Devuelve por cada item del template (con componente vinculado) el estado
actual del componente en el vehículo. Permite al frontend del proveedor
mostrar el banner "estado actual" sobre cada ítem.

```json
{
  "vehiculo_id": 42,
  "kilometraje_actual": 85000,
  "items": [
    {
      "item_template_id": 17,
      "componente": {"id": 7, "nombre": "Pastillas de Freno", "slug": "brakes"},
      "salud_actual": 60.0,
      "nivel_alerta_actual": "ATENCION",
      "fuente_actual": "ENGINE",
      "fecha_ultimo_servicio": "2026-01-12T10:00:00Z",
      "tipo_actualizacion": "INSPECCIONA"
    }
  ]
}
```

### `POST /api/checklists/instances/{id}/preview-impacto/`

Sin body (lee respuestas guardadas). Devuelve el diff sin persistir.

```json
{
  "salud_general_actual": 58.4,
  "salud_general_estimada": 81.7,
  "diff": [
    {
      "componente": {"id": 7, "nombre": "Pastillas de Freno", "slug": "brakes"},
      "salud_actual": 60.0,
      "salud_nueva": 70.0,
      "tipo_actualizacion": "INSPECCIONA",
      "delta": 10.0
    },
    {
      "componente": {"id": 1, "nombre": "Aceite Motor", "slug": "oil"},
      "salud_actual": 12.0,
      "salud_nueva": 100.0,
      "tipo_actualizacion": "REEMPLAZA",
      "delta": 88.0
    }
  ]
}
```

## Migraciones

| App | Migración | Cambios |
|---|---|---|
| `checklists` | `0004_checklist_intencion_componente_salud` | `tipo_intencion_default` en `ChecklistTemplate`, `tipo_actualizacion` y `componente_salud_asociado` en `ChecklistItemTemplate`, `COMPONENT_HEALTH` en `ChecklistItemCatalog.TIPO_PREGUNTA_CHOICES` |
| `vehiculos` | `0024_componente_salud_anclada_inspeccion_evento` | `salud_anclada_pct` en `ComponenteSaludVehiculo`, `INSPECCION_DECLARADA` en `EventoSaludVehiculo.TIPO_EVENTO_CHOICES` |

Datos preexistentes: los `ChecklistItemTemplate` antiguos quedan con
`tipo_actualizacion=null` y `componente_salud_asociado=null`. La task usa el
fallback `tipo_intencion_default` (default `MIXTO`, mapea a `INFORMATIVO`),
por lo que no se actualizan métricas hasta que `populate_checklists_por_servicio`
corra y rellene los datos.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Migración deja templates "ciegos" | `populate_checklists_por_servicio` se ejecuta en `build.sh` antes de `collectstatic` y es idempotente |
| `mapeo_componentes` eliminado rompe checklists históricos | El refactor mantiene `procesar_checklists_historicos_vehiculo` con la misma lógica nueva (sin substring matching) y se reprocesa con `manage.py procesar_checklists_historicos` después del primer deploy |
| Ancla Weibull no se restaura tras reemplazo | El branch `REEMPLAZA` setea `salud_anclada_pct=None` explícitamente |
| `SELECT → porcentaje` no cubre todas las opciones de `opciones_seleccion` | Tabla SALUD_DESDE_SELECT acepta strings exactos; valores no mapeados quedan como `INFORMATIVO` (no afectan salud) y se loguean |
| Frontend muestra salud_actual desfasada de cache | El endpoint snapshot fuerza recálculo desde `ComponenteSaludVehiculo` (no usa cache de respuesta), evita inconsistencias durante el llenado |

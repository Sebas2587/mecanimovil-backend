# Tareas

## 1. Modelado de datos

- [ ] 1.1 Agregar `('COMPONENT_HEALTH', 'Vida útil de componente (slider 0–100%)')` a `ChecklistItemCatalog.TIPO_PREGUNTA_CHOICES`.
- [ ] 1.2 Agregar `tipo_intencion_default` a `ChecklistTemplate` con choices `REPARACION|INSPECCION|PRECOMPRA|MIXTO` (default `MIXTO`).
- [ ] 1.3 Agregar `tipo_actualizacion` (`REEMPLAZA|INSPECCIONA|INFORMATIVO`, nullable) y `componente_salud_asociado` (FK `vehiculos.ComponenteSalud`, nullable) a `ChecklistItemTemplate`.
- [ ] 1.4 Migración `checklists/migrations/0004_checklist_intencion_componente_salud.py`.
- [ ] 1.5 Agregar `salud_anclada_pct` (Float nullable) a `ComponenteSaludVehiculo`.
- [ ] 1.6 Agregar `('INSPECCION_DECLARADA', 'Inspección con porcentaje declarado')` a `EventoSaludVehiculo.TIPO_EVENTO_CHOICES`.
- [ ] 1.7 Migración `vehiculos/migrations/0024_*` con los dos campos anteriores.

## 2. HealthEngine — anclaje Weibull

- [ ] 2.1 Lógica de anclaje en `HealthEngine`: si `historial_fuente='CHECKLIST'` y `salud_anclada_pct is not None`, recalcular `km_base_efectivo` y proyectar la curva desde ahí.
- [ ] 2.2 El cap por fuente (`SALUD_MAX_POR_FUENTE`) sigue aplicando; documentar que `CHECKLIST` no tiene cap.

## 3. Refactor `actualizar_salud_desde_checklist`

- [ ] 3.1 Eliminar el dict `mapeo_componentes` y el matching por substring.
- [ ] 3.2 Iterar respuestas usando `respuesta.item_template.componente_salud_asociado` (skip si null o `tipo_actualizacion=INFORMATIVO`).
- [ ] 3.3 Resolver `tipo_actualizacion` efectivo con fallback `tipo_intencion_default → REEMPLAZA|INSPECCIONA|INFORMATIVO`.
- [ ] 3.4 Branch `REEMPLAZA`: salud=100, alerta=OPTIMO, `salud_anclada_pct=None`, `historial_fuente='CHECKLIST'`.
- [ ] 3.5 Branch `INSPECCIONA`: extraer porcentaje (slider o tabla SELECT), setear `salud_porcentaje`, `salud_anclada_pct`, `historial_fuente='CHECKLIST'`, `nivel_alerta` por umbrales (≥80 OPTIMO, ≥60 ATENCION, ≥35 URGENTE, <35 CRITICO).
- [ ] 3.6 Incluir `historial_fuente` y `salud_anclada_pct` en `bulk_update_fields`.
- [ ] 3.7 `EventoSaludVehiculo`: `SERVICIO_REALIZADO` para REEMPLAZA, `INSPECCION_DECLARADA` para INSPECCIONA.
- [ ] 3.8 Aplicar refactor equivalente a `procesar_checklists_historicos_vehiculo`.

## 4. Endpoints API

- [ ] 4.1 Nuevo endpoint `GET /api/checklists/instances/{id}/salud-snapshot/` (action en `ChecklistInstanceViewSet`).
- [ ] 4.2 Nuevo endpoint `POST /api/checklists/instances/{id}/preview-impacto/` (action en `ChecklistInstanceViewSet`).
- [ ] 4.3 Extender `ChecklistItemTemplateSerializer` con `tipo_actualizacion`, `componente_salud_asociado` (id+nombre+slug).
- [ ] 4.4 Documentar/registrar las rutas en `checklists/urls.py` (DRF router lo hace automático con `@action`).

## 5. Management command + deploy Render

- [ ] 5.1 Reescribir `populate_checklists_por_servicio.py`: tuplas extendidas `(nombre, orden, obligatorio, tipo_actualizacion, componente_slug)`.
- [ ] 5.2 Definir `tipo_intencion_default` por servicio (mapping dict).
- [ ] 5.3 Crear ítems `COMPONENT_HEALTH` por componente para los servicios INSPECCION.
- [ ] 5.4 Poblar `ComponenteSalud.servicios_asociados` (M2M) cuando aplique.
- [ ] 5.5 Agregar `python manage.py populate_checklists_por_servicio` a `build.sh`.

## 6. Frontend proveedor (mecanimovil-prov)

- [ ] 6.1 Tipos en `services/checklistService.ts`: `COMPONENT_HEALTH`, `tipo_actualizacion`, `componente_salud_asociado`, `salud_actual`, `nivel_alerta_actual`.
- [ ] 6.2 Métodos `getSaludSnapshot(instanceId)` y `getPreviewImpacto(instanceId)` en `checklistService`.
- [ ] 6.3 Renderer `COMPONENT_HEALTH` en `ChecklistItemRenderer.tsx` (slider 0–100, paso 5, label dinámica con categoría).
- [ ] 6.4 Banner "estado actual" sobre cada ítem que tenga `componente_salud_asociado`.
- [ ] 6.5 `ChecklistDiffModal.tsx` invocado desde `ChecklistContainer.tsx` antes de `finalizeChecklist`.

## 7. Frontend usuario (mecanimovil-usuarios)

- [ ] 7.1 Badge "Verificado por taller" en `VehicleHealthCard.js` cuando `historial_fuente === 'CHECKLIST'`.
- [ ] 7.2 Detalle "Inspeccionado el dd/mm/yyyy — declarado en X%" cuando `salud_anclada_pct != null`.

## 8. Calidad y cierre

- [ ] 8.1 Validar sintaxis Python (ast.parse) de archivos modificados.
- [ ] 8.2 Lints frontend (TS + JS) sin errores nuevos.
- [ ] 8.3 `openspec validate checklist-inteligente-salud --strict`.
- [ ] 8.4 `openspec archive checklist-inteligente-salud` (pipe `y`).

# Tasks: Selección Inteligente de Repuestos

## Phase 1: Extracción Estructurada con LLM

- [x] Crear módulo `extraccion_pedido_llm.py`
  - [x] Definir Pydantic models: `VehiculoExtraido`, `ServicioExtraido`, `RepuestoMencionado`, `PedidoExtraido`
  - [x] Implementar `extraer_pedido_con_llm()` con prompt estructurado
  - [x] Agregar validación con schema Pydantic
  - [x] Implementar fallback a regex si LLM falla (timeout/error/schema inválido)
  - [x] Agregar logging de uso LLM vs fallback

- [ ] Integrar extracción en flujo de cotización
  - [ ] Modificar `agente_dueno_cotizacion.py::_empezar()` para usar extracción LLM
  - [ ] Modificar `cotizacion_borrador.py::crear_cotizacion_borrador_desde_agente()` para usar resultado estructurado
  - [ ] Alimentar resultado a `_parse_servicios_solicitados()` y prompt Gemini
  - [ ] Mantener compatibilidad con flujo actual (no romper)

## Phase 2: Selección Inteligente de Casas

- [x] Crear módulo `seleccion_casa_repuestos.py`
  - [x] Definir dataclasses: `OpcionCasa`, `ResultadoSeleccion`
  - [x] Implementar `seleccionar_casa_optima()` con ponderación precio/stock/plazo
  - [x] Implementar `consolidar_si_posible()` para detectar casa única viable
  - [x] Implementar `_construir_motivo()` para texto legible al taller
  - [x] Implementar `_construir_alternativas()` para documentar opciones descartadas

- [x] Integrar selección en flujo de consulta casas
  - [x] Modificar `consulta_casas.py::_aplicar_en_cotizacion()` para invocar selección
  - [x] Acumular opciones de todas las consultas antes de decidir
  - [x] Persistir resultado en campos nuevos del repuesto JSON
  - [x] Mantener `opciones_casa` poblado para backward compatibility

## Phase 3: API Changes

- [x] Actualizar serializer de repuestos
  - [x] Agregar campo `casa_repuesto_nombre` a `RepuestoCotizacionSerializer`
  - [x] Agregar campo `motivo_seleccion`
  - [x] Agregar campo `alternativas_descartadas`
  - [x] Agregar campo `consolidacion_aplicada`
  - [x] Verificar que campos son opcionales con defaults para backward compat

- [ ] Verificar endpoints existentes
  - [ ] GET `/api/ordenes/cotizaciones-canal/{id}/` debe retornar nuevos campos
  - [ ] PATCH `/api/ordenes/cotizaciones-canal/{id}/` debe aceptar nuevos campos
  - [ ] Verificar que `opciones_casa` sigue funcionando

## Phase 4: Testing

- [x] Tests unitarios de extracción LLM
  - [x] Test: extraer filtro de aire simple
  - [x] Test: extraer pack pastillas+discos
  - [x] Test: extraer embrague completo (kit+volante+aceite)
  - [x] Test: extraer con patente y año
  - [x] Test: LLM falla → fallback a regex
  - [x] Test: validación Pydantic rechaza año inválido

- [x] Tests unitarios de selección de casas
  - [x] Test: mejor precio con stock gana
  - [x] Test: stock inmediato vs 5% más barato sin stock
  - [x] Test: consolidación viable (108% del óptimo)
  - [x] Test: consolidación no viable (120%, se distribuye)
  - [x] Test: ninguna casa con stock (elegir más barata)
  - [x] Test: motivo legible generado correctamente

- [ ] Tests de integración
  - [ ] Test: end-to-end chat → extracción → cotización → consulta → selección → API
  - [ ] Test: verificar JSON response con nuevos campos
  - [ ] Test: backward compat (frontend antiguo sigue funcionando)
  - [ ] Test: consolidación marca `consolidacion_aplicada=true` en todos los repuestos

- [ ] Ejecutar suite completa de tests
  - [ ] `python manage.py test mecanimovilapp.apps.agente_ia.tests.test_extraccion_pedido_llm`
  - [ ] `python manage.py test mecanimovilapp.apps.ordenes.tests.test_seleccion_casa_repuestos`
  - [ ] `python manage.py test mecanimovilapp.apps.ordenes.tests.test_cotizacion_canal`
  - [ ] Verificar que no hay regresiones en tests existentes

## Phase 5: Documentation & Deploy

- [ ] Actualizar documentación
  - [ ] Agregar docstrings completos a funciones nuevas
  - [ ] Documentar nuevos campos en modelo JSON de repuesto
  - [ ] Actualizar README de API con ejemplos de nuevos campos

- [ ] Preparar deployment
  - [ ] Verificar que no se requieren migraciones de BD
  - [ ] Verificar que no se requieren nuevas variables de entorno
  - [ ] Preparar plan de rollback (código es backward compatible)

- [ ] Deploy y validación
  - [ ] Commit cambios con mensaje descriptivo
  - [ ] Push a branch remoto
  - [ ] Crear PR hacia `main`
  - [ ] Esperar CI/CD pase (si existe)

## Phase 6: Validation & Archive

- [ ] Validar change con openspec CLI
  - [ ] `openspec validate agente-ia-seleccion-repuestos-inteligente`
  - [ ] Corregir errores si los hay

- [ ] Archivar change
  - [ ] `openspec archive agente-ia-seleccion-repuestos-inteligente`
  - [ ] Verificar que archived change está en `changes/archive/`

## Notes

- Priorizar Phase 1 y 2 (funcionalidad core)
- Phase 3 y 4 pueden hacerse en paralelo
- Si tests fallan, iterar en fix antes de avanzar
- Mantener backward compatibility en cada paso (no romper frontend actual)
- Logging abundante para facilitar debug en producción

# Spec delta — Fase 6 integración aprendizaje

## ADDED Requirements

### Requirement: Metadata IA en confirmación de catálogo
Al confirmar un candidato de catálogo, el cliente SHALL enviar `metadata_ia_entrada` con resumen del análisis (motor, interpretación, síntomas, IDs recomendados) y `componentes_salud`, sin persistir consultas efímeras de `analizar-necesidad`.

#### Scenario: Confirmar con análisis previo
- **WHEN** el usuario confirma proveedor desde el comparador tras analizar necesidad
- **THEN** la solicitud creada incluye `metadata_ia_entrada` no vacía
- **AND** la señal post_add de servicios registra patrones con componentes de salud si existen

### Requirement: Bootstrap de patrones históricos
Operaciones SHALL poder ejecutar `python manage.py alimentar_patrones_necesidad --limit N` para alimentar patrones desde solicitudes existentes.

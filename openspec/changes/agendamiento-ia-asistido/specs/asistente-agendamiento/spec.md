# asistente-agendamiento Specification (delta)

## ADDED Requirements

### Requirement: Análisis de necesidad sin persistencia
Las llamadas de análisis durante la creación de solicitud SHALL NOT persistir el contenido de la consulta.

#### Scenario: Múltiples consultas
- GIVEN un cliente autenticado
- WHEN envía POST analizar-necesidad varias veces
- THEN el backend responde recomendaciones
- AND no actualiza descripcion_problema en ninguna solicitud

### Requirement: Candidatos desde catálogo
El sistema SHALL devolver hasta 3 `OfertaServicio` compatibles con desglose de precios.

#### Scenario: Proveedores en zona
- GIVEN vehículo con marca y servicios seleccionados
- WHEN GET candidatos-proveedor
- THEN la respuesta tiene ≤3 ítems con precios y tipo domicilio/taller

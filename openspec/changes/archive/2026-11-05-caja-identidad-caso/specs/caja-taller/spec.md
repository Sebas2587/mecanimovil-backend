## ADDED Requirements

### Requirement: La página de caja identifica el caso sin inventar datos

Cada fila paginada de `casos` y de `movimientos` MUST incluir `cliente_nombre`, `vehiculo_patente` y `folio` tomados de datos ya guardados de una ancla de ese taller. Un valor vacío o ausente MUST ser null. El sistema MUST NOT inventar un nombre ni asignar un folio al leer. La lectura MUST resolver la página en lote, una consulta por tipo de ancla, y MUST NOT crecer con la cantidad de filas. El mecánico MUST recibir esos campos solo en anclas que ya puede leer. La respuesta MUST NOT incluir teléfono, correo ni dirección. Una ancla de otro taller MUST NOT aportar identidad.

#### Scenario: Cita con detalle y folio propio

- GIVEN una cita del taller con nombre, patente y folio guardados
- WHEN el taller lee la página de caja
- THEN el caso y el movimiento repiten ese nombre, esa patente y ese folio
- AND el teléfono del detalle no aparece

#### Scenario: Sin dato y ancla ajena

- GIVEN una cita sin folio y una cotización de otro taller
- WHEN se lee la caja
- THEN nombre, patente y folio son null
- AND un GET no escribe `numero_publico`

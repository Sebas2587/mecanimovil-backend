## ADDED Requirements

### Requirement: El nombre del servicio no es una faena extra

Si el nombre del servicio es solo un rótulo («Mantención» o «Servicio», con o sin el calificativo general, preventiva o básica) y el detalle ya nombra trabajos concretos, el sistema MUST NOT agregar ese rótulo como línea de mano de obra. Una mantención que nombra una pieza comprable MUST titularse «Cambio de» esa pieza. «Mantención con pastillas de freno» MUST quedar «Cambio de pastillas de freno». Si el pedido es solo el rótulo, MUST conservar esa única línea.

#### Scenario: Servicio Mantención y el detalle trae cuatro trabajos

- **WHEN** el nombre del servicio es «Mantención»
- **AND** el detalle es «mantención con pastillas de freno, cambio de aceite y filtro, bujías y filtro de aire»
- **AND** el modelo cotizó «Mantención» en $45.000, «Mantención con pastillas de freno» en $40.000, «Cambio de aceite y filtro» en $30.000, «Cambio de bujías» en $35.000 y «Cambio de filtro de aire» en $15.000
- **THEN** MUST haber exactamente cuatro líneas de mano de obra
- **AND** una línea MUST llamarse «Cambio de pastillas de freno»
- **AND** MUST NOT haber una línea llamada «Mantención»
- **AND** MUST NOT haber una línea llamada «Mantención con pastillas de freno»
- **AND** `mano_obra_clp` MUST ser la suma de las cuatro líneas

#### Scenario: Solo el rótulo

- **WHEN** el pedido es únicamente «Mantención» y no hay otro trabajo
- **THEN** MUST quedar una línea de mano de obra

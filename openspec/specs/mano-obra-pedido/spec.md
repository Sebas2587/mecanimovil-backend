# mano-obra-pedido Specification

## Purpose
TBD - created by archiving change quote-208-labor-branch-notes. Update Purpose after archive.
## Requirements
### Requirement: Cada trabajo pedido tiene mano de obra

Si el taller pide varios trabajos en una frase que empieza por un verbo de cambio, el sistema MUST crear una línea de mano de obra por cada trabajo, aunque los siguientes no repitan el verbo. «Aceite y filtro de aceite» MUST ser una sola faena. MUST NOT omitir el cambio de bujías ni el de aceite y filtro cuando vienen en esa lista. Cada faena pedida MUST tener un monto mayor que cero. El sistema MUST tomar ese monto de la tarifa del taller para ese servicio cuando existe, y si no, de la tarifa por hora configurada por las horas estándar de la faena cuando existe. Si no hay ninguna de las dos, MUST usar el estimado del modelo para esa faena. Si el modelo entrega un total que cubre menos faenas, MUST recalcular las que faltan y MUST NOT dejarlas en cero ni forzarlas a que la suma calce con ese total. `mano_obra_clp` MUST ser la suma de las faenas.

#### Scenario: Pastillas, aceite y filtro, bujías y filtro de aire

- **WHEN** el pedido es «Cambio de pastillas de freno delanteras, aceite y filtro de aceite, bujías y filtro de aire»
- **AND** el modelo solo cotizó $35.000 de pastillas y $15.000 de filtro de aire, con un total de $50.000
- **AND** el taller no tiene tarifa ni hora para esas faenas
- **THEN** las cuatro líneas MUST tener un monto mayor que cero
- **AND** pastillas MUST quedar en $35.000 y el filtro de aire en $15.000
- **AND** el cambio de aceite y el de bujías MUST recalcularse
- **AND** `mano_obra_clp` MUST ser la suma de las cuatro líneas

#### Scenario: La tarifa del taller gana al modelo

- **WHEN** el taller tiene tarifa de mano de obra para el cambio de aceite y filtro
- **AND** el modelo no cotizó esa faena
- **THEN** esa línea MUST usar la tarifa del taller
- **AND** MUST NOT quedar en cero


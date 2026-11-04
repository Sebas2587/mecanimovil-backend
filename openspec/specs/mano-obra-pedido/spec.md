# mano-obra-pedido Specification

## Purpose
TBD - created by archiving change quote-208-labor-branch-notes. Update Purpose after archive.
## Requirements
### Requirement: Cada trabajo pedido tiene mano de obra

Si el taller pide varios trabajos en una frase que empieza por un verbo de cambio, el sistema MUST crear una línea de mano de obra por cada trabajo, aunque los siguientes no repitan el verbo. «Aceite y filtro de aceite» MUST ser una sola faena. MUST NOT omitir el cambio de bujías ni el de aceite y filtro cuando vienen en esa lista.

#### Scenario: Pastillas, aceite y filtro, bujías y filtro de aire

- **WHEN** el pedido es «Cambio de pastillas de freno delanteras, aceite y filtro de aceite, bujías y filtro de aire»
- **AND** el modelo solo cotizó mano de obra de pastillas y de filtro de aire
- **THEN** las líneas de mano de obra MUST incluir el cambio de pastillas, el cambio de aceite y filtro de aceite, el cambio de bujías y el cambio de filtro de aire


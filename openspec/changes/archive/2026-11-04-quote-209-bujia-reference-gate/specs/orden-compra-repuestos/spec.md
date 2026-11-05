## MODIFIED Requirements

### Requirement: Orden de compra de repuestos

El taller **MUST** poder descargar un PDF «Orden de compra de repuestos» de una cotización propia. El PDF **MUST** incluir el nombre del taller, la fecha, el vehículo (patente, marca, modelo, año, motor y VIN cuando existen), las piezas con cantidad y especificación (viscosidad, tipo o referencia OEM si está), la casa sugerida agrupada con dirección y teléfono, y el precio de referencia. **MUST NOT** incluir mano de obra ni el precio o margen que ve el cliente. Una casa con precio a consultar **MUST** decir «A consultar» y **MUST NOT** mostrar un monto como si fuera el de esa casa. El PDF **MUST** imprimir una referencia de otra tienda solo cuando ese monto pasó las mismas compuertas de modelo, año, motor y banda que una ficha elegida, y **MUST** mostrarlo por unidad. Si no pasa, el PDF **MUST NOT** citar esa tienda ni ese monto.

#### Scenario: El PDF sale sin mano de obra

- GIVEN una cotización con repuestos y mano de obra
- WHEN el taller pide el PDF de compra
- THEN la respuesta **SHALL** ser un PDF
- AND **SHALL** nombrar el taller, la patente y la pieza
- AND **SHALL NOT** incluir la mano de obra ni un margen al cliente

#### Scenario: Precio a consultar

- GIVEN una línea recomendada a Indra con precio a consultar y una referencia de otra tienda que pasó las compuertas
- WHEN se arma el PDF
- THEN el precio de Indra **SHALL** decir «A consultar»
- AND **SHALL NOT** imprimir la referencia como precio de Indra

#### Scenario: Referencia de bujía fuera de banda

- **GIVEN** bujías a consultar con una referencia guardada de Lider a $28.432 y banda por unidad de $8.000–$12.000
- **WHEN** se arma el PDF
- **THEN** el texto MUST NOT contener «28.432» ni «Lider»

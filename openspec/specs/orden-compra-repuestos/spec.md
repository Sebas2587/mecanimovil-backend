# orden-compra-repuestos Specification

## Purpose
TBD - created by archiving change taller-specialist-houses. Update Purpose after archive.
## Requirements
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

### Requirement: El PDF usa la sucursal del taller

Al generar la orden de compra, el sistema MUST imprimir la sucursal de la casa que corresponde a la dirección configurada del taller, aunque la línea hubiera guardado otra sucursal. Si la dirección solo nombra Santiago, MUST imprimir la primera sucursal de Santiago y MUST NOT imprimir una sucursal posterior de la misma comuna.

#### Scenario: Taller en La Florida

- **GIVEN** una cotización cuya línea dice Lira 664
- **AND** el taller está configurado en John Kennedy 709, La Florida
- **WHEN** se genera el PDF
- **THEN** el texto MUST incluir Av. Vicuña Mackenna 8580, La Florida
- **AND** MUST NOT usar Lira 664 como sucursal de esa orden

#### Scenario: Santiago sin comuna específica

- **GIVEN** la dirección configurada nombra Santiago y no nombra La Florida
- **AND** la línea guardó Avenida Brasil 28
- **WHEN** se genera el PDF
- **THEN** el texto MUST incluir Lira 664, Santiago
- **AND** MUST NOT incluir Avenida Brasil 28


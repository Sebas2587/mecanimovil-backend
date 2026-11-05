## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: El historial del taller no es una casa

El historial del taller es un precio de referencia, no una tienda. El sistema MUST NOT usar «Historial del taller» como `casa_repuesto_nombre` ni como grupo del PDF de compra. La pieza cuyo precio sale del historial MUST agruparse bajo la casa especialista de la marca, con la sucursal que corresponde al taller. El PDF MUST NOT imprimir esa sucursal dos veces. Si el unitario del historial es mayor que cero, la nota y el PDF MUST incluir «Referencia: historial del taller» seguido de ese monto, y el precio de la casa MUST decir «A consultar». El unitario de la cotización y el total MUST NOT cambiar por este reagrupado.

#### Scenario: Pastillas con precio de historial en un Fiat

- **WHEN** las pastillas tienen `fuente_marketplace` historial, proveedor «Historial del taller» y unitario $40.000
- **AND** la marca es Fiat y la especialista es Indra
- **THEN** `casa_repuesto_nombre` MUST ser Indra
- **AND** MUST NOT ser «Historial del taller»
- **AND** la nota MUST incluir «Referencia: historial del taller $40.000»
- **AND** el unitario MUST seguir en $40.000

#### Scenario: El PDF no duplica la sucursal

- **GIVEN** pastillas cuyo proveedor guardado es «Historial del taller» y el resto de las piezas en Indra
- **AND** el taller está en La Florida
- **WHEN** se genera el PDF de compra
- **THEN** el texto MUST NOT usar «Historial del taller» como título de grupo
- **AND** las pastillas MUST quedar bajo Indra
- **AND** la dirección de la sucursal MUST aparecer una sola vez
- **AND** el precio de las pastillas MUST decir «A consultar» y «Referencia: historial del taller»

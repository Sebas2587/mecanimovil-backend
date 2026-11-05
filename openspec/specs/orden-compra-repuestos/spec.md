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

### Requirement: La orden de compra es un documento del taller

El PDF de orden de compra MUST presentarse como documento: encabezado con la identidad del taller (logo si `foto_perfil` se puede leer; si no, iniciales; nombre; dirección, teléfono, RUT y correo solo cuando existen), el título «Orden de compra de repuestos», la fecha y el número de cotización, y un recuadro del vehículo con patente, marca, modelo, año, motor y VIN cuando existen. Cada casa MUST ir en una sección separada con su nombre, la insignia de especialista cuando la casa lo es para la marca, la sucursal, el teléfono y el horario solo si está registrado. La sección MUST incluir una tabla con las columnas #, repuesto, especificación o marca, cantidad y referencia. La referencia MUST nombrar la tienda y el monto verificado, y MUST enlazar la ficha del producto cuando hay URL. El PDF MUST numerar las páginas y MUST cerrar con «No incluye mano de obra ni el valor cobrado al cliente.». MUST NOT incluir mano de obra ni el total cobrado al cliente. MUST NOT inventar un horario.

#### Scenario: Encabezado, vehículo y tabla

- **GIVEN** un taller con nombre, dirección, teléfono, RUT y correo
- **AND** una cotización con patente, marca, modelo, año, motor, VIN y dos casas
- **WHEN** se genera el PDF
- **THEN** el texto MUST incluir «Orden de compra de repuestos», el nombre del taller, la patente y el número de cotización
- **AND** MUST incluir las columnas de la tabla
- **AND** MUST incluir «No incluye mano de obra ni el valor cobrado al cliente.»
- **AND** MUST NOT incluir el monto de mano de obra ni el total del cliente

#### Scenario: Ficha con enlace

- **GIVEN** una línea con URL de producto http(s) y un precio de referencia que pasó las compuertas
- **WHEN** se genera el PDF
- **THEN** el PDF MUST contener un enlace a esa URL
- **AND** el texto MUST nombrar la tienda y el monto

#### Scenario: Sin horario no se inventa

- **GIVEN** una casa sin horario en el perfil ni en la línea
- **WHEN** se genera el PDF
- **THEN** el texto MUST NOT incluir un horario de esa casa

### Requirement: La cotización del taller expone la ficha verificada

Cada repuesto de la respuesta de cotización del taller MUST incluir `url_referencia` (string), `tienda_referencia` (string) y `precio_verificado_clp` (entero o null). Si hay una ficha http(s) con camino y un monto que pasó las compuertas, `url_referencia` MUST ser esa URL, `tienda_referencia` MUST ser la tienda y `precio_verificado_clp` MUST ser el monto por unidad. Si no hay ficha verificada, `url_referencia` y `tienda_referencia` MUST ser vacíos y `precio_verificado_clp` MUST ser null. El historial del taller MUST NOT llenar esos campos. La vista pública del cliente MUST NOT incluir `url_referencia`, `tienda_referencia` ni `precio_verificado_clp`.

#### Scenario: Ficha web en la API del taller

- **WHEN** el taller lee una cotización cuya línea tiene `url_producto` de una ficha y un precio verificado
- **THEN** `url_referencia` MUST ser esa URL
- **AND** `tienda_referencia` MUST ser la tienda
- **AND** `precio_verificado_clp` MUST ser ese monto

#### Scenario: Sin ficha

- **WHEN** la línea no tiene URL de producto
- **THEN** `url_referencia` MUST ser vacío
- **AND** `precio_verificado_clp` MUST ser null

#### Scenario: El cliente no recibe la ficha

- **WHEN** se arma la vista pública del cliente
- **THEN** el repuesto MUST NOT incluir `url_referencia` ni `tienda_referencia` ni `precio_verificado_clp`

### Requirement: La dirección del taller no repite partes

El encabezado de la orden de compra MUST armar la dirección del taller sin repetir el número, la comuna ni la ciudad. La comparación MUST ser por trozo y MUST ignorar mayúsculas y espacios de más. Si el número ya está en la calle, MUST NOT imprimirse otra vez. La calle y el número MUST quedar juntos («John Kennedy 709»). Una ciudad repetida, incluso cuando la región es la misma ciudad, MUST aparecer una sola vez.

#### Scenario: Número y ciudad duplicados

- **GIVEN** la calle guardada es «John Kennedy, 709, La Florida, Santiago, Santiago»
- **AND** el número es 709 y la comuna es La Florida
- **WHEN** se genera el PDF de compra
- **THEN** el encabezado MUST incluir «John Kennedy 709, La Florida, Santiago»
- **AND** MUST NOT incluir «709, 709» ni «Santiago, Santiago»

#### Scenario: La comuna ya va en la calle

- **GIVEN** la calle es «John Kennedy 709, La Florida» y la comuna guardada es «la florida»
- **WHEN** se genera el PDF de compra
- **THEN** «La Florida» MUST aparecer una sola vez en la dirección del taller


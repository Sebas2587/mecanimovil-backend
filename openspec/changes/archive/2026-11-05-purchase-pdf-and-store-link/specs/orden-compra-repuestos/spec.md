## ADDED Requirements

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

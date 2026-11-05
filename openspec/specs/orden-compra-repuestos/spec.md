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

### Requirement: La ficha y la casa sugerida no se mezclan

`url_referencia`, `tienda_referencia` y `precio_verificado_clp` MUST describir la misma ficha. `tienda_referencia` MUST ser la tienda de ese enlace. La casa recomendada para comprar MUST ir en `casa_sugerida`. Si el enlace no es de esa casa, `precio_verificado_en_casa` MUST ser falso y `nota_referencia` MUST decir que el precio es referencial de la tienda del enlace y que no está verificado en la casa sugerida. El historial del taller MUST NOT llenar la ficha. La búsqueda MUST consultar primero el sitio de la casa sugerida cuando esa casa publica catálogo, y MUST usar otra tienda solo si ahí no hay una ficha con precio. El PDF agrupado por casa MUST nombrar la tienda del enlace y MUST NOT presentar ese enlace como precio de la casa.

#### Scenario: Berlingo con ficha de otra tienda

- **GIVEN** una línea cuya casa sugerida es Adriazola y cuya ficha es de TodoAuto
- **WHEN** el taller lee la cotización
- **THEN** `tienda_referencia` MUST ser TodoAuto
- **AND** `url_referencia` MUST ser el enlace de TodoAuto
- **AND** `precio_verificado_clp` MUST ser el monto de esa ficha
- **AND** `casa_sugerida` MUST ser Adriazola
- **AND** `nota_referencia` MUST incluir «no verificado en Adriazola»

#### Scenario: El PDF no presta el enlace

- **GIVEN** la misma línea en el PDF de compra, agrupada en Adriazola
- **WHEN** se genera el PDF
- **THEN** el texto MUST nombrar TodoAuto junto al monto
- **AND** el enlace MUST apuntar a TodoAuto
- **AND** MUST NOT tratar ese enlace como ficha de Adriazola

### Requirement: El taller ve la ganancia de los repuestos

Cada repuesto de la API del taller MUST incluir `costo_unitario_clp`, `precio_cobrado_clp`, `margen_clp` y `margen_pct`. La cotización MUST incluir `costo_total_repuestos_clp`, `cobrado_total_repuestos_clp`, `ganancia_repuestos_clp` y `margen_repuestos_pct`. Esos campos MUST recalcularse cuando cambia el precio cobrado. La vista pública del cliente MUST NOT incluirlos. `margen_clp` MUST ser la diferencia por la cantidad de la línea. `margen_pct` MUST ser el porcentaje de esa diferencia sobre el precio cobrado.

#### Scenario: El taller sube el precio cobrado

- **GIVEN** un repuesto con costo 5.000 y cantidad 2
- **WHEN** el precio cobrado pasa a 8.000
- **THEN** `margen_clp` MUST ser 6.000
- **AND** `margen_pct` MUST ser 37.5
- **AND** la ganancia de la cotización MUST incluir esos 6.000

#### Scenario: El cliente no ve el margen

- **WHEN** se arma la vista pública
- **THEN** el repuesto MUST NOT incluir `margen_clp`, `margen_pct`, `costo_unitario_clp` ni `casa_sugerida`

### Requirement: Cada repuesto se valida antes de salir

La respuesta del taller MUST validar cada repuesto antes de devolverlo. El detalle `GET /api/ordenes/cotizaciones-canal/{id}/` MUST usar esa misma respuesta. MUST interpretar el título de la ficha (`x4`, `juego`, `kit`, `set`, y un bidón de aceite en litros) y MUST usar ese precio por unidad de la línea en el costo, en el precio verificado y en el precio cobrado. Un monto que ya es el precio cobrado por unidad MUST NOT partirse otra vez porque el título diga pack. Una ficha de otro año, otro motor u otro modelo MUST NOT citarse. Una ficha del mismo auto, cuyo precio por unidad calza con el cobrado, MUST citarse con `url_referencia`, `tienda_referencia` y `precio_verificado_clp` aunque la banda guardada en la línea sea el precio del pack. Si ninguna ficha calza, `validacion_estado` MUST ser `sin_referencia_valida`. Si el costo y el cobrado siguen sin calzar, `validacion_estado` MUST ser `requiere_revision` y `margen_pct` MUST NOT ser menor a −100 por haber cotizado el pack como unidad. Si no hay ficha y el precio es asumido, `validacion_estado` MUST ser `asumido` y `validacion_motivo` MUST decir por qué. Una ficha válida MUST reemplazar un precio asumido. Cada línea MUST incluir `validacion_estado`, `validacion_motivo` y `alertas`. `casa_sugerida` MUST llenarse con la casa de la línea o con la especialista de la marca. La cotización MUST incluir `alertas_validacion`. La vista pública del cliente MUST NOT incluir esos campos.

#### Scenario: Pack x4 de bujías Champion

- **GIVEN** un Fiat Bravo 1.4 T-Jet y una línea de 4 bujías cuya ficha Entretuercas dice x4 a $15.826 y el precio cobrado por unidad es $3.956
- **WHEN** el taller lee la cotización
- **THEN** `precio_verificado_clp` y `costo_unitario_clp` MUST ser el precio de una bujía
- **AND** `url_referencia` MUST ser la ficha
- **AND** `tienda_referencia` MUST nombrar Entretuercas
- **AND** `casa_sugerida` MUST ser Indra
- **AND** `margen_pct` MUST ser mayor o igual a −100
- **AND** `alertas` MUST explicar que la ficha es un juego

#### Scenario: La banda de la línea es el pack

- **GIVEN** la ficha Entretuercas «Bujía Iridio Champion Fiat Bravo 1.4 2007-2014 x4» a $15.826, cantidad 4, cobrado $3.956 y una banda de $15.000 a $25.000
- **WHEN** el taller pide `GET /api/ordenes/cotizaciones-canal/{id}/`
- **THEN** `url_referencia` MUST ser esa ficha
- **AND** `tienda_referencia` MUST nombrar Entretuercas
- **AND** `precio_verificado_clp` MUST ser 3956
- **AND** `validacion_estado` MUST ser `ok`
- **AND** `alertas_validacion` MUST incluir esa línea

#### Scenario: La ficha es de otros años

- **GIVEN** la misma línea con una ficha que dice 1995-2001
- **WHEN** el taller lee la cotización
- **THEN** `validacion_estado` MUST ser `sin_referencia_valida`
- **AND** `url_referencia` MUST ser vacío
- **AND** `precio_verificado_clp` MUST ser null

#### Scenario: Precio asumido sin ficha

- **GIVEN** un filtro de aire de un Fiat sin casa y sin ficha, con precio asumido
- **WHEN** el taller lee la cotización
- **THEN** `casa_sugerida` MUST ser Indra
- **AND** `validacion_estado` MUST ser `asumido`
- **AND** `validacion_motivo` MUST decir que no hay ficha

#### Scenario: El cliente no ve la validación

- **WHEN** se arma la vista pública
- **THEN** el repuesto MUST NOT incluir `validacion_estado`, `validacion_motivo` ni `alertas`


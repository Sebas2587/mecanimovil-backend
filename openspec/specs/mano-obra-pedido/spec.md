# mano-obra-pedido Specification

## Purpose
TBD - created by archiving change quote-208-labor-branch-notes. Update Purpose after archive.
## Requirements
### Requirement: Cada trabajo pedido tiene mano de obra

Si el taller pide varios trabajos en una frase que empieza por un verbo de cambio, el sistema MUST crear una línea de mano de obra por cada trabajo, aunque los siguientes no repitan el verbo. «Aceite y filtro de aceite» MUST ser una sola faena. MUST NOT omitir el cambio de bujías ni el de aceite y filtro cuando vienen en esa lista. Cada faena pedida MUST tener un monto mayor que cero. El sistema MUST tomar ese monto de la tarifa del taller para ese servicio cuando existe, y si no, de la tarifa por hora configurada por las horas estándar de la faena cuando existe. Si no hay ninguna de las dos, MUST usar el estimado del modelo para esa faena. Si el modelo entrega un total que cubre menos faenas, MUST recalcular las que faltan y MUST NOT dejarlas en cero ni forzarlas a que la suma calce con ese total. `mano_obra_clp` MUST ser la suma de las faenas. El mismo trabajo escrito dos veces (la salida del modelo y el lector del pedido, o la descripción que repite el pedido) MUST quedar en una sola línea y MUST NOT sumar los dos precios. «Mantención con pastillas» y «Cambio de pastillas» son ese mismo trabajo.

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

#### Scenario: La descripción repite el pedido

- **WHEN** el pedido es «mantención con pastillas de freno, cambio de aceite y filtro, bujías y filtro de aire»
- **AND** la descripción repite «Cambio de pastillas de freno, cambio de aceite y filtro de aceite, cambio de bujías y cambio de filtro de aire»
- **AND** el modelo cotizó esas cuatro faenas en $45.000, $30.000, $30.000 y $15.000
- **THEN** MUST haber cuatro líneas de mano de obra
- **AND** `mano_obra_clp` MUST ser $120.000
- **AND** MUST NOT haber una segunda línea de bujías ni de filtro de aire

### Requirement: La pieza de la mantención no desaparece

Si el pedido nombra una pieza dentro de la mantención, el sistema MUST dejar esa línea de repuesto aunque ninguna tienda pase las compuertas de modelo, año, motor o banda. La búsqueda web MUST NOT borrar la línea cuando descarta un hit. El PDF de compra MUST seguir nombrando esa pieza.

#### Scenario: Mantención con pastillas

- **WHEN** el pedido es «mantención con pastillas de freno, cambio de aceite y filtro, bujías y filtro de aire»
- **THEN** los repuestos MUST incluir pastillas de freno

#### Scenario: Un hit que no pasa no borra la pastilla

- **GIVEN** una línea «Pastillas de freno» de un Fiat Bravo 2010
- **AND** la búsqueda devuelve una ficha de otro año que no pasa la compuerta
- **WHEN** termina la tarea de búsqueda
- **THEN** la línea MUST seguir en los repuestos
- **AND** el PDF MUST nombrar las pastillas


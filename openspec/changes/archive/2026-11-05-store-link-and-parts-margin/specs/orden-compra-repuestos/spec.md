## ADDED Requirements

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

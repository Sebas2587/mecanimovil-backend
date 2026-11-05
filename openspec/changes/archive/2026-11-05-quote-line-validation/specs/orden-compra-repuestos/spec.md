## ADDED Requirements

### Requirement: Cada repuesto se valida antes de salir

La respuesta del taller MUST validar cada repuesto antes de devolverlo. MUST interpretar el título de la ficha (`x4`, `juego`, `kit`, `set`, y un bidón de aceite en litros) y MUST usar ese precio por unidad de la línea en el costo, en el precio verificado y en el precio cobrado. Una ficha de otro año, otro motor u otro modelo MUST NOT citarse. Si ninguna ficha calza, `validacion_estado` MUST ser `sin_referencia_valida`. Si el costo y el cobrado siguen sin calzar, `validacion_estado` MUST ser `requiere_revision` y `margen_pct` MUST NOT ser menor a −100 por haber cotizado el pack como unidad. Si no hay ficha y el precio es asumido, `validacion_estado` MUST ser `asumido` y `validacion_motivo` MUST decir por qué. Una ficha válida MUST reemplazar un precio asumido. Cada línea MUST incluir `validacion_estado`, `validacion_motivo` y `alertas`. `casa_sugerida` MUST llenarse con la casa de la línea o con la especialista de la marca. La cotización MUST incluir `alertas_validacion`. La vista pública del cliente MUST NOT incluir esos campos.

#### Scenario: Pack x4 de bujías Champion

- **GIVEN** un Fiat Bravo 1.4 T-Jet y una línea de 4 bujías cuya ficha Entretuercas dice x4 a $15.826 y el precio cobrado por unidad es $3.956
- **WHEN** el taller lee la cotización
- **THEN** `precio_verificado_clp` y `costo_unitario_clp` MUST ser el precio de una bujía
- **AND** `url_referencia` MUST ser la ficha
- **AND** `tienda_referencia` MUST nombrar Entretuercas
- **AND** `casa_sugerida` MUST ser Indra
- **AND** `margen_pct` MUST ser mayor o igual a −100
- **AND** `alertas` MUST explicar que la ficha es un juego

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

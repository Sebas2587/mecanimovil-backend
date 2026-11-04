## MODIFIED Requirements

### Requirement: La especialista no sube la bujía asumida

Sin ficha de tienda que haya pasado las compuertas, el precio unitario asumido de las bujías MUST NOT superar el techo por unidad de la banda de esa línea. Recomendar la casa especialista MUST NOT cambiar ese unitario y MUST NOT conservar una referencia cuyo monto no pasó las mismas compuertas o no es el precio por unidad.

#### Scenario: Iridio sobre el techo

- **GIVEN** bujías sin tienda, cantidad 4, unitario $15.000 y banda $8.000–$11.250
- **WHEN** se deja el precio asumido y se recomienda Indra
- **THEN** el unitario MUST ser $11.250
- **AND** MUST NOT quedar en $15.000

#### Scenario: Referencia de estante no se conserva

- **GIVEN** bujías sin tienda, unitario asumido $12.000, banda $8.000–$12.000 y una referencia guardada de Lider a $28.432
- **WHEN** se recomienda Indra
- **THEN** la línea MUST NOT guardar `precio_referencia_clp` en 28432
- **AND** el unitario MUST seguir en $12.000

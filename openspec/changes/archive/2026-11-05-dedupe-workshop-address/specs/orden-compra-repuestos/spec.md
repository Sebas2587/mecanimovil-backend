## ADDED Requirements

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

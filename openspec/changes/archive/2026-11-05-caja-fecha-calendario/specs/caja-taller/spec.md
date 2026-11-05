## ADDED Requirements

### Requirement: Una fecha imposible no crea un cobro

El POST de un cobro manual MUST responder 400 `fecha_invalida` cuando `fecha_efectiva` no existe en el calendario. MUST NOT crear un movimiento. La respuesta MUST NOT ser 500.

#### Scenario: 30 de febrero

- GIVEN `fecha_efectiva` `2026-02-30`
- WHEN el taller envía el cobro
- THEN la respuesta es 400 `fecha_invalida`
- AND el libro no tiene una fila nueva

## ADDED Requirements

### Requirement: La nota explica la casa y el origen no muestra el slug

La nota visible **MUST** decir por qué se eligió la casa, en a lo más 160 caracteres. Donde se muestra el origen del precio, el nombre **MUST** ser el de la casa y **MUST NOT** ser el slug del dominio.

#### Scenario: Especialista con todo el pedido

- GIVEN una cotización Fiat cuyas piezas quedan en Indra
- WHEN se escribe la nota
- THEN `motivo_seleccion` **SHALL** ser «Indra: especialista Fiat, tiene todos los repuestos de esta cotización.»
- AND **SHALL** medir a lo más 160 caracteres

#### Scenario: Origen sin slug

- GIVEN una ficha cuya tienda llega como «Todoautochile»
- WHEN se arma la línea de origen del precio
- THEN el nombre visible **SHALL** ser «TodoAuto»
- AND **SHALL NOT** contener «Todoautochile»

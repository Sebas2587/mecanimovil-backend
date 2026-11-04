## MODIFIED Requirements

### Requirement: La nota explica la casa y el origen no muestra el slug

La nota visible MUST decir por qué se eligió la casa, en a lo más 160 caracteres. Donde se muestra el origen del precio, el nombre MUST ser el de la casa y MUST NOT ser el slug del dominio. Si la especialista no tiene ficha, la nota MUST pedir consultar disponibilidad y precio y MUST incluir la referencia de la tienda validada de esa línea. MUST NOT decir que tiene todos los repuestos si el stock no está verificado en cada línea. Una nota ya guardada con esa frase vieja MUST reescribirse al leer la cotización y al terminar la búsqueda web asíncrona. La marca en la nota MUST ir en título.

#### Scenario: Especialista con todo el pedido verificado

- **GIVEN** una cotización Fiat cuyas piezas tienen ficha con precio en Indra
- **WHEN** se escribe la nota
- **THEN** `motivo_seleccion` SHALL ser «Indra: especialista Fiat, tiene todos los repuestos de esta cotización.»
- **AND** SHALL medir a lo más 160 caracteres

#### Scenario: Sin ficha, cada línea conserva su referencia

- **GIVEN** pastillas de un Fiat con precio validado en Lider por $21.390 y sin ficha de Indra
- **WHEN** se recomienda Indra
- **THEN** la nota SHALL ser «Indra (especialista Fiat): consulta disponibilidad y precio. Referencia: Lider $21.390.»
- **AND** SHALL medir a lo más 160 caracteres

#### Scenario: La frase vieja se reescribe al leer y en la tarea

- **GIVEN** una línea guardada con «Indra: especialista FIAT, tiene todos los repuestos. Precio a consultar.»
- **AND** la referencia de esa línea es Lider por $21.390
- **WHEN** la tarea de búsqueda web termina o el taller vuelve a leer la cotización
- **THEN** `motivo_seleccion` SHALL ser «Indra (especialista Fiat): consulta disponibilidad y precio. Referencia: Lider $21.390.»
- **AND** SHALL NOT contener «tiene todos»
- **AND** SHALL NOT contener «FIAT»

#### Scenario: Origen sin slug

- **GIVEN** una ficha cuya tienda llega como «Todoautochile»
- **WHEN** se arma la línea de origen del precio
- **THEN** el nombre visible SHALL ser «TodoAuto»
- **AND** SHALL NOT contener «Todoautochile»

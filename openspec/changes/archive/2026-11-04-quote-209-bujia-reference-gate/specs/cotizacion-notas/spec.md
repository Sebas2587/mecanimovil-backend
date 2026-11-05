## MODIFIED Requirements

### Requirement: La nota explica la casa y el origen no muestra el slug

La nota visible MUST decir por qué se eligió la casa, en a lo más 160 caracteres. Donde se muestra el origen del precio, el nombre MUST ser el de la casa y MUST NOT ser el slug del dominio. Si la especialista no tiene ficha, la nota MUST pedir consultar disponibilidad y precio. La referencia de otra tienda MUST incluirse solo cuando ese monto pasó las mismas compuertas de modelo, año, motor y banda que una ficha elegida, y MUST ser el precio por unidad. Si no pasa, la nota MUST NOT citarla. MUST NOT decir que tiene todos los repuestos si el stock no está verificado en cada línea. Una nota ya guardada con esa frase vieja, o con una referencia que ya no pasa, MUST reescribirse al leer la cotización y al terminar la búsqueda web asíncrona. La marca en la nota MUST ir en título.

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

#### Scenario: Bujía fuera de banda no se cita

- **GIVEN** bujías de un Fiat Bravo 2010 1.4 T-Jet, banda $8.000–$12.000 por unidad, sin tienda y con precio asumido de $12.000
- **AND** una ficha de Lider a $28.432 cuyo título no dice que es un juego
- **WHEN** la búsqueda web termina o se vuelve a leer la cotización
- **THEN** la nota MUST NOT contener «28.432» ni «Referencia: Lider»
- **AND** el unitario MUST seguir en $12.000

#### Scenario: El juego de bujías se cita por unidad

- **GIVEN** la misma banda y un juego de 4 bujías Fiat Bravo 1.4 T-Jet a $36.000 que pasa modelo, año y motor
- **WHEN** se cita esa referencia
- **THEN** el monto citado MUST ser $9.000
- **AND** MUST NOT citar $36.000

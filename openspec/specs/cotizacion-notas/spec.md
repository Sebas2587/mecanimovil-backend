# cotizacion-notas Specification

## Purpose
TBD - created by archiving change short-mechanic-notes. Update Purpose after archive.
## Requirements
### Requirement: Nota visible corta

Cada línea de repuesto que deja el agente de cotización **MUST** guardar en `motivo_seleccion` una nota en español de a lo más 160 caracteres. La nota **MUST NOT** incluir códigos internos (`anio_incompatible`, `precio_bajo_banda`), URLs, la lista de búsquedas ni títulos rechazados repetidos.

#### Scenario: Hay tienda

- GIVEN una ficha de Lider compatible con un Fiat Bravo 1.4 T-Jet
- WHEN la línea queda con esa casa
- THEN `motivo_seleccion` **SHALL** ser «Lider: compatible con Fiat Bravo 1.4 T-Jet, mejor precio encontrado.»

#### Scenario: No hay tienda

- GIVEN que ninguna ficha sirve para un Bravo 1.4 T-Jet 2010
- WHEN la línea se guarda sin casa
- THEN `motivo_seleccion` **SHALL** empezar con «Precio estimado. No encontramos este repuesto para tu auto (Bravo 1.4 T-Jet 2010)»
- AND **SHALL** pedir confirmar precio y tienda

#### Scenario: Precio de oferta

- GIVEN una ficha de TodoAuto que cobra menos que el precio tachado de $10.990
- WHEN la línea usa ese precio
- THEN `motivo_seleccion` **SHALL** ser «TodoAuto, precio en oferta (normal $10.990).»

#### Scenario: Un solo porqué

- GIVEN títulos descartados por año o por modelo
- WHEN se arma la nota sin tienda
- THEN la nota **MAY** agregar una sola frase «Lo encontrado era para otro año o modelo.»
- AND **MUST NOT** listar cada título

### Requirement: El detalle técnico no sale en la nota

El mismo rechazo **MUST** seguir en el log con el título y el motivo interno. La descripción de la pieza en `comentario` (juego, litros, viscosidad) **MUST NOT** reemplazarse por la nota de búsqueda.

#### Scenario: Log conserva el rechazo

- GIVEN un título de Linea 2013-2017 rechazado para un Bravo 2010
- WHEN la búsqueda no elige ficha
- THEN el log **SHALL** incluir el título y `anio_incompatible`
- AND `motivo_seleccion` **SHALL NOT** incluir ese título ni el código

### Requirement: Ningún campo visible repite la nota larga

El payload de cada repuesto que ve el taller o el cliente **MUST NOT** incluir, en ningún texto visible de la línea, las frases «Se buscó», «Sin ficha de», «cubre otros años», «nombra otro motor» ni «Única casa con stock». `motivo_seleccion` y un `comentario` que sea nota **MUST** medir a lo más 160 caracteres. El detalle de títulos y consultas **MUST** quedar solo en el log.

#### Scenario: La tarea async cierra sin tienda

- GIVEN una búsqueda que no elige ficha y un aviso con el párrafo largo de títulos
- WHEN termina `buscar_precios_web_cotizacion_task`, incluida la consulta de casas que corre después
- THEN ningún texto visible del repuesto guardado **SHALL** contener esas frases
- AND `motivo_seleccion` **SHALL** empezar con «Precio estimado.»

#### Scenario: Una cotización ya guardada se vuelve a leer

- GIVEN una línea guardada con el párrafo largo en `motivo_seleccion`
- WHEN el taller pide la cotización
- THEN la respuesta **SHALL** traer la nota corta
- AND **SHALL NOT** devolver el párrafo largo

### Requirement: La tienda se nombra como la conoce el taller

Si la ficha es de un dominio conocido, la nota y `casa_repuesto_nombre` **MUST** usar el nombre de la casa, no el dominio en una sola palabra.

#### Scenario: Comercial Ramírez

- GIVEN una ficha cuya tienda llega como «Comercialramirezspa»
- WHEN la línea queda con esa casa
- THEN `motivo_seleccion` **SHALL** ser «Comercial Ramírez: compatible con Fiat Bravo 1.4 T-Jet, mejor precio encontrado.» cuando el auto es un Fiat Bravo 1.4 T-Jet
- AND `casa_repuesto_nombre` **SHALL** ser «Comercial Ramírez»

#### Scenario: La casa responde por el canal

- GIVEN una respuesta de casa con precio que el selector resume como «Única casa con stock disponible»
- WHEN esa respuesta se escribe en la línea
- THEN `motivo_seleccion` **SHALL** usar la frase corta con el nombre de la casa
- AND **SHALL NOT** copiar el motivo interno del selector

### Requirement: El slug de la tienda no se muestra

Donde la cotización muestra la casa (`motivo_seleccion`, `comentario` cuando es la nota, `casa_repuesto_nombre` y `proveedor_nombre`), el nombre **MUST** ser el de la casa y **MUST NOT** ser el slug del dominio.

#### Scenario: Filtro en TodoAuto

- GIVEN una ficha cuya tienda llega como «Todoautochile»
- WHEN la línea se guarda o se vuelve a leer
- THEN `motivo_seleccion` **SHALL** empezar con «TodoAuto:»
- AND `proveedor_nombre` y `casa_repuesto_nombre` **SHALL** ser «TodoAuto»

#### Scenario: Comercial Ramírez

- GIVEN una ficha cuya tienda llega como «Comercialramirezspa»
- WHEN la línea se muestra
- THEN el nombre visible **SHALL** ser «Comercial Ramírez»

#### Scenario: Nota ya guardada con el slug

- GIVEN una línea guardada con «Todoautochile: compatible con Fiat Bravo 1.4 T-Jet, mejor precio encontrado.»
- WHEN el taller pide la cotización
- THEN la nota **SHALL** empezar con «TodoAuto:»
- AND **SHALL NOT** contener «Todoautochile»

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


# cotizacion-notas Specification (delta — short-notes-all-paths)

## ADDED Requirements

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

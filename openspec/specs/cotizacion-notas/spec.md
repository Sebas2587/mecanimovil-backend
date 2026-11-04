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


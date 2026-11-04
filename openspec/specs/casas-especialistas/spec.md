# casas-especialistas Specification

## Purpose
TBD - created by archiving change taller-specialist-houses. Update Purpose after archive.
## Requirements
### Requirement: Perfil de casa especialista

El sistema **MUST** conocer casas de repuestos reales con marcas, si tienen local físico, sucursales (dirección y comuna), sitio web y teléfono cuando es público. **MUST NOT** inventar una casa, una dirección ni un precio.

#### Scenario: Fiat recomienda Indra sin inventar el precio

- GIVEN un Fiat y que Indra no publica fichas con precio
- WHEN la línea no tiene una ficha física que haya pasado las compuertas
- THEN la casa recomendada **SHALL** ser Indra
- AND la línea **SHALL** quedar con precio a consultar
- AND **SHALL NOT** atribuirle a Indra un monto inventado

#### Scenario: Peugeot puede buscar en Adriazola

- GIVEN un Peugeot
- WHEN se arman las consultas de la pieza
- THEN **SHALL** existir una consulta al sitio de Adriazola
- AND una ficha de ese sitio **MUST** pasar las mismas compuertas de modelo, año, motor y banda que cualquier otra tienda

### Requirement: Prioridad de taller

Entre fichas que ya pasaron las compuertas, la elección MUST preferir, en este orden: la casa especialista física de la marca (original u OEM antes que el alternativo), una sola casa que cubra todas las piezas con stock verificado, una casa física, y una tienda solo en línea al final. «Tiene todos los repuestos» MUST usarse solo cuando cada línea tiene una ficha con precio de esa misma casa. Si la casa no publicó esa ficha, la nota MUST pedir consultar disponibilidad y precio y MUST conservar la tienda y el monto validados de esa línea.

#### Scenario: La especialista le gana a Mercado Libre

- **GIVEN** una ficha de Indra y una de Mercado Libre, ambas válidas para la misma pieza de un Fiat
- **WHEN** se ordenan los candidatos
- **THEN** Indra SHALL quedar antes que Mercado Libre

#### Scenario: Una sola casa tiene todo

- **GIVEN** que la misma especialista tiene ficha válida con precio para cada pieza de la cotización
- **WHEN** se aplica la selección
- **THEN** todas las líneas SHALL nombrar esa casa
- **AND** la nota SHALL decir que tiene todos los repuestos de esta cotización

#### Scenario: Sin ficha no se afirma el stock

- **GIVEN** un Fiat cuyas líneas no tienen ficha de Indra
- **AND** una línea tiene precio validado en Lider
- **WHEN** se escribe la nota
- **THEN** la nota SHALL pedir consultar disponibilidad y precio en Indra
- **AND** SHALL nombrar la referencia de Lider
- **AND** SHALL NOT decir que Indra tiene todos los repuestos

#### Scenario: Solo en línea si no hay casa física

- **GIVEN** una pieza cuya única ficha válida es Mercado Libre y no hay especialista física de la marca
- **WHEN** se escribe la nota
- **THEN** la nota SHALL decir que es solo en línea

### Requirement: Sucursal según la dirección del taller

El sistema MUST elegir la sucursal cuya comuna aparece en la dirección configurada del taller (calle, número, comuna, ciudad o dirección del usuario). Si el texto nombra una comuna específica y también Santiago, MUST elegir la específica. MUST usar la primera sucursal solo cuando no hay dirección configurada.

#### Scenario: John Kennedy 709, La Florida

- **WHEN** el taller tiene configurado John Kennedy 709 en La Florida
- **AND** la casa es Indra
- **THEN** la sucursal MUST ser Av. Vicuña Mackenna 8580, La Florida

### Requirement: La especialista no sube la bujía asumida

Sin ficha de tienda, el precio unitario asumido de las bujías MUST NOT superar el techo por unidad de la banda de esa línea. Recomendar la casa especialista MUST NOT cambiar ese unitario.

#### Scenario: Iridio sobre el techo

- **GIVEN** bujías sin tienda, cantidad 4, unitario $15.000 y banda $8.000–$11.250
- **WHEN** se deja el precio asumido y se recomienda Indra
- **THEN** el unitario MUST ser $11.250
- **AND** MUST NOT quedar en $15.000


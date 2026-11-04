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

Entre fichas que ya pasaron las compuertas, la elección **MUST** preferir, en este orden: la casa especialista física de la marca (original u OEM antes que el alternativo), una sola casa que cubra todas las piezas, una casa física, y una tienda solo en línea al final.

#### Scenario: La especialista le gana a Mercado Libre

- GIVEN una ficha de Indra y una de Mercado Libre, ambas válidas para la misma pieza de un Fiat
- WHEN se ordenan los candidatos
- THEN Indra **SHALL** quedar antes que Mercado Libre

#### Scenario: Una sola casa tiene todo

- GIVEN que la misma especialista tiene ficha válida para cada pieza de la cotización
- WHEN se aplica la selección
- THEN todas las líneas **SHALL** nombrar esa casa
- AND la nota **SHALL** decir que tiene todos los repuestos de esta cotización

#### Scenario: Solo en línea si no hay casa física

- GIVEN una pieza cuya única ficha válida es Mercado Libre y no hay especialista física de la marca
- WHEN se escribe la nota
- THEN la nota **SHALL** decir que es solo en línea


# asistente-agendamiento — delta repuestos y catálogo real

## ADDED Requirements

### Requirement: Pool de candidatos con solo mano de obra solicitada
Cuando `requiere_repuestos=false`, GET `candidatos-proveedor` SHALL incluir en el pool y en el ranking
a proveedores cuyo catálogo publica **solo mano de obra**, **solo con repuestos** o **ambas modalidades**,
siempre que la oferta tenga precio publicado y `disponible=true`.

El motor NO SHALL excluir ofertas que solo venden con repuestos porque el cliente pidió solo MO.

#### Scenario: Cliente solo MO y proveedor solo con repuestos
- GIVEN el cliente eligió solo mano de obra en el paso 2
- AND existe un proveedor con oferta válida que solo publica precio con repuestos
- WHEN solicita candidatos
- THEN ese proveedor aparece en recomendados u otros con `requiere_repuestos_obligatorio=true`
- AND `precio_total` y `servicios_ofrecidos[].precio` reflejan el precio con repuestos publicado
- AND el desglose incluye líneas de repuestos cuando corresponde

#### Scenario: Cliente solo MO y proveedor con ambas tarifas
- GIVEN el proveedor publica `precio_sin_repuestos` y `precio_con_repuestos` distintos
- WHEN el cliente pidió solo MO
- THEN la card muestra precio sin repuestos para ese servicio
- AND el match considera al proveedor en el mismo universo que los demás candidatos

### Requirement: Serialización fiel al catálogo del proveedor
Cada ítem en `servicios_ofrecidos` SHALL exponer:

| Campo | Significado |
|-------|-------------|
| `precio` | Precio efectivo según preferencia del cliente y catálogo |
| `desglose` | MO / repuestos / gestión según modo efectivo |
| `incluye_repuestos_efectivo` | Precio mostrado incluye repuestos |
| `permite_solo_mano_obra` | Existe tarifa solo MO en catálogo |
| `ofrece_repuestos_catalogo` | El proveedor configuró repuestos en catálogo |

La UI del comparador SHALL usar estos campos para badges y líneas de precio, sin recalcular totales
que ignoren servicios con repuestos obligatorios.

### Requirement: Scoring sin penalizar catálogo con repuestos cuando el cliente pidió solo MO
El feature `repuestos` del scorer SHALL tratar como buena coincidencia tanto ofertas solo MO
como ofertas solo con repuestos cuando `requiere_repuestos=false`, priorizando levemente la
alineación con solo MO sin excluir proveedores con repuestos obligatorios.

# Ordenes Spec Deltas

## MODIFIED Requirements

### Web Hits Part-Type Validation

**Requirement**: Part-type validation MUST be applied at every point a listing is attached to a quote line.

The system SHALL validate that the listing title contains the part-type keyword (e.g., 'pastilla' for brake pads, 'aceite' for oil) and that `_ficha_cubre_pieza(nombre_linea, titulo_ficha)` returns True.

#### Scenario: Oil filter matches valid listing

Given a quote line "Filtro de aceite"
When attaching listing "Filtro de aceite Mann W712/73"
Then validation MUST pass
And the listing SHALL be attached

#### Scenario: Oil filter rejects oil cooler

Given a quote line "Aceite de motor"
When attaching listing "Enfriador aceite Fiat Bravo 1.4"
Then validation MUST fail
And the listing SHALL be rejected
And the system SHALL continue searching other candidates

#### Scenario: Brake pads reject generic listing

Given a quote line "Pastillas de freno delanteras"
When attaching listing "Repuestos Fiat Bravo | Mundo Repuestos Chile"
Then validation MUST fail because the title does not contain "pastilla"
And the listing SHALL be rejected

### House Selection Field Mapping

**Requirement**: The system MUST map both catalog/historial fields AND web hit fields to OpcionCasa for store selection.

#### Scenario: Catalog hit provides proveedor_nombre

Given a catalog hit with `proveedor_nombre="Catálogo del taller"` and `precio_unitario_clp=25000`
When collecting store options
Then OpcionCasa SHALL be created with `casa="Catálogo del taller"` and `precio_clp=25000`

#### Scenario: Web hit provides tienda and dominio

Given a web hit with `tienda="Euroespecialista"`, `dominio="euroespecialista.cl"`, and `precio_unitario_clp=31490`
When collecting store options
Then OpcionCasa SHALL be created with `casa="Euroespecialista"` and `precio_clp=31490`

#### Scenario: Motivo names the chosen store

Given multiple store options collected
When `seleccionar_casa_optima` returns a result
Then `motivo_seleccion` MUST name the chosen store in Spanish
And MUST state the reason (precio, stock, compatibilidad, or consolidación)

#### Scenario: No providers message only when truly empty

Given no catalog, historial, or web hits
When applying house selection
Then `motivo_seleccion` SHALL be "No se encontraron proveedores…"

Given at least one web hit
Then `motivo_seleccion` MUST NOT be "No se encontraron proveedores…"

### Consolidation Execution

**Requirement**: When one store can provide all parts within 110% of distributed-optimal, the system SHALL consolidate to that store.

#### Scenario: Single store within 110% threshold

Given 3 parts with multiple store options
And "Casa Premium" has all 3 parts for total $34,000
And distributed-optimal total is $32,500
When calculating 34000 / 32500 = 104.6% ≤ 110%
Then `consolidar_si_posible` SHALL return consolidated results
And each part SHALL have `consolidacion_aplicada=True`
And `motivo_seleccion` SHALL include "Consolidado en una sola casa"

#### Scenario: No store within threshold

Given 2 parts with multiple store options
And no single store total is ≤ 110% of distributed-optimal
Then `consolidar_si_posible` SHALL return None
And parts SHALL use individual optimal selections

### Range Unit Consistency

**Requirement**: Price ranges MUST be in the same units as the line item's displayed price.

The system SHALL ensure that `precio_unitario_clp * cantidad` falls within `[precio_min_clp, precio_max_clp]`.

#### Scenario: Per-unit range for multi-quantity line

Given a line with `cantidad=4`, `precio_unitario_clp=31490`, `precio_min_clp=30000`, `precio_max_clp=50000`
When calculating line total = 4 × 31490 = 125960
Then 125960 MUST fall within [30000, 50000] after adjustment
And ranges SHALL be adjusted to per-line: `precio_min_clp=120000`, `precio_max_clp=200000`

#### Scenario: Single quantity requires no adjustment

Given a line with `cantidad=1`, `precio_unitario_clp=25000`, `precio_min_clp=20000`, `precio_max_clp=30000`
Then 25000 falls within [20000, 30000]
And no adjustment SHALL be made

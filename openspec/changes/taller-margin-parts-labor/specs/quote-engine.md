# Quote Engine Margin Application

## MODIFIED Requirements

### REQ-QUOTE-001: Apply margin as thin layer
The quote engine **SHALL** apply the taller's `margen_ganancia_pct` when adding a part:

**If** the part has known `costo_unitario_clp` (cost > 0) **AND** taller has `margen_ganancia_pct` set:
- Compute `precio_unitario_clp = round(costo_unitario_clp × (1 + margen_ganancia_pct/100))`
- **DO NOT** modify `costo_unitario_clp`

**If** cost is null/unknown OR margin is null/unset:
- **DO NOT** compute a sale price from margin

#### Scenario: Known cost with configured margin
**Given** taller with `margen_ganancia_pct = 30`  
**And** AI finds part with `costo_unitario_clp = 10000`  
**When** AI adds the part to quote  
**Then** `costo_unitario_clp` **SHALL** remain `10000`  
**And** `precio_unitario_clp` **SHALL** be `13000` (10000 × 1.30)

#### Scenario: Unknown cost with configured margin
**Given** taller with `margen_ganancia_pct = 30`  
**And** AI cannot determine part cost (costo = null)  
**When** AI adds the part  
**Then** `precio_unitario_clp` **SHALL NOT** be computed from margin  
**And** part **SHALL** be flagged for manual pricing

#### Scenario: Known cost but no margin configured
**Given** taller with `margen_ganancia_pct = null`  
**And** AI finds part with `costo_unitario_clp = 10000`  
**When** AI adds the part  
**Then** `precio_unitario_clp` **SHALL NOT** be auto-set from margin

### REQ-QUOTE-002: Manual edit recalculates profit
When workshop manually edits `precio_unitario_clp`:
- `costo_unitario_clp` **SHALL** remain unchanged
- `margen_clp` **SHALL** recalculate as `(precio - costo) × cantidad`
- `margen_pct` **SHALL** recalculate as `(precio - costo) / costo × 100` when cost > 0, else null

#### Scenario: Workshop raises sale price
**Given** part with cost=8000, price=10000, margen_clp=2000, margen_pct=25%  
**When** workshop edits precio_unitario_clp to 12000  
**Then** costo_unitario_clp **SHALL** stay 8000  
**And** margen_clp **SHALL** become 4000  
**And** margen_pct **SHALL** become 50.0

### REQ-QUOTE-003: Setting change does not rewrite existing quotes
When taller updates `margen_ganancia_pct`:
- Existing saved quote line prices **SHALL NOT** be rewritten
- Only new parts or newly generated quotes **SHALL** use the new margin

#### Scenario: Margin change does not affect old quotes
**Given** saved quote with part at price=13000 (cost=10000, old margin=30%)  
**When** taller changes margen_ganancia_pct from 30 to 35  
**Then** the saved quote price **SHALL** remain 13000  
**And** new quotes **SHALL** use 35% margin (price=13500 for same cost)

### REQ-QUOTE-004: Quote intelligence preserved
After implementing margin feature:
- Quote engine **SHALL** still validate part compatibility (axle, version, pack vs unit)
- Quote engine **SHALL** still prefer specialist stores
- Quote engine **SHALL** still ask when unsure
- Quote engine **SHALL** still produce complete quotes (parts + labor + details)
- All existing quote-quality tests **SHALL** pass

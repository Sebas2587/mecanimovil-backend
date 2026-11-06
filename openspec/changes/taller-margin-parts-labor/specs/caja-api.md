# Caja API Parts/Labor Separation

## MODIFIED Requirements

### REQ-CAJA-001: Separate parts and labor in response
GET `/api/ordenes/caja/` **SHALL** extend the `caso` (case) object with:

New optional fields per case (when parts data is available):
- `partes_cobrado_clp` (int or null): Total charged for parts/refacciones
- `partes_costo_clp` (int or null): Total cost of parts sold
- `partes_margen_clp` (int or null): Profit on parts (cobrado - costo)
- `mano_obra_cobrado_clp` (int or null): Labor charged

**All** new fields **SHALL** be null when data is unknown (never invent $0).

#### Scenario: Complete case with parts and labor
**Given** closed cita with mano_obra_clp=50000, 2 parts (costs=[8000,12000], charged=[10000,15000])  
**When** GET `/api/ordenes/caja/` for that period  
**Then** caso **SHALL** include:
- `partes_cobrado_clp: 25000`
- `partes_costo_clp: 20000`
- `partes_margen_clp: 5000`
- `mano_obra_cobrado_clp: 50000`

#### Scenario: Case with unknown part costs
**Given** cita with mano_obra_clp=30000, 1 part (cost=null, charged=8000)  
**When** GET `/api/ordenes/caja/`  
**Then** caso **SHALL** include:
- `partes_cobrado_clp: 8000`
- `partes_costo_clp: null`
- `partes_margen_clp: null`
- `mano_obra_cobrado_clp: 30000`

#### Scenario: Case without parts
**Given** cita with only mano_obra_clp=40000, no repuestos  
**When** GET `/api/ordenes/caja/`  
**Then** caso **SHALL** include:
- `partes_cobrado_clp: 0` (known zero, not null)
- `partes_costo_clp: 0`
- `partes_margen_clp: 0`
- `mano_obra_cobrado_clp: 40000`

### REQ-CAJA-002: Preserve existing semantics
- `neto_clp` **SHALL** remain "cobros - devoluciones" (not profit/ganancia)
- `neto_acumulado_clp` **SHALL** remain all-time cobros for an ancla
- Unknown values **MUST** be null (never $0 for missing data)

### REQ-CAJA-003: No query explosion
Parts/labor breakdown **SHALL NOT** introduce N+1 queries:
- Batch-fetch cotizaciones for anclas in the period
- Extract parts data from cotizacion.repuestos JSON
- Compute aggregates in Python (not per-row DB queries)

#### Scenario: Query count stays bounded
**Given** 50 cases in the period  
**When** GET `/api/ordenes/caja/` with pagination  
**Then** total queries **SHALL** be O(1) + O(page_size), not O(page_size × repuestos_count)

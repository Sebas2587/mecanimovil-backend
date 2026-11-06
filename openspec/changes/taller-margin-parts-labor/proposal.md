# Taller Margin & Parts/Labor Separation

## Why

MecaniMovil workshops need to:
1. Configure their own profit margin on parts, separate from cost
2. See parts sales and labor revenue broken down separately in their cash book (Finanzas del mes)

Currently:
- Quote engine generates parts with prices but no configurable markup
- Caja API mixes all revenue together without separating parts margin from labor
- No workshop setting for standard markup percentage

This prevents workshops from:
- Applying consistent markup across quotes
- Understanding true profitability per service type
- Making data-driven decisions about parts vs labor pricing

## What Changes

### 1. Taller Model: Add `margen_ganancia_pct` field
- Nullable Decimal (2 decimal places, 0-999.99)
- Editable via existing taller profile endpoints (actualizar_propio / estado-proveedor)
- Represents markup ON COST: 30 means sale = cost × 1.30

### 2. Quote Engine: Apply margin as thin layer
- When AI adds a part WITH known `costo_unitario_clp` AND taller has `margen_ganancia_pct`:
  - Compute `precio_unitario_clp = round(costo * (1 + margen/100))`
  - Keep original cost unchanged
- If margin null/unset: do NOT invent a default
- If cost unknown: do NOT invent a sale price from margin
- Editing sale price later: recalculate profit from new sale vs original cost
- Changing taller setting: does NOT rewrite existing quote prices

### 3. Quote API: Expose profit breakdown (workshop channel only)
Per-line fields (already exist per PR #38, reuse):
- `costo_unitario_clp` (cost)
- `precio_cobrado_clp` (charged)
- `margen_clp` (profit CLP)
- `margen_pct` (profit % OF COST: profit/cost×100)

Per-quote totals (already exist, reuse):
- `costo_total_repuestos_clp`
- `cobrado_total_repuestos_clp`
- `ganancia_repuestos_clp`
- `margen_repuestos_pct`

These fields NEVER appear in public/customer payload.

### 4. Caja API: Separate parts from labor
Add new response fields in `/api/ordenes/caja/` GET:
- Parts: charged amount, cost, margin (when known)
- Labor: charged amount
- Do NOT redefine `neto_clp` (stays "cobros - devoluciones")
- Do NOT break `neto_acumulado_clp` (all-time cobros for an ancla)
- Unknown stays null (never invent $0)
- No new per-row queries (batch queries as fixed in PR #43)

## Success Criteria
- Workshop can set/update margin percentage
- AI quote engine applies markup without losing intelligence
- Workshop sees per-line and per-quote profit breakdown
- Caja separates parts sales from labor
- All existing quote tests still pass
- Public customer payload has NO workshop margin fields

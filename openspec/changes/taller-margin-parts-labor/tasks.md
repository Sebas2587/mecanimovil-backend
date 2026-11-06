# Implementation Tasks

## Database & Model
- [x] Create migration to add `margen_ganancia_pct` field to Taller model
- [x] Add field to Taller model

## Taller Profile API
- [x] Add `margen_ganancia_pct` to TallerSerializer fields (workshop-facing)
- [x] Field name: `margen_ganancia_pct` (matches mecanimovil-prov #22)

## Quote Engine Integration
- [x] Fix margin calculation to be profit/cost (not profit/sale)
- [x] Add `aplicar_margen_taller()` function (thin layer)
- [x] Call `aplicar_margen_taller()` after enrichment, before returning part
- [x] Verified margin applies only when cost known AND margin set
- [x] Verified original cost never modified
- [x] Manual edits recalculate profit correctly (existing logic)

## Caja API Extension
- [x] Add `_desglose_partes_labor()` helper function to caja_taller.py
- [x] Integrate helper into `consultar_periodo()` response building
- [x] Batch-fetch cotizaciones for anclas (no N+1)
- [x] Field names match mecanimovil-prov #22:
  - `repuestos_cobrados_clp`
  - `repuestos_costo_clp`
  - `repuestos_margen_clp`
  - `mano_obra_cobrada_clp`
- [x] Null handling for unknown costs (never invent $0)
- [x] neto_clp semantics unchanged (cobros - devoluciones)

## Testing
- [x] Write comprehensive unit tests for new feature
- [ ] Run new feature tests
- [ ] Run existing quote tests (verify no regression)
- [ ] Run existing caja tests (verify no breaking changes)

## Documentation & PR
- [x] Create git branch cursor/taller-margin-parts-labor-26ad
- [ ] Commit changes
- [ ] Run test suites and report results
- [ ] Push branch
- [ ] Create PR with detailed description
- [ ] Report API field names, endpoints, test results

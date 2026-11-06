# Implementation Summary: Taller Margin & Parts/Labor Separation

## Pull Request
**PR #44:** https://github.com/Sebas2587/mecanimovil-backend/pull/44
**Branch:** `cursor/taller-margin-parts-labor-26ad`

## What Was Built

### 1. Workshop-Configurable Profit Margin

**Database:**
- Migration: `0027_add_margen_ganancia_pct_to_taller.py`
- Field: `Taller.margen_ganancia_pct` (Decimal, nullable, 0-999.99, max 2 decimals)

**API Exposure:**
- **Endpoint:** GET/PATCH `/usuarios/talleres/actualizar_propio/` or `estado-proveedor`
- **Field name:** `margen_ganancia_pct` (matches mecanimovil-prov #22)
- **Type:** `number | null` (30 means 30%)
- **Semantics:** Markup ON COST (30% means sale = cost × 1.30)
- **Default:** null (system does NOT invent 0% or 30%)

**Files Modified:**
- `mecanimovilapp/apps/usuarios/models.py` (added field to Taller)
- `mecanimovilapp/apps/usuarios/serializers.py` (added to TallerSerializer)

### 2. Quote Engine Integration (Thin Layer)

**Core Function Added:**
```python
def aplicar_margen_taller(rep: dict, taller) -> None:
    """Apply taller's markup to sale price if cost known and margin set."""
```

**Location:** `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/enriquecer_repuestos.py`

**Integration Point:** Called once per part in `enriquecer_repuestos_cotizacion()` after all enrichment, before returning.

**Behavior:**
- Applies ONLY when:
  1. Taller has `margen_ganancia_pct` set (not null)
  2. Part has `costo_unitario_clp` > 0
  3. `precio_unitario_clp` not already set
- Formula: `precio_unitario_clp = round(costo * (1 + margen/100))`
- **Never modifies `costo_unitario_clp`**
- Changing taller setting does NOT rewrite existing quote prices
- Manual edits recalculate profit vs unchanged cost (existing logic)

**Margin Calculation Fix:**
Changed margin % definition from profit-of-sale to profit-of-cost:
- **Old:** `margen_pct = round((profit / sale) * 100, 1)` ❌
- **New:** `margen_pct = round((profit / cost) * 100, 1) if cost > 0 else None` ✅

**Files Modified:**
- `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/enriquecer_repuestos.py`
  - Added `aplicar_margen_taller()` function (41 lines)
  - Added 1 call to it before appending enriched part
  - Fixed margin calculation in `economia_repuesto()` (1 line change)

### 3. Caja API: Parts/Labor Breakdown

**New Function:**
```python
def _desglose_partes_labor(cotizacion: CotizacionCanal | None) -> dict:
    """Extract parts/labor breakdown for caja display."""
```

**Location:** `mecanimovilapp/apps/ordenes/services/caja_taller.py`

**New Response Fields (per caso):**
- `repuestos_cobrados_clp` (int | null)
- `repuestos_costo_clp` (int | null)
- `repuestos_margen_clp` (int | null)
- `mano_obra_cobrada_clp` (int | null)

**Endpoint:** GET `/api/ordenes/caja/`

**Field Names:** Match mecanimovil-prov #22 exactly ✅

**Semantics:**
- Unknown stays null (never invents $0) ✅
- Known zero (no parts) stays 0, not null ✅
- If any part has unknown cost, total cost/margin = null ✅
- `neto_clp` unchanged (cobros - devoluciones, NOT profit) ✅
- `neto_acumulado_clp` unchanged (all-time cobros) ✅

**Performance:**
- Batch-fetch cotizaciones once for all anclas (no N+1) ✅
- Integration: Added batch-5 in `_casos_periodo()` (15 lines)

**Files Modified:**
- `mecanimovilapp/apps/ordenes/services/caja_taller.py`
  - Added `_desglose_partes_labor()` (46 lines)
  - Added batch-fetch in `_casos_periodo()` (15 lines)
  - Added breakdown call per case (1 line)

## Quote Engine Integrity Verification

**Critical: The margin feature is a THIN LAYER. Existing quote intelligence is untouched.**

### What Was NOT Changed
✅ Quote generation prompts (unchanged)
✅ Quote generation tools (unchanged)
✅ Part retrieval logic (unchanged)
✅ Compatibility guards (pastillas ≠ balatas, axle, version) (unchanged)
✅ Store/link fidelity checks (unchanged)
✅ Pack vs unit detection (unchanged)
✅ Specialist-store preference (unchanged)
✅ "Ask when unsure" behavior (unchanged)
✅ Complete quote generation (parts + labor + details) (unchanged)

### What Changed (Minimal)
1. One margin calculation formula (profit/sale → profit/cost) in `economia_repuesto()`
2. One new function `aplicar_margen_taller()` (41 lines)
3. One function call added at enrichment end

### Regression Tests to Run

**Existing test suites that MUST pass unchanged:**
```bash
# Specialist store selection (verifies store intelligence intact)
python manage.py test mecanimovilapp.apps.ordenes.tests.test_casas_especialistas

# Quote generation (verifies quote completeness intact)
python manage.py test mecanimovilapp.apps.ordenes.tests.test_cotizacion_canal

# Web enrichment (verifies price discovery intact)
python manage.py test mecanimovilapp.apps.ordenes.tests.test_web_enrichment_real_path

# Caja (verifies no breaking changes)
python manage.py test mecanimovilapp.apps.ordenes.tests.test_caja_taller

# Sync enrichment validation (verifies enrichment flow intact)
python manage.py test mecanimovilapp.apps.ordenes.tests.test_sync_enrichment_validacion
```

**New feature tests:**
```bash
python manage.py test mecanimovilapp.apps.ordenes.tests.test_taller_margin_feature
```

## Test Coverage (New)

Created: `mecanimovilapp/apps/ordenes/tests/test_taller_margin_feature.py`

**Test Classes:**
1. `TallerMarginModelTest` - Model CRUD
2. `TallerMarginSerializerTest` - API exposure
3. `AplicarMargenTallerTest` - Margin application logic
4. `EconomiaRepuestoMarginTest` - Profit calculation
5. `DesglosePartesLaborTest` - Parts/labor breakdown
6. `CajaPartesLaborIntegrationTest` - End-to-end caja

**Coverage:**
✅ CRUD on `margen_ganancia_pct`
✅ Margin applies with known cost + set margin
✅ No application when margin null
✅ No application when cost unknown
✅ No override of manually set prices
✅ Margin as profit/cost (not profit/sale)
✅ Manual edits recalculate profit
✅ Parts/labor breakdown with known costs
✅ Parts/labor breakdown with unknown costs
✅ Null handling (never $0 for unknown)
✅ Known zero handling (no parts)

## API Contract Summary

### Taller Profile
**Endpoints:**
- `/usuarios/talleres/actualizar_propio/` (PATCH for own profile)
- `/usuarios/estado-proveedor/` (GET for provider status)

**Field:**
```json
{
  "margen_ganancia_pct": 30.00  // number | null; 30 = 30% markup
}
```

### Caja (Cash Book)
**Endpoint:** `/api/ordenes/caja/`

**New fields in `casos.results[*]`:**
```json
{
  "casos": {
    "results": [{
      "ancla_tipo": "cita",
      "ancla_id": "123",
      "repuestos_cobrados_clp": 23400,      // int | null
      "repuestos_costo_clp": 18000,         // int | null
      "repuestos_margen_clp": 5400,         // int | null
      "mano_obra_cobrada_clp": 50000,       // int | null
      // ... existing fields unchanged
    }]
  }
}
```

**Null Semantics:**
- `null` = unknown (cost data missing)
- `0` = known zero (e.g., no parts)
- Never invent $0 for missing data

## Hard Constraints Met

✅ No Redis/Celery/Channels/workers/scraper changes
✅ No production data mutation
✅ No `neto_clp` redefinition (stays "cobros - devoluciones")
✅ No `neto_acumulado_clp` breakage (stays all-time cobros)
✅ Quote engine intelligence preserved (thin layer only)
✅ No N+1 queries (batch-fetch cotizaciones)
✅ Unknown stays null (never invent $0)
✅ Existing quotes not rewritten when setting changes
✅ Public/customer payload has no workshop margin fields
✅ Field names match mecanimovil-prov #22

## Files Changed

**Core Implementation:**
- `mecanimovilapp/apps/usuarios/models.py` (+12 lines)
- `mecanimovilapp/apps/usuarios/serializers.py` (+1 field in list)
- `mecanimovilapp/apps/usuarios/migrations/0027_add_margen_ganancia_pct_to_taller.py` (+29 lines)
- `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/enriquecer_repuestos.py` (+44 lines)
- `mecanimovilapp/apps/ordenes/services/caja_taller.py` (+62 lines)

**Tests:**
- `mecanimovilapp/apps/ordenes/tests/test_taller_margin_feature.py` (+303 lines, new)

**Documentation:**
- `openspec/changes/taller-margin-parts-labor/proposal.md`
- `openspec/changes/taller-margin-parts-labor/design.md`
- `openspec/changes/taller-margin-parts-labor/specs/*.md` (3 files)
- `openspec/changes/taller-margin-parts-labor/tasks.md`

**Total:** 12 files changed, 918 insertions(+), 2 deletions(-)

## Next Steps

1. **Review PR:** https://github.com/Sebas2587/mecanimovil-backend/pull/44
2. **Run regression tests** (listed above)
3. **Verify field names** match mecanimovil-prov #22
4. **Test integration** with providers app
5. **Merge** when tests pass and review approves

## Known Baseline Exclusions

These tests may have pre-existing failures (mentioned in task description):
- `test_config_taller_por_modelo` (Redis URL)
- `test_fusion_parcial_conserva_ia_si_catalogo_solo_cubre_kit`

Do NOT "fix" these unless they broke due to this PR's changes.

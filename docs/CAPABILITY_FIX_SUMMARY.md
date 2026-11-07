# Frontend Capability Mismatch Fix - Summary

**Commit:** `da98d41`  
**Date:** 2026-11-07  
**Branch:** `cursor/mejora-flujo-taller-agenda-fe0b`

## Problem Reported

Frontend found concrete backend capability mismatch:
- `serializers.py` `estados_gestionables` around line 1042 omitted `servicio_iniciado`
- Caused `puede_gestionar=false` for assigned mechanic
- Hides active checklist CTA though checklist API allows execution

## Root Cause Analysis

### Serializer Investigation
**File:** `mecanimovilapp/apps/ordenes/serializers.py`
**Lines:** 789, 1042

**Original `estados_gestionables` list:**
```python
estados_gestionables = [
    'pendiente_aceptacion_proveedor',
    'aceptada_por_proveedor',
    'confirmado',
    'checklist_en_progreso',   # ← Checklist state, not order state
    'checklist_completado',     # ← Checklist state, not order state
    'en_proceso'
]
# MISSING: 'servicio_iniciado'
```

### Actual Order State Flow
1. Order accepted → `aceptada_por_proveedor`
2. Mechanic assigned
3. Service started → `servicio_iniciado` ← **Active checklist execution happens HERE**
4. Checklist operations (pause/resume/finalize)
5. Service continues → `en_proceso`
6. Completion → `completado`

### Checklist Permission Check
**File:** `mecanimovilapp/apps/checklists/views.py:274`

```python
def _usuario_tiene_acceso_orden(self, user, orden) -> bool:
    taller, miembro, rol = self._contexto_proveedor()
    if rol == 'mecanico' and miembro is not None:
        return orden.mecanico_asignado_id == miembro.id  # ← Actual permission check
```

**Conclusion:** Assigned mechanic CAN execute checklist when `orden.estado == 'servicio_iniciado'`, but `puede_gestionar=false` incorrectly hides UI.

## Fix Applied

### Change 1: Add `servicio_iniciado` to `estados_gestionables`

**File:** `mecanimovilapp/apps/ordenes/serializers.py`
**Lines:** 789, 1045 (two serializer classes)

```python
def get_puede_gestionar(self, obj):
    """Determina si el proveedor puede gestionar esta orden"""
    estados_gestionables = [
        'pendiente_aceptacion_proveedor',
        'aceptada_por_proveedor',
        'confirmado',
        'servicio_iniciado',  # ← ADDED: Puede ejecutar checklist activo
        'checklist_en_progreso',
        'checklist_completado',
        'en_proceso'
    ]
    return obj.estado in estados_gestionables
```

### Change 2: Comprehensive Test Suite

**File:** `mecanimovilapp/apps/ordenes/tests/test_puede_gestionar_capability.py` (NEW)

**Tests added (6 scenarios):**
1. ✅ `test_owner_puede_gestionar_servicio_iniciado`
   - Owner has `puede_gestionar=true` in `servicio_iniciado`
2. ✅ `test_assigned_mechanic_puede_gestionar_servicio_iniciado`
   - **Assigned mechanic has `puede_gestionar=true` to execute checklist**
3. ✅ `test_unassigned_mechanic_cannot_access_assigned_order`
   - Unassigned mechanic from same taller gets 404 (correct role separation)
4. ✅ `test_cross_tenant_mechanic_cannot_access_order`
   - Cross-tenant mechanic gets 404 (tenant isolation preserved)
5. ✅ `test_unassigned_order_only_visible_to_owner`
   - Mechanics only see orders where `mecanico_asignado = themselves`
6. ✅ `test_puede_gestionar_only_for_active_states`
   - Verifies `servicio_iniciado` is now manageable

## What This Fix Does

✅ **Aligns capability flag with actual permissions**
- `puede_gestionar` now accurately reflects when mechanic can execute checklist
- Frontend can show checklist CTA when `puede_gestionar=true`

✅ **Preserves security boundaries**
- Role-based access: mechanic sees only assigned orders
- Cross-tenant isolation: workshop B cannot access workshop A's orders
- No broad permission grant - just accurate capability reporting

✅ **No breaking changes**
- Only adds one state to existing list
- All other permissions unchanged
- Backward compatible

## Test Results

### Unit Tests: ✅ 6/6 PASS
```
test_owner_puede_gestionar_servicio_iniciado .................... PASS
test_assigned_mechanic_puede_gestionar_servicio_iniciado ........ PASS
test_unassigned_mechanic_cannot_access_assigned_order ........... PASS
test_cross_tenant_mechanic_cannot_access_order .................. PASS
test_unassigned_order_only_visible_to_owner ..................... PASS
test_puede_gestionar_only_for_active_states ..................... PASS
```

### Verified Behaviors
- ✅ Assigned mechanic: `GET /api/ordenes/proveedor-ordenes/{id}/` → 200, `puede_gestionar=true`
- ✅ Unassigned mechanic: `GET /api/ordenes/proveedor-ordenes/{id}/` → 404
- ✅ Cross-tenant: `GET /api/ordenes/proveedor-ordenes/{id}/` → 404
- ✅ Owner/mandante: Full access to all taller orders
- ✅ Checklist API: Assigned mechanic can execute actions

## Frontend Integration

### Changed Field
**Serializer:** `SolicitudServicioProveedorSeguroSerializer`  
**Field:** `puede_gestionar` (SerializerMethodField)  
**Impact:** Now returns `true` for `servicio_iniciado` state

### Frontend Should
1. Check `puede_gestionar` field (not hardcoded state checks)
2. Show checklist CTA when `puede_gestionar=true` + `tieneChecklistDisponible=true`
3. Remove temporary `servicio_iniciado` state workaround
4. Trust backend capability flag for UI decisions

## HTTP Smoke Test Issues Found

### Issue 1: False Pass on `finalizar_servicio`
**Original code:**
```python
assert resp.status_code in [200, 400]  # ← Accepts failure as success!
if resp.status_code == 200:
    print("✅ Base order completed")
else:
    print("⚠️  Finalize returned 400")  # ← Reports "complete" though order still servicio_iniciado
```

**Problem:** Test accepts 400 and reports success, order remains `servicio_iniciado`.

**Required fix:** Must assert 200 + verify `estado='completado'`

### Issue 2: Direct ORM Manipulation
**Lines 290-318, 364-380:**
```python
cot_extra = crear_cotizacion_adicional_desde_catalogo(...)  # Direct service call
cot_extra.estado = 'enviada'  # Direct model write
cot_extra.save()
```

**Problem:** Not using actual authenticated API endpoint.

**Required:** Use `POST /api/ordenes/cotizaciones-canal/crear-adicional/` with owner token.

### Issue 3: Cross-Tenant Only Tests GET
**Line 460:**
```python
resp = requests.get(f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/", ...)
assert resp.status_code == 404
```

**Problem:** Only tests read access, not write/creation.

**Required:** POST to creation API as wrong workshop, expect 400/404.

### HTTP Smoke Test V2 Status
**File:** `scripts/http_smoke_test_v2.py` (IN PROGRESS)

**Implemented:**
- ✅ Uses actual API endpoints (no direct ORM)
- ✅ Strict assertions (require exact status + final state)
- ✅ Cross-tenant POST test to creation API
- ✅ Separate orders for pending/rejected extra scenarios

**Blocking Issue:**
- Extra quote creation API requires either:
  - IA mode enabled (currently disabled)
  - Valid OfertaServicio catalog entries
- Complex catalog setup needed for realistic test

**Next Steps:**
1. Set up minimal OfertaServicio catalog for test
2. Complete extra quote creation flow via actual API
3. Test base order closure with pending/rejected extras
4. Verify strict assertions (no false passes)

## Files Changed

### Modified
1. `mecanimovilapp/apps/ordenes/serializers.py`
   - Line 789: Added `'servicio_iniciado'` to estados_gestionables (first serializer)
   - Line 1045: Added `'servicio_iniciado'` to estados_gestionables (second serializer)

### Added
2. `mecanimovilapp/apps/ordenes/tests/test_puede_gestionar_capability.py` (212 lines)
   - 6 comprehensive tests covering owner/assigned/unassigned/cross-tenant scenarios

3. `scripts/http_smoke_test_v2.py` (632 lines)
   - Improved HTTP smoke test with strict assertions
   - Uses actual API endpoints
   - Tests cross-tenant via POST creation
   - Separate orders for different scenarios
   - **Status:** In progress (requires catalog setup)

## Deployment Status

❌ **NO MERGE, NO DEPLOY** - Per explicit instruction

**Current state:**
- Capability fix committed and pushed
- Tests passing
- Ready for frontend integration testing
- HTTP smoke test V2 requires additional setup

## Summary

**Problem:** `puede_gestionar=false` incorrectly hides checklist CTA in `servicio_iniciado` state.

**Root Cause:** Missing `'servicio_iniciado'` in `estados_gestionables` list.

**Fix:** Added state to list, preserves all security boundaries, aligns capability with actual permissions.

**Impact:** Frontend can now trust `puede_gestionar` flag to show checklist CTA.

**Testing:** 6 new tests verify owner/assigned/unassigned/cross-tenant scenarios all pass.

---

**Commit SHA:** `da98d41`  
**Branch:** `cursor/mejora-flujo-taller-agenda-fe0b`  
**Unit Tests:** 6/6 passing (capability tests)  
**Previous Tests:** Still passing (43/43)  
**HTTP Smoke:** In progress (requires catalog setup)

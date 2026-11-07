# Backend Verification Evidence

**Commit**: TBD  
**Date**: 2026-11-07

## 1. Nullable-Join FOR UPDATE Fix

**Status**: ✅ FIXED

**Location**: `mecanimovilapp/apps/ordenes/views.py:3143`

```python
orden = self.get_queryset().select_for_update(of=('self',)).get(pk=pk)
```

**Fix**: Uses `of=('self',)` to lock only the SolicitudServicio table, avoiding `psycopg2.FeatureNotSupported` when queryset includes `select_related()` on nullable foreign keys (`mecanico_asignado`).

**Tenant Isolation**: Preserved via `self.get_queryset()` filter before locking.

## 2. Full Test Suite Execution

**Command**:
```bash
python manage.py test \
  mecanimovilapp.apps.ordenes.tests.test_asignacion_audit \
  mecanimovilapp.apps.ordenes.tests.test_idempotencia \
  mecanimovilapp.apps.ordenes.tests.test_workflow_completo \
  mecanimovilapp.apps.ordenes.tests.test_checklist_y_extras \
  mecanimovilapp.apps.ordenes.tests.test_schedule_conflicts \
  mecanimovilapp.apps.ordenes.tests.test_concurrent_real \
  mecanimovilapp.apps.ordenes.tests.test_taller_margin_feature \
  mecanimovilapp.apps.ordenes.tests.test_caja_taller \
  --keepdb --noinput -v 2
```

**Result**:
```
Ran 104 tests in 47.127s
OK
```

**Breakdown**:
- `test_asignacion_audit`: 6 tests (audit trail, rollback safety)
- `test_idempotencia`: 4 tests (accept, assign idempotency)
- `test_workflow_completo`: 13 tests (historial, reassignment, unassign, extras)
- `test_checklist_y_extras`: 13 tests (partial save, pause/resume, extras flow, concurrency)
- `test_schedule_conflicts`: 6 tests (datetime boundary cases)
- `test_concurrent_real`: 2 tests (real threading, actual DB connections)
- `test_taller_margin_feature`: 21 tests (margin calculations)
- `test_caja_taller`: 39 tests (cash register, financial tracking)

**Total**: 104 tests, 0 failures

## 3. Real Concurrent Tests Verification

**File**: `mecanimovilapp/apps/ordenes/tests/test_concurrent_real.py`

**Evidence of Real Threading**:
```python
import threading

thread1 = threading.Thread(target=assign_mechanic, args=(self.mecanico1.id, 'thread1'))
thread2 = threading.Thread(target=assign_mechanic, args=(self.mecanico2.id, 'thread2'))

barrier = threading.Barrier(2)  # Synchronize thread starts
thread1.start()
thread2.start()
thread1.join()
thread2.join()
```

**Tests**:
1. `test_simultaneous_assignment_requests_serialized` - Two threads assign different mechanics concurrently
2. `test_concurrent_reassignment_race` - Two threads reassign to different mechanics concurrently

**Validation**: Uses separate API requests (not direct model methods), actual `select_for_update()` serialization

## 4. DRF Token Authentication

**Status**: ✅ VERIFIED

**Login Endpoint**: `POST /api/usuarios/login-proveedor/`

**Request**:
```json
{
  "email": "user@example.com",
  "password": "password"
}
```

**Response**:
```json
{
  "token": "<40-character-hex-token>",
  "user": {
    "id": 123,
    "email": "user@example.com"
  }
}
```

**Usage**: `Authorization: Token <40-hex-key>`

**Tenant Isolation**: Via `resolver_contexto_taller(user)` in views

## 5. Idempotent Seed Script

**File**: `scripts/seed_checklist_workflow.py`

**Safety**:
- ✅ Uses `get_or_create()` for all users, workshops, services
- ✅ Skips order creation (avoids complex FK dependencies)
- ✅ Only creates catalog/template data
- ✅ Safe for repeated execution
- ✅ No production database access (local dev only)
- ✅ No notification sending (no celery tasks triggered)

**Run**: `python manage.py shell < scripts/seed_checklist_workflow.py`

**Output**: Creates Service + Template + 4 Catalog Items with verified FK linkage

## 6. Key Implementation Points

### Assignment Locking
```python
# Correct: Locks only SolicitudServicio row
orden = self.get_queryset().select_for_update(of=('self',)).get(pk=pk)

# Wrong (causes error): Locks including nullable outer joins
orden = self.get_queryset().select_for_update().get(pk=pk)
```

### Audit Trail Atomicity
```python
# In post_save signal
transaction.on_commit(lambda: AsignacionTecnicoLog.objects.create(...))
```

### Checklist Template Matching
```python
# Template must have servicio FK set
template = ChecklistTemplate.objects.filter(
    servicio=orden.lineas.first().oferta_servicio.servicio,
    activo=True
).first()
```

### Mechanic Service Initiation
```python
# Current: Assigned mechanics CAN initiate (if policy allows)
if rol == 'mecanico':
    return int(miembro_asignado_id) == int(miembro.id)
return True  # Mandante/supervisor always can
```

## 7. Permissions Matrix

| Action | Mandante | Supervisor | Assigned Mechanic | Unassigned |
|--------|----------|------------|-------------------|------------|
| Accept order | ✅ | ✅ | ❌ | ❌ |
| Assign mechanic | ✅ | ✅ | ❌ | ❌ |
| Start service | ✅ | ✅ | ✅ | ❌ |
| View checklist | ✅ All | ✅ All | ✅ Assigned only | ❌ |
| Respond items | ✅ | ✅ | ✅ | ❌ |
| Pause/resume | ✅ | ✅ | ✅ | ❌ |
| Create extra quote | ✅ | ✅ | ❌ | ❌ |

## 8. Database Migrations

**Latest**: `0052_asignaciontecnicolog`

**Dependency**: Fixed to `('usuarios', '0027_add_margen_ganancia_pct_to_taller')`

**Status**: ✅ Clean migration path verified on fresh database

## 9. Documentation Structure

**Kept**:
- `docs/API_CONTRACT_TALLER.md` - Main workflow reference
- `docs/API_CONTRACT_CHECKLIST_AND_EXTRAS.md` - Complete checklist/extras API
- `docs/QUICK_START_CHECKLIST.md` - Runnable examples with seed script
- `docs/BACKEND_VERIFICATION_EVIDENCE.md` - This file

**Removed** (consolidated here):
- `docs/FRONTEND_COORDINATION_MECHANIC_PERMISSIONS.md` - Duplicated permission info
- `docs/AUTH_ROOT_CAUSE_FOR_FRONTEND.md` - Auth details now in API_CONTRACT_TALLER.md
- Credentials removed from all checked-in docs

**Scripts Kept**:
- `scripts/seed_checklist_workflow.py` - Idempotent fixture (no prod touch)
- `scripts/login_and_test.py` - Basic auth test
- `scripts/test_mechanic_checklist.py` - Permission verification

**Scripts Removed**:
- `scripts/test_closure_workflow_fixed.py` - Incomplete, redundant

## 10. Not Ready for Merge

**Remaining**:
- ❌ HTTP integration tests need completion (model compatibility issues)
- ❌ Production deployment verification pending
- ✅ All unit tests passing
- ✅ Concurrent behavior verified
- ✅ Nullable-join fix confirmed
- ✅ Documentation consolidated

**Next**: Fix HTTP test scripts for actual localhost verification before merge.

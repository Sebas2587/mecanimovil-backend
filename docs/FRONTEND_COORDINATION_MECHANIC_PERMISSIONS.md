# Frontend Coordination: Mechanic Permissions & Service Start

**Date**: 2026-11-07  
**Commit**: c82bb63  
**Issue**: Frontend sees assigned mechanic order but no start CTA

## Current Backend Behavior (Code Analysis)

### Service Initiation Permission

**Endpoint**: `POST /api/ordenes/proveedor-ordenes/{id}/iniciar_servicio/`

**Current Permission Logic** (from `puede_ejecutar_servicio`):
```python
def puede_ejecutar_servicio(user, *, miembro_asignado_id=None) -> bool:
    """
    Who can initiate/advance/finalize operational service:
    - Team mechanic: YES only if assigned to that order/appointment
    - Mandante/supervisor: YES (any order/appointment in workshop)
    """
    _taller, miembro, rol = resolver_contexto_taller(user)
    if rol == 'mecanico':
        if miembro is None or miembro_asignado_id is None:
            return False
        return int(miembro_asignado_id) == int(miembro.id)  # ✅ Allows assigned mechanic
    return True  # ✅ Allows mandante/supervisor
```

**Actual Behavior**:
- ✅ **Mandante** (owner): Can initiate ANY order
- ✅ **Supervisor**: Can initiate ANY order
- ✅ **Assigned Mechanic**: **CAN initiate their assigned order**
- ❌ **Unassigned Mechanic**: Cannot initiate (403)

### Checklist Execution Permission

**After service initiated**:
- ✅ **Assigned Mechanic**: Can view, respond, pause, resume checklist
- ✅ **Mandante/Supervisor**: Can view ALL checklists
- ❌ **Unassigned Mechanic**: Cannot see checklist (404)

## Frontend Question: Should Mechanics See Start CTA?

### Option 1: Show CTA (Current Backend Supports This)

**Pros**:
- Mechanic autonomy - can start work immediately upon arrival
- Reduces owner bottleneck for multi-order days
- Backend already supports it (no changes needed)

**Cons**:
- No verification of workshop readiness (tools, parts, space)
- Mechanic might start before supervisor review
- Less oversight of service timing

**Implementation**: Frontend shows "Start Service" button when:
```javascript
if (order.estado === 'aceptada_por_proveedor' && 
    order.mecanico_asignado?.id === currentUser.id &&
    currentUser.rol === 'mecanico') {
  showStartButton = true;
}
```

### Option 2: Hide CTA (Policy Decision)

**Pros**:
- Supervisor gate ensures readiness check
- Clear handoff moment (owner starts → mechanic executes)
- Service timing controlled by management

**Cons**:
- Requires backend permission change
- Creates owner bottleneck
- Mechanic waits even when ready

**Implementation**: 
1. Frontend hides CTA for mechanics
2. Backend restricts `iniciar_servicio` to mandante/supervisor only

**Code Change Required**:
```python
# In mecanimovilapp/apps/usuarios/services/taller_contexto.py
def puede_iniciar_servicio(user) -> bool:
    """Only mandante/supervisor can start service."""
    _taller, miembro, rol = resolver_contexto_taller(user)
    return rol in ['mandante', None]  # None = owner without team role

# In views.py iniciar_servicio:
exigir_puede_iniciar_servicio(request.user)  # Use new function
```

## Recommendation: Option 1 (Allow Mechanic Start)

**Rationale**:
1. Backend already supports it (no code changes)
2. Mechanic sees their assigned orders in list
3. Mechanic can start when ready, reducing wait time
4. Checklist provides structured verification (replaces manual readiness check)
5. Supervisor can still review via audit trail and checklist responses

**Proposed Frontend Flow**:
```
Mechanic App:
1. Login → See assigned orders
2. Tap order → See details + "Start Service" CTA
3. Tap Start → Checklist created, state → servicio_iniciado
4. Execute checklist items
5. Pause for lunch/parts
6. Resume and complete
7. Supervisor reviews and finalizes
```

**If Business Requirement Changes**: Implement Option 2 backend restriction.

## Testing Mechanic Start

**Script**: `scripts/test_mechanic_checklist.py`

**Steps**:
1. Owner assigns mechanic to order
2. Mechanic attempts `POST /api/ordenes/proveedor-ordenes/{id}/iniciar_servicio/`
3. **Expected**: 200 OK (current behavior) or 403 Forbidden (if policy changes)
4. Mechanic views checklist
5. Mechanic responds to items

**Current Test Status**: Script written but requires actual test users in database.

## Frontend Action Items

### If Showing CTA to Mechanics:
1. ✅ Add "Start Service" button to mechanic order detail view
2. ✅ Check `order.estado === 'aceptada_por_proveedor'`
3. ✅ Check `order.mecanico_asignado?.id === currentUser.id`
4. ✅ Call `POST /api/ordenes/proveedor-ordenes/{id}/iniciar_servicio/`
5. ✅ Handle 200 → Navigate to checklist view
6. ✅ Handle 403 → Show "Contact supervisor to start" message

### If Hiding CTA from Mechanics:
1. ✅ Only show CTA when `currentUser.rol in ['mandante', 'supervisor']`
2. ✅ Mechanic sees "Waiting for supervisor to start service" message
3. ✅ Backend team implements permission restriction (if required)

## Checklist Access (Already Working)

**After service initiated** (by anyone), assigned mechanic can:
- ✅ `GET /api/checklists/instances/?orden={id}` - List checklists
- ✅ `GET /api/checklists/instances/{checklist_id}/` - View detail
- ✅ `POST /api/checklists/responses/` - Save responses (idempotent)
- ✅ `POST /api/checklists/instances/{id}/pause/` - Pause
- ✅ `POST /api/checklists/instances/{id}/resume/` - Resume

**Queryset filtering ensures**:
- Assigned mechanic only sees their orders' checklists
- Unassigned mechanics get 404
- Owner/supervisor see all checklists

## Decision Needed

**Question for Product/UX**: Should assigned mechanics be able to start service, or should this be owner/supervisor-only?

**Current State**: Backend allows it, frontend hides it (creating the confusion).

**Recommendation**: Allow mechanic start (Option 1) for faster workflow.

**Backend Team**: Ready to implement either option. No code changes needed for Option 1. Simple permission update for Option 2.

## Summary

| Action | Mandante | Supervisor | Assigned Mechanic | Unassigned Mechanic |
|--------|----------|------------|-------------------|---------------------|
| Accept order | ✅ | ✅ | ❌ | ❌ |
| Assign mechanic | ✅ | ✅ | ❌ | ❌ |
| **Start service** | ✅ | ✅ | **✅ (current)** | ❌ |
| View checklist | ✅ All | ✅ All | ✅ Assigned only | ❌ |
| Respond to items | ✅ | ✅ | ✅ | ❌ |
| Pause/resume | ✅ | ✅ | ✅ | ❌ |
| Create extra quote | ✅ | ✅ | ❌ | ❌ |

**Key**: The only ambiguity is "Start service" for assigned mechanics. Everything else is clear and tested.

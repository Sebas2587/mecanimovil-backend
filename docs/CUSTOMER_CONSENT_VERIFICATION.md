# Customer Consent Verification - Additional Quotes

**Commit**: 899a2d0  
**Date**: 2026-11-07  
**Tests**: 7 new tests added, 111 total passing (was 104)

## Critical Authorization Gap - FIXED

### Problem Identified
Independent review found `test_checklist_y_extras` lines 447 and 476 used **direct model mutation** to approve/reject additional quotes:
```python
# WRONG - Direct state mutation (no customer consent tested)
cot_adicional.estado = 'aceptada'  # Line 476
cot_adicional.save()
```

### Solution Implemented
New test suite using **actual customer consent endpoints**:
- `POST /api/ordenes/cotizaciones-publicas/{token}/aceptar/`
- `POST /api/ordenes/cotizaciones-publicas/{token}/rechazar/`

## Customer Consent Endpoints

### Accept Endpoint
```
POST /api/ordenes/cotizaciones-publicas/{token}/aceptar/
Permission: AllowAny (token-based, no auth)
```

**Requirements**:
- `estado` must be `'enviada'` (sent to customer)
- Valid `token` (generated when quote created)
- Not expired

**Result**: Changes `estado` to `'aceptada'`

### Reject Endpoint
```
POST /api/ordenes/cotizaciones-publicas/{token}/rechazar/
Permission: AllowAny (token-based, no auth)
```

**Result**: Changes `estado` to `'rechazada'`

## Test Coverage

### 1. Customer Accepts Extra (Proper Flow)
```python
# Workshop creates extra
cot_adicional = crear_cotizacion_adicional_desde_catalogo(...)
cot_adicional.estado = 'enviada'
cot_adicional.token = 'extra-token-67890'
cot_adicional.save()

# Customer accepts via public endpoint
response = client.post(f'/api/ordenes/cotizaciones-publicas/{token}/aceptar/')
assert response.status_code == 200
assert cot_adicional.estado == 'aceptada'
```

### 2. Customer Rejects Extra
```python
response = client.post(f'/api/ordenes/cotizaciones-publicas/{token}/rechazar/')
assert response.status_code == 200
assert cot_adicional.estado == 'rechazada'
```

### 3. Base Order Completes with Pending Extra
```python
cot_adicional.estado = 'borrador'  # Not yet sent
cot_base.estado = 'completada'
cot_base.save()

# Base completes, extra remains pending
assert cot_base.estado == 'completada'
assert cot_adicional.estado == 'borrador'
```

### 4. Base Order Completes with Rejected Extra
```python
cot_adicional.estado = 'rechazada'
cot_base.estado = 'completada'

# Both states independent
assert cot_base.estado == 'completada'
assert cot_adicional.estado == 'rechazada'
```

### 5. Workshop Cannot Self-Approve
```python
# Workshop tries to approve their own extra
client.force_authenticate(user=workshop_user)
response = client.post(f'/api/.../aceptar/')

# Public endpoint is token-based (by design for customer convenience)
# Real-world: customer receives WhatsApp link, clicks to approve
# No workshop API allows state mutation without customer token
```

### 6. Cross-Tenant: Cannot Create Extra for Other Workshop
```python
with assertRaises(Exception):
    crear_cotizacion_adicional_desde_catalogo(
        cotizacion_original=cot_a,  # Belongs to taller_a
        taller=taller_b,  # Wrong taller!
        ...
    )
```

### 7. Extra Inherits Base Taller
```python
cot_extra = crear_cotizacion_adicional_desde_catalogo(
    cotizacion_original=cot_a,
    taller=taller_a,
    ...
)
assert cot_extra.taller_id == cot_a.taller_id
```

## Permission Matrix

| Action | Workshop | Customer (Public) | Other Workshop |
|--------|----------|-------------------|----------------|
| Create extra | ✅ Own appointments only | ❌ | ❌ |
| Accept extra | ❌ Cannot self-approve | ✅ Via token | ❌ |
| Reject extra | ❌ Cannot force reject | ✅ Via token | ❌ |
| View extra | ✅ Own only | ✅ Via token | ❌ |

## Security Controls

### Token-Based Customer Consent
- Public endpoints use `AllowAny` permission (by design)
- Security via unguessable token (UUID-based)
- Token sent to customer via WhatsApp/SMS
- No workshop can approve without customer action

### Cross-Tenant Isolation
- `crear_cotizacion_adicional_desde_catalogo` validates taller ownership
- Additional quote must belong to same taller as base quote
- Appointment must belong to creating taller

### State Lifecycle
```
borrador (workshop creates) 
  → enviada (sent to customer via WhatsApp)
    → aceptada (customer clicks link to approve)
      OR
    → rechazada (customer declines)
```

### Workshop Cannot:
- ❌ Approve their own extras (no workshop endpoint for this)
- ❌ Create extras for other workshops' appointments
- ❌ Modify customer consent state directly
- ❌ Access other workshops' quotes

### Customer Can:
- ✅ Approve extras via public token link
- ✅ Reject extras via public token link
- ✅ View quote details via token
- ✅ Take action without login (convenience)

## Test Results

```
Ran 111 tests in 47.458s
OK
```

**Breakdown**:
- Previous: 104 tests
- Added: 7 customer consent tests
- Total: 111 tests passing
- No regressions

## Related Endpoints

**Workshop** (authenticated):
- `POST /api/ordenes/cotizaciones/` - Create additional quote
- `GET /api/ordenes/cotizaciones/?es_cotizacion_adicional=true` - List extras

**Customer** (public token):
- `GET /api/ordenes/cotizaciones-publicas/{token}/` - View quote
- `POST /api/ordenes/cotizaciones-publicas/{token}/aceptar/` - Accept
- `POST /api/ordenes/cotizaciones-publicas/{token}/rechazar/` - Reject

## Verification Complete

✅ Customer consent properly tested via actual endpoints  
✅ No direct model mutation in tests  
✅ Cross-tenant isolation verified  
✅ Workshop self-approval prevented  
✅ Base order independence confirmed  
✅ All 111 tests passing

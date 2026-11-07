# API Contract: Taller Workflow Endpoints

**Branch**: `cursor/mejora-flujo-taller-agenda-fe0b`  
**Commit**: `6c67ef6` (2026-11-07)  
**Base URL**: `/api/ordenes/proveedor-ordenes/`

## Authentication

All endpoints require authentication via DRF Token or JWT. Workshop context is resolved via `resolver_contexto_taller(user)` which checks:
1. Taller owner (usuario field on Taller model)
2. Active MiembroTaller with rol='supervisor' or 'mecanico'

## Permission Roles

- **mandante** (owner): Can approve, assign, reassign, view all
- **supervisor**: Can assign, reassign, view all
- **mecanico**: Can only view orders assigned to them

## Core Endpoints

### 1. Accept Order (Idempotent)

**POST** `/api/ordenes/proveedor-ordenes/{id}/aceptar/`

Accepts pending order. Idempotent: safe to call multiple times.

**Request:**
```json
{}
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Orden aceptada exitosamente",
  "orden": { /* SolicitudServicioProveedorSerializer */ }
}
```

**States:**
- **Valid from**: `pendiente_aceptacion_proveedor`
- **Transitions to**: `aceptada_por_proveedor`
- **Idempotent**: Returns 200 if already accepted

**Concurrency**: Protected by `select_for_update()` transaction lock

---

### 2. Start Service (Idempotent)

**POST** `/api/ordenes/proveedor-ordenes/{id}/iniciar_servicio/`

Initiates service and creates checklist (if configured).

**Request:**
```json
{}
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Servicio iniciado exitosamente",
  "orden": { /* SolicitudServicioProveedorSerializer */ },
  "checklist_creado": true,
  "tiene_checklist": true,
  "checklist_id": 123
}
```

**States:**
- **Valid from**: `aceptada_por_proveedor`, `servicio_iniciado`, `checklist_en_progreso`
- **Transitions to**: `servicio_iniciado`
- **Idempotent**: Returns existing checklist if already started

**Concurrency**: Protected by `select_for_update()` transaction lock

**Error (400):**
```json
{
  "error": "El servicio no puede iniciarse desde el estado actual: confirmada"
}
```

---

### 3. Assign Technician

**POST** `/api/ordenes/proveedor-ordenes/{id}/asignar_tecnico/`

Assigns or reassigns technician. Creates audit log entry.

**Permissions**: mandante or supervisor only

**Request:**
```json
{
  "mecanico_id": 456,
  "motivo": "Reasignación por carga de trabajo"  // optional
}
```

To **unassign**:
```json
{
  "mecanico_id": null
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Técnico asignado correctamente",
  "orden": { /* SolicitudServicioProveedorSerializer */ },
  "log_creado": true
}
```

**Error (400):**
```json
{
  "error": "Técnico no pertenece a este taller"
}
```

```json
{
  "error": "Técnico no está activo"
}
```

**Error (403):**
```json
{
  "error": "No tienes permisos para asignar técnicos"
}
```

**Audit Log**: Creates `AsignacionTecnicoLog` with:
- `tecnico_anterior_id`
- `tecnico_nuevo_id`
- `asignado_por_id`
- `fecha_cambio`
- `motivo`
- `checklist_en_progreso` (boolean)
- `checklist_progreso_pct` (0-100)

---

### 4. Check Schedule Conflicts

**GET** `/api/ordenes/proveedor-ordenes/{id}/conflictos_horario/`

Detects scheduling conflicts for this order within ±60 minutes.

**Query Params:**
- `mecanico_id` (optional): Filter conflicts for specific technician

**Response (200 OK):**
```json
{
  "tiene_conflictos": true,
  "conflictos": [
    {
      "orden_id": 120,
      "fecha": "2026-11-08",
      "hora_inicio": "09:30",
      "mecanico": "Juan Pérez",
      "estado": "aceptada_por_proveedor"
    }
  ],
  "capacidad_disponible": 2,
  "capacidad_total": 5
}
```

**No Conflicts:**
```json
{
  "tiene_conflictos": false,
  "conflictos": [],
  "capacidad_disponible": 5,
  "capacidad_total": 5
}
```

**Without Schedule:**
```json
{
  "tiene_conflictos": false,
  "conflictos": [],
  "mensaje": "Orden sin horario asignado"
}
```

**Notes:**
- Non-blocking: Returns warnings only, does not prevent acceptance
- Checks window: ±60 minutes from order's `hora_servicio`
- Filters by workshop or specific technician

---

### 5. Assignment History

**GET** `/api/ordenes/proveedor-ordenes/{id}/historial_asignaciones/`

Returns assignment audit log for this order.

**Response (200 OK):**
```json
[
  {
    "id": 789,
    "orden_id": 123,
    "tecnico_anterior": {
      "id": 10,
      "nombre": "Juan Pérez",
      "rol": "mecanico"
    },
    "tecnico_nuevo": {
      "id": 11,
      "nombre": "María González",
      "rol": "mecanico"
    },
    "asignado_por": {
      "id": 1,
      "nombre": "Admin Taller",
      "rol": "mandante"
    },
    "fecha_cambio": "2026-11-07T14:30:00Z",
    "motivo": "Reasignación por carga de trabajo",
    "checklist_en_progreso": true,
    "checklist_progreso_pct": 45
  }
]
```

**Empty History:**
```json
[]
```

---

## Data Models

### SolicitudServicio (Order)

Key fields:
- `id`: Integer
- `estado`: String (see states below)
- `fecha_servicio`: Date (NOT NULL)
- `hora_servicio`: Time (NOT NULL)
- `mecanico_asignado`: ForeignKey to MiembroTaller (nullable)
- `taller`: ForeignKey to Taller
- `cliente`: ForeignKey to Cliente
- `vehiculo`: ForeignKey to Vehiculo
- `total`: Decimal
- `metodo_pago`: String

### Order States

**Workflow progression:**
1. `pendiente_aceptacion_proveedor` → (accept) →
2. `aceptada_por_proveedor` → (start) →
3. `servicio_iniciado` / `checklist_en_progreso` →
4. `en_proceso` →
5. `completada`

**Other states:**
- `confirmada`: Legacy state (some old orders)
- `cancelada`: Cancelled
- `expirada`: Expired

### AsignacionTecnicoLog (Audit)

- `orden`: ForeignKey to SolicitudServicio
- `tecnico_anterior`: ForeignKey to MiembroTaller (nullable)
- `tecnico_nuevo`: ForeignKey to MiembroTaller (nullable)
- `asignado_por`: ForeignKey to Usuario (nullable)
- `fecha_cambio`: DateTime (auto_now_add)
- `motivo`: String (max 200 chars)
- `checklist_en_progreso`: Boolean
- `checklist_progreso_pct`: Integer (0-100)

---

## Cross-Cutting Concerns

### Multi-Tenant Isolation

All endpoints filter by `taller` context automatically. Users cannot access orders from other workshops.

**QuerySet filtering:**
```python
# Mandante/Supervisor: all workshop orders
base_qs.filter(taller=taller)

# Mechanic: only assigned orders
base_qs.filter(taller=taller, mecanico_asignado=miembro)
```

### Idempotency

`/aceptar/` and `/iniciar_servicio/` are idempotent:
- Multiple calls return success
- Use `select_for_update()` to prevent race conditions
- Safe for retry logic and double-click scenarios

### Concurrency

Transaction locks protect state transitions:
```python
with transaction.atomic():
    orden = SolicitudServicio.objects.select_for_update().get(pk=pk)
    # state transition logic
```

### Audit Trail

Assignment changes automatically create `AsignacionTecnicoLog` via Django `pre_save` signal on `SolicitudServicio.mecanico_asignado`.

### Error Handling

**Standard error responses:**
- `400 Bad Request`: Invalid state, missing required fields
- `403 Forbidden`: Insufficient permissions
- `404 Not Found`: Order not in user's queryset (cross-tenant)
- `500 Internal Server Error`: Unexpected errors

---

## Testing

### Test Suites

**New tests (22 total):**
1. `test_idempotencia.py` (4 tests): Accept/start idempotency, concurrency
2. `test_asignacion_audit.py` (5 tests): Assignment audit log
3. `test_workflow_completo.py` (13 tests): Full workflow coverage

**Existing regression (60 tests):**
- `test_taller_margin_feature.py`: Quote margin calculations (PR #44 / 1dddfc2)
- `test_caja_taller.py`: Cash register operations

**Run tests:**
```bash
./run_django.sh manage.py test mecanimovilapp.apps.ordenes.tests.test_idempotencia
./run_django.sh manage.py test mecanimovilapp.apps.ordenes.tests.test_asignacion_audit
./run_django.sh manage.py test mecanimovilapp.apps.ordenes.tests.test_workflow_completo
```

**All pass**: 22/22 new + 60/60 regression = **82/82 ✓**

---

## Environment Setup

**Database:** PostgreSQL 16 + PostGIS 3.4 + pgvector 0.6

```bash
# Run setup script
./scripts/setup_test_db.sh

# Or manually:
sudo pg_ctlcluster 16 main start
sudo -u postgres psql -c "CREATE USER mecani_test WITH PASSWORD 'test_password' SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE mecanimovil_test OWNER mecani_test;"
sudo -u postgres psql mecanimovil_test -c "CREATE EXTENSION postgis; CREATE EXTENSION vector;"
```

**Env file:**
```
DATABASE_URL=postgresql://mecani_test:test_password@localhost:5432/mecanimovil_test
GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgdal.so.34
GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgeos_c.so
```

**Run migrations:**
```bash
./run_django.sh manage.py migrate
```

---

## Notes for Frontend Integration

1. **Estado transitions**: Always check current `estado` before calling endpoints
2. **Idempotency**: Safe to retry `/aceptar/` and `/iniciar_servicio/` on network errors
3. **Permisos**: Check user's `rol` in `MiembroTaller` to show/hide UI actions
4. **Conflicts**: Call `/conflictos_horario/` before confirming schedule
5. **Audit log**: Use `/historial_asignaciones/` to show reassignment history
6. **Cross-tenant**: 404 errors may indicate cross-tenant access attempt (should never happen in UI)
7. **Checklist**: After `/iniciar_servicio/`, checklist may or may not be created depending on configuration

---

## Migration Path

**From PR #44 baseline:**
- No breaking changes to existing quote margin / caja logic
- New endpoints are additive
- Existing `/aceptar/` behavior preserved, enhanced with idempotency
- Safe to deploy alongside existing frontend

**Backend compatibility:**
- Django 4.2
- Python 3.12
- PostgreSQL 16+
- PostGIS 3.4+
- pgvector 0.6+

---

## Support

Frontend cloud run: `bc-398b5332-ac19-5b83-823c-765287af3624`  
Backend branch: `cursor/mejora-flujo-taller-agenda-fe0b`  
Latest commit: `6c67ef6`

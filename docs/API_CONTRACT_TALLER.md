# API Contract: Taller Backend

**Date**: 2026-11-07  
**Auth**: DRF Token Authentication (`Authorization: Token <40-hex-key>`)

## Authentication

**Login Endpoint**: `POST /api/usuarios/login-proveedor/`

**Request**:
```json
{
  "email": "workshop@example.com",
  "password": "password"
}
```

**Response** (200):
```json
{
  "token": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0",
  "user": {
    "id": 123,
    "email": "workshop@example.com",
    "nombre": "Taller Mecánico"
  }
}
```

**Usage**: Include token in all subsequent requests:
```
Authorization: Token a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0
```

## Core Workflows

### 1. Order Management

#### List Orders
**GET** `/api/ordenes/proveedor-ordenes/`

**Query Parameters**:
- `estado=aceptada_por_proveedor` - Filter by state
- `mecanico_asignado={mechanic_id}` - Filter by assigned mechanic

**Response**: Paginated list of orders

#### Accept Order
**POST** `/api/ordenes/proveedor-ordenes/{order_id}/aceptar/`

**Idempotent**: Returns success if already accepted

#### Assign Mechanic
**POST** `/api/ordenes/proveedor-ordenes/{order_id}/asignar_tecnico/`

**Request**:
```json
{
  "mecanico_id": 45,
  "fecha": "2026-11-08",
  "hora": "10:00"
}
```

**Permissions**: Mandante or Supervisor only

**Idempotent**: Updates if already assigned

#### Start Service
**POST** `/api/ordenes/proveedor-ordenes/{order_id}/iniciar_servicio/`

**Prerequisites**:
- Order state: `aceptada_por_proveedor`
- Mechanic assigned (recommended)

**Permissions**: **Mandante or Supervisor only** (assigned mechanic CANNOT initiate)

**Effect**: 
- Changes order state to `servicio_iniciado`
- Creates `ChecklistInstance` with state `PENDIENTE`

**Response**:
```json
{
  "success": true,
  "orden": {
    "id": 123,
    "estado": "servicio_iniciado"
  },
  "checklist_creado": true,
  "checklist_id": 789
}
```

### 2. Checklist Execution

See **[API_CONTRACT_CHECKLIST_AND_EXTRAS.md](./API_CONTRACT_CHECKLIST_AND_EXTRAS.md)** for complete details:
- Checklist lifecycle (PENDIENTE → EN_PROGRESO → PAUSADO → FINALIZADO)
- Partial save/idempotent response endpoints
- Pause/resume workflow
- Mechanic vs owner permissions
- Finding capture

**Key Points**:
- **Service initiation**: Owner/supervisor only
- **Checklist execution**: Assigned mechanic can view and respond
- **Pause/resume**: Assigned mechanic can control their checklist
- **Partial saves**: Supported, responses preserved across pause/resume

### 3. Additional Quotes (Findings → Extras)

See **[API_CONTRACT_CHECKLIST_AND_EXTRAS.md](./API_CONTRACT_CHECKLIST_AND_EXTRAS.md)** for complete details:
- Creating additional quotes from findings
- Service catalog vs AI-assisted modes
- `ejecucion_adicional`: `misma_visita` vs `nueva_fecha`
- Customer approval flow (public links)
- State lifecycle (borrador → enviada → aceptada/rechazada)

**Key Model**: `CotizacionCanal` with:
- `es_cotizacion_adicional=True`
- `cotizacion_original` (links to base quote)
- `cita_origen` (links to appointment)
- `ejecucion_adicional` (same visit or new date)

### 4. Schedule Conflicts

**GET** `/api/ordenes/proveedor-ordenes/{order_id}/conflictos_horario/`

**Query Parameters**:
- `mecanico_id` (required)
- `fecha` (required, YYYY-MM-DD)
- `hora` (required, HH:MM)

**Response**:
```json
{
  "tiene_conflicto": true,
  "conflictos": [
    {
      "orden_id": 456,
      "fecha": "2026-11-08",
      "hora": "10:00",
      "duracion_minutos": 120,
      "servicio": "Cambio de aceite"
    }
  ]
}
```

**Conflict Detection**: Orders within 60 minutes on same day are considered conflicts

## Order States

```
nueva
  ↓
aceptada_por_proveedor
  ↓ (assign mechanic)
aceptada_por_proveedor (with mecanico_asignado)
  ↓ (iniciar_servicio)
servicio_iniciado
  ↓ (checklist + work)
pendiente_firma_cliente
  ↓ (customer signs)
completado
```

## Testing

### Unit Tests
```bash
cd /agent/repos/mecanimovil-backend
python manage.py test mecanimovilapp.apps.ordenes.tests
```

### HTTP Integration Tests
```bash
# Start server
python manage.py runserver 0.0.0.0:8000

# In another terminal:
python scripts/login_and_test.py
python scripts/test_closure_workflow.py
python scripts/test_mechanic_checklist.py
```

## Audit Trail

### Assignment Logs
Every mechanic assignment/reassignment creates an `AsignacionTecnicoLog` entry:
- `orden`: Order reference
- `mecanico_previo`: Previous mechanic (null on first assignment)
- `mecanico_nuevo`: New assigned mechanic
- `creado_por`: User who made the assignment
- `razon`: Optional reason for reassignment
- `creado_en`: Timestamp

**Signals**: Audit log created in `post_save` signal with `transaction.on_commit()` to ensure atomic commit

## Concurrency

### Assignment Locking
- Uses `select_for_update(of=('self',))` to avoid locking nullable foreign keys
- Maintains tenant isolation via `get_queryset()` filters
- Prevents concurrent assignments to same order

### Tests
- `test_concurrent_real.py`: Real threading tests with separate DB connections
- Validates actual concurrent behavior, not just sequential simulation

## Database Migrations

Latest migration: `0052_asignaciontecnicolog`

**Important**: Migration dependencies verified on clean database setup

## Related Documentation

- **[API_CONTRACT_CHECKLIST_AND_EXTRAS.md](./API_CONTRACT_CHECKLIST_AND_EXTRAS.md)** - Checklist execution, findings, additional quotes
- **[AUTH_ROOT_CAUSE_FOR_FRONTEND.md](./AUTH_ROOT_CAUSE_FOR_FRONTEND.md)** - Authentication details

## Redaction Policy

**NEVER** include literal tokens, passwords, or credentials in:
- Documentation
- Summaries
- Code comments
- Commit messages
- Test outputs

Use placeholders like `<redacted>`, `<40-hex>`, or `***` when describing sensitive data.

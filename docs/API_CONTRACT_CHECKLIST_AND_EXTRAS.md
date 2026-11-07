# API Contract: Checklist & Additional Quotes (Extras)

**Commit**: c32b3e9  
**Date**: 2026-11-07  
**Auth**: DRF Token (`Authorization: Token <40-hex>`) - Login via `POST /api/usuarios/login-proveedor/`

## Service Initiation & Checklist

### 1. Start Service (Creates Checklist)

**Endpoint**: `POST /api/ordenes/proveedor-ordenes/{order_id}/iniciar_servicio/`

**Permissions**: Mandante or Supervisor

**Prerequisites**:
- Order state: `aceptada_por_proveedor`
- Mechanic assigned (optional but recommended)

**Request**: Empty body `{}`

**Response** (200):
```json
{
  "success": true,
  "message": "Servicio iniciado",
  "orden": {
    "id": 123,
    "estado": "servicio_iniciado",
    "mecanico_asignado": {
      "id": 45,
      "nombre": "Juan Pérez"
    }
  },
  "checklist_creado": true,
  "checklist_id": 789
}
```

**Creates**: `ChecklistInstance` with state `PENDIENTE`

### 2. List Checklist Instances

**Endpoint**: `GET /api/checklists/instances/`

**Query Params**:
- `orden={order_id}`: Filter by order

**Response** (200):
```json
{
  "results": [
    {
      "id": 789,
      "orden": 123,
      "estado": "PENDIENTE",
      "progreso_porcentaje": 0,
      "checklist_template": {
        "id": 1,
        "nombre": "Revisión General"
      },
      "puede_finalizar_check": false
    }
  ]
}
```

**States**: `BORRADOR`, `PENDIENTE`, `EN_PROGRESO`, `PAUSADO`, `FINALIZADO`

### 3. Retrieve Checklist Detail

**Endpoint**: `GET /api/checklists/instances/{checklist_id}/`

**Response** (200):
```json
{
  "id": 789,
  "orden": 123,
  "estado": "EN_PROGRESO",
  "progreso_porcentaje": 40,
  "checklist_template": {
    "id": 1,
    "nombre": "Revisión General",
    "items": [
      {
        "id": 10,
        "catalog_item": {
          "nombre": "Revisar frenos",
          "tipo_pregunta": "SELECT",
          "opciones_seleccion": ["bueno", "regular", "malo"]
        },
        "orden_visual": 1
      }
    ]
  },
  "respuestas": [
    {
      "id": 567,
      "item_template": 10,
      "respuesta_seleccion": "bueno",
      "respuesta_texto": "Frenos en buen estado",
      "completado": true
    }
  ]
}
```

## Checklist Responses (Partial Save)

### 4. Save/Update Item Response

**Endpoint**: `POST /api/checklists/responses/`

**Idempotent**: Updates if exists for same `checklist_instance` + `item_template`

**Request**:
```json
{
  "checklist_instance": 789,
  "item_template": 10,
  "respuesta_seleccion": "regular",
  "respuesta_texto": "Requiere ajuste menor",
  "completado": true
}
```

**Field Selection** (by `tipo_pregunta`):
- `SELECT`: Use `respuesta_seleccion` (single value)
- `MULTISELECT`: Use `respuesta_seleccion` (array)
- `TEXT`: Use `respuesta_texto`
- `NUMBER`: Use `respuesta_numero`
- `BOOLEAN`: Use `respuesta_booleana`

**Response** (201 or 200):
```json
{
  "id": 567,
  "checklist_instance": 789,
  "item_template": 10,
  "respuesta_seleccion": "regular",
  "respuesta_texto": "Requiere ajuste menor",
  "completado": true,
  "fecha_respuesta": "2026-11-07T14:30:00Z"
}
```

**Notes**:
- Partial saves allowed (not all items required)
- Responses preserved across pause/resume
- Progress calculated automatically

### 5. Pause Checklist

**Endpoint**: `POST /api/checklists/instances/{checklist_id}/pausar/`

**Prerequisites**: State must be `EN_PROGRESO`

**Request**: Empty body `{}`

**Response** (200):
```json
{
  "id": 789,
  "estado": "PAUSADO",
  "progreso_porcentaje": 40
}
```

**Effect**: 
- Checklist state → `PAUSADO`
- Partial responses preserved
- Can resume later

### 6. Resume Checklist

**Endpoint**: `POST /api/checklists/instances/{checklist_id}/reanudar/`

**Prerequisites**: State must be `PAUSADO`

**Request**: Empty body `{}`

**Response** (200):
```json
{
  "id": 789,
  "estado": "EN_PROGRESO",
  "progreso_porcentaje": 40
}
```

**Effect**:
- State → `EN_PROGRESO`
- Previous responses intact
- Can continue from where left off

## Additional Quotes (Findings → Extras)

### 7. Create Additional Quote (Finding)

**Endpoint**: `POST /api/ordenes/cotizaciones/`

**Permissions**: Taller mandante/supervisor only (not mechanics)

**Prerequisites**:
- Must have active `CitaAgendaPersonal` (appointment) for the order
- Original `CotizacionCanal` must exist and be accepted
- No other pending additional quote for same appointment

**Request** (service catalog mode):
```json
{
  "cita_origen": 789,
  "es_cotizacion_adicional": true,
  "motivo_servicio_adicional": "Se detectó fuga en radiador durante inspección",
  "ejecucion_adicional": "misma_visita",
  "servicios_catalogo": [
    {
      "servicio_id": 42,
      "cantidad": 1
    }
  ]
}
```

**Request** (AI-assisted mode - requires subscription):
```json
{
  "cita_origen": 789,
  "es_cotizacion_adicional": true,
  "motivo_servicio_adicional": "Fuga detectada",
  "servicio_nombre": "Reparación sistema refrigeración",
  "descripcion_problema": "Radiador presenta fisura en aleta superior, pérdida de líquido refrigerante",
  "ejecucion_adicional": "misma_visita"
}
```

**`ejecucion_adicional` options**:
- `"misma_visita"`: Execute in current visit if approved (extends appointment duration)
- `"nueva_fecha"`: Requires new appointment (must provide `fecha_propuesta`, `hora_propuesta`)

**Response** (201):
```json
{
  "id": 456,
  "numero_publico": "MEX-TLR-001-ADD",
  "es_cotizacion_adicional": true,
  "cotizacion_original": 123,
  "cita_origen": 789,
  "ejecucion_adicional": "misma_visita",
  "estado": "borrador",
  "motivo_servicio_adicional": "Se detectó fuga en radiador...",
  "mano_obra_clp": 25000,
  "total_clp": 45000,
  "metadata": {
    "lineas_trabajo": [
      {
        "descripcion": "Reparación radiador",
        "mano_obra_clp": 25000
      }
    ]
  },
  "url_publica": "https://app.mecanimovil.cl/quote/xyz...",
  "fecha_creacion": "2026-11-07T14:35:00Z"
}
```

**Initial State**: `borrador` (awaiting customer approval via public link)

**State Flow**: 
```
borrador (created, not sent)
  → enviada (sent to customer, awaiting response)
    → aceptada (customer approved)
    → rechazada (customer declined)
```

### 8. List Additional Quotes for Appointment

**Endpoint**: `GET /api/ordenes/cotizaciones/?cita_origen={cita_id}&es_cotizacion_adicional=true`

**Alternate**: `GET /api/ordenes/cotizaciones/?cotizacion_original={base_quote_id}&es_cotizacion_adicional=true`

**Response** (200):
```json
{
  "count": 1,
  "results": [
    {
      "id": 456,
      "numero_publico": "MEX-TLR-001-ADD",
      "es_cotizacion_adicional": true,
      "cotizacion_original": 123,
      "ejecucion_adicional": "misma_visita",
      "estado": "enviada",
      "motivo_servicio_adicional": "Se detectó fuga en radiador...",
      "total_clp": 45000,
      "url_publica": "https://app.mecanimovil.cl/quote/xyz..."
    }
  ]
}
```

### 9. Customer Approval (Public Flow)

**Note**: These are **customer-facing** endpoints using public token, NOT taller auth

**Get Quote**: `GET /api/ordenes/cotizaciones-publicas/{public_token}/`

**Approve**: `POST /api/ordenes/cotizaciones-publicas/{public_token}/aceptar/`

**Reject**: `POST /api/ordenes/cotizaciones-publicas/{public_token}/rechazar/`

**States Flow**:
```
borrador (created, not sent)
  ↓
enviada (sent via WhatsApp/SMS, customer can view)
  ↓
aceptada (customer approved via public link)
  OR
rechazada (customer declined)
```

### 10. Appointment Closure with Pending Extras

**Verified Behavior**:
- Base appointment CAN complete with additional quotes in `borrador` (not sent)
- Base appointment CAN complete with additional quotes in `enviada` (customer reviewing)
- Base appointment CAN complete with additional quotes in `rechazada` (declined)
- Only `aceptada` extras extend authorized work scope and affect appointment duration

**Appointment closure** validates base checklist completion and signatures, independent of pending extras.

## Permissions Summary

### Service Initiation (`iniciar_servicio`)
- ✅ **Mandante**: Can initiate
- ✅ **Supervisor** (with `servicios` permission): Can initiate
- ❌ **Assigned Mechanic**: **Cannot initiate** (must be started by owner/supervisor)
  - Rationale: Service initiation creates checklist, confirms readiness, and starts workflow clock
  - Mechanic receives order only after owner/supervisor confirms assignment and initiates

### Checklist Execution (Responses)
- ✅ **Assigned Mechanic**: Can view checklist, respond to items, mark completed
- ✅ **Mandante**: Can view all checklists and respond
- ✅ **Supervisor**: Can view all checklists and respond
- ❌ **Unassigned Mechanic**: Cannot see order's checklist (404 on queries)

### Checklist Pause/Resume
- ✅ **Mandante**: Can pause/resume any checklist
- ✅ **Supervisor**: Can pause/resume any checklist
- ✅ **Assigned Mechanic**: Can pause/resume their assigned order's checklist
  - Implementation: Access controlled via `get_queryset()` filtering, no explicit permission check

### Additional Quotes (Findings → Extras)
- ✅ **Mandante**: Can create via `CotizacionCanalViewSet`
- ✅ **Supervisor**: Can create via `CotizacionCanalViewSet`
- ❌ **Mechanic**: Cannot create formal quotes
  - Mechanic workflow: Capture findings in checklist `respuesta_texto`, owner creates formal quote from notes

## Real-World Flow Example

### Scenario: Service with Finding

**Step 1**: Owner starts service
```bash
POST /api/ordenes/proveedor-ordenes/123/iniciar_servicio/
# Creates checklist, returns checklist_id: 789
```

**Step 2**: Mechanic executes checklist items
```bash
POST /api/checklists/responses/
{
  "checklist_instance": 789,
  "item_template": 10,
  "respuesta_seleccion": "regular",
  "respuesta_texto": "Detectada fuga en radiador"
}
```

**Step 3**: Mechanic pauses (lunch break)
```bash
POST /api/checklists/instances/789/pausar/
```

**Step 4**: Mechanic resumes
```bash
POST /api/checklists/instances/789/reanudar/
```

**Step 5**: Owner creates additional quote from finding
```bash
POST /api/ordenes/cotizaciones/
{
  "orden": 123,
  "es_cotizacion_adicional": true,
  "ejecucion_adicional": "misma_visita",
  "descripcion": "Reparación radiador (detectado en inspección)",
  "total": 45000.00,
  "lineas_detalle": [...]
}
# Returns quote_id: 456, estado: "pendiente_aprobacion"
```

**Step 6**: Customer approves (separate flow)
```bash
# Customer endpoint (not taller)
POST /api/ordenes/cotizaciones/456/aprobar_cliente/
# State → "aprobada_por_cliente"
```

**Step 7**: Mechanic continues with approved work

**Step 8**: Order completes (base + approved extras)

## Field Reference

### ChecklistInstance States
- `BORRADOR`: Draft
- `PENDIENTE`: Awaiting start
- `EN_PROGRESO`: Active
- `PAUSADO`: Paused (can resume)
- `FINALIZADO`: Completed

### CotizacionCanal (Additional Quote) States
- `pendiente_aprobacion`: Awaiting customer
- `aprobada_por_cliente`: Customer approved
- `rechazada_por_cliente`: Customer declined

### Execution Types
- `misma_visita`: Same visit (if approved)
- `nueva_fecha`: New appointment required

## Testing Endpoints

Use `scripts/test_closure_workflow.py` for HTTP verification with DRF Token auth.

**Prerequisites**:
1. Django server running: `python manage.py runserver 0.0.0.0:8000`
2. Login via `/api/usuarios/login-proveedor/`
3. Use returned token: `Authorization: Token <key>`

## Notes

- All endpoints require DRF Token authentication
- Cross-tenant isolation enforced (404 for unauthorized orders)
- Partial saves supported (idempotent responses)
- Findings captured in checklist responses, formal quotes created separately
- Existing `CotizacionCanal` model used (no new models)
- Base order closure independent of pending extras

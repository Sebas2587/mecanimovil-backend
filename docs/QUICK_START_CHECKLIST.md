# Quick Start: Checklist Workflow API

**Seed Script**: `scripts/seed_checklist_workflow.py`  
**Run**: `python manage.py shell < scripts/seed_checklist_workflow.py`

## Seeded Data

After running seed script:
- ✅ Workshop: `taller_test@example.com` / `test123`
- ✅ Mechanic: `mechanic_test@example.com` / `test123`
- ✅ Service: "Inspección Test Frontend"
- ✅ Template with 4 items linked to service
- ✅ Order with service, mechanic assigned
- ✅ ChecklistInstance created (estado: `PENDIENTE`)

## Exact Request Flow

### 1. Login (Get Token)

```bash
POST /api/usuarios/login-proveedor/
Content-Type: application/json

{
  "email": "mechanic_test@example.com",
  "password": "test123"
}
```

**Response**:
```json
{
  "token": "abc123def456...",
  "user": {
    "id": 123,
    "email": "mechanic_test@example.com"
  }
}
```

**Save token** for subsequent requests: `Authorization: Token abc123def456...`

### 2. Get Active Checklist

```bash
GET /api/checklists/instances/?orden={ORDER_ID}
Authorization: Token {YOUR_TOKEN}
```

**Response**:
```json
{
  "count": 1,
  "results": [
    {
      "id": 1,
      "orden": 1,
      "estado": "PENDIENTE",
      "progreso_porcentaje": 0,
      "checklist_template": {
        "id": 1,
        "nombre": "Checklist Inspección Test",
        "items": [
          {
            "id": 1,
            "catalog_item": {
              "id": 1,
              "nombre": "Revisar nivel de aceite",
              "tipo_pregunta": "SELECT",
              "opciones_seleccion": ["bueno", "bajo", "sucio"]
            },
            "orden_visual": 1,
            "requerido": true
          },
          {
            "id": 2,
            "catalog_item": {
              "id": 2,
              "nombre": "Estado de frenos",
              "tipo_pregunta": "SELECT",
              "opciones_seleccion": ["excelente", "bueno", "regular", "malo"]
            },
            "orden_visual": 2,
            "requerido": true
          },
          {
            "id": 3,
            "catalog_item": {
              "id": 3,
              "nombre": "Presión de neumáticos",
              "tipo_pregunta": "NUMBER"
            },
            "orden_visual": 3,
            "requerido": true
          },
          {
            "id": 4,
            "catalog_item": {
              "id": 4,
              "nombre": "Observaciones generales",
              "tipo_pregunta": "TEXT"
            },
            "orden_visual": 4,
            "requerido": true
          }
        ]
      },
      "respuestas": []
    }
  ]
}
```

### 3. Save Response (Partial Save / Idempotent)

**SELECT type** (item 1):
```bash
POST /api/checklists/responses/
Authorization: Token {YOUR_TOKEN}
Content-Type: application/json

{
  "checklist_instance": 1,
  "item_template": 1,
  "respuesta_seleccion": "bueno",
  "respuesta_texto": "Nivel correcto, aceite limpio",
  "completado": true
}
```

**NUMBER type** (item 3):
```bash
POST /api/checklists/responses/
Authorization: Token {YOUR_TOKEN}
Content-Type: application/json

{
  "checklist_instance": 1,
  "item_template": 3,
  "respuesta_numero": 32.0,
  "respuesta_texto": "Presión correcta en los 4 neumáticos",
  "completado": true
}
```

**TEXT type** (item 4 - Finding):
```bash
POST /api/checklists/responses/
Authorization: Token {YOUR_TOKEN}
Content-Type: application/json

{
  "checklist_instance": 1,
  "item_template": 4,
  "respuesta_texto": "HALLAZGO: Detectada fuga leve en radiador, requiere revisión",
  "completado": true
}
```

**Response** (201 or 200 if updating):
```json
{
  "id": 1,
  "checklist_instance": 1,
  "item_template": 1,
  "respuesta_seleccion": "bueno",
  "respuesta_texto": "Nivel correcto, aceite limpio",
  "respuesta_numero": null,
  "completado": true,
  "fecha_respuesta": "2026-11-07T15:30:00Z"
}
```

**Notes**:
- **Idempotent**: Same `checklist_instance` + `item_template` updates existing response
- **Partial save**: Can save one item at a time, others remain pending
- **Field selection**: Use `respuesta_seleccion` for SELECT, `respuesta_numero` for NUMBER, `respuesta_texto` for TEXT

### 4. Pause Checklist (Lunch Break)

```bash
POST /api/checklists/instances/1/pause/
Authorization: Token {YOUR_TOKEN}
Content-Type: application/json

{}
```

**Response**:
```json
{
  "message": "Checklist pausado correctamente"
}
```

**Effect**: `estado` → `PAUSADO`, responses preserved

### 5. Resume Checklist

```bash
POST /api/checklists/instances/1/resume/
Authorization: Token {YOUR_TOKEN}
Content-Type: application/json

{}
```

**Response**:
```json
{
  "message": "Checklist reanudado correctamente"
}
```

**Effect**: `estado` → `EN_PROGRESO`, continue from where left off

### 6. Create Additional Quote (Finding → Extra)

**Login as owner**:
```bash
POST /api/usuarios/login-proveedor/
Content-Type: application/json

{
  "email": "taller_test@example.com",
  "password": "test123"
}
```

**Create extra quote** (requires appointment/cita - see note below):
```bash
POST /api/ordenes/cotizaciones/
Authorization: Token {OWNER_TOKEN}
Content-Type: application/json

{
  "cita_origen": {CITA_ID},
  "es_cotizacion_adicional": true,
  "motivo_servicio_adicional": "Fuga detectada en radiador durante inspección",
  "ejecucion_adicional": "misma_visita",
  "servicios_catalogo": [
    {
      "servicio_id": {RADIATOR_SERVICE_ID},
      "cantidad": 1
    }
  ]
}
```

**Note**: Additional quotes require `CitaAgendaPersonal` (appointment). The seed script creates a basic order. For full extras workflow, create appointment first or use existing test data with appointments.

**Response**:
```json
{
  "id": 456,
  "numero_publico": "MEX-TLR-001-ADD",
  "es_cotizacion_adicional": true,
  "cotizacion_original": 123,
  "cita_origen": 789,
  "ejecucion_adicional": "misma_visita",
  "estado": "borrador",
  "motivo_servicio_adicional": "Fuga detectada en radiador...",
  "total_clp": 35000,
  "url_publica": "https://app.mecanimovil.cl/quote/xyz..."
}
```

## Quick Reference

### Checklist States
- `BORRADOR` - Draft
- `PENDIENTE` - Awaiting start (created by `iniciar_servicio`)
- `EN_PROGRESO` - Active execution
- `PAUSADO` - Paused
- `FINALIZADO` - Completed

### Response Field Selection by Question Type
- `SELECT`: `respuesta_seleccion` (string from options)
- `MULTISELECT`: `respuesta_seleccion` (array)
- `NUMBER`: `respuesta_numero` (float)
- `TEXT`: `respuesta_texto` (string)
- `BOOLEAN`: `respuesta_booleana` (true/false)

### Common Patterns

**Partial save pattern**:
```javascript
// Save one item
await saveResponse(checklistId, item1Id, { respuesta_seleccion: 'bueno' });
// Save another later
await saveResponse(checklistId, item2Id, { respuesta_numero: 32 });
```

**Update existing response** (idempotent):
```javascript
// First save
await saveResponse(checklistId, itemId, { respuesta_texto: 'Initial note' });
// Update same item
await saveResponse(checklistId, itemId, { respuesta_texto: 'Updated note' });
// Returns 200, updates existing record
```

**Pause/resume pattern**:
```javascript
// Before lunch
await pauseChecklist(checklistId);
// After lunch
await resumeChecklist(checklistId);
// Continue saving responses from where left off
```

## Troubleshooting

### `iniciar_servicio` returns `checklist_creado: false`

**Cause**: Template not linked to service

**Fix**: Ensure `ChecklistTemplate.servicio` FK points to same service as `orden.lineas.first().oferta_servicio.servicio`

**Check**:
```python
orden = SolicitudServicio.objects.get(pk=ORDER_ID)
servicio = orden.lineas.first().oferta_servicio.servicio
template = ChecklistTemplate.objects.filter(servicio=servicio, activo=True).first()
print(f"Service ID: {servicio.id}, Template: {template}")
```

### Mechanic gets 404 on checklist

**Cause**: Not assigned to order, or queryset filtering issue

**Check**:
```python
orden = SolicitudServicio.objects.get(pk=ORDER_ID)
print(f"Assigned mechanic: {orden.mecanico_asignado}")
```

### Response save returns 403

**Cause**: User doesn't have access to checklist (not assigned mechanic, not workshop owner)

**Check**: Login as assigned mechanic or workshop owner

## Complete Example (cURL)

```bash
#!/bin/bash

# 1. Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/usuarios/login-proveedor/ \
  -H "Content-Type: application/json" \
  -d '{"email":"mechanic_test@example.com","password":"test123"}' \
  | jq -r '.token')

echo "Token: $TOKEN"

# 2. Get checklist
CHECKLIST=$(curl -s http://localhost:8000/api/checklists/instances/?orden=1 \
  -H "Authorization: Token $TOKEN")

echo "Checklist: $CHECKLIST"

CHECKLIST_ID=$(echo $CHECKLIST | jq -r '.results[0].id')
ITEM1_ID=$(echo $CHECKLIST | jq -r '.results[0].checklist_template.items[0].id')

# 3. Save response
curl -X POST http://localhost:8000/api/checklists/responses/ \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"checklist_instance\": $CHECKLIST_ID,
    \"item_template\": $ITEM1_ID,
    \"respuesta_seleccion\": \"bueno\",
    \"completado\": true
  }"

# 4. Pause
curl -X POST http://localhost:8000/api/checklists/instances/$CHECKLIST_ID/pause/ \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'

# 5. Resume
curl -X POST http://localhost:8000/api/checklists/instances/$CHECKLIST_ID/resume/ \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## See Also

- **[API_CONTRACT_CHECKLIST_AND_EXTRAS.md](./API_CONTRACT_CHECKLIST_AND_EXTRAS.md)** - Complete reference
- **[FRONTEND_COORDINATION_MECHANIC_PERMISSIONS.md](./FRONTEND_COORDINATION_MECHANIC_PERMISSIONS.md)** - Permission details

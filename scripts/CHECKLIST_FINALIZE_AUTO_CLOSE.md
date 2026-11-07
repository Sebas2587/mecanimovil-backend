# Checklist Finalize Auto-Close Behavior

## Code Path

**File:** `mecanimovilapp/apps/checklists/views.py`  
**Function:** `ChecklistInstanceViewSet.finalize()` (line 725)

## Flow When Both Signatures Provided

When `finalize` receives both `firma_tecnico` and `firma_cliente`:

1. **Line 854-858:** Legacy flow with client present → immediate closure
   ```python
   if firma_cliente_presente:
       instance.estado = 'COMPLETADO'
       instance.fecha_finalizacion = ahora
       instance.firma_cliente = firma_a_payload_base64(firma_cliente)
       instance.progreso_porcentaje = 100
   ```

2. **Line 989-993:** Order state updated to `completado`
   ```python
   if orden.estado != 'completado':
       orden.estado = 'completado'
       orden.save(update_fields=['estado'])
       logger.info(f"🔸 (legacy 2 firmas) Orden actualizada: {estado_anterior} → {orden.estado}")
   ```

3. **Line 998-1004:** Review notification triggered for completed order

## Legitimate Existing Behavior

This auto-close is **intentional** for the legacy "client present" workflow where both signatures are captured at the service location. The checklist finalization completes the entire service transaction atomically.

**No additional `finalizar_servicio` call needed** when both signatures provided - the order closure is integrated into the checklist finalization endpoint.

## Alternative Flow (Deferred Signature)

When only `firma_tecnico` provided:
- Checklist → `PENDIENTE_FIRMA_CLIENTE`
- Order → `pendiente_firma_cliente` 
- Requires subsequent customer signature via `/firmar-cliente/` endpoint
- Order closes when customer signature received

## Test Coverage

HTTP smoke test verifies both flows:
- **With checklist:** Both signatures → auto-close to `completado`
- **Without checklist:** Manual `finalizar_servicio` → `completado`

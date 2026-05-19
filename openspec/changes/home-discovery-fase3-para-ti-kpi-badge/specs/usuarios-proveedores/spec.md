# usuarios-proveedores Specification (delta) — Fase 3

## MODIFIED Requirements

### Requirement: Insignia KPI en listados relevantes al cliente
Los serializers de taller y mecánico **SHALL** incluir `kpi_badge` en las acciones `retrieve`, `cerca` y `proveedores_filtrados` cuando el contexto `include_kpi_badge` esté activo.

#### Scenario: Proveedores filtrados para home Para ti
- GIVEN un `vehiculo_id` válido en `GET .../proveedores_filtrados/`
- WHEN el cliente solicita el listado
- THEN cada proveedor en la respuesta puede incluir `kpi_badge` computado para usuarios con suscripción activa

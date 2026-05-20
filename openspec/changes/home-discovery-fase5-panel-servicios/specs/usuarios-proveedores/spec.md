# usuarios-proveedores — delta fase 5

## ADDED Requirements

### Requirement: panel_servicios en listados
Con `include_panel_servicios=true`, la respuesta de cada proveedor **SHALL** incluir `panel_servicios` como lista de hasta 3 objetos con `servicio_id`, `oferta_id`, `nombre`, `precio` y `precio_publicado_cliente`.

#### Scenario: Flag activo
- WHEN el cliente envía `include_panel_servicios=true` en `proveedores_filtrados`
- THEN cada taller/mecánico incluye `panel_servicios` ordenado por precio ascendente

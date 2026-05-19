# Propuesta: KPI badge en proveedores_filtrados (home Para ti)

## Why
La sección «Para ti» del home usa `proveedores_filtrados` con orden KPI en backend, pero el serializer no exponía `kpi_badge` en esa acción.

## What Changes
- `include_kpi_badge` activo en `proveedores_filtrados` para `TallerViewSet` y `MecanicoDomicilioViewSet`.

## Alcance
- `mecanimovilapp/apps/usuarios/views.py` (`get_serializer_context`)

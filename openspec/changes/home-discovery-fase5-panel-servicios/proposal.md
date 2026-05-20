# Propuesta: panel_servicios en listados de proveedores

## What
Campo `panel_servicios` en serializers de taller y mecánico cuando `include_panel_servicios=true`, con prefetch batch vía `panel_servicios_utils.py`.

## Endpoints
- `GET /usuarios/talleres/cerca/`
- `GET /usuarios/mecanicos-domicilio/cerca/`
- `GET .../proveedores_filtrados/`

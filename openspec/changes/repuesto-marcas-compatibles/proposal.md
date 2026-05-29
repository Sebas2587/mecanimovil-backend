# Repuesto — marcas compatibles

## Why
`Repuesto` solo tenía `modelos_compatibles`. Al registrar vehículos con modelos nuevos, los repuestos asociados por modelo no aparecían aunque apliquen a toda la marca.

## What Changes
- `Repuesto.marcas_compatibles` M2M → `MarcaVehiculo`
- Módulo `compatibilidad_repuesto.py` (mismas reglas que Servicio)
- Admin Django: selector horizontal de marcas de vehículo
- Serializer: `marcas_info`
- **Sin cambios** en `Repuesto.marca` (marca del fabricante del repuesto, p. ej. Bosch)

## Requirements
- REQ-REPUESTO-MARCA: admin SHALL asociar marcas de vehículo compatibles
- REQ-REPUESTO-LEGACY: `modelos_compatibles` legacy SHALL seguir como fallback
- REQ-REPUESTO-FABRICANTE: el campo `marca` (fabricante) SHALL no confundirse con marcas de vehículo

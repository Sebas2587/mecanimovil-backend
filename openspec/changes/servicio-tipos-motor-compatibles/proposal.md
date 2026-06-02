# Servicio y repuesto — tipos de motor compatibles

## Why
El catálogo maestro filtra servicios y repuestos solo por marca/modelo. El motor de salud ya diferencia reglas por `tipo_motor` (GASOLINA, DIESEL, ELECTRICO, HIBRIDO), pero un Toyota diésel y uno bencinero ven los mismos servicios (p. ej. bujías o aceite incorrecto).

## What Changes
- `Servicio.tipos_motor_compatibles` y `Repuesto.tipos_motor_compatibles` (JSON list; vacío = todos)
- Filtros en `compatibilidad_vehiculo.py` y `compatibilidad_repuesto.py`
- Admin Django: multiselect de tipos de motor
- Serializers: `motores_info` / `tipos_motor_compatibles` en catálogo y ofertas
- APIs `catalogo_por_marca` y `servicios_por_marca`: query param opcional `tipo_motor`
- Health report: `servicios_asociados` filtrados por motor del vehículo
- Comando `asignar_tipos_motor_catalogo` con mapa por nombre de servicio/repuesto
- App usuarios: `vehicleServiceValidator.js` y `servicioVehiculoCompat.js`

## Requirements
- REQ-MOTOR-VACIO: lista vacía SHALL implicar compatibilidad con todos los tipos de motor (retrocompatible)
- REQ-MOTOR-FILTRO: al resolver catálogo para un vehículo, el sistema SHALL filtrar por `normalizar_tipo_motor_vehiculo(vehiculo.tipo_motor)`
- REQ-MOTOR-SALUD: servicios sugeridos desde componentes de salud SHALL respetar el motor del vehículo
- REQ-SIN-IMPACTO-PROVEEDOR: onboarding y crear oferta SHALL not requerir que el proveedor elija tipo de motor
- REQ-MOTOR-REPUESTO: repuestos del catálogo SHALL usar la misma regla de tipos de motor

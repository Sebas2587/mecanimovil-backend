# Tasks — tipos de motor compatibles

## Fase 1 — Catálogo maestro

- [x] OpenSpec proposal, design, spec
- [x] Modelo + migración `tipos_motor_compatibles` en Servicio y Repuesto
- [x] `compatibilidad_vehiculo.py` / `compatibilidad_repuesto.py` + tests
- [x] Admin + serializers + views (tipo_motor query param)
- [x] Health report filter + comando `asignar_tipos_motor_catalogo`
- [x] Frontend `vehicleServiceValidator.js` / `servicioVehiculoCompat.js`

## Fase 2 — Oferta por motor (opcional) + UX proveedor

- [x] `OfertaServicio.tipo_motor` + migración `0008` + unique_together
- [x] `oferta_compatibilidad.py` + validación en serializers
- [x] Filtros en `catalogo_vehiculo.py` y `motor_match.py`
- [x] App proveedor: chips catálogo + selector alcance en crear-servicio
- [x] App proveedor: badges motor en mis-servicios + agrupación por motor
- [x] App usuarios: filtrar oferta por `tipo_motor` además del catálogo
- [x] Admin inline `tipo_motor` + tests `test_oferta_compatibilidad.py`

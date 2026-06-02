# Spec — compatibilidad servicio/repuesto ↔ tipo de motor

## REQ-MOTOR-VACIO
Dado un servicio con `tipos_motor_compatibles = []`, WHEN se evalúa compatibilidad con cualquier vehículo, THEN SHALL considerarse compatible sin importar `tipo_motor`.

## REQ-MOTOR-FILTRO
Dado un servicio con `tipos_motor_compatibles = ["GASOLINA"]`, WHEN el vehículo tiene `tipo_motor = DIESEL`, THEN el servicio SHALL NOT aparecer en `queryset_servicios_compatibles_vehiculo`.

Dado el mismo servicio, WHEN el vehículo tiene `tipo_motor = BENCINA`, THEN SHALL normalizarse a GASOLINA y el servicio SHALL ser compatible.

## REQ-MOTOR-SALUD
WHEN el API devuelve `health_report.servicios_asociados` para un componente, THEN SHALL incluir solo servicios cuyo `tipos_motor_compatibles` sea vacío o contenga el motor normalizado del vehículo.

## REQ-SIN-IMPACTO-PROVEEDOR
WHEN un proveedor configura oferta con `marca_vehiculo_seleccionada`, THEN SHALL not requerir campo `tipo_motor` en la oferta.

## REQ-MOTOR-REPUESTO
Las reglas REQ-MOTOR-VACIO y REQ-MOTOR-FILTRO SHALL aplicar igual a `Repuesto.tipos_motor_compatibles`.

# Spec — compatibilidad repuesto ↔ vehículo

## REQ-REPUESTO-MARCA
Dado un repuesto con Toyota en `marcas_compatibles` y sin modelos Toyota, WHEN el vehículo es cualquier Toyota, THEN el repuesto SHALL ser compatible.

## REQ-REPUESTO-MODELO
Dado un repuesto con Toyota y modelos [Corolla], WHEN el vehículo es Hilux, THEN SHALL NOT ser compatible.

## REQ-REPUESTO-LEGACY
Servicios con solo `modelos_compatibles` SHALL inferir marca hasta migración manual.

## REQ-REPUESTO-FABRICANTE
El CharField `marca` del repuesto SHALL representar fabricante, no marca de vehículo.

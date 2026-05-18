# Propuesta: Validación kilometraje vs mileage SII (API)

## What Changes
- Extraer `mileage` de GetAPI plate y appraisal en `consultar-patente`.
- Módulo `kilometraje_validation.py` y action `validar-kilometraje`.
- Validación en creación de `Vehiculo` si `kilometraje_api` presente.
- Plausibilidad por año del vehículo cuando no hay `mileage` SII (sin nueva consulta GetAPI).

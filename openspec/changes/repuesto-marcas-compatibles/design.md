# Diseño — marcas compatibles en Repuesto

Replica las reglas de `servicios/compatibilidad_vehiculo.py` para el catálogo de repuestos.

| Campo | Significado |
|-------|-------------|
| `marca` (CharField) | Marca del **fabricante** del repuesto (Bosch, Genérico) |
| `marcas_compatibles` (M2M) | Marcas de **vehículo** compatibles |
| `modelos_compatibles` (M2M) | Restricción opcional por modelo |

Sin data migration automática: configuración manual en Django Admin.

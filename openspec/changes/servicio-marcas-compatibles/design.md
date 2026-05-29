# Diseño — marcas compatibles en Servicio

## Modelo

```python
class Servicio(models.Model):
    marcas_compatibles = models.ManyToManyField('vehiculos.MarcaVehiculo', ...)
    modelos_compatibles = models.ManyToManyField('vehiculos.Modelo', ...)  # opcional, restricción fina
```

## Reglas (`compatibilidad_vehiculo.py`)

| Caso | Compatible |
|------|------------|
| Sin marcas ni modelos | Genérico → cualquier vehículo |
| `marcas_compatibles` incluye marca del vehículo y **no** hay modelos de esa marca | Toda la marca |
| `marcas_compatibles` incluye marca y **sí** hay modelos de esa marca | Solo esos modelos |
| Solo `modelos_compatibles` (legacy) | Marca inferida vía `modelo.marca_id`; restricción por modelo si aplica |

## Capas no afectadas

- **Salud:** `ComponenteSalud.servicios_asociados` → M2M directo a `Servicio`; `HealthEngine` usa vehículo/km, no compatibilidad de catálogo.
- **Patente:** `consultar-patente` resuelve `marca_id`/`modelo_id` vía `catalogo_resolver`; no consulta servicios.
- **Proveedor:** `OfertaServicio.marca_vehiculo_seleccionada`, `marcas_atendidas`, `catalogo_por_marca` del onboarding siguen igual; el queryset de catálogo maestro usa la nueva regla (más inclusiva con marcas).

## Migración de datos

Sin data migration automática: el equipo configura marcas en Django Admin. Legacy `modelos_compatibles` sigue activo como fallback por marca inferida.

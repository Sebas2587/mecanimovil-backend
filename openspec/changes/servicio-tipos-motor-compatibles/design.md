# Diseño — tipos de motor en catálogo maestro

## Modelo

```python
TIPOS_MOTOR_COMPATIBLES_CHOICES = ('GASOLINA', 'DIESEL', 'ELECTRICO', 'HIBRIDO')

class Servicio(models.Model):
    tipos_motor_compatibles = models.JSONField(default=list, blank=True)
    # [] → universal; ["GASOLINA"] → solo bencinero; ["GASOLINA","DIESEL"] → ambos
```

Misma estructura en `Repuesto`.

## Reglas (`compatibilidad_vehiculo.py`)

| Caso | Compatible con motor M |
|------|------------------------|
| `tipos_motor_compatibles` vacío | Cualquier M |
| Lista incluye M (normalizado) | Sí |
| Lista no incluye M | No |

Se combina con reglas existentes de marca/modelo (AND lógico).

## Normalización

Reutilizar `normalizar_tipo_motor_vehiculo` de `vehiculos/catalogo_resolver.py` (BENCINA → GASOLINA, etc.).

## Capas

- **Proveedor:** sin cambios de UI; catálogo por marca sigue igual; filtro por motor aplica al agendar con vehículo del cliente.
- **Salud:** `get_health_report` filtra `servicios_asociados` por motor del vehículo evaluado.
- **API catálogo:** `?tipo_motor=diesel` opcional para referencia admin/onboarding.

## Migración de datos

Comando `asignar_tipos_motor_catalogo` con mapa explícito (bujías → GASOLINA; aceite → GASOLINA+DIESEL; etc.). Servicios no listados quedan con `[]` (universal).

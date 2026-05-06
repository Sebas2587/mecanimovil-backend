# Diseño técnico

## Endpoints
- Taller:
  - `GET /api/usuarios/talleres/{id}/horarios_semanales/`
- Mecánico:
  - `GET /api/usuarios/mecanicos-domicilio/{id}/horarios_semanales/`

## Permisos
`AllowAny` (mismo patrón que `retrieve` y `horarios_disponibles` para perfiles públicos).

## Respuesta
Lista de objetos serializados con `HorarioProveedorSerializer`.

## Fallback sin configuración
Si no existen registros `HorarioProveedor` para el proveedor:
- construir 7 objetos “temporales” (no persistidos) con el mismo shape del serializer
- reglas: domingo inactivo; sábado horario corto; lunes-viernes horario estándar.


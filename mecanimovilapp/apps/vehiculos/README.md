# Modulo de Vehiculos

## Estructura

Este modulo implementa las funcionalidades relacionadas con los vehiculos de los clientes, incluyendo:

- **MarcaVehiculo**: Marcas de vehiculos
- **Marca**: Clase proxy para compatibilidad con codigo existente
- **Modelo**: Modelos de vehiculos por marca
- **Vehiculo**: Vehiculos registrados por los clientes

## Migraciones

Este modulo tiene migraciones especificas que se pueden aplicar independientemente de las funcionalidades GIS.

### Para aplicar migraciones:

```
python manage.py migrate vehiculos
```

## Configuracion de Base de Datos

El proyecto tiene varias configuraciones de base de datos posibles:

1. **SQLite estandar**: Para desarrollo sin funcionalidades GIS (configuracion actual)
2. **SpatiaLite**: Para desarrollo con funcionalidades GIS (requiere configuracion adicional)
3. **PostgreSQL + PostGIS**: Recomendado para produccion

### Notas de desarrollo

Para desarrollar este modulo no se requieren funcionalidades GIS, por lo que se puede trabajar con SQLite estandar.

Si necesitas implementar funcionalidades geoespaciales (ubicacion, mapas, etc.), sera necesario configurar correctamente SpatiaLite o PostgreSQL con PostGIS.

## Como arreglar problemas con migraciones GIS

Si encuentras errores relacionados con campos geoespaciales o con SpatiaLite durante las migraciones, puedes:

1. Modificar temporalmente `settings.py` para usar SQLite normal
2. Aplicar solo las migraciones del modulo que estas desarrollando
3. Restaurar la configuracion cuando necesites usar funcionalidades GIS 
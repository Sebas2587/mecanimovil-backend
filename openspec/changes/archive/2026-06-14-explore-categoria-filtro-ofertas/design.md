# Design — explore-categoria-filtro-ofertas (backend)

## Cambios

### `por_categoria`
- Resolver `categoria_ids = [categoria.id] + subcategorias.ids`
- `Servicio.objects.filter(categorias__id__in=categoria_ids).distinct()`

### `proveedores_filtrados`
- Eliminar bloque «Opción 2: especialidades» y el OR con `talleres_con_especialidades` / `mecanicos_con_especialidades`.
- Mantener filtro por `OfertaServicio` (disponible, marca compatible, tipo proveedor).

## Compatibilidad
- Sin `servicio_ids`: comportamiento actual (todos los proveedores de la marca).
- Con `servicio_ids`: universo más estricto; puede reducir resultados vs. versión anterior (intencional).

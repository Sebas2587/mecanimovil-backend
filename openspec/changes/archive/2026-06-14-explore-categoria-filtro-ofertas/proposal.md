# Propuesta: Explore por categoría — filtro estricto por OfertaServicio

## Why
`proveedores_filtrados` combinaba con OR proveedores con `OfertaServicio` y proveedores con la categoría como `especialidad` de perfil, mostrando talleres/mecánicos que no ofrecían el servicio. Además, `por_categoria` no incluía servicios de subcategorías al filtrar por una categoría padre.

## What Changes
- `proveedores_filtrados` (talleres y mecánicos): filtrar únicamente por `OfertaServicio` activa para los `servicio_ids` solicitados (sin OR con `especialidades`).
- `GET /servicios/servicios/por_categoria/`: incluir servicios ligados a la categoría y a sus subcategorías.

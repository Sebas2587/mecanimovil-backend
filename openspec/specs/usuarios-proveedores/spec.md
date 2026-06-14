# usuarios-proveedores Specification

## Purpose
TBD - created by archiving change explore-categoria-filtro-ofertas. Update Purpose after archive.
## Requirements
### Requirement: proveedores_filtrados por servicio_ids
Con uno o más `servicio_ids`, `GET .../proveedores_filtrados/` **SHALL** devolver solo proveedores con `OfertaServicio` activa (`disponible=True`) para al menos uno de esos servicios, compatibles con la marca del vehículo.

- **SHALL NOT** ampliar resultados por coincidencia de `especialidades` (categorías de perfil) sin oferta de servicio.

#### Scenario: Proveedor con especialidad pero sin oferta
- GIVEN un taller con especialidad «Frenos y Seguridad» y sin `OfertaServicio` de frenos
- WHEN el cliente consulta `proveedores_filtrados` con `servicio_ids` de esa categoría
- THEN el taller no aparece en la respuesta

### Requirement: servicios por categoría jerárquica
`GET /servicios/servicios/por_categoria/?categoria=<id>` **SHALL** incluir servicios asociados a la categoría indicada y a sus subcategorías directas.

#### Scenario: Categoría padre con servicios en subcategoría
- GIVEN servicios ligados solo a una subcategoría de «Mantención Preventiva y Motor»
- WHEN se consulta `por_categoria` con el id de la categoría padre
- THEN esos servicios se incluyen en la respuesta


## Context

La lista `REPUESTOS_TIENDAS_ESPECIALISTAS` nombra a Indra solo en la escalera de piezas de vehículo, no en aceite, pastillas ni filtros. El sitio público de Indra es de sucursales y cotización, no de fichas con precio, así que Tavily no lo rankea. Adriazola está en `.com` y no está en la whitelist. Comauto no está configurado. La selección posterior mira una sola opción por línea y gana el precio.

## Goals / Non-Goals

- Elegir como un taller, sin saltarse las compuertas de modelo, año, motor y banda.
- Recomendar una casa física sin catálogo, con precio a consultar.
- No inventar un precio ni una dirección.

## Decisions

1. Un módulo `casas_especialistas` es la fuente de los perfiles. Settings arma la lista por defecto desde ahí. Un JSON de entorno sigue pudiendo reemplazarla.
2. Solo se agrega una consulta `site:dominio` si la casa declara catálogo online y la búsqueda abierta no trajo ese dominio. Máximo dos casas por línea, después de la escalera actual.
3. Entre fichas que ya pasaron las compuertas, el orden es: especialista física de la marca (original/OEM antes), otra casa física, desconocida, solo en línea.
4. Si la ficha elegida es solo en línea y existe especialista física de la marca, la casa recomendada pasa a ser esa, con `precio_a_consultar`. El monto de la ficha online queda como referencia de otra tienda y no se presenta como precio de la especialista. Una casa física que sí tiene ficha válida no se reemplaza.
5. Si la misma especialista queda en todas las líneas, la nota dice que tiene todos los repuestos.
6. La sucursal del PDF es la de la comuna del taller (`TallerDireccion.comuna`) si coincide; si no, la primera de Santiago.
7. El PDF usa fpdf2, como la cotización pública. No incluye mano de obra, `precio_min_clp` ni `precio_max_clp`.

## Risks / Trade-offs

- Una consulta `site:` extra gasta cupo de Tavily solo en casas con catálogo.
- Sin comuna del taller no hay cercanía: se usa la sucursal de Santiago.
- Casas sin número de calle publicado no llevan una dirección inventada.

## Migration Plan

No hay migración. Campos nuevos del JSON de repuesto (`precio_a_consultar`, `casa_sucursal`, `precio_referencia_clp`) son opcionales.

## Open Questions

Ninguna. Las casas sin sitio verificable quedan fuera.

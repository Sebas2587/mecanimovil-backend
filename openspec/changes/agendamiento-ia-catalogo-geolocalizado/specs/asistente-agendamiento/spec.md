# asistente-agendamiento — delta catálogo geolocalizado

## ADDED Requirements

### Requirement: Precondiciones antes de candidatos
GET `candidatos-proveedor` SHALL recibir `servicio_ids`, `requiere_repuestos` y coordenadas del servicio (`lat`, `lng`). El ranking SHALL priorizar proveedores más cercanos cuando hay ubicación.

#### Scenario: Cliente con ubicación
- GIVEN servicio seleccionado y `requiere_repuestos=true`
- AND lat/lng de la dirección de servicio
- WHEN solicita candidatos
- THEN recibe hasta 3 ofertas con precio según repuestos y explicación que mencione proximidad si hay distancia calculada
- AND recibe `otros_candidatos` con proveedores del mismo servicio dentro del radio, excluyendo los recomendados

### Requirement: Secciones recomendados y otros proveedores
La respuesta SHALL incluir `candidatos_recomendados` (alias `candidatos`, hasta 3) y `otros_candidatos` (hasta 10). Los recomendados son el ranking por requisitos del servicio; `otros_candidatos` solo incluye proveedores con el mismo servicio dentro de `MAX_RADIO_KM` respecto a la dirección del usuario, sin repetir usuario de proveedor ya listado en recomendados.

#### Scenario: Otros en zona
- GIVEN hay más de 3 ofertas válidas dentro del radio
- WHEN solicita candidatos con ubicación
- THEN `candidatos` tiene hasta 3 recomendados
- AND `otros_candidatos` lista ofertas adicionales ordenadas por distancia, todas con `distancia_km` ≤ `radio_km`

### Requirement: Filtros de catálogo en candidatos
GET `candidatos-proveedor` SHALL devolver solo `OfertaServicio` que cumplan simultáneamente:

1. `disponible=true` y precio publicado o legacy (`precio_con_repuestos` / `precio_sin_repuestos`) > 0.
2. `servicio_id` en la lista solicitada.
3. Marca del vehículo: mismo criterio que `GET /servicios/{id}/ofertas/?marca=` (oferta explícita para la marca o genérica de proveedor verificado que atiende la marca).
4. Geolocalización: priorizar ofertas dentro de `MAX_RADIO_KM`; si no alcanzan 3, completar con las más cercanas fuera del radio.
5. Mecánico a domicilio: mismo universo que `proveedores_filtrados` (sin excluir por comuna); la distancia solo ordena resultados.
6. Si ninguna oferta tiene precio configurado pero sí `disponible=true`, el sistema MAY reintentar sin filtro de precio y marcar `catalogo_completo: false` en el desglose.

#### Scenario: Sin proveedores en radio
- GIVEN hay ofertas válidas de catálogo solo a 50 km
- WHEN solicita candidatos con ubicación
- THEN recibe hasta 3 candidatos ordenados por distancia ascendente
- AND la respuesta HTTP es 200 (no error 500)

#### Scenario: Oferta incompleta excluida
- GIVEN una oferta con `disponible=false` o precio publicado 0
- WHEN solicita candidatos
- THEN esa oferta no aparece en la respuesta

### Requirement: Flujo sin chat
La confirmación de catálogo SHALL crear solicitud `pendiente_confirmacion` sin abrir chat obligatorio. El proveedor acepta, rechaza o propone fecha; el pago se habilita solo tras confirmación sin fecha alternativa pendiente.

#### Scenario: Confirmación exitosa
- WHEN el cliente confirma un candidato con fecha preferida y ubicación
- THEN la solicitud queda dirigida al proveedor en estado pendiente de confirmación

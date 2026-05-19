# asistente-agendamiento — delta catálogo geolocalizado

## ADDED Requirements

### Requirement: Precondiciones antes de candidatos
GET `candidatos-proveedor` SHALL recibir `servicio_ids`, `requiere_repuestos` y coordenadas del servicio (`lat`, `lng`). El ranking SHALL priorizar proveedores más cercanos cuando hay ubicación.

#### Scenario: Cliente con ubicación
- GIVEN servicio seleccionado y `requiere_repuestos=true`
- AND lat/lng de la dirección de servicio
- WHEN solicita candidatos
- THEN recibe hasta 3 ofertas con precio según repuestos y explicación que mencione proximidad si hay distancia calculada

### Requirement: Filtros de catálogo en candidatos
GET `candidatos-proveedor` SHALL devolver solo `OfertaServicio` que cumplan simultáneamente:

1. `disponible=true` y precios de catálogo configurados (mano de obra y precio publicado > 0).
2. `servicio_id` en la lista solicitada.
3. Marca del vehículo: proveedor con la marca en `marcas_atendidas` y oferta con `marca_vehiculo_seleccionada` nula o igual a la marca del vehículo.
4. Geolocalización: priorizar ofertas dentro de `MAX_RADIO_KM`; si no alcanzan 3, completar con las más cercanas fuera del radio.
5. Mecánico a domicilio: dentro del radio por distancia o con comuna de cobertura que coincida con la dirección.

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

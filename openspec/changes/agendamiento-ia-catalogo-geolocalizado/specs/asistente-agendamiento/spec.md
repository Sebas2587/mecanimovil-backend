# asistente-agendamiento — delta catálogo geolocalizado

## ADDED Requirements

### Requirement: Precondiciones antes de candidatos
GET `candidatos-proveedor` SHALL recibir `servicio_ids`, `requiere_repuestos` y coordenadas del servicio (`lat`, `lng`). El ranking SHOULD priorizar proveedores más cercanos cuando hay ubicación.

#### Scenario: Cliente con ubicación
- GIVEN servicio de frenos seleccionado y `requiere_repuestos=true`
- AND lat/lng de la dirección de servicio
- WHEN solicita candidatos
- THEN recibe hasta 3 ofertas con precio según repuestos y explicación que mencione proximidad si hay distancia calculada

### Requirement: Flujo sin chat
La confirmación de catálogo SHALL crear solicitud `pendiente_confirmacion` sin abrir chat obligatorio. El proveedor acepta, rechaza o propone fecha; el pago se habilita solo tras confirmación sin fecha alternativa pendiente.

#### Scenario: Confirmación exitosa
- WHEN el cliente confirma un candidato con fecha preferida y ubicación
- THEN la solicitud queda dirigida al proveedor en estado pendiente de confirmación

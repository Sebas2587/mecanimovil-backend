# solicitudes Specification (delta)

## ADDED Requirements

### Requirement: Listado mis-solicitudes aislado por cliente
El endpoint `GET /api/ordenes/solicitudes-publicas/mis-solicitudes/` SHALL devolver únicamente solicitudes cuyo `cliente` es el del usuario autenticado.

#### Scenario: Dos clientes no comparten listado
- GIVEN Cliente A con solicitud publicada
- AND Cliente B autenticado sin solicitudes propias
- WHEN B llama a `mis-solicitudes`
- THEN la respuesta no incluye la solicitud de A

#### Scenario: List sin perfil cliente
- GIVEN usuario proveedor sin perfil Cliente
- WHEN llama a `GET /ordenes/solicitudes-publicas/` (list)
- THEN recibe lista vacía

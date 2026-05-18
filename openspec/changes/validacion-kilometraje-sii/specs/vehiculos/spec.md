# vehiculos Specification (delta)

## ADDED Requirements

### Requirement: Mileage SII en consulta de patente
`GET /api/vehiculos/consultar-patente/` SHALL incluir `mileage`, `tiene_mileage_sii` y `kilometraje_api` cuando GetAPI los provea.

#### Scenario: Mileage desde plate o appraisal
- GIVEN GetAPI plate devuelve mileage 80000
- WHEN el cliente consulta la patente
- THEN la respuesta incluye mileage=80000 y tiene_mileage_sii=true

### Requirement: Validar kilometraje del usuario
`GET /api/vehiculos/validar-kilometraje/` SHALL rechazar km menor que mileage SII.

#### Scenario: km menor que SII
- GIVEN mileage_sii=100000
- WHEN kilometraje=90000
- THEN nivel=error y code=km_menor_que_sii

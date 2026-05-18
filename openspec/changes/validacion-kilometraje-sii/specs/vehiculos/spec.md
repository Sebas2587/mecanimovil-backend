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

### Requirement: Plausibilidad de kilometraje sin referencia SII
Cuando `tiene_mileage_sii` es false, `validar-kilometraje` y la creación de vehículo SHALL validar plausibilidad según el año del vehículo sin consultar GetAPI.

#### Scenario: km coherente con edad del vehículo
- GIVEN tiene_mileage_sii=false y year=2012
- WHEN kilometraje=150000
- THEN nivel=ok y code=km_plausible_edad

#### Scenario: km muy bajo para la edad
- GIVEN tiene_mileage_sii=false y year=2010
- WHEN kilometraje=5000
- THEN nivel=error y code=km_muy_bajo_edad

#### Scenario: km alto pero plausible con confirmación
- GIVEN tiene_mileage_sii=false y year=2015
- WHEN kilometraje supera el máximo habitual pero no es extremo
- THEN nivel=aviso, requiere_confirmacion=true y code=km_alto_edad

#### Scenario: posible error de tipeo
- GIVEN tiene_mileage_sii=false y year=2012
- WHEN kilometraje=15800 y 158000 cae en la banda esperada
- THEN nivel=aviso, code=km_posible_typo y km_sugerido=158000

#### Scenario: Con mileage SII no aplica plausibilidad por edad
- GIVEN tiene_mileage_sii=true y mileage_sii=120000
- WHEN kilometraje=125000
- THEN solo se evalúa regla SII (code=km_coherente_sii) sin banda por edad

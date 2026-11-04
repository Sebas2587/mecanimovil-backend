# cotizacion-notas Specification (delta — human-store-names)

## ADDED Requirements

### Requirement: El slug de la tienda no se muestra

Donde la cotización muestra la casa (`motivo_seleccion`, `comentario` cuando es la nota, `casa_repuesto_nombre` y `proveedor_nombre`), el nombre **MUST** ser el de la casa y **MUST NOT** ser el slug del dominio.

#### Scenario: Filtro en TodoAuto

- GIVEN una ficha cuya tienda llega como «Todoautochile»
- WHEN la línea se guarda o se vuelve a leer
- THEN `motivo_seleccion` **SHALL** empezar con «TodoAuto:»
- AND `proveedor_nombre` y `casa_repuesto_nombre` **SHALL** ser «TodoAuto»

#### Scenario: Comercial Ramírez

- GIVEN una ficha cuya tienda llega como «Comercialramirezspa»
- WHEN la línea se muestra
- THEN el nombre visible **SHALL** ser «Comercial Ramírez»

#### Scenario: Nota ya guardada con el slug

- GIVEN una línea guardada con «Todoautochile: compatible con Fiat Bravo 1.4 T-Jet, mejor precio encontrado.»
- WHEN el taller pide la cotización
- THEN la nota **SHALL** empezar con «TodoAuto:»
- AND **SHALL NOT** contener «Todoautochile»

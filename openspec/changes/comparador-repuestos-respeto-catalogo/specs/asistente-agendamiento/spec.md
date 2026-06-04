# asistente-agendamiento — delta catálogo fiel (sin adaptar precio al cliente)

## ADDED Requirements

### Requirement: Precio mostrado = catálogo del proveedor
GET `candidatos-proveedor` SHALL serializar `precio`, `desglose` y `repuestos_info` según cómo
el proveedor configuró la oferta en catálogo (`_oferta_ofrece_repuestos`), **sin** sustituir por
`precio_sin_repuestos` cuando el cliente eligió solo mano de obra.

La preferencia `requiere_repuestos` SHALL usarse solo para:
- Inclusión en el pool (compatibles con y sin repuestos en catálogo).
- Ranking / `score_match` (priorizar alineación con la preferencia).
- Badges y mensajes de desajuste.

#### Scenario: Cliente solo MO, proveedor con batería solo repuestos
- GIVEN `requiere_repuestos=false`
- AND oferta con `precio_con_repuestos` y sin tarifa solo MO
- WHEN se serializa el candidato
- THEN `precio_total` y líneas usan precio con repuestos del catálogo
- AND `repuestos_info` está presente si el catálogo lo define

### Requirement: Ranking con preferencia del cliente
Con `requiere_repuestos=false`, el orden de candidatos MAY priorizar proveedores con tarifa
solo MO en catálogo, sin excluir proveedores que solo publican con repuestos.

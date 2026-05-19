# Spec delta — Fase 7 UX y operación

## ADDED Requirements

### Requirement: Comparador catálogo con contexto IA
En modo catálogo, el comparador SHALL mostrar al menos un candidato con interpretación previa, porcentaje de coincidencia y explicación del match cuando existan.

#### Scenario: Un solo proveedor en zona
- **WHEN** hay un candidato de catálogo
- **THEN** el cliente puede confirmarlo sin requerir una segunda oferta

### Requirement: Resumen operativo staff
GET `resumen-operacion` SHALL requerir usuario staff y retornar flags, conteo de patrones y métricas de catálogo sin texto de clientes.

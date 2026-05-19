# Diseño: Asistente agendamiento IA

## Persistencia
| Fase | Reglas |
|------|--------|
| `analizar-necesidad`, `candidatos-proveedor` | Sin escritura del texto consultado; sin logs con PII |
| `confirmar-candidato` | `descripcion_problema`, solicitud, oferta `origen=catalogo` |

## Módulos
`mecanimovilapp/apps/ordenes/services/agendamiento_ia/` — `motor_necesidad`, `motor_match`, `motor_confirmacion`.

## Feature flag
`AGENDAMIENTO_IA_ASISTIDO` (env, default False).

## Voz
STT on-device; backend solo recibe texto.

## Créditos
Consumo al confirmar proveedor (fase 2, alinear con `adjudicacion_publica`).

# Diseño: Asistente agendamiento IA

## Persistencia
| Fase | Reglas |
|------|--------|
| `analizar-necesidad`, `candidatos-proveedor` | Sin escritura del texto consultado; sin logs con PII |
| `confirmar-candidato` | `descripcion_problema`, solicitud, oferta `origen=catalogo` |

## Módulos
`mecanimovilapp/apps/ordenes/services/agendamiento_ia/` — `motor_necesidad`, `motor_match`, `motor_confirmacion`.

## Feature flag
- Backend Render: `AGENDAMIENTO_IA_ASISTIDO=True` en `render.yaml` (servicio `mecanimovil-api`).
- App usuarios: `app.json` → `extra.agendamientoIaAsistido` + `EXPO_PUBLIC_*` en `eas.json`.

## Voz
STT on-device; backend solo recibe texto.

## Créditos
Consumo al confirmar proveedor (fase 2, alinear con `adjudicacion_publica`).

## Flujo principal (catálogo geolocalizado)
1. Cliente elige vehículo, servicio(s) y si requiere repuestos.
2. Ubicación del servicio (lat/lng desde dirección).
3. Fecha/hora preferida.
4. Hasta 3 candidatos `OfertaServicio` ordenados por cercanía y rating.
5. Comparar precios (con/sin repuestos según elección) y confirmar → `pendiente_confirmacion`.
6. Proveedor acepta / rechaza / propone fecha → cliente paga si aplica.

## Backlog (no implementar ahora)
- Chat en flujo catálogo.
- APIs conversacionales oficiales (OpenAI, Gemini, etc.) para mensajería asistida.
- El análisis de texto (`analizar-necesidad`) permanece opcional para sugerir servicios; no bloquea el catálogo.

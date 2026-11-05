## Context

El editor llama `GET /api/ordenes/cotizaciones-canal/{id}/` (`CotizacionCanalViewSet.retrieve` → `CotizacionCanalSerializer`). Ahí se arma `url_referencia`, `validacion_estado` y `alertas_validacion`. La ficha sigue en `fuentes_detalle` aunque la validación la descarte, y el editor la muestra como origen sin link de referencia.

La banda de la IA a veces es el pack ($15.000–$25.000) y no llega al corte de $22.000 que parte la banda por bujía. $3.956 queda «bajo el rango» y se borra el link. Si el único monto guardado ya es $3.956 y el título sigue diciendo x4, se parte otra vez a $989.

## Goals / Non-Goals

**Goals:**

- Citar la ficha compatible cuyo precio por unidad calza con lo cobrado.
- No partir de nuevo un monto que ya es esa unidad.
- Probar el JSON de `GET /api/ordenes/cotizaciones-canal/{id}/`, no solo el serializer en memoria.

**Non-Goals:**

- No relajar el descarte por año, motor o modelo.
- No poner estos campos en `vista-previa`.

## Decisions

1. Si el motivo es solo de banda (`precio_bajo_banda` / `precio_alto_banda`) y la unidad de la ficha está a lo sumo a 8 % del precio cobrado, la ficha se cita. Año, motor y modelo siguen botando el link.
2. Si el monto de la ficha ya es el cobrado y no hay un estante más alto que partir, no se divide por el pack del título.
3. El detalle HTTP usa `?sin_retry=1` en el test para no disparar otra búsqueda.

## Risks / Trade-offs

- Una ficha cara que justo cae a 8 % del cobrado se cita. El cobrado ya es el precio de esa línea; la ficha lo respalda.
- Una banda realmente unitaria y un cobrado demasiado bajo siguen en `requiere_revision` sin link.

## Context

`_lineas_mano` dejaba en $0 las faenas que el modelo no nombró cuando el total ya coincidía con las que sí nombró. El editor muestra esas líneas.

La tarifa por servicio está en `OfertaServicio.precio_sin_repuestos` (o el costo de mano de obra con IVA). No hay un campo de tarifa por hora en el modelo; se lee si el taller o su configuración lo traen (`tarifa_hora_clp`). Las horas estándar salen de la familia del trabajo (pastillas 120 min, aceite, filtro y bujías 90 min).

## Goals / Non-Goals

**Goals:**

- Ninguna faena pedida queda en $0.
- La tarifa del taller gana al estimado del modelo. La hora configurada también.
- El total es la suma. Un total del modelo que no cubre todas las faenas no recorta ni rellena las demás.

**Non-Goals:**

- Inventar una tarifa por hora en la base de datos.
- Cambiar el precio de una faena que ya viene del catálogo del taller.

## Decisions

1. Orden: tarifa del servicio, luego hora × minutos estándar, luego el monto del modelo para esa faena, luego el recálculo.
2. El recálculo usa la mediana de las horas que implican las faenas que el modelo sí cotizó. Sin ninguna, $15.000 por hora × los minutos estándar.
3. Una sola faena sin desglose se queda con el total del modelo: ese total es su estimado.
4. `mano_obra_clp` se reemplaza por la suma después de completar las líneas.

## Risks / Trade-offs

- Sin tarifa ni hora, el aceite y las bujías de la cotización 208 salen a $20.625 cada uno, porque el modelo cotizó pastillas a $35.000 (2 h) y el filtro de aire a $15.000 (1,5 h).

## Context

El lector del pedido y la salida del modelo escriben mano de obra. Si la descripción repite el pedido con otros nombres, el lector emitía las dos listas. «Mantención con pastillas» se leía como trabajo sin repuesto y la pieza se descartaba antes de buscar tienda.

## Goals / Non-Goals

**Goals:**

- Una línea por trabajo, con un precio. Bujías y bobinas en la misma faena siguen sumando sus montos.
- La pastilla nombrada queda en `repuestos` y en el PDF. Un hit que no pasa la compuerta no borra esa línea.

**Non-Goals:**

- No cambia la tarifa por hora ni el precio de una faena que el modelo sí cotizó.
- No se debilita la compuerta de año, motor o banda.

## Decisions

1. La lista de faenas del lector es la única. Se deduplica por los tokens del trabajo: pastillas con pastillas, el pack de aceite consigo mismo, el filtro de aire aparte.
2. Al copiar precios del modelo, dos líneas del mismo trabajo no se suman. Dos piezas distintas de una faena conjunta sí.
3. Una mantención que nombra pastillas, bujías, filtro o aceite deja esa pieza. Una revisión o limpieza sin pieza sigue sin repuesto.

## Risks / Trade-offs

- «Cambio de aceite» y «Cambio de aceite y filtro» se leen como el mismo trabajo cuando uno contiene al otro. El filtro de aire no entra en ese grupo.

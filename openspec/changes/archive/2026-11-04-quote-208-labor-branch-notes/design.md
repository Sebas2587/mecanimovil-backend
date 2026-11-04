## Context

El pedido «Cambio de pastillas…, aceite y filtro de aceite, bujías y filtro de aire» se parte por comas. Solo el primer tramo y «filtro de aire» heredaban una faena. El resto quedaba como repuesto sin mano de obra.

`cubre_todo` era verdadero cuando todas las líneas apuntaban a Indra, aunque ninguna tuviera ficha. Indra no publica catálogo.

`sucursal_para` comparaba solo `TallerDireccion.comuna`. Si la comuna iba en la calle («John Kennedy 709, La Florida») o el campo venía vacío, caía en Lira 664.

El techo de bujías ($8.000–$11.250) no limitaba un unitario de $15.000 ya escrito por la IA.

## Goals / Non-Goals

**Goals:**

- Una línea de mano de obra por cada trabajo de esa frase.
- Nota de consulta con la referencia propia de la línea. «Tiene todos» solo con ficha y precio en cada línea.
- Sucursal cuya comuna aparece en la dirección configurada del taller. La Florida → Vicuña Mackenna 8580.
- El unitario asumido de bujías, sin tienda, no supera el techo por unidad de su banda.

**Non-Goals:**

- Inventar tarifas de mano de obra que el modelo no entregó: la línea existe y el monto queda en 0 si nadie lo cotizó.
- Geocodificar metros entre el taller y la sucursal.
- Cambiar el precio de una ficha que sí pasó las compuertas.

## Decisions

1. El verbo de cambio que abre la lista («Cambio de») se copia a los tramos siguientes que no traen verbo propio. «Aceite y filtro de aceite» sigue siendo una sola faena y dos piezas.
2. `catalogo_online` falso no verifica stock. Una URL de esa casa con precio que pasó las compuertas sí.
3. La sucursal se elige buscando la comuna dentro de calle, número, comuna, ciudad y la dirección del usuario. Una comuna específica gana a «Santiago» si ambas aparecen. Sin texto de dirección, la primera sucursal que no es Concepción.
4. El PDF vuelve a elegir la sucursal al generarse, con la dirección actual del taller.
5. Sin ficha, después de partir un juego, `precio_unitario_clp` de bujías se recorta al techo ya dividido por la cantidad.

## Risks / Trade-offs

- Faenas sin monto quedan en $0 hasta que el taller las complete. Se ven en el editor.
- «Filtro de aire» y «Filtro de aceite» no pueden colapsar por compartir la palabra filtro.

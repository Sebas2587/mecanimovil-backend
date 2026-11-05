## Context

`precio_unitario_desde_pack` parte el juego de bujías al guardar el precio cobrado, pero el costo y la ficha siguen leyendo el estante ($15.826). Si ese estante no pasa la banda por unidad, la línea pierde `url_referencia` y `casa_sugerida` queda vacía cuando no hay casa guardada.

## Goals / Non-Goals

**Goals:**

- Cada línea de la respuesta del taller trae unidad, ficha y casa coherentes, más `validacion_estado`, `validacion_motivo` y `alertas`.
- Un pack x4, un juego, un kit o un set se cotiza por la unidad de la línea. Un bidón de aceite, por litro.
- Una ficha de otro año, otro motor u otro modelo no se cita.
- El margen no baja de −100 % por haber mezclado el pack con la unidad. Si no se puede corregir, la línea pide revisión.
- Un precio asumido no pisa una ficha válida. Si se asume, el motivo lo dice.

**Non-Goals:**

- No llamar a un LLM en cada lectura. El título, el año y el motor ya se deciden con las compuertas de la búsqueda.
- No guardar una tabla nueva de rangos. La banda que ya trae la línea, si existe, es el rango.

## Decisions

1. La validación corre al serializar, sobre las fichas ya guardadas. Así la cotización en vivo se corrige sin regenerarla.
2. El costo de una ficha válida es el precio por unidad de esa ficha, no el estante del pack ni el monto asumido.
3. `casa_sugerida` es la casa de la línea o, si no hay, la especialista de la marca.
4. `alertas_validacion` en la cotización junta las líneas que no quedaron en `ok` o que tienen una alerta.

## Risks / Trade-offs

- [Una ficha genérica sin el nombre del auto se usa si no lo contradice] → La alerta lo dice. Si nombra otro año, otro motor u otro modelo, se descarta.
- [Partir un juego de pastillas] → Solo se parte cuando el título trae cantidad (x4, kit 4) y la línea pide al menos esas unidades, o cuando es un juego de bujías.

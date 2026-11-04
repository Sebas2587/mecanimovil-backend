## Context

La re-búsqueda al abrir un borrador corre `buscar_precios_web_cotizacion_task`. `_rechazo_precio_pastilla` dejaba pasar una bujía Bravo 1.4 cuyo unitario superaba la banda pero no llegaba a 2,5× el máximo. $28.432 contra un techo de $12.000 entra en ese hueco. El título sin «juego» o «x4» no se parte, y la nota copiaba el estante a `precio_referencia_clp`.

## Goals / Non-Goals

**Goals:**

- La misma función que decide si una ficha se elige decide si su monto se puede citar.
- El número citado de una bujía es por unidad. El juego se parte solo cuando el título lo dice y esa unidad cae dentro de la banda.
- Un hit que no pasa no se adjunta en la tarea, ni queda como referencia en la nota o en el PDF.

**Non-Goals:**

- No se inventa un /4 cuando el título no dice que es un juego.
- No se endurece el piso del 40% de las pastillas Bravo 1.4.
- No cambia el precio de la mano de obra ni la frase verificada «tiene todos los repuestos de esta cotización».

## Decisions

1. Después de partir el pack, una bujía con unidad > techo es `precio_alto_banda` y con unidad < piso es `precio_bajo_banda`, antes del retorno temprano de Bravo 1.4.
2. `monto_por_unidad_citable` devuelve 0 cuando no hay un unitario citable. La nota, el PDF y la prioridad de la especialista lo usan. 0 borra `referencia_tienda` y `precio_referencia_clp`.
3. Si el monto ya está dentro de la banda, se le quitan las palabras de pack al título antes de volver a medir, para no partir otra vez una unidad ya cotizada.
4. La tarea, al rechazar el hit, no escribe la ficha y limpia la referencia que hubiera quedado de una búsqueda anterior.

## Risks / Trade-offs

- Una bujía Bravo justo bajo el piso deja de entrar por la regla del 40%. Esa regla sigue valiendo para pastillas.
- Una ficha de $28.432 sin la palabra juego no se cita, aunque 28.432 / 4 cayera cerca de la banda.

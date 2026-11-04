## Why

En la cotización 209, al abrirla, la re-búsqueda «Precios de tienda» dejó en las bujías la nota «Referencia: Lider $28.432». La línea sigue sin tienda y con el precio asumido de $12.000 por unidad. Ese monto de estante (o un juego mostrado como si fuera cada bujía) no pasó las mismas compuertas que una ficha elegida.

## What Changes

- Una referencia que se cita en la nota o en el PDF de compra MUST pasar `_motivo_calidad_pastilla` (modelo, año, motor y banda) y MUST ser el precio por unidad. Si no pasa, no se cita y el hit no se pega a la línea.
- En bujías, la unidad por encima del techo de la banda o por debajo del piso es `precio_alto_banda` o `precio_bajo_banda`, aunque el título nombre Bravo 1.4 y el estante quede bajo 2,5× el máximo. Un juego de 4 se parte antes de medir: $36.000 son $9.000 y eso sí se puede citar.
- La re-búsqueda al abrir la cotización usa esa misma compuerta antes de escribir tienda, precio o referencia.

## Capabilities

### New Capabilities

- (ninguna)

### Modified Capabilities

- `cotizacion-notas`: la referencia citada tiene que haber pasado las compuertas y ser por unidad.
- `orden-compra-repuestos`: el PDF no imprime una referencia que esas compuertas rechazan.
- `casas-especialistas`: recomendar la especialista no conserva una referencia de bujía fuera de la banda.

## Impact

- `busqueda_web_repuestos.py`, `tasks.py`, `generador.py`, `enriquecer_repuestos.py`, `orden_compra_pdf.py`.
- Sin migración.

## Why

En la cotización 210 la mano de obra salió duplicada (ocho líneas, $250.000) y la línea de pastillas de freno no apareció ni en el borrador ni en el PDF. El pedido era una mantención con pastillas, aceite y filtro, bujías y filtro de aire.

## What Changes

- Cada trabajo pedido tiene una sola línea de mano de obra. Si la IA y el lector del pedido nombran el mismo trabajo («Mantención: pastillas» y «Cambio de pastillas»), queda uno, con un solo precio, y el total es la suma.
- «Mantención con pastillas de freno» compra las pastillas. La línea de repuesto sigue en el borrador y en el PDF aunque ninguna ficha pase las compuertas.

## Capabilities

### New Capabilities

- (ninguna)

### Modified Capabilities

- `mano-obra-pedido`: un trabajo no se cobra dos veces, y la pieza nombrada en la mantención no desaparece.

## Impact

- `separar_pedido_taller.py`. Sin migración.

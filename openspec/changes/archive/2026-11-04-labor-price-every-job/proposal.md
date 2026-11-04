## Why

La cotización 208 dejó el cambio de aceite y el de bujías en $0. Un taller no cobra cero por un trabajo pedido. El total de la IA cubría solo las faenas que el modelo desglosó, y el resto se anuló para que la suma calzara.

## What Changes

- Cada faena pedida tiene un precio de mano de obra mayor que cero.
- Primero la tarifa del taller para ese servicio. Si no hay, la tarifa por hora configurada por las horas estándar de esa faena. Si tampoco hay, el monto que el modelo dio para esa faena.
- Una faena que el modelo no cotizó se recalcula. No se parte el total del modelo para rellenar huecos.
- `mano_obra_clp` es la suma de las faenas.

## Capabilities

### New Capabilities

- (ninguna)

### Modified Capabilities

- `mano-obra-pedido`: el precio de cada faena y el total.

## Impact

- `separar_pedido_taller.py`, `normalizar.py`, `generador.py`, `cotizacion_borrador.py`.
- Sin migración.

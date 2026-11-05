## Why

El encabezado de la orden de compra arma la dirección del taller pegando la calle (que a veces ya trae número, comuna y ciudad) con los campos `numero`, `comuna`, `ciudad` y `region`. En la cotización 214 eso imprime «John Kennedy, 709, 709, La Florida, Santiago» a partir de «John Kennedy, 709, La Florida, Santiago, Santiago» más el número y la comuna por separado.

## What Changes

- La dirección del encabezado del PDF de compra se arma sin repetir número, comuna ni ciudad, comparando esos trozos sin distinguir mayúsculas.
- El caso de Kennedy queda «John Kennedy 709, La Florida, Santiago».
- No cambia el agrupado de casas, los precios ni la vista pública.

## Capabilities

### New Capabilities

### Modified Capabilities

- `orden-compra-repuestos`: la dirección del taller en el encabezado no repite número, comuna ni ciudad.

## Impact

- Código: `orden_compra_pdf.py`. Sin endpoint nuevo y sin migración.
- La sucursal de la casa de repuestos sigue eligiendo La Florida o Lira con la dirección cruda del taller; este cambio solo afecta el texto del encabezado.

## Non-goals

- No reescribir `direccion_completa` del modelo ni el parseo al guardar la dirección.
- No cambiar la dirección de la sucursal de la casa de repuestos.
- No inventar comuna o ciudad que no estén en los datos.

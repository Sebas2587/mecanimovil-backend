## Why

La caja lista anclas por id. El frontend necesita nombre, patente y folio ya guardados, sin una consulta por fila y sin inventar datos.

## What Changes

- `cliente_nombre`, `vehiculo_patente` y `folio` en las páginas de casos y movimientos.
- La identidad se resuelve en lote y solo para anclas de ese taller. Un dato ausente queda null. Un GET no crea folio.

## Capabilities

### New Capabilities

- Ninguna.

### Modified Capabilities

- `caja-taller`: identidad legible de la página.

## Impact

- Campos aditivos. Sin migración. Sin teléfono, correo ni dirección.

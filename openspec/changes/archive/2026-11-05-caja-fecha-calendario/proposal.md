## Why

`2026-02-30` tiene forma de fecha y no existe. `date.fromisoformat` lanza `ValueError` y el POST de cobros solo atrapa `CajaError`, así que la petición terminaba en 500.

## What Changes

- Una fecha imposible responde 400 `fecha_invalida` y no crea movimiento.

## Capabilities

### New Capabilities

- Ninguna.

### Modified Capabilities

- `caja-taller`: calendario inválido en el cobro manual.

## Impact

- Sin migración. `resumen.faltantes` sigue siendo una lista de códigos.

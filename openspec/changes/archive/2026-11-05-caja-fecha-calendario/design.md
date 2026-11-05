## Context

El POST toma `fecha_efectiva` como texto. El formato ISO de un día imposible igual dispara `ValueError`.

## Decisions

1. Ese error se convierte en `CajaError` `fecha_invalida` antes de registrar el movimiento.
2. El GET de un período imposible ya respondía 400 `periodo_invalido`. No cambia.

## Migration Plan

No hay migración.

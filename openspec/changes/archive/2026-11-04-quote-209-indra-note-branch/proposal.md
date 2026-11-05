## Why

La cotización 209, ya con la mano de obra correcta, sigue mostrando en las cinco líneas «Indra: especialista FIAT, tiene todos los repuestos. Precio a consultar.» y el PDF imprime Indra en Avenida Brasil 28, Santiago. Indra no tiene ficha con precio, y el taller está en La Florida.

## What Changes

- La nota vieja que afirma stock y deja el precio a consultar se reescribe al leer la cotización y al cerrar la tarea asíncrona. Cada línea queda en «consulta disponibilidad y precio» con la referencia de su propia tienda validada, y la marca en título (Fiat, no FIAT).
- «Tiene todos los repuestos de esta cotización» se mantiene solo cuando cada línea tiene ficha con precio de esa casa.
- Si varias sucursales comparten la comuna Santiago, se usa la primera de la lista. Una comuna específica del taller (también si está en otra dirección guardada del usuario) gana a Santiago. La ciudad «Santiago» sola no elige Avenida Brasil 28.

## Capabilities

### New Capabilities

- (ninguna)

### Modified Capabilities

- `casas-especialistas`: la primera sucursal de Santiago cuando no hay comuna específica; la dirección física y las direcciones guardadas del usuario entran al match.
- `cotizacion-notas`: la nota vieja de stock no verificado se reemplaza en la lectura y en la tarea asíncrona.
- `orden-compra-repuestos`: el PDF no imprime Avenida Brasil 28 cuando el taller no está en esa sucursal.

## Impact

- `casas_especialistas.py`, `generador.py`, `enriquecer_repuestos.py`.
- Sin migración. No se escribe a mano la dirección del taller.

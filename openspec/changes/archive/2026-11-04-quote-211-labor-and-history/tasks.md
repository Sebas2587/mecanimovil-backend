## 1. Mano de obra (app ordenes)

- [x] 1.1 En `separar_pedido_taller.py`, titular «Cambio de» la pieza cuando la mantención la nombra, y quitar el rótulo «Mantención» si ya hay trabajos. Test unitario del pedido de la cotización 211.

## 2. Historial no es casa (app ordenes)

- [x] 2.1 En `casas_especialistas.py` y `generador.py`, no usar «Historial del taller» como casa: la pieza queda en la especialista, con referencia del historial y el mismo unitario. Test unitario.
- [x] 2.2 En `orden_compra_pdf.py` y la nota de referencia, el PDF agrupa bajo la especialista, no repite la sucursal y dice «A consultar. Referencia: historial del taller». Test del PDF.

## 3. Cierre

- [x] 3.1 Validar el change OpenSpec, correr la suite de cotización y archivar el change.

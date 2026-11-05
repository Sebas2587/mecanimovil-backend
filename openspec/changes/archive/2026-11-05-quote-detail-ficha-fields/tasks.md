## 1. Ficha compatible en el detalle

- [x] 1.1 No descartar por banda una ficha cuya unidad ya es el precio cobrado, y no volver a partir ese monto
- [x] 1.2 Test HTTP de `GET /api/ordenes/cotizaciones-canal/{id}/` con la ficha Entretuercas 2007-2014 x4 a $15.826 y banda de pack: link, tienda, `precio_verificado_clp` 3956, `validacion_estado` y `alertas_validacion`; la vista previa no los trae

## 2. Cierre

- [x] 2.1 Validar el cambio OpenSpec y correr la suite de cotización

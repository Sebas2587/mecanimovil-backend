# short-mechanic-notes

## Why

La nota de cada línea de repuesto le mostraba al taller las búsquedas, los títulos rechazados y motivos internos (`anio_incompatible`, `precio_bajo_banda`). El texto se cortaba en pantalla y el mecánico no podía usarlo.

## What Changes

- La nota visible (`motivo_seleccion` y, si no hay una descripción de la pieza, `comentario`) queda en una frase de a lo más 160 caracteres, en español simple.
- Con tienda: «Lider: compatible con Fiat Bravo 1.4 T-Jet, mejor precio encontrado.»
- Sin tienda: «Precio estimado. No encontramos este repuesto para tu auto (Bravo 1.4 T-Jet 2010); confirma precio y tienda.» Como mucho se agrega un resumen («Lo encontrado era para otro año o modelo.» u «Lo encontrado era otra pieza.»).
- Oferta: «TodoAuto, precio en oferta (normal $10.990).» El precio de lista sale del tachado de la ficha.
- Consultas, URLs, títulos repetidos y códigos quedan solo en el log.
- No hay endpoint nuevo ni migración. `comentario` y `motivo_seleccion` siguen siendo texto libre.

## Non-goals

- No se cambia el criterio que acepta o rechaza una ficha.
- No se reescribe el motivo interno del selector de casas; los tests de ese módulo siguen leyendo «mejor precio» y «consolidado».
- No se toca la nota de configuración del taller («Precio del taller para…»).
- No se modifica el frontend: este repo no interpreta el texto viejo salvo para reconocer que una nota es de la búsqueda y poder reemplazarla.

## API

- Sin endpoints nuevos. Los campos existentes siguen siendo `CharField` libres.
- La cotización pública y el PDF muestran `comentario`. El taller ve también `motivo_seleccion`.
- `precio_normal_clp` puede viajar en el JSON de la línea para armar la frase de oferta. No entra en las claves públicas.

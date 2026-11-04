# short-notes-all-paths

## Why

La nota corta ya sale de la búsqueda web, pero la cotización en vivo sigue mostrando el texto largo («Se buscó…», «Sin ficha de…», «cubre otros años», «nombra otro motor») y, cuando hay tienda, «Única casa con stock disponible (Comercialramirezspa)». Esos textos los vuelven a escribir la respuesta de una casa, el nombre crudo del dominio y cualquier línea ya guardada que el API entrega tal cual.

## What Changes

- Toda nota visible (`motivo_seleccion`, `comentario` cuando es una nota, y cualquier otro texto de la línea que traiga esas frases) pasa por el constructor corto, también al final de la tarea async y al leer la cotización.
- Con tienda, la frase es «Comercial Ramírez: compatible con Fiat Bravo 1.4 T-Jet, mejor precio encontrado.» El chip usa el nombre de persona, no el dominio.
- El selector de casas sigue devolviendo su motivo interno. La línea y el log no se mezclan.
- El frontend del taller solo muestra `motivo_seleccion`. No arma la frase.

## Non-goals

- No cambia qué ficha se acepta o se rechaza.
- No se reescriben los tests del motivo interno del selector.
- La nota «Precio del taller para…» y la descripción de la pieza (juego, litros, viscosidad) se conservan.

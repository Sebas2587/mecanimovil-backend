# Design — nota corta para el mecánico

## Decisión

`_aviso_sin_ficha` sigue clasificando títulos (año, motor, modelo, otra pieza) y escribe ese texto largo en el log `busqueda_web_repuestos[aviso]`. Lo que devuelve en `detalle` es `nota_sin_tienda`.

`anotar_busqueda_sin_ficha` copia solo esa frase. Si le llega un texto viejo («Se buscó…»), lo registra en `nota_busqueda_tecnica` y lo cambia por la frase corta.

`_aplicar_seleccion_casa_repuestos` escribe la frase de tienda u oferta en `motivo_seleccion`. El motivo del selector («Única casa…», «Consolidado en una sola casa…») se loguea como `motivo_interno` y no se muestra. `consolidacion_aplicada` no cambia. Una descripción de la pieza («Juego completo…», «por litro») se queda en `comentario`.

El precio tachado se lee de `<del>` / «precio original» solo si es mayor que el cobrado y menor que el triple. Si no, no hay nota de oferta.

## Dónde vive

- Frases: `enriquecer_repuestos.py` (`nota_sin_tienda`, `nota_con_tienda`, `nota_oferta`, `nota_cola_caida`).
- Búsqueda: `busqueda_web_repuestos.py`.
- Selección visible: `generador.py`.
- Cola caída: `disparar_busqueda_web.py`.

## Qué no se parsea

Ningún serializer exige el formato «Se buscó». `nota_de_busqueda` reconoce tanto el prefijo viejo como la frase nueva, para reemplazar una nota larga en un reintento y para no pisar «Juego completo» ni «5W40 sintético».

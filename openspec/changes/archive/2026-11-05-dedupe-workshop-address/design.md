## Context

`TallerDireccion.direccion_completa` concatena `calle`, `numero`, `comuna`, `ciudad` y `region` con comas. En talleres reales `calle` ya puede ser la línea geocodificada («John Kennedy, 709, La Florida, Santiago, Santiago») y `numero` / `comuna` vienen además en campos propios. El PDF de compra imprime esa concatenación en el encabezado.

## Goals / Non-Goals

**Goals:**

- El encabezado muestra cada número, comuna y ciudad una sola vez, sin distinguir mayúsculas.
- Kennedy queda «John Kennedy 709, La Florida, Santiago»: la calle y el número van juntos, y la ciudad repetida se cae.

**Non-Goals:**

- No corregir el registro guardado ni `direccion_completa`.
- No usar esta cadena para elegir la sucursal de la casa de repuestos.

## Decisions

1. Armar el encabezado desde los trozos de `calle` más `numero`, `comuna`, `ciudad` y `region`, no desde `direccion_completa`. Un trozo que ya apareció (igualdad casefold, espacios colapsados) no se vuelve a agregar. «Chile», «s/n» y los marcadores «Sin comuna» / «Sin ciudad» no se imprimen.
2. Si el número es un trozo propio y la calle todavía no lo contiene como token, se pega a la calle con un espacio (`John Kennedy` + `709` → `John Kennedy 709`). Si la calle ya dice «John Kennedy 709», el campo `numero` no se repite.
3. La región se imprime solo cuando no es la misma ciudad ni la misma comuna. Así «Santiago, Santiago» queda en un Santiago y «Metropolitana» se conserva.
4. Si no hay `direccion_fisica`, se deduplican los trozos de `usuario.direccion` con la misma regla.

## Risks / Trade-offs

- [Una calle cuyo nombre es el de la comuna se funde con la comuna] → La comparación es por trozo completo, no por subcadena, salvo el número de la calle.
- [El encabezado deja de verse igual que `direccion_completa`] → Es el resultado pedido; el modelo no cambia.

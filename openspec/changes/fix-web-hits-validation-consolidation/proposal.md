# Fix Web Hits Validation, House Selection & Consolidation

## Why

Four production bugs in the provider web 'Generar con IA' flow cause incorrect part matching, missing provider information, failed consolidation, and inconsistent price ranges:

1. **Part-type validation gap**: `_validar_tipo_parte` logic exists only in `_mejor_hit()` for catalog/historial hits, but is NOT applied to `PrecioRepuestoWeb` (web cache) or `.cl` tiendas hits in `_candidatos_web_cache` (~line 846). Production: 'Aceite de motor' matched 'Enfriador aceite Fiat Bravo 1.4 | Euroespecialista' $31.490 — wrong part type. 

2. **House selection field mismatch**: `_aplicar_seleccion_casa_repuestos` (currently non-existent) should read `proveedor_nombre`/`fuente_marketplace` from catalog/historial hits, but web hits use `tienda`/`dominio`/`url_producto`/`nombre_producto`. These fields are never mapped to `OpcionCasa`, so **every web-sourced candidate store is lost** and `motivo_seleccion` shows 'No se encontraron proveedores…' even when valid tiendas exist.

3. **Consolidation never runs**: Because bug #2 leaves `todas_las_opciones` empty for web hits, `consolidar_si_posible` always returns `None`. When fixed, it should detect when a single store can provide all parts within 110% of distributed-optimal and set `consolidacion_aplicada=True`.

4. **Range inconsistency**: `_ajustar_rangos_consistentes` (currently non-existent) never validates that `precio_min_clp`/`precio_max_clp` are in the same units as the line item's displayed price. Production: oil filter range $30.000–$50.000 (per-unit) vs line total 4×$31.490=$125.960 (quantity × unit), causing the line price to fall outside its own stated range.

## What Changes

1. **Add part-type validation to web cache hits**:
   - Extract the existing validation logic from `_mejor_hit()` into a standalone `_validar_tipo_parte(nombre_linea: str, titulo_ficha: str) -> bool` function that reuses `_ficha_cubre_pieza` and requires the listing title to contain the part-type keyword (e.g., 'pastilla' for pads).
   - Apply `_validar_tipo_parte` at every point a listing is attached:
     - In `_candidatos_web_cache` before appending each hit
     - In `_mejor_hit` before comparing scores
     - In `enriquecer_repuestos_cotizacion` when attaching web/ML hits
   - Reject mismatches (log + skip) and continue searching other candidates.

2. **Implement `_aplicar_seleccion_casa_repuestos` in enriquecer_repuestos.py**:
   - Create `_aplicar_seleccion_casa_repuestos(repuestos: list[dict]) -> list[dict]` that:
     - For each repuesto, collect all candidate stores from:
       - Catalog/historial: read `proveedor_nombre`, `fuente_marketplace`, `precio_unitario_clp`
       - Web hits: read `tienda` (from `PrecioRepuestoWeb.tienda`), `dominio`, `url_producto`, `nombre_producto`, `precio_unitario_clp`
     - Map each candidate to `OpcionCasa(casa=tienda/proveedor, proveedor_id=hash, precio_clp=precio_unitario, stock_disponible=True)`
     - Call `seleccionar_casa_optima(opciones)` to get `ResultadoSeleccion`
     - Populate `motivo_seleccion` (Spanish) naming the chosen store and reason (precio/stock/compatibilidad/consolidación)
     - Populate `alternativas_descartadas` with other stores + reasons
     - Only show 'No se encontraron proveedores…' when `opciones` is truly empty
   - Call `_aplicar_seleccion_casa_repuestos` at the end of `enriquecer_repuestos_cotizacion` before returning.

3. **Enable consolidation**:
   - After `_aplicar_seleccion_casa_repuestos` populates `todas_las_opciones`, call `consolidar_si_posible(repuestos, todas_las_opciones)`.
   - When consolidation returns results, replace per-part selections with the consolidated choice and set `consolidacion_aplicada=True` on each line.
   - Log consolidation decisions.

4. **Implement `_ajustar_rangos_consistentes` in resolver_precio.py**:
   - Create `_ajustar_rangos_consistentes(repuestos: list[dict]) -> list[dict]` that:
     - For each repuesto with `cantidad > 1`:
       - Check if `precio_min_clp`/`precio_max_clp` are per-unit or per-line (compare against `precio_unitario_clp` and `cantidad`)
       - If ranges are per-unit but the UI displays line totals, multiply both by `cantidad`
       - If ranges are per-line but the UI displays per-unit, divide both by `cantidad`
     - Ensure `precio_unitario_clp * cantidad` always falls within `[precio_min_clp, precio_max_clp]`
   - Call `_ajustar_rangos_consistentes` in `generar_cotizacion_ia` after enrichment and before returning.

## Testing

- Unit tests with realistic production data fixtures:
  - FIAT BRAVO 2010 1.4 "Cambio de pastillas de freno delanteras y cambio de aceite de motor con filtro"
  - Fixtures include oil cooler listing (wrong part type, rejected), pads generic listing (missing keyword, rejected), filter accepted
  - `motivo_seleccion` names the chosen store + reason
  - Consolidation when one store has all parts within 110%
  - Ranges consistent (line price falls within range)
- Run full backend test suite with pinned dependencies

## Dependencies

None — internal refactor of existing enriquecer_repuestos.py, seleccion_casa_repuestos.py, and resolver_precio.py modules.

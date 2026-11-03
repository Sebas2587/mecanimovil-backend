# Tasks

## Implementation

- [x] Extract `_validar_tipo_parte(nombre_linea, titulo_ficha) -> bool` in enriquecer_repuestos.py
- [x] Apply `_validar_tipo_parte` in `_candidatos_web_cache` before appending each hit
- [x] Apply `_validar_tipo_parte` in `_mejor_hit` before score comparison
- [x] Apply `_validar_tipo_parte` when attaching web/ML hits in `enriquecer_repuestos_cotizacion`
- [x] Implement `_aplicar_seleccion_casa_repuestos(repuestos, hits_by_part)` in enriquecer_repuestos.py
- [x] Map catalog/historial hits (`proveedor_nombre`) to `OpcionCasa`
- [x] Map web hits (`tienda`, `dominio`) to `OpcionCasa`
- [x] Call `seleccionar_casa_optima` per part
- [x] Call `consolidar_si_posible` with all options
- [x] Populate `motivo_seleccion` and `alternativas_descartadas` on each repuesto
- [x] Call `_aplicar_seleccion_casa_repuestos` at end of `enriquecer_repuestos_cotizacion`
- [x] Implement `_ajustar_rangos_consistentes(repuestos)` in resolver_precio.py
- [x] Detect per-unit vs per-line ranges by comparing line_total to range bounds
- [x] Adjust ranges to match line total units
- [x] Call `_ajustar_rangos_consistentes` in `generar_cotizacion_ia` after enrichment

## Testing

- [x] Create realistic test fixtures for FIAT BRAVO 2010 1.4 with web hits
- [x] Test: oil cooler listing rejected (wrong part type)
- [x] Test: generic pads listing rejected (missing keyword)
- [x] Test: filter listing accepted
- [x] Test: web hits mapped to OpcionCasa
- [x] Test: `motivo_seleccion` names chosen store + reason
- [x] Test: consolidation runs when one store within 110%
- [x] Test: ranges adjusted for multi-quantity lines
- [x] Run full backend test suite with pinned dependencies
- [x] Verify test output shows all bugs fixed

## Validation

- [ ] Commit changes with descriptive message
- [ ] Push branch to remote
- [ ] Create PR with bug descriptions and fix summary
- [ ] Report PR URL and test results

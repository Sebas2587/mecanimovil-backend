# Tasks

## Implementation

- [ ] Extract `_validar_tipo_parte(nombre_linea, titulo_ficha) -> bool` in enriquecer_repuestos.py
- [ ] Apply `_validar_tipo_parte` in `_candidatos_web_cache` before appending each hit
- [ ] Apply `_validar_tipo_parte` in `_mejor_hit` before score comparison
- [ ] Apply `_validar_tipo_parte` when attaching web/ML hits in `enriquecer_repuestos_cotizacion`
- [ ] Implement `_aplicar_seleccion_casa_repuestos(repuestos, hits_by_part)` in enriquecer_repuestos.py
- [ ] Map catalog/historial hits (`proveedor_nombre`) to `OpcionCasa`
- [ ] Map web hits (`tienda`, `dominio`) to `OpcionCasa`
- [ ] Call `seleccionar_casa_optima` per part
- [ ] Call `consolidar_si_posible` with all options
- [ ] Populate `motivo_seleccion` and `alternativas_descartadas` on each repuesto
- [ ] Call `_aplicar_seleccion_casa_repuestos` at end of `enriquecer_repuestos_cotizacion`
- [ ] Implement `_ajustar_rangos_consistentes(repuestos)` in resolver_precio.py
- [ ] Detect per-unit vs per-line ranges by comparing line_total to range bounds
- [ ] Adjust ranges to match line total units
- [ ] Call `_ajustar_rangos_consistentes` in `generar_cotizacion_ia` after enrichment

## Testing

- [ ] Create realistic test fixtures for FIAT BRAVO 2010 1.4 with web hits
- [ ] Test: oil cooler listing rejected (wrong part type)
- [ ] Test: generic pads listing rejected (missing keyword)
- [ ] Test: filter listing accepted
- [ ] Test: web hits mapped to OpcionCasa
- [ ] Test: `motivo_seleccion` names chosen store + reason
- [ ] Test: consolidation runs when one store within 110%
- [ ] Test: ranges adjusted for multi-quantity lines
- [ ] Run full backend test suite with pinned dependencies
- [ ] Verify test output shows all bugs fixed

## Validation

- [ ] Commit changes with descriptive message
- [ ] Push branch to remote
- [ ] Create PR with bug descriptions and fix summary
- [ ] Report PR URL and test results

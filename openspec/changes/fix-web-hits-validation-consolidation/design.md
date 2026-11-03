# Design

## Architecture

All changes are internal to existing modules:
- `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/enriquecer_repuestos.py` — add `_validar_tipo_parte()` and `_aplicar_seleccion_casa_repuestos()`
- `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/resolver_precio.py` — add `_ajustar_rangos_consistentes()`
- Existing `seleccion_casa_repuestos.py` — no changes needed, only called from new code

## Data Flow

```
generar_cotizacion_ia
  ↓
enriquecer_repuestos_cotizacion
  ↓
[FOR EACH PART]
  _candidatos_web_cache (NOW WITH _validar_tipo_parte)
    ↓
  _mejor_hit (NOW WITH _validar_tipo_parte)
    ↓
  _aplicar_hit_campos
  _aplicar_precio
    ↓
_aplicar_seleccion_casa_repuestos (NEW)
  → Collect OpcionCasa from all hits
  → seleccionar_casa_optima
  → consolidar_si_posible
    ↓
_ajustar_rangos_consistentes (NEW in resolver_precio.py, called from generador.py)
  → Fix range units
    ↓
RETURN enriched repuestos
```

## Implementation Details

### 1. `_validar_tipo_parte(nombre_linea: str, titulo_ficha: str) -> bool`

```python
def _validar_tipo_parte(nombre_linea: str, titulo_ficha: str) -> bool:
    """Validate that the listing title matches the part type.
    
    Uses existing _ficha_cubre_pieza logic and requires the part-type
    keyword to appear in the listing title.
    """
    from .busqueda_web_repuestos import _ficha_cubre_pieza
    
    if not _ficha_cubre_pieza(nombre_linea, titulo_ficha):
        return False
    
    # Extract part-type keyword (first significant word)
    linea_norm = _norm(nombre_linea)
    tokens = linea_norm.split()
    if not tokens:
        return True
    
    # Check for part-type keyword in title
    # Examples: 'pastilla' in 'Pastillas Brembo', 'aceite' in 'Aceite Mobil 1'
    keyword = tokens[0] if len(tokens[0]) > 3 else (tokens[1] if len(tokens) > 1 else tokens[0])
    titulo_norm = _norm(titulo_ficha)
    
    # Special handling for common synonyms
    synonyms = {
        'aceite': ['lubricante', 'oil'],
        'filtro': ['filter'],
        'pastilla': ['balata', 'pad'],
        'disco': ['rotor'],
    }
    
    keywords_to_check = [keyword] + synonyms.get(keyword, [])
    return any(kw in titulo_norm for kw in keywords_to_check if len(kw) > 2)
```

### 2. `_aplicar_seleccion_casa_repuestos(repuestos, hits_by_part)`

Creates `OpcionCasa` instances from all hit types and calls existing `seleccionar_casa_optima` / `consolidar_si_posible`.

```python
def _aplicar_seleccion_casa_repuestos(
    repuestos: list[dict],
    hits_by_part: dict[str, list[dict]]
) -> list[dict]:
    """Apply house selection to each part using all available candidates.
    
    Maps both catalog/historial (proveedor_nombre) and web hits (tienda/dominio)
    to OpcionCasa format for unified selection logic.
    """
    from .seleccion_casa_repuestos import (
        OpcionCasa,
        seleccionar_casa_optima,
        consolidar_si_posible,
    )
    
    todas_las_opciones: dict[str, list[OpcionCasa]] = {}
    
    for i, rep in enumerate(repuestos):
        nombre = rep.get('nombre', '')
        hits = hits_by_part.get(nombre, [])
        
        opciones: list[OpcionCasa] = []
        for hit in hits:
            # Catalog/historial: proveedor_nombre
            casa = hit.get('proveedor_nombre') or hit.get('tienda') or ''
            if not casa:
                continue
            
            precio = _to_int_clp(hit.get('precio_unitario_clp'))
            if precio <= 0:
                continue
            
            opciones.append(OpcionCasa(
                casa=casa,
                proveedor_id=hash(casa) % 1000000,  # Stable hash for grouping
                precio_clp=precio,
                stock_disponible=True,
                compatibilidad_score=hit.get('confianza', 0.5),
            ))
        
        if opciones:
            todas_las_opciones[nombre] = opciones
    
    # Try consolidation first
    consolidado = consolidar_si_posible(repuestos, todas_las_opciones)
    if consolidado:
        for i, rep in enumerate(repuestos):
            nombre = rep.get('nombre', '')
            if nombre in consolidado:
                res = consolidado[nombre]
                rep['motivo_seleccion'] = res.motivo_seleccion
                rep['alternativas_descartadas'] = res.alternativas_descartadas
                rep['consolidacion_aplicada'] = res.consolidacion_aplicada
        return repuestos
    
    # Individual selection per part
    for i, rep in enumerate(repuestos):
        nombre = rep.get('nombre', '')
        opciones = todas_las_opciones.get(nombre, [])
        
        if not opciones:
            rep['motivo_seleccion'] = 'No se encontraron proveedores para esta pieza'
            rep['alternativas_descartadas'] = []
            continue
        
        res = seleccionar_casa_optima(opciones)
        rep['motivo_seleccion'] = res.motivo_seleccion
        rep['alternativas_descartadas'] = res.alternativas_descartadas
        rep['consolidacion_aplicada'] = False
    
    return repuestos
```

### 3. `_ajustar_rangos_consistentes(repuestos) -> list[dict]`

In `resolver_precio.py`:

```python
def _ajustar_rangos_consistentes(repuestos: list[dict]) -> list[dict]:
    """Ensure price ranges are in the same units as the line price.
    
    If cantidad > 1, ranges should be per-line (cantidad × unit price).
    Validates that precio_unitario_clp × cantidad falls within the range.
    """
    out: list[dict] = []
    for rep in repuestos:
        next_rep = dict(rep)
        cantidad = max(1, int(next_rep.get('cantidad') or 1))
        unitario = _to_int_clp(next_rep.get('precio_unitario_clp'))
        precio_min = _to_int_clp(next_rep.get('precio_min_clp'))
        precio_max = _to_int_clp(next_rep.get('precio_max_clp'))
        
        if cantidad <= 1 or unitario <= 0 or (precio_min <= 0 and precio_max <= 0):
            out.append(next_rep)
            continue
        
        line_total = unitario * cantidad
        
        # Check if ranges appear to be per-unit (line total would be outside)
        if precio_min > 0 and precio_max > 0:
            if line_total > precio_max * 1.5:
                # Ranges are per-unit, convert to per-line
                next_rep['precio_min_clp'] = precio_min * cantidad
                next_rep['precio_max_clp'] = precio_max * cantidad
            elif line_total < precio_min * 0.7:
                # Ranges are per-line but should be per-unit (uncommon)
                next_rep['precio_min_clp'] = precio_min // cantidad
                next_rep['precio_max_clp'] = precio_max // cantidad
        
        out.append(next_rep)
    return out
```

## Testing Strategy

### Unit Tests

`mecanimovilapp/apps/ordenes/tests/test_enriquecer_repuestos_bugs.py`:

- `test_validar_tipo_parte_oil_cooler_rejected`
- `test_validar_tipo_parte_pads_generic_rejected`
- `test_validar_tipo_parte_filter_accepted`
- `test_aplicar_seleccion_casa_maps_web_hits`
- `test_motivo_seleccion_names_store`
- `test_consolidation_runs_when_viable`
- `test_ajustar_rangos_multi_quantity`

### Integration Test

Full flow test with FIAT BRAVO 2010 1.4 fixture covering all 4 bugs.

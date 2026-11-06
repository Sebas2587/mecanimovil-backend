# Design

## Database Changes

### Migration: Add `margen_ganancia_pct` to Taller
```python
operations = [
    migrations.AddField(
        model_name='taller',
        name='margen_ganancia_pct',
        field=models.DecimalField(
            blank=True,
            null=True,
            max_digits=5,
            decimal_places=2,
            validators=[MinValueValidator(0), MaxValueValidator(999.99)],
            help_text='Margen de ganancia sobre costo de repuestos (%). Ej: 30 = vender a costo × 1.30',
        ),
    ),
]
```

## API Changes

### Taller Profile Serializers
**TallerSerializer** (workshop-facing):
- Add `margen_ganancia_pct` to fields list
- Read-write, validated by Django validators

**TallerPublicSerializer** (customer-facing):
- **DO NOT** include `margen_ganancia_pct`

### Quote Engine Integration Point
File: `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/enriquecer_repuestos.py`

Function to add: `aplicar_margen_taller(repuesto: dict, taller: Taller) -> None`

```python
def aplicar_margen_taller(repuesto: dict, taller: Taller) -> None:
    """
    Apply taller's markup to a part's sale price if cost is known and margin is set.
    Modifies repuesto in place.
    """
    margen = taller.margen_ganancia_pct
    if margen is None:
        return  # No configured margin
    
    costo = repuesto.get('costo_unitario_clp')
    if not costo or costo <= 0:
        return  # No known cost
    
    # Apply markup: sale = cost × (1 + margin%)
    precio_calculado = round(float(costo) * (1 + float(margen) / 100))
    
    # Only set if not already manually priced
    if not repuesto.get('precio_unitario_clp'):
        repuesto['precio_unitario_clp'] = precio_calculado
```

**Integration points** (minimal changes):
1. After AI determines `costo_unitario_clp`, call `aplicar_margen_taller()`
2. Existing profit calculation logic already handles manual edits correctly

## Caja API Changes

File: `mecanimovilapp/apps/ordenes/services/caja_taller.py`

Function to add: `_desglose_partes_labor(caso_dict: dict, cotizacion: CotizacionCanal | None) -> dict`

```python
def _desglose_partes_labor(caso_dict: dict, cotizacion: CotizacionCanal | None) -> dict:
    """
    Add parts/labor breakdown to a caso dict from its cotizacion.
    Returns dict with: partes_cobrado_clp, partes_costo_clp, partes_margen_clp, mano_obra_cobrado_clp
    """
    if cotizacion is None:
        return {
            'partes_cobrado_clp': None,
            'partes_costo_clp': None,
            'partes_margen_clp': None,
            'mano_obra_cobrado_clp': None,
        }
    
    repuestos = cotizacion.repuestos if isinstance(cotizacion.repuestos, list) else []
    
    partes_cobrado = 0
    partes_costo = 0
    costo_conocido = True
    
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        cantidad = int(rep.get('cantidad') or 1)
        cobrado = int(rep.get('precio_cobrado_clp') or rep.get('precio_unitario_clp') or 0)
        costo = rep.get('costo_unitario_clp')
        
        partes_cobrado += cobrado * cantidad
        if costo and costo > 0:
            partes_costo += int(costo) * cantidad
        else:
            costo_conocido = False
    
    # If any part has unknown cost, report total cost as null
    partes_costo_final = partes_costo if costo_conocido and repuestos else (0 if not repuestos else None)
    partes_margen = (partes_cobrado - partes_costo) if partes_costo_final is not None else None
    
    return {
        'partes_cobrado_clp': partes_cobrado,
        'partes_costo_clp': partes_costo_final,
        'partes_margen_clp': partes_margen,
        'mano_obra_cobrado_clp': int(cotizacion.mano_obra_clp or 0),
    }
```

**Integration**:
- In `consultar_periodo()`, batch-fetch cotizaciones for all anclas
- For each caso, call `_desglose_partes_labor()` and merge into response
- No change to queries (cotizacion already batch-fetched in PR #43)

## Testing Strategy

### New Tests
1. `test_taller_margin_field_crud` - CRUD operations on margen_ganancia_pct
2. `test_margin_applied_to_known_cost` - Quote with margin applies markup
3. `test_no_margin_without_setting` - Null margin does not compute price
4. `test_no_margin_without_cost` - Known margin but unknown cost does not compute price
5. `test_manual_edit_recalculates_profit` - Editing price keeps cost, recalcs margin
6. `test_margin_change_not_retroactive` - Changing setting doesn't rewrite old quotes
7. `test_caja_parts_labor_separation` - Caja response includes breakdown
8. `test_caja_unknown_cost_null_margin` - Unknown costs return null, not $0
9. `test_no_workshop_fields_in_public_payload` - Customer payload excludes margins

### Regression Tests to Verify
- All tests in `test_casas_especialistas.py` (specialist store selection)
- All tests in `test_cotizacion_canal.py` (quote generation)
- All tests in `test_caja_taller.py` (cash book)
- Verify quote engine still asks when unsure
- Verify complete quotes still include parts + labor + details

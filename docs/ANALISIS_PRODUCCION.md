# Análisis Producción - Fallos AI Quotation (Commit 60ff171)

## Casos de Prueba Fallidos

### Caso 1: FIAT BRAVO SPORT 2010 (Cotización 181)
**Request**: "Cambio de pastillas de freno delanteras y cambio de aceite de motor con filtro"  
**Patente**: CJXP98, 1.4 bencinero

**Problemas detectados**:

1. ✗ **FALTA FILTRO DE ACEITE**
   - Pedido dice "con filtro" pero cotización no tiene línea de filtro
   - Gemini solo incluyó: "Aceite de motor TISS" x4
   
2. ✗ **MATCH INCORRECTO DE PRODUCTO**
   - Repuesto: "Aceite de motor TISS" x4, $31.490
   - Producto matched: "Enfriador aceite Fiat Bravo 1.4" (Euroespecialista)
   - **Problema**: Aceite ≠ Enfriador de aceite (oil cooler)
   
3. ✗ **PASTILLAS SIN CASA**
   - Línea: "Pastillas de freno delanteras"
   - Precio: "Precio asumido $70.000"
   - NO hay consulta a casas de repuestos
   
4. ✗ **UI SIN MOTIVOS/CONSOLIDACIÓN**
   - Frontend no muestra: `motivo_seleccion`, `consolidacion_aplicada`, `alternativas_descartadas`
   - API no devuelve esos campos para este flujo

5. ✗ **RANGO INCONSISTENTE**
   - UI muestra estimado: $8.000–$15.000
   - Precio línea: $31.490
   - Cálculo de rango incorrecto

### Caso 2: Suzuki Celerio "cambio de embrague" (Cotización 174)
**Problema**: Agregó repuestos NO solicitados:
- Piola de embrague
- 3x Aceite de caja
- Rodamiento volante
- Retén cigüeñal

**Causa**: Prompt ambiguo sobre qué incluir en trabajo de embrague

---

## Análisis de Código Path

### Flujo "Generar con IA" (Prov Web)

```
views_cotizacion_canal.py:generar_ia()
  ↓
generador.py:generar_cotizacion_ia()
  ↓
1. armar_contexto_cotizacion(vehiculo, servicio_nombre, descripcion)
2. _intentar_contenido_solo_catalogo() [si hay OfertaServicio]
3. Llamada Gemini con prompt
4. enriquecer_repuestos_cotizacion() [matching fuzzy con casas]
5. Crear CotizacionCanal
```

### ❌ Problemas Identificados

#### 1. NO usa `extraccion_pedido_llm.py`
- **Dónde**: `generador.py` línea 437+
- **Qué falta**: Extracción estructurada pre-Gemini para enriquecer contexto
- **Impacto**: Gemini no tiene guidance sobre partes implícitas

#### 2. NO usa `seleccion_casa_repuestos.py`
- **Dónde**: `generador.py` línea 656+ llama `enriquecer_repuestos_cotizacion()`
- **Qué falta**: Scoring multi-criterio, consolidación, motivos en español
- **Impacto**: No hay `motivo_seleccion`, `alternativas_descartadas`, `consolidacion_aplicada`

#### 3. Matching sin validación de tipo
- **Dónde**: `enriquecer_repuestos.py:_mejor_hit()` línea 992+
- **Qué hace**: Fuzzy matching por similitud de texto
- **Qué falta**: Validación que "aceite" NO matche con "enfriador"
- **Impacto**: Matches incorrectos (oil vs oil cooler, brake pad vs brake disc, etc.)

#### 4. Prompt ambiguo sobre partes implícitas
- **Dónde**: `generador.py` línea 373-433
- **Regla 5-6**: General sobre "separa faena y pieza"
- **Qué falta**: Explícito sobre "con filtro" → incluir filtro como repuesto
- **Impacto**: Gemini omite partes que debería incluir

---

## Solución Correcta (Requiere Refactor Mayor - NO IMPLEMENTAR AHORA)

### Opción A: Integrar módulos existentes en `generar_cotizacion_ia()`

```python
def generar_cotizacion_ia(...):
    # 1. PRE-GEMINI: Extracción estructurada
    from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import extraer_pedido_con_llm
    
    pedido_extraido = extraer_pedido_con_llm(
        texto_cliente=f"{servicio_nombre}. {descripcion_problema}",
        vehiculo_context={'marca': ctx['marca'], 'modelo': ctx['modelo'], ...},
        taller=taller
    )
    
    # Enriquecer prompt con partes extraídas
    partes_requeridas = [
        {"servicio": s.nombre_servicio, "repuestos": [r.nombre for r in s.repuestos_mencionados]}
        for s in pedido_extraido.servicios
    ]
    
    # 2. Llamar Gemini con contexto enriquecido
    contenido = _llamar_gemini_con_partes(prompt_mejorado, partes_requeridas)
    
    # 3. POST-GEMINI: Consultar casas reales con scoring
    from mecanimovilapp.apps.ordenes.services.consulta_casas import consultar_casas_para_repuestos
    from mecanimovilapp.apps.ordenes.services.seleccion_casa_repuestos import seleccionar_casa_optima
    
    for repuesto in contenido['repuestos']:
        opciones_casas = consultar_casas_para_repuestos(
            nombre=repuesto['nombre'],
            vehiculo={'marca': ctx['marca'], 'modelo': ctx['modelo'], ...}
        )
        
        if opciones_casas:
            seleccion = seleccionar_casa_optima(opciones_casas)
            repuesto['casa_repuesto_nombre'] = seleccion.casa_elegida
            repuesto['motivo_seleccion'] = seleccion.motivo_seleccion
            repuesto['alternativas_descartadas'] = seleccion.alternativas_descartadas
            repuesto['consolidacion_aplicada'] = seleccion.consolidacion_aplicada
```

**Riesgo**: Alto - cambio invasivo en flujo crítico, requiere testing extensivo

### Opción B: Fix quirúrgico en matching (MENOS RIESGOSO)

```python
# enriquecer_repuestos.py
def _validar_tipo_parte(nombre_repuesto: str, producto_matched: str) -> bool:
    """Rechaza mismatches obvios por tipo de parte."""
    # Normalizar
    rep_norm = _norm(nombre_repuesto)
    prod_norm = _norm(producto_matched)
    
    # Exclusiones: si repuesto pide X, producto NO debe tener Y
    exclusiones = {
        'aceite motor': ['enfriador', 'filtro', 'cooler', 'radiador'],
        'aceite': ['enfriador', 'cooler', 'radiador', 'filtro'],
        'filtro aceite': ['enfriador', 'cooler', 'radiador', 'deposito'],
        'pastilla freno': ['disco', 'tambor', 'campana'],
        'disco freno': ['pastilla', 'zapata'],
        'bujia': ['bobina', 'cable'],
        'amortiguador': ['resorte', 'espiral'],
    }
    
    for tipo, prohibidas in exclusiones.items():
        if tipo in rep_norm:
            if any(p in prod_norm for p in prohibidas):
                return False
    
    return True

def _mejor_hit(...):
    # ... matching existente ...
    if mejor and mejor['score'] >= min_score:
        # NUEVO: validar tipo de parte
        if not _validar_tipo_parte(needle, mejor['nombre']):
            logger.warning(
                'ordenes[enrich] mismatch_tipo_rechazado repuesto=%s producto=%s',
                needle[:50], mejor['nombre'][:50]
            )
            return None
        return mejor
    return None
```

**Riesgo**: Bajo - solo agrega validación, no cambia flujo

### Opción C: Mejorar prompt Gemini (INMEDIATO, BAJO RIESGO)

Agregar regla explícita en prompt:

```
5d. PARTES IMPLÍCITAS (CRÍTICO): Si el servicio menciona explícitamente que incluye una parte, DEBES incluirla:
   - "cambio de aceite CON FILTRO" → repuestos: "Aceite de motor" + "Filtro de aceite"
   - "pastillas Y discos" → repuestos: "Pastillas" + "Discos"
   - "kit de embrague con volante" → repuestos: "Kit de embrague" + "Volante bimasa"
   La palabra "con", "incluye", "y" o "más" indica parte adicional que DEBE estar en repuestos.
   
5e. CANTIDADES POR CAPACIDAD: 
   - Aceite de motor: cantidad en litros según capacidad del motor (ej. 1.4L = 4-5 litros, 2.0L = 5-6 litros)
   - NO uses cantidad=4 si vendes bidones de 4L (eso sería 16L). Para un 1.4L: cantidad=1, precio del bidón 4L.
```

**Riesgo**: Muy bajo - solo mejora guidance

---

## Recomendación URGENTE

**Para deploy inmediato** (hoy):
1. ✅ Mejorar prompt Gemini (Opción C) - bajo riesgo
2. ✅ Agregar validación anti-mismatch (Opción B) - bajo riesgo
3. ✅ Documentar problema de arquitectura

**Para refactor posterior** (sprint dedicado):
4. ⏰ Integrar `extraccion_pedido_llm` + `seleccion_casa_repuestos` en `generar_cotizacion_ia()`
5. ⏰ Tests end-to-end con casos reales (FIAT Bravo, Suzuki Celerio)
6. ⏰ Verificar que frontend renderiza campos nuevos (PR en mecanimovil-prov)

---

## Tests Necesarios (Mínimo)

```python
# test_generador_casos_reales.py
def test_cambio_aceite_con_filtro():
    """Caso FIAT Bravo: debe incluir filtro de aceite."""
    resultado = generar_cotizacion_ia(
        servicio_nombre="Cambio de aceite de motor con filtro",
        vehiculo={'marca': 'FIAT', 'modelo': 'BRAVO', 'anio': 2010, 'motor': '1.4 T-Jet'},
        taller=taller_fixture
    )
    repuestos = resultado['contenido']['repuestos']
    nombres = [r['nombre'].lower() for r in repuestos]
    
    assert any('aceite' in n for n in nombres), "Debe incluir aceite"
    assert any('filtro' in n and 'aceite' in n for n in nombres), "Debe incluir filtro de aceite"

def test_no_match_aceite_con_enfriador():
    """Validar que aceite NO matche con enfriador."""
    from enriquecer_repuestos import _validar_tipo_parte
    
    assert _validar_tipo_parte("Aceite de motor", "Aceite sintético 5W30") == True
    assert _validar_tipo_parte("Aceite de motor", "Enfriador aceite") == False
    assert _validar_tipo_parte("Filtro de aceite", "Enfriador aceite") == False
```

---

## Conclusión

El problema es **arquitectural**: PR #5 agregó módulos inteligentes (`extraccion_pedido_llm`, `seleccion_casa_repuestos`) pero solo los integró en el chat del dueño, NO en el flujo principal "Generar con IA" del prov web.

**Fix completo = Refactor mayor = Riesgo alto ahora**

**Fix quirúrgico hoy**:
- Mejorar prompt
- Validar tipo de parte
- Documentar deuda técnica

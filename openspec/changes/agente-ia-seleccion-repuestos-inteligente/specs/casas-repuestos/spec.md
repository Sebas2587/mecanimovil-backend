# casas-repuestos (delta)

## ADDED Requirements

### REQ-CASA-SELECCION-INTELIGENTE
El módulo `seleccion_casa_repuestos.py` SHALL proporcionar:
- `seleccionar_casa_optima(opciones_casa, criterios)` que evalúa precio, stock, plazo y compatibilidad
- `consolidar_si_posible(repuestos, opciones_todas_casas)` que detecta si una casa puede proveer todo
- Retorna tupla `(casa_elegida, motivo_str, alternativas_descartadas_list)`

### REQ-CASA-CRITERIOS-PONDERACION
La selección SHALL usar ponderaciones por defecto:
- Stock disponible: bloqueante (si no hay, descarta)
- Precio: peso 0.6 (menor es mejor, normalizado)
- Plazo entrega: peso 0.3 (<24h mejor, 24-48h neutro, >48h peor)
- Compatibilidad verificada: peso 0.1 (boost si casa tiene historial de piezas correctas)

### REQ-CASA-MOTIVO-EXPLICITO
El `motivo_seleccion` SHALL ser texto legible para el taller, ej: "Mejor precio con stock inmediato ($12.500)", "Única casa con stock disponible", "Consolidado: tiene todos los repuestos con precios competitivos".

### REQ-CASA-ALTERNATIVAS-COMPLETAS
`alternativas_descartadas` SHALL incluir para cada opción no elegida: `{casa: str, precio_clp: int, stock: bool, plazo_dias: int, motivo_descarte: str}`.

### REQ-CASA-CONSOLIDACION-THRESHOLD
Consolidación SHALL aplicarse si:
- Una casa tiene ≥80% de los repuestos
- Los precios de esa casa están dentro del 10% del mejor precio individual para cada repuesto
- No hay repuesto crítico (categoría "frenos", "dirección") con alternativa significativamente mejor en otra casa

## MODIFIED Requirements

### REQ-CASA-APLICAR-COTIZACION (modificación)
**Original:** `_aplicar_en_cotizacion()` graba respuesta de casa en opciones_casa del repuesto
**Nueva regla:** Después de acumular todas las respuestas en `opciones_casa`, SHALL invocar `seleccionar_casa_optima()` y persistir resultado en nuevos campos:
- `rep['casa_repuesto_nombre']`
- `rep['motivo_seleccion']`
- `rep['alternativas_descartadas']`
- `rep['consolidacion_aplicada']`

**Backward compat:** `opciones_casa` se mantiene poblado para clientes antiguos.

### REQ-CASA-SERIALIZER (modificación)
**Original:** RepuestoCotizacionSerializer expone campos básicos
**Nuevos campos obligatorios:**
```python
casa_repuesto_nombre = serializers.CharField(required=False, allow_blank=True, default='')
motivo_seleccion = serializers.CharField(required=False, allow_blank=True, default='')
alternativas_descartadas = serializers.ListField(
    child=serializers.DictField(),
    required=False,
    default=list
)
consolidacion_aplicada = serializers.BooleanField(required=False, default=False)
```

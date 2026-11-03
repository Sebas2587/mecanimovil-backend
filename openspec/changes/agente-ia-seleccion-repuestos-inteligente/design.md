# Design: Selección Inteligente de Repuestos con IA

## Architecture

### 1. Extracción Estructurada (LLM)

**Módulo:** `mecanimovilapp/apps/agente_ia/services/extraccion_pedido_llm.py`

```python
# Pydantic models
class VehiculoExtraido(BaseModel):
    marca: str = ""
    modelo: str = ""
    anio: Optional[int] = Field(None, ge=1980, le=2030)
    motor: str = ""
    version: str = ""
    patente: str = ""
    tipo_motor: Optional[str] = None  # GASOLINA/DIESEL/HIBRIDO/ELECTRICO

class ServicioExtraido(BaseModel):
    nombre: str
    cantidad: int = Field(default=1, ge=1)
    incluye_repuestos: Optional[bool] = None

class RepuestoMencionado(BaseModel):
    nombre: str
    especificacion: str = ""
    cantidad: int = Field(default=1, ge=1)

class PedidoExtraido(BaseModel):
    vehiculo: VehiculoExtraido
    servicios: List[ServicioExtraido] = []
    repuestos_mencionados: List[RepuestoMencionado] = []
    alcance_repuestos: str = "no_definido"  # con_repuestos/solo_mano_obra/no_definido
    calidad_preferida: str = ""  # original/oem/alternativo
    descripcion_problema: str = ""

# Función principal
def extraer_pedido_con_llm(
    texto_cliente: str,
    vehiculo_context: dict,
    *,
    taller = None
) -> PedidoExtraido:
    """
    Extrae información estructurada del pedido del cliente.
    
    Fallback: si LLM falla, usa regex de alcance_pedido.py
    """
```

**Prompt LLM:**
```
Extrae del mensaje del cliente la información del pedido de servicio automotriz.
REGLAS CRÍTICAS:
- Solo extrae lo que el cliente MENCIONA AHORA, no agregues mantenimientos preventivos
- "Cambio de aceite" es UN servicio de mano de obra
- "Filtro de aceite" mencionado es un repuesto, no un servicio separado
- Si dice "cambio de pastillas y discos", son 2 repuestos pero 1 servicio de mano de obra
- Patente formato chileno: ABCD12 o AB1234

Responde SOLO JSON válido:
{
  "vehiculo": {"marca": "...", "modelo": "...", ...},
  "servicios": [{"nombre": "Cambio de pastillas de freno", "cantidad": 1}],
  "repuestos_mencionados": [{"nombre": "Pastillas de freno delanteras", "cantidad": 1}],
  "alcance_repuestos": "con_repuestos",
  "calidad_preferida": "",
  "descripcion_problema": "..."
}
```

**Integración en flujo:**
1. `agente_dueno_cotizacion.py::_empezar()` llama a `extraer_pedido_con_llm()` antes de `_armar()`
2. `cotizacion_borrador.py::crear_cotizacion_borrador_desde_agente()` usa extracción para mejorar `_parse_servicios_solicitados()`
3. Resultado estructurado alimenta tanto prompt de Gemini como lógica de catálogo

### 2. Selección Inteligente de Casas

**Módulo:** `mecanimovilapp/apps/ordenes/services/seleccion_casa_repuestos.py`

```python
@dataclass
class OpcionCasa:
    casa: str
    proveedor_id: int
    precio_clp: int
    stock_disponible: bool
    plazo_dias: Optional[int] = None
    compatibilidad_score: float = 0.0
    consulta_id: Optional[int] = None

@dataclass
class ResultadoSeleccion:
    casa_elegida: str
    proveedor_id: int
    motivo_seleccion: str
    alternativas_descartadas: List[Dict[str, Any]]
    precio_final_clp: int
    consolidacion_aplicada: bool = False

def seleccionar_casa_optima(
    opciones: List[OpcionCasa],
    *,
    criterios: Optional[Dict] = None
) -> ResultadoSeleccion:
    """
    Selecciona la mejor casa según múltiples criterios.
    
    Ponderación por defecto:
    - Stock: bloqueante (sin stock = descartado)
    - Precio: 60% (normalizado entre min-max)
    - Plazo: 30% (< 24h = 1.0, 24-48h = 0.5, > 48h = 0.0)
    - Compatibilidad: 10% (historial de aciertos)
    """
    # 1. Filtrar sin stock
    con_stock = [o for o in opciones if o.stock_disponible]
    if not con_stock:
        # Tomar la más barata aunque no tenga stock (para documentar)
        mejor_sin_stock = min(opciones, key=lambda o: o.precio_clp)
        return ResultadoSeleccion(
            casa_elegida=mejor_sin_stock.casa,
            proveedor_id=mejor_sin_stock.proveedor_id,
            motivo_seleccion="Única opción cotizada (sin stock confirmado)",
            alternativas_descartadas=_construir_alternativas(opciones, mejor_sin_stock),
            precio_final_clp=mejor_sin_stock.precio_clp
        )
    
    # 2. Calcular scores ponderados
    scores = []
    for opc in con_stock:
        precio_norm = _normalizar_precio(opc.precio_clp, con_stock)
        plazo_score = _score_plazo(opc.plazo_dias)
        compat_score = opc.compatibilidad_score
        
        score_total = (
            precio_norm * 0.6 +
            plazo_score * 0.3 +
            compat_score * 0.1
        )
        scores.append((score_total, opc))
    
    # 3. Elegir mejor score
    mejor_score, mejor_opc = max(scores, key=lambda x: x[0])
    
    # 4. Construir motivo legible
    motivo = _construir_motivo(mejor_opc, con_stock)
    
    return ResultadoSeleccion(
        casa_elegida=mejor_opc.casa,
        proveedor_id=mejor_opc.proveedor_id,
        motivo_seleccion=motivo,
        alternativas_descartadas=_construir_alternativas(opciones, mejor_opc),
        precio_final_clp=mejor_opc.precio_clp
    )

def consolidar_si_posible(
    repuestos: List[Dict],
    todas_las_opciones: Dict[str, List[OpcionCasa]]
) -> Optional[Dict[str, ResultadoSeleccion]]:
    """
    Detecta si una sola casa puede proveer todos los repuestos competitivamente.
    
    Retorna dict {repuesto_id: ResultadoSeleccion} si hay consolidación,
    None si es mejor distribuir entre casas.
    """
    # 1. Identificar casas que aparecen en todos los repuestos
    casas_por_repuesto = {
        rid: {o.proveedor_id for o in opciones}
        for rid, opciones in todas_las_opciones.items()
    }
    casas_completas = set.intersection(*casas_por_repuesto.values())
    
    if not casas_completas:
        return None  # Ninguna casa tiene todo
    
    # 2. Para cada casa completa, calcular costo total
    costos_consolidados = {}
    for casa_id in casas_completas:
        costo_total = 0
        costo_optimo = 0
        for rid, opciones in todas_las_opciones.items():
            opc_casa = next(o for o in opciones if o.proveedor_id == casa_id)
            mejor_precio = min(o.precio_clp for o in opciones if o.stock_disponible)
            costo_total += opc_casa.precio_clp
            costo_optimo += mejor_precio
        
        # Threshold: 10% más caro que óptimo distribuido
        if costo_total <= costo_optimo * 1.10:
            costos_consolidados[casa_id] = costo_total
    
    if not costos_consolidados:
        return None  # Consolidar sería muy caro
    
    # 3. Elegir casa con mejor costo consolidado
    casa_elegida_id = min(costos_consolidados, key=costos_consolidados.get)
    
    # 4. Construir ResultadoSeleccion para cada repuesto
    resultados = {}
    for rid, opciones in todas_las_opciones.items():
        opc_elegida = next(o for o in opciones if o.proveedor_id == casa_elegida_id)
        resultados[rid] = ResultadoSeleccion(
            casa_elegida=opc_elegida.casa,
            proveedor_id=casa_elegida_id,
            motivo_seleccion=f"Consolidado en una sola casa (tiene todos los repuestos con precios competitivos)",
            alternativas_descartadas=_construir_alternativas(opciones, opc_elegida),
            precio_final_clp=opc_elegida.precio_clp,
            consolidacion_aplicada=True
        )
    
    return resultados
```

### 3. Integración en `consulta_casas.py`

**Modificar `_aplicar_en_cotizacion()`:**

```python
def _aplicar_en_cotizacion(consulta: ConsultaRepuesto, parsed: dict) -> None:
    with transaction.atomic():
        cot = CotizacionCanal.objects.select_for_update().get(pk=consulta.cotizacion_id)
        # ... código existente que acumula en opciones_casa ...
        
        # NUEVO: aplicar selección inteligente
        repuestos_con_opciones = {}
        for rep in cot.repuestos:
            if isinstance(rep, dict) and rep.get('opciones_casa'):
                repuestos_con_opciones[rep['id']] = rep['opciones_casa']
        
        # Intentar consolidación
        from mecanimovilapp.apps.ordenes.services.seleccion_casa_repuestos import (
            consolidar_si_posible,
            seleccionar_casa_optima,
            OpcionCasa
        )
        
        consolidacion = None
        if len(repuestos_con_opciones) >= 2:
            todas_opciones = {
                rid: [OpcionCasa(**opc) for opc in opciones]
                for rid, opciones in repuestos_con_opciones.items()
            }
            consolidacion = consolidar_si_posible(list(cot.repuestos), todas_opciones)
        
        # Aplicar selección (consolidada o individual)
        reps_actualizados = []
        for rep in cot.repuestos:
            if not isinstance(rep, dict):
                reps_actualizados.append(rep)
                continue
            
            rid = rep.get('id')
            if rid and rid in repuestos_con_opciones:
                if consolidacion and rid in consolidacion:
                    resultado = consolidacion[rid]
                else:
                    opciones = [OpcionCasa(**o) for o in rep.get('opciones_casa', [])]
                    if opciones:
                        resultado = seleccionar_casa_optima(opciones)
                    else:
                        reps_actualizados.append(rep)
                        continue
                
                # Persistir resultado
                rep_actualizado = {
                    **rep,
                    'casa_repuesto_nombre': resultado.casa_elegida,
                    'motivo_seleccion': resultado.motivo_seleccion,
                    'alternativas_descartadas': resultado.alternativas_descartadas,
                    'consolidacion_aplicada': resultado.consolidacion_aplicada,
                    'proveedor_id': resultado.proveedor_id,
                    'precio_unitario_clp': resultado.precio_final_clp,
                }
                reps_actualizados.append(rep_actualizado)
            else:
                reps_actualizados.append(rep)
        
        cot.repuestos = reps_actualizados
        # ... resto del código ...
```

### 4. API Changes

**Serializer:** `mecanimovilapp/apps/ordenes/serializers_cotizacion_canal.py`

```python
class RepuestoCotizacionSerializer(serializers.Serializer):
    # ... campos existentes ...
    
    # NUEVOS CAMPOS
    casa_repuesto_nombre = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text='Nombre de la casa de repuestos elegida'
    )
    motivo_seleccion = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text='Explicación de por qué se eligió esta casa'
    )
    alternativas_descartadas = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text='Otras opciones consideradas y razón de descarte'
    )
    consolidacion_aplicada = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Si este repuesto fue consolidado con otros en la misma casa'
    )
```

## Testing Strategy

### Unit Tests

1. **test_extraccion_pedido_llm.py:**
   - Caso filtro de aire simple
   - Caso pack (pastillas + discos)
   - Caso embrague completo (kit + volante + aceite caja)
   - Caso con patente y año
   - Caso LLM falla → fallback regex

2. **test_seleccion_casa_repuestos.py:**
   - Mejor precio con stock
   - Stock vs precio (stock inmediato gana vs 5% más barato sin stock)
   - Consolidación viable (una casa al 108% del óptimo)
   - Consolidación no viable (una casa al 120%, se distribuye)
   - Sin stock en ninguna casa (elegir más barata documentando)

### Integration Tests

3. **test_cotizacion_con_seleccion_inteligente.py:**
   - End-to-end: chat cliente → extracción LLM → cotización → consulta casas → selección → API
   - Verificar que frontend recibe nuevos campos
   - Verificar backward compat (opciones_casa sigue ahí)

### Manual Testing

- Probar en staging con conversación real WhatsApp
- Verificar notificación push al taller cuando hay selección consolidada
- Verificar que PR mecanimovil-prov#7 renderiza correctamente los nuevos campos

## Deployment Considerations

### Environment Variables

Ninguna nueva variable requerida (usa `GEMINI_API_KEY` existente).

### Migrations

No requiere migración de base de datos (campos en JSON existente).

### Rollout

1. Deploy a staging
2. Validar con casos de test reales
3. Deploy a producción en horario valle (00:00-06:00 CLT)
4. Monitorear logs `agente_ia[extraccion]` y `ordenes[seleccion_casa]`
5. Si hay rollback, código nuevo es backward compatible (no rompe)

### Monitoring

Agregar logs:
- `logger.info('agente_ia[extraccion] fallback_regex=%s', used_fallback)`
- `logger.info('ordenes[seleccion_casa] consolidacion=%s repuestos=%d', consolidado, n)`
- `logger.warning('ordenes[seleccion_casa] sin_stock_ninguna_casa rep=%s', rep_id)`

## Risks & Mitigations

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| LLM lento (>5s) en extracción | Media | Bajo | Timeout 5s → fallback regex inmediato |
| LLM extrae servicios no pedidos | Baja | Medio | Prompt explícito "SOLO lo mencionado" + validación Pydantic |
| Consolidación elige casa cara | Baja | Medio | Threshold 10%, logs para auditoría |
| Frontend espera formato distinto | Baja | Alto | Test de integración con mock del PR#7 |

## Future Enhancements (out of scope)

- Machine learning para aprender ponderaciones de cada taller
- Integración con APIs de casas de repuestos (no solo WhatsApp)
- Negociación automática con casas si precio muy alto
- Sugerencias proactivas de servicios relacionados (no pedidos pero relevantes)

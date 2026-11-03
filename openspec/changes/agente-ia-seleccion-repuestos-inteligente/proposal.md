# agente-ia-seleccion-repuestos-inteligente

## Why

El agente de cotizaciones automáticas con IA no entiende bien qué pide el cliente al cotizar un vehículo:
- Regex limitadas en `alcance_pedido.py` pierden contexto y matices
- Muestra información incompleta o errónea sobre repuestos y servicios
- Al consultar múltiples casas de repuestos, no documenta por qué eligió una sobre otra
- No hay trazabilidad de alternativas descartadas para el taller
- Frontend (PR mecanimovil-prov#7) requiere `casa_repuesto_nombre`, `motivo_seleccion`, `alternativas_descartadas` que no existen

El agente debe funcionar como un "segundo cerebro" que deja la cotización lista, exacta y completa para que el taller solo revise y apruebe.

## What Changes

### 1. Interpretación inteligente con LLM
- **Extracción estructurada:** nuevo servicio `extraccion_pedido_llm.py` que reemplaza regex con LLM estructurado para capturar:
  - Vehículo (marca/modelo/año/motor/versión/patente)
  - Servicios solicitados (lista con cantidades)
  - Repuestos mencionados (con especificaciones)
  - Alcance (solo mano de obra vs con repuestos)
  - Calidad preferida (original/OEM/alternativo)
- **Validación y fallback:** schema Pydantic con validación; si LLM falla, fallback a regex actual
- Integración en `agente_dueno_cotizacion.py` y `cotizacion_borrador.py`

### 2. Configuración de servicios por modelo
- Usar `buscar_oferta_exacta()` existente para priorizar tarifas específicas por marca/modelo/motor
- Aplicar precios y tiempos de mano de obra configurados en `OfertaServicio`
- Respetar repuestos incluidos en el catálogo del taller

### 3. Selección inteligente de casas de repuestos
- **Nuevo módulo** `seleccion_casa_repuestos.py`:
  - `seleccionar_casa_optima()`: evalúa opciones por precio, stock, plazo, compatibilidad
  - `consolidar_si_posible()`: si una casa tiene todos los repuestos, consolida salvo razón fuerte
  - Genera `motivo_seleccion` (str) y `alternativas_descartadas` (list[dict])
- **Campos nuevos en repuesto JSON:**
  - `casa_repuesto_nombre`: str (nombre de la casa elegida)
  - `motivo_seleccion`: str (razón de la elección)
  - `alternativas_descartadas`: list[dict] con `{casa, precio_clp, motivo_descarte}`
  - `consolidacion_aplicada`: bool (si se consolidó en una sola casa)

### 4. Integración en flujo real
- Modificar `consulta_casas.py::_aplicar_en_cotizacion()` para invocar selección inteligente
- Exponer nuevos campos en `RepuestoCotizacionSerializer`
- Mantener compatibilidad con `opciones_casa` existente (backward compatible)

### 5. Tests realistas
- Test de extracción LLM con casos reales (filtros, embrague, pastillas+discos)
- Test de selección con múltiples casas (mejor precio vs stock inmediato)
- Test de consolidación (una casa con todo vs dividir)
- Test de integración end-to-end desde chat hasta API

## Scope (out)

- Refactor completo del orquestador (se mantiene estructura actual)
- Integración con APIs externas de casas de repuestos (usa WhatsApp actual)
- Machine learning para aprender de decisiones pasadas del taller
- Interfaz de administración para configurar ponderaciones de selección

## Requirements

### REQ-AGENTE-EXTRACCION-LLM
El agente IA SHALL extraer del pedido del cliente via LLM estructurado: vehículo (marca/modelo/año/motor/versión/patente), servicios (lista con cantidades), repuestos mencionados, alcance (solo MO vs con repuestos), calidad preferida.

#### Scenario: Cliente pide cambio de aceite con filtros
```
Input: "Hola necesito cambio de aceite y filtro de aire y polen para mi Yaris 2018 1.5 bencina"
Output JSON debe incluir:
  vehiculo: {marca: "Toyota", modelo: "Yaris", anio: 2018, motor: "1.5", tipo_motor: "GASOLINA"}
  servicios: ["Cambio de aceite", "Cambio de filtro de aire", "Cambio de filtro de polen"]
  repuestos_mencionados: ["aceite", "filtro de aire", "filtro de polen"]
  alcance_repuestos: "con_repuestos"
```

### REQ-AGENTE-VALIDACION-FALLBACK
La extracción LLM SHALL validar con schema Pydantic y SHALL hacer fallback a regex si el LLM falla o devuelve datos inválidos.

#### Scenario: LLM no disponible
```
Given: Gemini devuelve error 503
When: se invoca extraccion_pedido_llm()
Then: debe retornar resultado de regex de alcance_pedido.py actual
And: debe loggear fallback
```

### REQ-AGENTE-CATALOGO-ESPECIFICO
Al cotizar, el agente SHALL priorizar OfertaServicio del taller que coincidan con marca/modelo/motor del vehículo antes de usar estimaciones genéricas.

#### Scenario: Taller tiene tarifa configurada
```
Given: OfertaServicio existe para "Cambio de pastillas" en "Toyota Yaris 2018"
When: se genera cotización para Yaris 2018
Then: mano_obra_clp debe venir de OfertaServicio.precio_sin_repuestos
And: repuestos debe incluir items de OfertaServicio.repuestos_seleccionados
And: metadata.precio_desde_catalogo debe ser true
```

### REQ-AGENTE-SELECCION-CASA
Al recibir respuestas de múltiples casas de repuestos, el agente SHALL documentar para cada repuesto: casa elegida, motivo de selección (precio/stock/plazo/compatibilidad), alternativas descartadas con razón.

#### Scenario: Múltiples casas responden
```
Given: ConsultaRepuesto tiene 3 respuestas (Casa A: $15.000 stock ok, Casa B: $12.000 sin stock, Casa C: $14.500 stock ok)
When: se aplica selección inteligente
Then: debe elegir Casa C (balance precio-stock)
And: casa_repuesto_nombre = "Casa C"
And: motivo_seleccion = "Mejor balance precio-disponibilidad ($14.500, stock inmediato)"
And: alternativas_descartadas debe incluir [
  {casa: "Casa A", precio_clp: 15000, motivo_descarte: "Precio 3.4% más alto"},
  {casa: "Casa B", precio_clp: 12000, motivo_descarte: "Sin stock disponible"}
]
```

### REQ-AGENTE-CONSOLIDACION
Si una sola casa de repuestos tiene todos los repuestos necesarios con precio/stock competitivos, el agente SHALL consolidar la compra en esa casa y MUST documentar la consolidación.

#### Scenario: Una casa tiene todo
```
Given: 3 repuestos cotizados (filtro aceite, filtro aire, filtro polen)
And: Casa Premium tiene los 3 con precios dentro de 5% del mejor precio individual
When: se aplica consolidación
Then: los 3 repuestos deben tener casa_repuesto_nombre = "Casa Premium"
And: cada uno debe tener consolidacion_aplicada = true
And: motivo_seleccion debe incluir "consolidado en una sola casa"
```

### REQ-AGENTE-API-NUEVOS-CAMPOS
RepuestoCotizacionSerializer SHALL exponer los nuevos campos: casa_repuesto_nombre (str), motivo_seleccion (str), alternativas_descartadas (list), consolidacion_aplicada (bool).

#### Scenario: Serialización de repuesto con selección
```
When: se serializa CotizacionCanal con repuestos
Then: JSON debe incluir por cada repuesto:
  "casa_repuesto_nombre": "Casa Automotriz Central",
  "motivo_seleccion": "Mejor precio con stock inmediato",
  "alternativas_descartadas": [
    {"casa": "Repuestos Norte", "precio_clp": 18000, "motivo_descarte": "Precio 12% más alto"}
  ],
  "consolidacion_aplicada": false
```

### REQ-AGENTE-COMPATIBILIDAD
Los cambios SHALL mantener compatibilidad hacia atrás con opciones_casa existente y NO deben romper frontend actual.

#### Scenario: Frontend antiguo sigue funcionando
```
Given: frontend consume opciones_casa (campo existente)
When: se actualiza backend con nuevos campos
Then: opciones_casa debe seguir poblado
And: requests sin nuevos campos deben seguir funcionando
```

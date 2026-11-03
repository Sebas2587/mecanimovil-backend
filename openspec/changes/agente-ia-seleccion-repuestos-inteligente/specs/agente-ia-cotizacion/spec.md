# agente-ia-cotizacion (delta)

## ADDED Requirements

### REQ-AGENTE-EXTRACCION-ESTRUCTURADA
El módulo `extraccion_pedido_llm.py` SHALL proporcionar función `extraer_pedido_con_llm(texto_cliente, vehiculo_context)` que retorna estructura Pydantic con vehículo, servicios, repuestos, alcance y calidad.

### REQ-AGENTE-SCHEMA-VALIDACION
La extracción SHALL usar Pydantic models: `VehiculoExtraido`, `ServicioExtraido`, `PedidoExtraido` con validadores que aseguren tipos correctos y valores en rangos válidos (ej. año 1980-2030).

### REQ-AGENTE-PROMPT-EXTRACCION
El prompt LLM SHALL instruir explícitamente: "Extrae SOLO lo que el cliente menciona ahora, no servicios de mantenimiento preventivo ni recomendaciones. Si dice 'cambio de aceite y filtro', son 2 servicios: mano de obra de cambio y el filtro como repuesto."

### REQ-AGENTE-FALLBACK-REGEX
Si LLM falla (timeout, error, schema inválido), la función SHALL llamar a las funciones regex existentes de `alcance_pedido.py` y retornar resultado compatible.

## MODIFIED Requirements

### REQ-AGENTE-COTIZACION-BORRADOR (modificación)
**Original:** Agente crea borrador con estimaciones IA
**Nueva regla:** Antes de llamar a Gemini para generar contenido, SHALL invocar `extraer_pedido_con_llm()` para obtener estructura validada del pedido. El resultado estructurado SHALL alimentar tanto el prompt de Gemini como la lógica de `_acotar_servicios_al_pedido()`.

**Rationale:** Extracción estructurada primero mejora precisión en todo el pipeline downstream.

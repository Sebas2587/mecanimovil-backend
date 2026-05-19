# asistente-agendamiento — delta fase 5 (gratuito)

## ADDED Requirements

### Requirement: Análisis semántico sin costo por defecto
Con `AGENDAMIENTO_IA_SEMANTICO_ENABLED=True` y `AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR=lexico`, POST `analizar-necesidad` SHALL clasificar la necesidad usando solo recursos locales (léxico + similitud fuzzy) sin llamadas a APIs externas de pago.

#### Scenario: Coloquial chileno sin API key
- GIVEN proveedor `lexico` y vehículo con servicios de frenos compatibles
- WHEN el cliente escribe «pedal de freno se va al piso»
- THEN `motor_analisis` es `lexico`
- AND se recomienda servicio de frenos con interpretación clara

### Requirement: Proveedores gratuitos opcionales
El sistema MAY usar Gemini, Hugging Face u Ollama solo si el operador configura credenciales/URL gratuitas. Si fallan, SHALL usar léxico local.

#### Scenario: Gemini no disponible
- GIVEN `PROVEEDOR=gemini` sin respuesta válida
- WHEN se analiza una necesidad
- THEN el resultado proviene del motor léxico local
- AND no se expone error al cliente por fallo del proveedor externo

### Requirement: Sin proveedores de pago
El sistema SHALL NOT requerir OpenAI ni Anthropic.

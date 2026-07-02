# Diseño — Asistente diagnóstico IA

**Change:** `asistente-diagnostico-ia`
**App Django:** `ordenes`
**Fecha:** 2026-07-02

## Flujo

```mermaid
sequenceDiagram
    participant App as mecanimovil-prov
    participant API as ProveedorOrdenesViewSet
    participant Svc as asistente_diagnostico
    participant Gemini as Gemini API
    participant DB as DiagnosticoAsistidoOrden

    App->>API: POST /asistente-ia/
    API->>Svc: generar_guia(orden)
    Svc->>Gemini: generateContent JSON
    Gemini-->>Svc: guia JSON
    Svc->>DB: save contenido
    Svc-->>API: resultado
    API-->>App: 200 guia
```

## Esquema JSON de salida

```json
{
  "vehiculo": "Marca Modelo Año (cilindraje)",
  "problema_reportado": "texto",
  "causas_probables": ["..."],
  "procedimiento_reparacion_detallado": ["Paso 1: ..."],
  "referencia_manual": {
    "titulo": "...",
    "url": "https://..."
  },
  "advertencias_seguridad": ["..."]
}
```

## Decisiones

| Decisión | Razón |
|----------|-------|
| HTTP directo a Gemini | Consistente con `motor_semantico.py`, sin langchain |
| Cache en DB | Evita costos repetidos al reabrir la orden |
| Feature flag | Rollout gradual y control de costos |

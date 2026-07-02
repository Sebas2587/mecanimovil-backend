# Tasks: asistente-diagnostico-ia

## Backend
- [x] Modelo `DiagnosticoAsistidoOrden` + migración
- [x] Servicio `asistente_diagnostico/generador.py`
- [x] Action `asistente-ia` en `ProveedorOrdenesViewSet`
- [x] Setting `ASISTENTE_DIAGNOSTICO_IA_ENABLED`

## Verificación
- [x] POST genera y persiste JSON de guía
- [x] GET devuelve último cache
- [x] Mecánico no asignado recibe 403

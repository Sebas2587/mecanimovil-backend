# Multimarca — tarifas por marca de vehículo

## Why
Los proveedores multimarca configuraban ofertas solo con `marca_vehiculo_seleccionada = null` (precio único para todos los vehículos). Eso perjudica al mecánico en marcas de mayor complejidad y al cliente, que ve un precio que no refleja su auto.

Los especialistas ya publican por marca (`marcas_atendidas` + oferta por marca). El modelo `OfertaServicio` ya soporta ambos modos; faltaba habilitar la UX multimarca y unificar la resolución **marca específica > precio base genérico**.

## What Changes
- `mis_marcas`: multimarca recibe catálogo completo de marcas; especialista sin cambios.
- Módulo `oferta_resolucion.py`: prioridad de oferta por marca del vehículo.
- `panel_servicios_utils`, `motor_match`, cotización por solicitud: deduplicación con prioridad.
- App proveedor: configurar precio base y/o por marca en onboarding y `crear-servicio`.
- App usuarios: perfil y agendamiento muestran precio resuelto según vehículo del cliente.

## Requirements
- REQ-MM-COBERTURA: `tipo_cobertura_marca=multimarca` SHALL seguir implicando visibilidad para cualquier marca del cliente.
- REQ-MM-PRECIO-MARCA: el proveedor multimarca MAY crear ofertas con `marca_vehiculo_seleccionada` distinta por marca.
- REQ-MM-PRECIO-BASE: oferta con marca `null` SHALL actuar como precio base cuando no exista oferta para la marca del vehículo.
- REQ-ESP-SIN-CAMBIO: especialistas SHALL seguir limitados a `marcas_atendidas` sin cambio de contrato API.
- REQ-RESOLUCION: al listar o cotizar para marca X, el sistema SHALL preferir oferta con `marca_vehiculo_seleccionada=X` sobre oferta genérica del mismo proveedor y servicio.

## Sin impacto
- Motor de salud, consulta patente, verificación admin de proveedores.

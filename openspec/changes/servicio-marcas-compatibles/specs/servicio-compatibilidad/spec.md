# Spec — compatibilidad servicio ↔ vehículo

## REQ-MARCA-CATALOGO
El catálogo maestro SHALL exponer `marcas_compatibles` configurable en Django Admin.

## REQ-MARCA-MODELO
Dado un servicio con marca Toyota en `marcas_compatibles` y sin modelos Toyota en `modelos_compatibles`, WHEN un usuario registra cualquier Toyota, THEN el servicio SHALL considerarse compatible.

Dado un servicio con marca Toyota y modelos [Corolla, Yaris], WHEN el vehículo es Toyota Hilux, THEN el servicio SHALL NOT ser compatible salvo otra regla (oferta proveedor, multimarca).

## REQ-LEGACY-MODELOS
Dado un servicio sin `marcas_compatibles` pero con `modelos_compatibles` de marca X, WHEN se filtra por marca X, THEN el servicio SHALL aparecer (comportamiento actual de `catalogo_por_marca`).

## REQ-SIN-IMPACTO-PROVEEDOR
WHEN un proveedor completa onboarding o crea oferta con `marca_vehiculo_seleccionada`, THEN el flujo SHALL no requerir cambios de UI ni nuevos campos.

## REQ-SIN-IMPACTO-SALUD
WHEN el motor de salud calcula métricas o `consultar-patente` devuelve datos, THEN SHALL not usar `Servicio.modelos_compatibles` ni `marcas_compatibles`.

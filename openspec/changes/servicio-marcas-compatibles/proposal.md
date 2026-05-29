# Servicio — marcas compatibles (catálogo maestro)

## Why
El catálogo maestro (`Servicio`) solo relacionaba `modelos_compatibles`. Un vehículo con modelo nuevo (p. ej. creado al registrar patente) no aparecía en filtros que exigen modelo exacto, aunque el servicio aplique a toda la marca.

Los proveedores ya configuran ofertas por **marca** (`OfertaServicio.marca_vehiculo_seleccionada`); el catálogo maestro debe alinearse sin cambiar onboarding ni flujos de proveedor.

## What Changes
- `Servicio.marcas_compatibles` M2M → `MarcaVehiculo`
- Módulo `servicios/compatibilidad_vehiculo.py` (reglas centralizadas)
- Admin Django: selector horizontal de marcas (configuración manual)
- Serializers: `marcas_info` en respuestas de catálogo/oferta
- Filtros unificados en catálogo, IA agendamiento, personalización y órdenes
- **Sin cambios** en motor de salud, `consultar-patente`, `OfertaServicio`, onboarding proveedor

## Requirements
- REQ-MARCA-CATALOGO: el admin SHALL asociar marcas compatibles a cada servicio
- REQ-MARCA-MODELO: si un servicio tiene modelos de una marca listados, SHALL restringir a esos modelos; si solo tiene marca, SHALL aplicar a todos los modelos de esa marca
- REQ-LEGACY-MODELOS: servicios con solo `modelos_compatibles` SHALL seguir filtrando por marca inferida hasta migración manual
- REQ-SIN-IMPACTO-PROVEEDOR: onboarding, crear servicio y especialidades del proveedor SHALL comportarse igual
- REQ-SIN-IMPACTO-SALUD: motor de salud y API patente SHALL no depender de `modelos_compatibles` del servicio

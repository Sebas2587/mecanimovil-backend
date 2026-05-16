# Propuesta: Aislamiento listado Mis solicitudes (API)

## Why
`GET /ordenes/solicitudes-publicas/` devolvía el feed de proveedor a usuarios sin perfil `Cliente`, filtrando solicitudes ajenas en la app de usuarios.

## What Changes
- Acciones de listado cliente (`list`, `activas`, `mis_solicitudes`, `puede_crear_solicitud`) filtran solo por `cliente` autenticado.
- Nuevo action `mis-solicitudes` para la app usuarios.
- `OfertaProveedorViewSet`: ofertas del cliente solo por `solicitud__cliente` (sin `vehiculo__cliente`).
- Tests de regresión.

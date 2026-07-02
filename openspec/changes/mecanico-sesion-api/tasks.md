# Tasks: mecanico-sesion-api

## Backend
- [x] Extender `taller_contexto.resolver_contexto_taller` para rol `mecanico`
- [x] Extender `login_proveedor` y `EstadoProveedorView` con `rol_taller=mecanico`, `miembro_id`
- [x] Actualizar `MiembroTallerSerializer` para credenciales de mecánico
- [x] Scoping `ProveedorOrdenesViewSet.get_queryset` y bloqueo aceptar/rechazar
- [x] Scoping `ChecklistInstanceViewSet` (queryset + acceso por orden)
- [x] Forzar filtro de agenda en `ProveedorAgendaViewSet` para mecánico
- [x] Push `orden_asignada_mecanico` y checklist al mecánico asignado
- [x] Permitir `subir_foto` al mecánico sobre su propio registro

## Verificación
- [x] Login mecánico activo retorna `rol_taller=mecanico` y `miembro_id`
- [x] Mecánico solo ve órdenes con `mecanico_asignado` propio
- [x] Mecánico recibe 403 en aceptar/rechazar
- [x] Mecánico no accede a checklist de orden ajena

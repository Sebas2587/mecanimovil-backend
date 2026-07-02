# mecanico-sesion-api

## Why

Los mecánicos del equipo (`MiembroTaller.rol='mecanico'`) son recursos agendables pero no tienen sesión propia en la app de proveedores. No pueden ver sus órdenes asignadas, su calendario ni completar el checklist de verificación del servicio. El taller debe poder configurarles acceso (usuario/contraseña) como ya ocurre con el supervisor.

## What Changes

- Extender `login_proveedor` y `EstadoProveedorView` para resolver `rol_taller='mecanico'` con `miembro_id` y `taller_id`.
- Extender `resolver_contexto_taller` para incluir mecánicos con login activo.
- Permitir credenciales opcionales al crear/editar mecánicos en `MiembroTallerSerializer`.
- Scoping de órdenes, checklist y agenda al mecánico asignado.
- Bloquear `aceptar`/`rechazar` órdenes para rol mecánico.
- Push `orden_asignada_mecanico` y notificación de checklist al mecánico asignado.
- Autoservicio de foto de perfil para mecánico logueado.

## Scope (out)

- Permisos configurables para mecánico (son fijos por rol).
- Aceptar/rechazar órdenes por mecánico.
- Asistente IA de reparación (change `asistente-diagnostico-ia`).

## Requirements

- REQ-MECANICO-LOGIN: un `MiembroTaller(rol='mecanico', activo=True)` con `usuario` SHALL poder iniciar sesión vía `POST /usuarios/login-proveedor/` y recibir `rol_taller='mecanico'`, `miembro_id`, `taller_id`.
- REQ-MECANICO-SCOPE-ORDENES: el mecánico autenticado SHALL ver solo `SolicitudServicio` donde `mecanico_asignado` es su `MiembroTaller`.
- REQ-MECANICO-SCOPE-CHECKLIST: el mecánico SHALL acceder solo a checklists de órdenes asignadas a él.
- REQ-MECANICO-SCOPE-AGENDA: el mecánico SHALL ver solo eventos de agenda filtrados a su `miembro_taller_id`.
- REQ-MECANICO-NO-ACEPTAR: `aceptar`/`rechazar` SHALL devolver 403 para rol mecánico.
- REQ-MECANICO-CREDENCIALES: el mandante SHALL poder asignar/actualizar username/password/email de un mecánico vía CRUD de equipo.
- REQ-MECANICO-PUSH: al asignar `mecanico_asignado` con usuario activo, SHALL enviarse push `orden_asignada_mecanico`.

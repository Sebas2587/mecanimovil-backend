# Delta: proveedor-equipo (sesión mecánico)

## ADDED Requirements

### Requirement: Login de mecánico de equipo
Un `MiembroTaller` con `rol='mecanico'`, `activo=True` y `usuario` asociado **SHALL** poder autenticarse en `POST /api/usuarios/login-proveedor/` y recibir `tipo_proveedor='taller'`, `rol_taller='mecanico'`, `miembro_id` y `taller_id`.

#### Scenario: Login mecánico activo
- GIVEN un mecánico con usuario y contraseña configurados por el mandante
- WHEN hace POST a `/usuarios/login-proveedor/` con credenciales válidas
- THEN la respuesta incluye `rol_taller: 'mecanico'` y `miembro_id` del miembro

#### Scenario: Login mecánico deshabilitado
- GIVEN un mecánico con `activo=False`
- WHEN intenta iniciar sesión
- THEN recibe HTTP 403 con mensaje de acceso deshabilitado

### Requirement: Scoping de órdenes del mecánico
El mecánico autenticado **SHALL** listar y consultar solo `SolicitudServicio` donde `mecanico_asignado_id` coincide con su `MiembroTaller`.

#### Scenario: Listar órdenes propias
- GIVEN un mecánico autenticado con 2 órdenes asignadas y 5 del taller no asignadas a él
- WHEN hace GET a `/ordenes/proveedor-ordenes/`
- THEN recibe exactamente las 2 órdenes asignadas

### Requirement: Mecánico no acepta ni rechaza órdenes
Las acciones `aceptar` y `rechazar` **SHALL NOT** estar disponibles para rol mecánico.

#### Scenario: Rechazo de aceptar orden
- GIVEN un mecánico autenticado y una orden asignada pendiente de aceptación
- WHEN hace POST a `/ordenes/proveedor-ordenes/{id}/aceptar/`
- THEN recibe HTTP 403

### Requirement: Credenciales de acceso del mecánico
El mandante **SHALL** poder asignar o actualizar username, email y password de un mecánico vía `/usuarios/taller/equipo/`.

#### Scenario: Dar acceso a mecánico existente
- GIVEN un mecánico sin `usuario`
- WHEN el mandante hace PATCH con username y password
- THEN se crea el `Usuario` y queda ligado al `MiembroTaller`

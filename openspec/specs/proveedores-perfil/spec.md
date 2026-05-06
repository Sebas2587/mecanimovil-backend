# proveedores-perfil Specification

## Purpose
Gestionar el perfil público y operativo del proveedor: datos personales, especialidades,
marcas que atiende, documentos de verificación y estado de activación.

## Requirements

### Requirement: Perfil del proveedor
El proveedor puede ver y editar su información profesional.

#### Scenario: Actualizar perfil
- GIVEN un proveedor autenticado
- WHEN hace PATCH /api/proveedores/perfil/ con datos válidos
- THEN el perfil se actualiza
- AND la información se refleja en el listado público solo si el proveedor está verificado

#### Scenario: Subir foto de perfil
- GIVEN un proveedor autenticado
- WHEN hace POST /api/proveedores/perfil/foto/ con imagen válida
- THEN la imagen se sube a Cloudinary
- AND se actualiza la URL de foto en el perfil

### Requirement: Especialidades y marcas
El proveedor especifica qué tipos de servicio y marcas de vehículo atiende.

#### Scenario: Configurar especialidades
- GIVEN un proveedor autenticado
- WHEN hace PUT /api/proveedores/especialidades/ con lista de especialidades
- THEN las especialidades del proveedor se actualizan
- AND se usan para filtrar solicitudes relevantes

### Requirement: Verificación de documentos
Los documentos del proveedor deben ser aprobados por un admin antes de activarse.

#### Scenario: Proveedor sube documentos
- GIVEN un proveedor con estado=pendiente_verificacion
- WHEN hace POST /api/proveedores/documentos/ con archivos requeridos
- THEN los documentos se almacenan y quedan en estado=pendiente_revision

#### Scenario: Admin aprueba proveedor
- GIVEN documentos subidos en estado=pendiente_revision
- WHEN un admin hace POST /api/admin/proveedores/{id}/aprobar/
- THEN el proveedor pasa a estado=verificado
- AND puede operar en la plataforma (recibir solicitudes, completar órdenes)

#### Scenario: Admin rechaza documentos
- GIVEN documentos con información incorrecta
- WHEN un admin rechaza con motivo
- THEN el proveedor recibe notificación con el motivo de rechazo
- AND puede volver a subir documentos corregidos

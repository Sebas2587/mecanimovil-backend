# Delta: proveedor-equipo (API)

## ADDED Requirements

### REQ-EQUIPO-API-CRUD
La app de proveedores **SHALL** exponer endpoints para que el dueño del taller gestione
su equipo: listar, crear, editar y eliminar mecánicos, y designar supervisor.

#### Scenario: Crear mecánico
- GIVEN un dueño autenticado con un taller
- WHEN hace POST a `/usuarios/taller/equipo/` con nombre, especialidades y modalidad
- THEN se crea el `MiembroTaller(rol='mecanico')` ligado a su taller

#### Scenario: Deshabilitar mecánico
- GIVEN un mecánico activo del taller
- WHEN el supervisor/dueño llama `POST .../equipo/{id}/deshabilitar/`
- THEN `activo=False` y el mecánico deja de aparecer en disponibilidad

#### Scenario: Acceso ajeno
- GIVEN un dueño A
- WHEN intenta editar un miembro del taller del dueño B
- THEN la operación es rechazada (404/403)

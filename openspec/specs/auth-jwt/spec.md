# auth-jwt Specification

## Purpose
Gestionar autenticación y autorización de usuarios mediante JWT (SimpleJWT).
Cubre registro, login, refresh de tokens y control de acceso por roles.

## Requirements

### Requirement: Registro y login por rol
Los usuarios se registran con un rol explícito (`usuario_final` o `proveedor`).
El login devuelve access token y refresh token.

#### Scenario: Login exitoso
- GIVEN un usuario registrado con email y password válidos
- WHEN hace POST /api/auth/login/
- THEN recibe access_token (15 min) y refresh_token (7 días) con status 200

#### Scenario: Login con credenciales inválidas
- GIVEN un email o password incorrecto
- WHEN hace POST /api/auth/login/
- THEN recibe status 401 con mensaje de error

#### Scenario: Registro de proveedor
- GIVEN datos válidos de nombre, email, password y rol=proveedor
- WHEN hace POST /api/auth/registro/
- THEN se crea el usuario con is_active=False pendiente de verificación
- AND se envía email de confirmación

### Requirement: Refresh de tokens
El access token se renueva usando el refresh token sin re-login.

#### Scenario: Refresh válido
- GIVEN un refresh_token vigente
- WHEN hace POST /api/auth/token/refresh/
- THEN recibe nuevo access_token con status 200

#### Scenario: Refresh expirado
- GIVEN un refresh_token vencido
- WHEN hace POST /api/auth/token/refresh/
- THEN recibe status 401 y el usuario debe volver a hacer login

### Requirement: Control de acceso por rol
Cada endpoint verifica el rol del usuario mediante permisos DRF.

#### Scenario: Proveedor accede a endpoint de proveedor
- GIVEN un usuario con rol=proveedor y access_token válido
- WHEN accede a un endpoint protegido con IsProveedor
- THEN recibe la respuesta con status 200

#### Scenario: Usuario final intenta acceso de proveedor
- GIVEN un usuario con rol=usuario_final
- WHEN accede a un endpoint protegido con IsProveedor
- THEN recibe status 403 Forbidden

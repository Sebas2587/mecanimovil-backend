# proveedores-horarios Specification

## Purpose
TBD - created by archiving change horarios-semanales-publicos-proveedor. Update Purpose after archive.
## Requirements
### Requirement: Endpoint público de horarios semanales
El backend **SHALL** exponer un endpoint público que devuelva la configuración semanal de horarios de un proveedor (taller o mecánico) para ser consumida por la app de usuarios.

#### Scenario: Obtener horarios semanales de taller
- GIVEN un taller existente y verificado
- WHEN se hace GET `/api/usuarios/talleres/{id}/horarios_semanales/`
- THEN el backend retorna status 200 con una lista de 7 días (0..6) indicando `activo`, `hora_inicio`, `hora_fin`

#### Scenario: Obtener horarios semanales de mecánico
- GIVEN un mecánico existente y verificado
- WHEN se hace GET `/api/usuarios/mecanicos-domicilio/{id}/horarios_semanales/`
- THEN el backend retorna status 200 con una lista de 7 días (0..6) indicando `activo`, `hora_inicio`, `hora_fin`

#### Scenario: Proveedor sin configuración
- GIVEN un proveedor sin registros `HorarioProveedor`
- WHEN se consulta su configuración semanal
- THEN el backend retorna lista vacía `[]` (sin horarios sintéticos)
- AND la app de usuarios muestra que el proveedor debe configurar su semana en la app proveedor

> **Nota (2026-05-21):** Se eliminó el fallback de 7 días genéricos. El calendario de agendamiento
> depende de filas reales en BD. Ver `openspec/specs/agendamiento-disponibilidad/spec.md`.


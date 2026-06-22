# taller-equipo-api

## Why

El dueño del taller (mandante) necesita administrar su equipo desde la app de proveedores:
crear/editar/eliminar mecánicos, definir sus especialidades y modalidad, designar un
supervisor, y habilitar/deshabilitar mecánicos (acción de supervisor).

## What Changes

- `MiembroTallerViewSet` bajo `/usuarios/taller/equipo/` (scoped al taller del usuario autenticado).
- CRUD de mecánicos (mandante): crear, editar, eliminar, set especialidades y `modalidad_tecnico`.
- Alta/edición del supervisor (máx. 1).
- Action `habilitar`/`deshabilitar` (toggle `activo`).
- Serializers con validación: mecánico requiere ≥1 especialidad; roles únicos.
- Permiso: solo el `Usuario` dueño del taller opera sobre su equipo.

## Scope (out)

- Login propio de supervisor/mecánico (futuro).
- Asignación automática (change `asignacion-automatica-mecanico`).

## Requirements

- REQ-EQUIPO-SCOPE: el endpoint SHALL exponer solo miembros del taller del usuario autenticado.
- REQ-EQUIPO-CRUD-MECANICO: el dueño SHALL poder crear/editar/eliminar mecánicos.
- REQ-EQUIPO-TOGGLE: `habilitar`/`deshabilitar` SHALL cambiar `activo` del mecánico.
- REQ-EQUIPO-SUPERVISOR-UNICO: SHALL rechazar un segundo supervisor.
- REQ-EQUIPO-ESPECIALIDAD: SHALL rechazar mecánico sin especialidades.

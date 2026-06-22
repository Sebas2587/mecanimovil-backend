# Tasks: taller-equipo-api

## Backend
- [ ] `MiembroTallerSerializer` (validación especialidades/roles)
- [ ] `MiembroTallerViewSet` (CRUD scoped al taller del usuario)
- [ ] Actions `habilitar` / `deshabilitar`
- [ ] Rutas en `usuarios/urls.py`
- [ ] Permisos: dueño del taller

## Verificación
- [ ] Crear mecánico sin especialidad → 400
- [ ] Segundo supervisor → 400
- [ ] Deshabilitar mecánico → `activo=False`

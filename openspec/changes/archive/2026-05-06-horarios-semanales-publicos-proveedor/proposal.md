# Propuesta: Horarios semanales públicos de proveedor (Backend)

## Why
La app de usuarios necesita mostrar los horarios semanales configurados por el proveedor (taller/mecánico) en la ficha pública/privada. Hoy existe `horarios_disponibles` pero requiere `fecha` y está pensado para slots; no entrega la configuración semanal completa de forma simple.

## What Changes
- Exponer endpoints públicos para obtener la **configuración semanal** (`HorarioProveedor`) de un proveedor:
  - Taller: `GET /api/usuarios/talleres/{id}/horarios_semanales/`
  - Mecánico: `GET /api/usuarios/mecanicos-domicilio/{id}/horarios_semanales/`
- Respuesta: lista de días con `activo`, `hora_inicio`, `hora_fin`, `duracion_slot`, `tiempo_descanso`, etc.
- Si no hay configuración en BD, retornar un set por defecto coherente con las reglas existentes (similar a `_generar_horario_defecto_*`).

## Non-goals
- No se calculan slots por fecha (eso sigue en `horarios_disponibles`).
- No se cambia el flujo de configuración por parte del proveedor.


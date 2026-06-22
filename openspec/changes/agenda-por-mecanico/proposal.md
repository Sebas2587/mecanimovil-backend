# agenda-por-mecanico

## Why

Cada mecánico del taller tiene agenda y horarios independientes. La disponibilidad pública
del taller debe ser la **unión** de las agendas de sus mecánicos aptos, no un único horario
a nivel taller. El supervisor administra el horario de cada mecánico (habilitar/deshabilitar
por día de la semana).

## What Changes

- `disponibilidad_proveedor.py`: cuando el taller tiene mecánicos `activo=True`, la
  disponibilidad = unión de ventanas libres por mecánico, filtrando por especialidad
  requerida (de `oferta_servicio_id → servicio → categoría`) y `modalidad_tecnico`.
- `intervalos_ocupados_dia` y `HorarioProveedor` resueltos por `miembro_taller`.
- Fallback: taller sin mecánicos → comportamiento actual a nivel taller.
- Mecánico deshabilitado se excluye de la unión.
- Endpoints de horario por mecánico (supervisor): listar/editar `HorarioProveedor` por miembro.

## Requirements

- REQ-DISPONIBILIDAD-UNION: con mecánicos activos, los slots ofrecidos SHALL ser la unión por mecánico apto.
- REQ-DISPONIBILIDAD-ESPECIALIDAD: solo mecánicos con la especialidad requerida SHALL aportar slots.
- REQ-DISPONIBILIDAD-MODALIDAD: solo mecánicos con `modalidad_tecnico` compatible SHALL aportar slots.
- REQ-DISPONIBILIDAD-DESHABILITADO: un mecánico `activo=False` SHALL NOT aportar slots.
- REQ-DISPONIBILIDAD-FALLBACK: sin mecánicos activos, SHALL usarse el horario a nivel taller.

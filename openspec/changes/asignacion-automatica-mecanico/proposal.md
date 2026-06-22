# asignacion-automatica-mecanico

## Why

Cuando un cliente agenda con un taller y elige fecha/hora, el sistema debe asignar
internamente el servicio a un mecánico que cumpla especialidad, modalidad y disponibilidad,
balanceando carga entre el equipo.

## What Changes

- Nuevo servicio `mecanimovilapp/apps/ordenes/services/asignacion_mecanico.py`:
  `asignar_mecanico_para_solicitud(taller, fecha, hora, servicio_ids, modalidad)`.
- Candidatos: `MiembroTaller(rol='mecanico', activo=True)` con especialidad ∈ requeridas y modalidad compatible.
- Filtra por agenda individual libre en el slot; desempate por balanceo de carga.
- Setea `SolicitudServicio.mecanico_asignado` en los 4 puntos de creación de orden.
- Si no hay técnico: deja `null` (reasignación manual del supervisor).

## Requirements

- REQ-ASIGNACION-ESPECIALIDAD: el mecánico asignado SHALL cubrir la especialidad requerida.
- REQ-ASIGNACION-MODALIDAD: el mecánico asignado SHALL tener modalidad compatible.
- REQ-ASIGNACION-DISPONIBLE: el mecánico asignado SHALL estar libre en el slot.
- REQ-ASIGNACION-BALANCEO: ante empate, SHALL preferirse el mecánico con menos órdenes en la ventana.
- REQ-ASIGNACION-NULL-SAFE: sin candidato, la orden SHALL crearse con `mecanico_asignado=null`.

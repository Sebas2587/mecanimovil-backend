# Tasks: proveedor-modelo-unificado-equipo

## Backend
- [ ] `Taller`: campos `modalidad_atencion`, `radio_cobertura`
- [ ] Nuevo modelo `MiembroTaller` (rol, especialidades M2M, modalidad_tecnico, activo) + constraints
- [ ] `HorarioProveedor`: FK `miembro_taller` + unique `(miembro_taller, dia_semana)`
- [ ] `CitaAgendaPersonal`: FK `miembro_taller`
- [ ] `SolicitudServicio`: FK `mecanico_asignado`
- [ ] `MechanicServiceArea`: FK `taller` (XOR con mechanic)
- [ ] Migración de esquema
- [ ] Data migration idempotente: mandante por taller + modalidad por defecto

## Verificación
- [ ] Constraints de roles únicos rechazan 2 mandantes / 2 supervisores
- [ ] Taller sin miembros sigue operando (no regresión)

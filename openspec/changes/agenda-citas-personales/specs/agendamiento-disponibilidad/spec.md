# Delta: agendamiento-disponibilidad

## ADDED Requirements

### REQ-CITAS-PERSONALES-OCUPAN-AGENDA
Las citas `CitaAgendaPersonal` en estado `activa` **SHALL** incluirse en
`intervalos_ocupados_dia()` fusionadas con intervalos de `SolicitudServicio`.

#### Scenario: Cita personal activa reduce slots
- GIVEN proveedor con cita personal activa 10:00 duración 60 min
- WHEN se llama `disponibilidad_con_duracion` ese día
- THEN ningún slot de inicio 10:00 está disponible

#### Scenario: Cita cerrada o cancelada no ocupa
- GIVEN cita personal en estado `cerrada` o `cancelada`
- WHEN se calcula disponibilidad
- THEN ese intervalo no se considera ocupado

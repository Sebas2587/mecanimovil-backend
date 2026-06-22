# proveedor-modelo-unificado-equipo

## Why

Hoy un `Taller` es un proveedor monolítico atado a un solo `Usuario`, sin concepto de
equipo. La especialidad y la agenda están mal atribuidas al taller-como-todo
(`HorarioProveedor` tiene unique `(taller, dia_semana)` → un solo horario por día).
El negocio necesita: equipo de taller (mandante, supervisor, mecánicos como recursos),
especialidad y agenda por mecánico, y unificar la atención por **modalidad**
(en taller / a domicilio / ambas) en vez de por clase de entidad.

## What Changes

- `Taller` se vuelve el superset "Proveedor": nuevos campos `modalidad_atencion` y
  `radio_cobertura`; se permite operar sin `TallerDireccion` (modalidad domicilio pura).
- Nuevo modelo `MiembroTaller` (recurso, sin login obligatorio): `rol`
  (`mandante|supervisor|mecanico`), `especialidades` M2M `CategoriaServicio`,
  `modalidad_tecnico`, `activo` (habilitado/deshabilitado).
- `HorarioProveedor`: FK nullable `miembro_taller` + unique `(miembro_taller, dia_semana)`.
- `CitaAgendaPersonal`: FK nullable `miembro_taller`.
- `SolicitudServicio`: FK nullable `mecanico_asignado → MiembroTaller`.
- `MechanicServiceArea`: FK nullable `taller` (XOR con `mechanic`) para cobertura domicilio del taller.
- Migración de datos idempotente: crear `MiembroTaller(rol=mandante)` por cada `Taller`
  con `usuario`; `modalidad_atencion='en_taller'` por defecto.
- `tipo_proveedor` se conserva como discriminador de compatibilidad (estrategia strangler).

## Scope (in)

| Área | Entregable |
|------|------------|
| Modelos Django | `MiembroTaller`; campos nuevos en `Taller`, `HorarioProveedor`, `MechanicServiceArea`, `CitaAgendaPersonal`, `SolicitudServicio` |
| Migraciones | Esquema + data migration mandante por taller |
| Constraints | 1 mandante + 1 supervisor por taller; mecánico requiere ≥1 especialidad (capa app) |

## Scope (out)

- Migración física de `MecanicoDomicilio` al modelo unificado (iniciativa posterior).
- Cambios de créditos (se mantienen por `Usuario`).
- Lógica de disponibilidad por mecánico (change `agenda-por-mecanico`).

## Requirements

- REQ-PROV-MODALIDAD: `Taller.modalidad_atencion` SHALL ser `en_taller|a_domicilio|ambas`.
- REQ-MIEMBRO-ROL: `MiembroTaller.rol` SHALL ser `mandante|supervisor|mecanico`.
- REQ-MIEMBRO-UNICOS: por taller SHALL existir a lo sumo 1 `mandante` y 1 `supervisor`.
- REQ-MIEMBRO-ESPECIALIDAD: un `mecanico` SHALL tener ≥1 especialidad.
- REQ-HORARIO-MIEMBRO: `HorarioProveedor` SHALL admitir `miembro_taller` con unique `(miembro_taller, dia_semana)`.
- REQ-SOLICITUD-ASIGNACION: `SolicitudServicio.mecanico_asignado` SHALL ser FK nullable a `MiembroTaller`.
- REQ-COMPAT-FALLBACK: un taller sin `MiembroTaller` activos SHALL operar como hoy.

## Referencias de código

- `mecanimovilapp/apps/usuarios/models.py` (`Taller` L236, `HorarioProveedor` L722, `MechanicServiceArea` L361)
- `mecanimovilapp/apps/ordenes/models.py` (`SolicitudServicio` L19, `CitaAgendaPersonal` L1870)

# agendamiento-disponibilidad — delta agente IA

## ADDED Requirements

### Requirement: Agente conversacional usa disponibilidad por equipo

El agendamiento post-cotización del agente IA (`agendamiento_conversacional`) SHALL usar `disponibilidad_con_duracion` respetando:

- Horario general del taller (`HorarioProveedor` sin `miembro_taller`)
- Horario individual de cada mecánico (`HorarioProveedor.miembro_taller`)
- Unión de cupos por mecánicos aptos cuando el taller tiene equipo
- Modalidad del servicio (`taller` / `domicilio`) mapeada a modalidad técnico

#### Scenario: Slot solo en horario del mecánico
- GIVEN taller abierto lun–vie 08:00–19:00
- AND mecánico Juan solo miércoles 10:00–14:00
- WHEN se consulta disponibilidad miércoles para servicio en taller
- THEN los slots ofrecidos por el agente no exceden la intersección/unión calculada por el motor existente

### Requirement: Especialidad del servicio cotizado

Con `oferta_servicio_id` en metadata del borrador, el agente SHALL llamar `disponibilidad_con_duracion` con `requiere_especialidad=True`. Si no hay slots, MAY reintentar sin filtro de especialidad. Al confirmar slot, `resolver_miembro_cita_personal` SHALL recibir `categorias_requeridas` derivadas de las categorías del servicio ofertado, con el mismo fallback.

#### Scenario: Sin mecánico especialista libre
- GIVEN servicio de frenos y ningún especialista libre en el slot pedido
- WHEN el cliente confirma horario
- THEN el sistema intenta asignar otro mecánico libre compatible con el horario (fallback)
- OR informa que el slot fue tomado y reofrece cupos

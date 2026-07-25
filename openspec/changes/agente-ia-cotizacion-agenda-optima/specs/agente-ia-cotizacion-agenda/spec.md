# agente-ia-cotizacion-agenda Specification

## Purpose

Agente IA conversacional por taller: captura lead, borrador cotizable con gate de envío, y agendamiento post-aceptación respetando horarios del taller/mecánicos y especialidad del servicio.

## ADDED Requirements

### Requirement: Readiness gate del borrador

Al crear o actualizar un borrador desde el agente IA, el sistema SHALL evaluar en código (sin LLM adicional) si está listo para envío: patente verificada, teléfono, precios de catálogo en todas las líneas, dirección si modalidad domicilio. SHALL persistir `listo_para_enviar` y `pendientes_revision` en `CotizacionCanal.metadata`.

#### Scenario: Borrador incompleto
- GIVEN borrador agente IA sin teléfono del cliente
- WHEN se guarda el borrador
- THEN `metadata.listo_para_enviar` es false
- AND `metadata.pendientes_revision` incluye falta de teléfono

#### Scenario: Borrador listo
- GIVEN patente enriquecida, teléfono, precios catálogo y modalidad taller
- WHEN se guarda el borrador
- THEN `metadata.listo_para_enviar` es true
- AND push al taller indica "Cotización lista para enviar"

### Requirement: Aceptación unificada dispara agendamiento

Cualquier aceptación de cotización enviada (link público, botón WhatsApp, `marcar-aceptada` mandante) SHALL crear `CitaAgendaPersonal` con `horario_por_confirmar=true` y encolar agendamiento conversacional si existe conversación omnicanal.

#### Scenario: Mandante marca aceptada en Messenger
- GIVEN cotización enviada en conversación Instagram
- WHEN el taller usa `POST .../marcar-aceptada/`
- THEN se crea cita placeholder
- AND se encola `iniciar_agendamiento_task`

### Requirement: Agenda con especialidad y propuesta proactiva

Tras aceptación, el agente SHALL calcular slots usando `disponibilidad_con_duracion` con `oferta_servicio_id` y especialidad requerida (fallback si no hay cupo). SHALL asignar mecánico con `categorias_requeridas` (fallback). SHALL proponer al cliente el slot más próximo disponible (o preferencia previa si sigue libre) antes de pedir día/hora abierto.

#### Scenario: Propuesta de slot óptimo
- GIVEN cotización aceptada con cupos mañana 10:00
- WHEN inicia agendamiento IA
- THEN el primer mensaje propone esa fecha/hora
- AND no lista todos los días sin priorizar

#### Scenario: Mecánico con horario propio
- GIVEN mecánico con `HorarioProveedor.miembro_taller` miércoles 09:00–18:00
- WHEN se calculan slots para ese día
- THEN solo se ofrecen horas dentro de su jornada (o unión con taller si aplica)

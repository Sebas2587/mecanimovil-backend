# OpenSpec — mecanimovil-backend

## Specs canónicas

| Spec | Tema |
|------|------|
| [agendamiento-disponibilidad](specs/agendamiento-disponibilidad/spec.md) | **API slots, duración oferta, HorarioProveedor** |
| [proveedores-horarios](specs/proveedores-horarios/spec.md) | `horarios_semanales` público |
| [servicio-compatibilidad](changes/servicio-marcas-compatibles/specs/servicio-compatibilidad/spec.md) | Marcas compatibles en catálogo maestro |
| [servicio-compatibilidad-motor](changes/servicio-tipos-motor-compatibles/specs/servicio-compatibilidad-motor/spec.md) | Tipos de motor en catálogo maestro |
| [repuesto-compatibilidad](changes/repuesto-marcas-compatibles/specs/repuesto-compatibilidad/spec.md) | Marcas compatibles en repuestos |
| [vehiculos — salud](specs/vehiculos/spec.md) | **HealthEngine, Weibull, ML, checklist→salud** |

## Skills Cursor (backend)

| Skill | Cuándo usarla |
|-------|----------------|
| [openspec-health-engine](.cursor/skills/openspec-health-engine/SKILL.md) | Editar algoritmo de salud, checklist→componentes, PredictorSalud, Celery salud |

## Changes de referencia

| Change | Cuándo leerlo |
|--------|----------------|
| [agendamiento-calendario-api-resilience](changes/agendamiento-calendario-api-resilience/design.md) | Fix 500, serialización slots |
| [agendamiento-disponibilidad-duracion](changes/agendamiento-disponibilidad-duracion/proposal.md) | Propuesta original duración/ventanas |
| [health-engine-edad-componente](changes/health-engine-edad-componente/design.md) | Cap edad por componente, pipeline salud, ML |
| [predicciones-ml-salud-vehicular](changes/predicciones-ml-salud-vehicular/design.md) | 3 capas PredictorSalud (bootstrap/ML/similares) |
| [checklist-inteligente-salud (archivo)](changes/archive/2026-05-09-checklist-inteligente-salud/design.md) | REEMPLAZA vs INSPECCIONA, ancla Weibull |

Cliente (navegación): `mecanimovil-usuarios/openspec/changes/agendamiento-calendario-contexto-unificado/design.md`

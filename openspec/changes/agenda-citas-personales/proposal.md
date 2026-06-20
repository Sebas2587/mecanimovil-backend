# agenda-citas-personales

## Why

Los proveedores (talleres y mecánicos a domicilio) atienden clientes fuera de la plataforma
Mecanimovil — walk-ins, referidos, WhatsApp — y necesitan bloquear su agenda sin crear una
`SolicitudServicio` completa (sin pago, checklist, créditos ni marketplace).

Hoy `intervalos_ocupados_dia` solo considera `SolicitudServicio` en estados de marketplace.
Las citas manuales no existen en BD y el calendario muestra slots libres que en realidad
están ocupados.

## What Changes

- Nuevo par de tablas normalizadas 1:1: `CitaAgendaPersonal` + `CitaAgendaPersonalDetalle`.
- Estados de ciclo de vida: `activa` | `cerrada` | `cancelada`.
- Solo citas `activa` bloquean disponibilidad en `disponibilidad_proveedor.intervalos_ocupados_dia`.
- Borrado físico permitido únicamente cuando `estado = cancelada`.
- Sin relación con `SolicitudServicio`, checklist, créditos ni flujo de pago.
- Extensión del servicio de disponibilidad para fusionar intervalos de citas personales.

## Scope (in)

| Área | Entregable |
|------|------------|
| Modelos Django | `CitaAgendaPersonal`, `CitaAgendaPersonalDetalle` en `apps/ordenes` |
| Migración | Tablas, constraints, índices |
| Disponibilidad | Query adicional en `intervalos_ocupados_dia` |
| API proveedor | CRUD citas personales (fase posterior; diseño DB aquí) |

## Scope (out)

- Conversión de cita personal → `SolicitudServicio`.
- Checklist, pagos, Mercado Pago, créditos de marketplace.
- Notificaciones push al cliente externo.
- App usuarios (clientes registrados no crean citas personales).

## Requirements

- REQ-CITA-XOR-PROVEEDOR: cada cita SHALL tener exactamente uno de `taller` o `mecanico`.
- REQ-CITA-ESTADOS: estados SHALL ser `activa`, `cerrada`, `cancelada` (default `activa`).
- REQ-CITA-BLOQUEO-AGENDA: solo `activa` SHALL ocupar intervalo en `intervalos_ocupados_dia`.
- REQ-CITA-SERVICIO-OR: en detalle, `oferta_servicio` OR `servicio_nombre` SHALL ser obligatorio.
- REQ-CITA-DELETE-CANCELADA: DELETE físico SHALL permitirse solo si `estado = cancelada`.
- REQ-CITA-SIN-MARKETPLACE: no FK ni side-effects hacia `SolicitudServicio`, checklist o créditos.

## Documentación

- Diseño DB (este change): `design.md`
- Spec canónica (post-implementación): `openspec/specs/agenda-citas-personales/spec.md`

## Referencias de código existente

- Patrón XOR proveedor: `SolicitudServicio`, `HorarioProveedor`
- Disponibilidad: `mecanimovilapp/apps/usuarios/services/disponibilidad_proveedor.py`
- Duración en minutos: campo explícito `duracion_minutos` (no deriva de `LineaServicio`)

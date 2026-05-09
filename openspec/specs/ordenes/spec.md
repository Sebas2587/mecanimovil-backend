# ordenes Specification

## Purpose
Gestionar el ciclo de vida completo de órdenes de servicio entre usuarios y proveedores.
Una orden se origina desde una solicitud aceptada y avanza por estados definidos.

## Requirements

### Requirement: Estados de una orden
Una orden sigue el flujo: pendiente → confirmada → en_progreso → completada | cancelada.
Solo el proveedor puede avanzar el estado; solo el usuario puede cancelar antes de confirmada.

#### Scenario: Proveedor confirma orden
- GIVEN una orden en estado=pendiente asignada al proveedor
- WHEN el proveedor hace PATCH /api/ordenes/{id}/ con estado=confirmada
- THEN la orden cambia a confirmada
- AND se envía notificación push al usuario

#### Scenario: Proveedor completa orden
- GIVEN una orden en estado=en_progreso
- WHEN el proveedor hace PATCH /api/ordenes/{id}/ con estado=completada
- THEN la orden se marca como completada
- AND se dispara el cálculo de pago al proveedor (Celery task)

#### Scenario: Usuario cancela orden pendiente
- GIVEN una orden en estado=pendiente
- WHEN el usuario hace PATCH /api/ordenes/{id}/ con estado=cancelada
- THEN la orden se cancela
- AND no se cobra al usuario

#### Scenario: Intento de retroceder estado
- GIVEN una orden en estado=completada
- WHEN cualquier actor intenta cambiar a estado anterior
- THEN recibe status 400 con mensaje "Transición de estado no permitida"

### Requirement: Visibilidad de órdenes
Cada actor solo ve sus propias órdenes.

#### Scenario: Proveedor lista sus órdenes
- GIVEN un proveedor autenticado
- WHEN hace GET /api/ordenes/
- THEN recibe solo las órdenes asignadas a ese proveedor

#### Scenario: Usuario lista sus órdenes
- GIVEN un usuario_final autenticado
- WHEN hace GET /api/ordenes/
- THEN recibe solo las órdenes creadas por ese usuario

### Requirement: Checklist de servicio
Cada orden puede tener un checklist de items a verificar durante el servicio.

#### Scenario: Proveedor completa checklist
- GIVEN una orden en estado=en_progreso con checklist asociado
- WHEN el proveedor marca todos los items del checklist
- THEN el checklist queda en estado=completado

### Requirement: Estado pendiente_firma_cliente

`SolicitudServicio.estado` **SHALL** soportar el valor
`pendiente_firma_cliente` para representar la ventana entre que el
técnico cierra el checklist con su firma y el cliente confirma desde su
app. Solo el endpoint `firmar-cliente` o el endpoint `finalize` con
ambas firmas pueden hacer transitar la orden fuera de este estado.

#### Scenario: Orden entra a pendiente_firma_cliente
- GIVEN una orden en `checklist_en_progreso`
- WHEN el proveedor finaliza el checklist con solo `firma_tecnico`
- THEN `orden.estado == 'pendiente_firma_cliente'`

#### Scenario: Orden completa al firmar el cliente
- GIVEN una orden en `pendiente_firma_cliente`
- WHEN el cliente dueño firma desde la app del cliente
- THEN `orden.estado == 'completado'`

#### Scenario: Compat con flujo legacy
- GIVEN una orden en `checklist_en_progreso`
- WHEN el proveedor finaliza con `firma_tecnico` y `firma_cliente` en
  la misma petición
- THEN `orden.estado == 'completado'` directamente sin pasar por
  `pendiente_firma_cliente`

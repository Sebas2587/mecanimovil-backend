# ordenes Spec Delta — Estado pendiente_firma_cliente

## ADDED Requirements

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

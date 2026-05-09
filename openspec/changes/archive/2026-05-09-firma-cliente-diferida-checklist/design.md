# Diseño — Firma diferida del cliente

## Contexto

`ChecklistInstance.finalize` y `finalize_by_order` exigen las dos firmas en
una misma transacción. Las firmas se persisten en `ChecklistInstance` como
Base64 (`firma_tecnico`, `firma_cliente`) y la `SolicitudServicio` se mueve
a `en_proceso` o `completado` según el endpoint usado. No existe un
endpoint dedicado para que el cliente firme desde su app autenticada.

## Objetivos

- Permitir que el técnico cierre el checklist con su firma sin que el
  cliente esté presente, dejando el servicio en un estado intermedio
  visible y reversible.
- Dar al cliente un canal propio (su app) para revisar y firmar, generando
  un registro independiente.
- Mantener compatibilidad: si por algún motivo el técnico recoge ambas
  firmas en sitio, el flujo actual sigue funcionando.

## No-goals

- Rechazo o disputa formal del checklist por parte del cliente (queda
  fuera; se podría modelar luego como `RECHAZADO_POR_CLIENTE`).
- Reemplazar `finalize_by_order` (se mantiene; se actualiza con la misma
  semántica de firma diferida).

## Estados nuevos

`ChecklistInstance.ESTADO_CHOICES`

```
('PENDIENTE_FIRMA_CLIENTE', 'Pendiente de firma del cliente')
```

`SolicitudServicio.ESTADO_CHOICES`

```
('pendiente_firma_cliente', 'Pendiente de Firma del Cliente')
```

Ubicación dentro del flujo:

```
checklist_en_progreso
   → (técnico firma)               → pendiente_firma_cliente
   → (cliente firma desde su app)  → completado
```

Si el técnico envía las dos firmas en la misma petición (compat), se salta
el estado intermedio y va directo a `completado`.

## Endpoints

### `POST /api/checklists/instances/{id}/finalize/` (modificado)

- Body: `firma_tecnico` (obligatoria), `firma_cliente` (opcional),
  `ubicacion_lat`, `ubicacion_lng` (opcionales).
- Permisos: proveedor (taller o mecánico) dueño de la orden.
- Lógica:
  - Si `firma_cliente` está presente y no vacío → comportamiento actual:
    `instance.estado='COMPLETADO'`, `orden.estado='completado'`.
  - Si `firma_cliente` ausente → `instance.estado='PENDIENTE_FIRMA_CLIENTE'`,
    `instance.firma_tecnico=...`, `orden.estado='pendiente_firma_cliente'`,
    `instance.fecha_finalizacion` se mantiene `null` (se setea cuando
    el cliente firma).
  - En ambos casos persistir `ubicacion_finalizacion` si llega.
- Respuesta agrega:
  - `requiere_firma_cliente: bool`
  - `mensaje`: copy listo para mostrar al técnico.

### `POST /api/checklists/instances/{id}/firmar-cliente/` (nuevo)

- Body: `firma_cliente` (obligatoria, Base64), `ubicacion_lat`,
  `ubicacion_lng` (opcionales).
- Permisos: `IsAuthenticated` + validación manual `instance.orden.cliente.usuario_id == request.user.id`.
- Lógica:
  - Validar `instance.estado == 'PENDIENTE_FIRMA_CLIENTE'`.
  - Validar `instance.firma_tecnico` presente.
  - Persistir `firma_cliente`, `ubicacion_finalizacion` (si llega y no se
    seteó antes), `fecha_finalizacion`, `progreso_porcentaje=100`,
    `estado='COMPLETADO'`.
  - Persistir `orden.estado='completado'`.
  - Calcula `tiempo_total_minutos` desde `fecha_inicio`.
  - El signal `post_save(ChecklistInstance, estado='COMPLETADO')` ya
    existente dispara `actualizar_salud_desde_checklist` y push de salud.

### `GET /api/checklists/instances/by_order/{orden_id}/` (modificado)

- Cliente dueño puede leer cuando `estado in ('PENDIENTE_FIRMA_CLIENTE','COMPLETADO')`.
- Hoy solo permite `COMPLETADO` para el cliente.

## Notificación

Cuando el técnico firma y la instancia queda en `PENDIENTE_FIRMA_CLIENTE`,
el endpoint `finalize` invoca un nuevo helper en
`vehiculos/tasks.py`:

```
enviar_push_pendiente_firma_cliente(orden)
```

- Crea `Notificacion` (in-app, `tipo='servicio_pendiente_firma'`).
- Encola `send_expo_push_notification` con copy:
  "Tu servicio espera tu firma" / "Revisa el detalle y confirma para
  cerrar el servicio."
- Data del payload: `{ "type": "servicio_pendiente_firma", "orden_id": ..., "checklist_instance_id": ... }`
- Dedup por `orden_id`.

## Migraciones

1. `checklists/0005_pendiente_firma_cliente_estado.py` — `AlterField` de
   `ChecklistInstance.estado` choices.
2. `ordenes/0008_pendiente_firma_cliente_estado.py` — `AlterField` de
   `SolicitudServicio.estado` choices (mismo `max_length=40`).

Ambas idempotentes; no copian datos.

## Frontend

### `mecanimovil-prov`

- `ChecklistContainer.handleSignaturesComplete`: ya no exige firma del
  cliente; envía solo `firma_tecnico`. Al recibir respuesta con
  `requiere_firma_cliente=true`, muestra modal informativo "Esperando
  firma del cliente para cerrar el servicio" y refresca la lista.
- `ChecklistSignatureModal` se invoca con `signatureMode='tecnico_only'`.
- `ChecklistFinalizationData.firma_cliente` pasa a `string | null`
  (opcional).

### `mecanimovil-usuarios`

- Nuevo `app/services/checklistService.js` extiende:
  - `firmarChecklistComoCliente(instanceId, firmaBase64, ubicacion?)`:
    POST a `/checklists/instances/{id}/firmar-cliente/`.
- Nuevo `app/components/checklist/CustomerSignatureModal.js`:
  - Captura firma con `react-native-signature-canvas`.
  - Solicita ubicación con `expo-location` (opcional, no bloqueante).
  - Llama al endpoint y refresca al éxito.
- Nuevo `app/components/checklist/PendingClientSignatureCard.js`: tarjeta
  visible cuando `orden.estado === 'pendiente_firma_cliente'`. Muestra
  CTA "Revisar y firmar checklist". Al tap abre el modal anterior.
- Integración en:
  - `app/screens/solicitudes/DetalleSolicitudScreen.js` (justo encima
    del bloque "Ver Checklist" / acciones).
  - `app/screens/appointments/AppointmentDetailScreen.js` (mismo punto
    de inserción).

## Riesgos y mitigaciones

- **Cliente nunca firma**: el servicio queda en `pendiente_firma_cliente`
  indefinidamente. Mitigación: la API `finalize` actual no lo borra; queda
  abierto por diseño hasta tener una política de auto-cierre (fuera del
  alcance). El push y la `Notificacion` quedan registradas para hacer
  follow-up manual.
- **Cliente sin app actualizada**: el endpoint nuevo es opt-in; mientras
  el técnico tenga la versión anterior del proveedor, sigue mandando
  ambas firmas y el flujo legacy completa de inmediato. El nuevo proveedor
  contra un usuario con app vieja deja el servicio pendiente — se
  comunica vía rollout coordinado.
- **Compat con `finalize_by_order`**: misma semántica que `finalize` (si
  faltara `firma_cliente`, queda en `PENDIENTE_FIRMA_CLIENTE`).

## Pruebas manuales

1. Proveedor con app nueva firma: orden queda `pendiente_firma_cliente`,
   cliente recibe push.
2. Cliente abre app, ve tarjeta nueva, firma: orden pasa a `completado`,
   se dispara recálculo de salud (signal existente).
3. Proveedor con app vieja firma con ambas firmas: backend acepta, orden
   `completado` directo (compat ok).

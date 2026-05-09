# Tareas — Firma diferida del cliente

## 1. Backend — Modelos y migraciones

- [x] 1.1 Agregar `('PENDIENTE_FIRMA_CLIENTE', ...)` a `ChecklistInstance.ESTADO_CHOICES`.
- [x] 1.2 Agregar `('pendiente_firma_cliente', ...)` a `SolicitudServicio.ESTADO_CHOICES`.
- [x] 1.3 Migración `checklists/0005_pendiente_firma_cliente_estado.py`.
- [x] 1.4 Migración `ordenes/0008_pendiente_firma_cliente_estado.py`.

## 2. Backend — Endpoints

- [x] 2.1 Refactor `finalize`: aceptar firma del cliente opcional, ramificar a `PENDIENTE_FIRMA_CLIENTE` u `COMPLETADO`. Devolver `requiere_firma_cliente` en la respuesta.
- [x] 2.2 Mismo refactor para `finalize_by_order`.
- [x] 2.3 Nuevo `POST /api/checklists/instances/{id}/firmar-cliente/` con permisos del cliente dueño.
- [x] 2.4 `by_order` admite lectura del cliente dueño cuando `PENDIENTE_FIRMA_CLIENTE`.
- [x] 2.5 Serializer `ChecklistInstance` expone `firma_tecnico_disponible`, `firma_cliente_disponible`, `requiere_firma_cliente` calculados (sin filtrar Base64 sensibles si no aplica).

## 3. Backend — Notificaciones

- [x] 3.1 Helper `enviar_push_pendiente_firma_cliente(orden)` en `vehiculos/tasks.py` (cerca de `enviar_push_inspeccion_taller`).
- [x] 3.2 Invocar el helper desde `finalize` cuando la instancia queda en `PENDIENTE_FIRMA_CLIENTE`.
- [x] 3.3 `Notificacion.crear_unica` con dedup por `orden_id`.

## 4. Frontend — Proveedor (`mecanimovil-prov`)

- [x] 4.1 `ChecklistFinalizationData.firma_cliente: string | null` opcional.
- [x] 4.2 `ChecklistContainer.handleSignaturesComplete` envía solo `firma_tecnico`; lee `requiere_firma_cliente` de la respuesta.
- [x] 4.3 `ChecklistSignatureModal` invocado con `signatureMode='tecnico_only'`.
- [x] 4.4 Mensaje de éxito ahora habla de "esperando firma del cliente".

## 5. Frontend — Cliente (`mecanimovil-usuarios`)

- [x] 5.1 Instalar `react-native-signature-canvas`.
- [x] 5.2 `app/services/checklistService.js`: agregar `firmarChecklistComoCliente`.
- [x] 5.3 Nuevo `CustomerSignatureModal` (canvas + GPS opcional).
- [x] 5.4 Nuevo `PendingClientSignatureCard` con CTA.
- [x] 5.5 Integrar tarjeta en `DetalleSolicitudScreen` y `AppointmentDetailScreen`.

## 6. Validación y cierre OpenSpec

- [x] 6.1 `openspec validate firma-cliente-diferida-checklist`.
- [x] 6.2 `openspec archive firma-cliente-diferida-checklist --yes`.

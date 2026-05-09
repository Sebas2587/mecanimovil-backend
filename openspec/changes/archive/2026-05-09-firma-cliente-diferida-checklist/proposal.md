# Firma diferida del cliente para finalizar el servicio

## Why

Hoy `POST /api/checklists/instances/{id}/finalize/` (y la variante
`finalize_by_order`) **exigen `firma_tecnico` y `firma_cliente` en la misma
petición desde la app del proveedor**. Esto fuerza al técnico a tener al
cliente físicamente presente con su dispositivo para poder cerrar el servicio
y obliga a que el cliente firme en el dispositivo del taller, sin un canal
propio que avale la conclusión del servicio.

Consecuencias del flujo actual:

- Servicios a domicilio o agendamientos en taller donde el cliente deja el
  vehículo y no está presente al cierre quedan **bloqueados** (técnico no
  puede finalizar) o se firma "por el cliente" desde el dispositivo del
  proveedor, lo que **invalida la firma como prueba**.
- No existe un **ente validador independiente**: la firma del cliente vive
  en el mismo dispositivo y sesión que la del técnico.
- El usuario no tiene visibilidad del cierre desde su app: el checklist solo
  se le muestra cuando ya está `COMPLETADO`, sin poder revisar el trabajo
  ni rechazarlo.

## What Changes

1. **Nuevo estado `PENDIENTE_FIRMA_CLIENTE`** en `ChecklistInstance` y
   `pendiente_firma_cliente` en `SolicitudServicio.estado`. Cubre la
   ventana entre que el técnico cierra el checklist y el cliente lo
   confirma desde su app.
2. **`finalize` con firma diferida**: si el proveedor envía solo
   `firma_tecnico`, la instancia pasa a `PENDIENTE_FIRMA_CLIENTE` (no a
   `COMPLETADO`) y la orden a `pendiente_firma_cliente`. Si por
   compatibilidad llega `firma_cliente` también, se completa de inmediato.
3. **Nuevo endpoint `POST /api/checklists/instances/{id}/firmar-cliente/`**
   con `permission_classes=[IsAuthenticated]`. Valida que `request.user`
   sea el cliente dueño de la orden y que la instancia esté en
   `PENDIENTE_FIRMA_CLIENTE`. Acepta `firma_cliente` (Base64) y, opcional,
   `ubicacion_lat` / `ubicacion_lng`. Marca `COMPLETADO`, persiste firma
   y `fecha_finalizacion`, y la orden pasa a `completado`. El signal de
   salud existente se dispara igual que hoy.
4. **`by_order` ampliado**: el cliente dueño puede leer el checklist
   también cuando está en `PENDIENTE_FIRMA_CLIENTE` (hoy solo
   `COMPLETADO`), para revisar respuestas y firmar.
5. **Push + notificación in-app al cliente** cuando el técnico firma:
   "Tu servicio espera tu firma" con deeplink al detalle de la solicitud.
6. **App proveedor (mecanimovil-prov)**: `ChecklistSignatureModal` corre en
   modo `tecnico_only` por defecto. Tras enviar, la UI confirma "Firma
   enviada — esperando firma del cliente" en vez de cerrar como si todo
   terminara.
7. **App usuario (mecanimovil-usuarios)**: nuevo `CustomerSignatureModal`
   con `react-native-signature-canvas` y nueva tarjeta en el detalle de
   solicitud / agendamiento que aparece cuando la orden está en
   `pendiente_firma_cliente`. Permite revisar el checklist y firmar.

## Impact

- **Affected specs**:
  - `openspec/specs/checklists/spec.md` (ADDED requirement de firma
    diferida y endpoint `firmar-cliente`).
  - `openspec/specs/ordenes/spec.md` (ADDED estado
    `pendiente_firma_cliente` y reglas de transición).
- **Affected code**:
  - Backend:
    `mecanimovilapp/apps/checklists/{models,views,serializers,urls}.py`,
    nuevas migraciones `checklists/0005_*` y `ordenes/0008_*`,
    `mecanimovilapp/apps/ordenes/models.py`,
    `mecanimovilapp/apps/vehiculos/tasks.py` (helper push pendiente
    firma).
  - Frontend (mecanimovil-prov):
    `services/checklistService.ts`,
    `components/checklist/ChecklistContainer.tsx`,
    `components/checklist/ChecklistSignatureModal.tsx`.
  - Frontend (mecanimovil-usuarios):
    `app/services/checklistService.js`,
    nuevo `app/components/checklist/CustomerSignatureModal.js`,
    nuevo `app/components/checklist/PendingClientSignatureCard.js`,
    integración en `app/screens/solicitudes/DetalleSolicitudScreen.js`
    y `app/screens/appointments/AppointmentDetailScreen.js`,
    `package.json` (dependencia `react-native-signature-canvas`).

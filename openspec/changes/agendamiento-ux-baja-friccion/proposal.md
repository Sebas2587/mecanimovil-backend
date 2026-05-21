# Agendamiento UX baja fricción + anti-duplicado

## Why
El flujo de nueva solicitud tiene demasiados pasos visibles y el paso 6 duplica la selección de fecha cuando ya se usó `CalendarioProveedorScreen`. Además, el usuario puede crear otra solicitud del mismo servicio para el mismo vehículo mientras una sigue activa.

## What Changes
- Servicio `solicitud_activa`: estados unificados y consulta vehículo+servicio.
- API `GET .../verificar-servicio-activo/?vehiculo_id=&servicio_ids=`
- Serializer: reutiliza el servicio; incluye `pendiente_confirmacion` y `esperando_creditos_proveedor`.
- App usuarios: validación temprana al elegir vehículo/servicio; ticket de resumen; copy en calendario.

## Non-goals
- Reserva directa vía `CarritoAgendamiento` (fase posterior).
- Reescribir `FormularioSolicitud` por completo.

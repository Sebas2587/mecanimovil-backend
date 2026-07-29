# Inventario de transferencias / encargados — App Proveedores

Documento de apoyo a la Política de Privacidad (Ley 21.719). Actualizado: 2026-07-21.

| Destinatario | País / región típica | Datos | Finalidad | Salvaguarda |
|--------------|----------------------|-------|-----------|-------------|
| Mercado Pago | AR / regional | Identificación comercial, montos, estados de pago | Cobros y liquidaciones | Contrato MP + minimización |
| Google Sign-In | Global / EE.UU. | Email, nombre, token OAuth | Autenticación | Config OAuth + HTTPS |
| Render (hosting) | EE.UU. / región del servicio | DB, logs, archivos | Operación API | Acceso restringido, TLS |
| Expo Push / FCM | Global | Push token, payloads operativos | Notificaciones | Tokens rotables, sin marketing por defecto |
| Meta / WhatsApp | Global | Contenido de chat de soporte | Soporte humano | Canal voluntario del titular |
| Nominatim / mapas | Según proveedor | Coordenadas / dirección | Geocodificación | Solo lo necesario para ubicación |

## Notas

- El consentimiento de **geolocalización** se registra en `ConsentimientoUsuario` tipo `ubicacion` (canal `app_prov`) antes del prompt del SO.
- Preferencias de marketing van en `PreferenciasNotificacion` (oposición).
- Baja de taller con obligaciones fiscales: flujo asistido (WhatsApp / soporte), no hard-delete.

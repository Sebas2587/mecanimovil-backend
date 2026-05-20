## ADDED Requirements

### Requirement: Adjuntos de chat con almacenamiento R2
Los mensajes con imagen en chat (API `/chat/` y `/ordenes/chat-solicitudes/`) SHALL exponer URLs absolutas válidas para el cliente móvil, compatibles con bucket privado R2 (presigned) o dominio público configurado.

#### Scenario: Listar mensajes con imagen
- GIVEN un mensaje con `attachment` o `archivo_adjunto` en R2
- WHEN el cliente solicita el historial del chat
- THEN cada mensaje incluye `attachment` y `archivo_adjunto` con la misma URL absoluta https
- AND la URL permite renderizar la imagen en React Native sin prefijar `/media/` del API

#### Scenario: Mensaje en tiempo real por WebSocket
- GIVEN un participante envía una imagen en el chat
- WHEN el otro participante recibe `nuevo_mensaje_chat` por WebSocket
- THEN el payload incluye `archivo_adjunto` (y `attachment`) con URL absoluta, no `null`

#### Scenario: URL presigned con query string
- GIVEN la URL termina en `.jpg?X-Amz-Algorithm=...`
- WHEN la app móvil evalúa si es imagen
- THEN la trata como imagen (extensión antes del `?` o ruta `chat_attachments` / `chat_solicitudes`)

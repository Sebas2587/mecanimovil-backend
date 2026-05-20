# Propuesta: Imágenes de chat visibles con Cloudflare R2

## Why
Tras migrar media a R2 (URLs firmadas o rutas distintas a cPanel), las imágenes del chat no se renderizaban: el WebSocket enviaba `archivo_adjunto: null`, los serializers no regeneraban URLs firmadas y el cliente validaba extensión con `$` (falla con `?` de presigned).

## What Changes
- Backend: `get_cpanel_file_url` en serializers de `Message` y `ChatSolicitud`; WebSocket con URL real.
- Apps: util `chatAttachmentMedia` para resolver URL y detectar imágenes con query string.

## Non-goals
- No cambiar política de expiración de presigned URLs (sigue `R2_URL_EXPIRE_SECONDS`).

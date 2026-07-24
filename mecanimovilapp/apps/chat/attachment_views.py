import logging
import mimetypes

from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

from .media_signing import verify_message_attachment_token
from .models import Message

logger = logging.getLogger(__name__)


@require_GET
def message_attachment_download(request, message_id: int):
    """Sirve el adjunto con token firmado (sin JWT). Compatible con <img>/<audio> web."""
    sig = request.GET.get('sig') or ''
    expires = request.GET.get('expires') or ''
    if not verify_message_attachment_token(message_id, sig, expires):
        return _forbidden()

    try:
        message = Message.objects.get(pk=message_id)
    except Message.DoesNotExist as exc:
        raise Http404('Mensaje no encontrado') from exc

    if not message.attachment:
        raise Http404('Sin adjunto')

    name = message.attachment.name or 'attachment'
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    lower = name.lower()
    if lower.endswith(('.oga', '.ogg', '.opus')):
        mime = 'audio/ogg'
    try:
        fh = message.attachment.open('rb')
    except Exception:
        logger.exception('No se pudo abrir attachment message=%s', message_id)
        raise Http404('Archivo no disponible') from None

    response = FileResponse(fh, content_type=mime)
    response['Content-Disposition'] = f'inline; filename="{name.rsplit("/", 1)[-1]}"'
    response['Cache-Control'] = 'private, max-age=3600'
    # Ayuda a <audio>/<video> cross-origin en web aun si CORS middleware falla en OPTIONS.
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Expose-Headers'] = 'Content-Type, Content-Length'
    return response


def _forbidden():
    from django.http import HttpResponseForbidden

    return HttpResponseForbidden('Token inválido o expirado')

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from django.contrib.contenttypes.models import ContentType

from mecanimovilapp.apps.omnichannel.models import ProviderChannelConnection
from mecanimovilapp.apps.omnichannel.serializers import (
    ProviderChannelConnectionSerializer,
    ProviderChannelConnectionToggleSerializer,
)
from mecanimovilapp.apps.omnichannel.services import MetaGraphClient
from mecanimovilapp.apps.omnichannel.services.meta_oauth import (
    MetaOAuthSessionData,
    build_oauth_callback_html,
    complete_meta_oauth_connection,
)
from mecanimovilapp.apps.omnichannel.tasks import process_meta_webhook
from mecanimovilapp.apps.omnichannel.utils import (
    build_embedded_config_payload,
    build_embedded_signup_url,
    generate_oauth_state,
    meta_verify_token,
    omnichannel_enabled,
    verify_meta_signature,
)
from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller

logger = logging.getLogger(__name__)

CHANNEL_MAP = {
    'whatsapp': 'WHATSAPP',
    'messenger': 'MESSENGER',
    'instagram': 'INSTAGRAM',
}


def get_proveedor_for_user(user):
    try:
        taller = Taller.objects.get(usuario=user)
        return taller, ContentType.objects.get_for_model(Taller)
    except Taller.DoesNotExist:
        pass
    try:
        mecanico = MecanicoDomicilio.objects.get(usuario=user)
        return mecanico, ContentType.objects.get_for_model(MecanicoDomicilio)
    except MecanicoDomicilio.DoesNotExist:
        pass
    return None, None


class ProviderChannelConnectionViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ProviderChannelConnectionSerializer

    def _ensure_connections(self, user, proveedor, content_type):
        connections = []
        for channel_code, _ in ProviderChannelConnection.CHANNEL_CHOICES:
            conn, _ = ProviderChannelConnection.objects.get_or_create(
                content_type=content_type,
                object_id=proveedor.id,
                channel=channel_code,
                defaults={
                    'usuario': user,
                    'status': 'no_configurada',
                    'mensaje_estado': 'Conecta tu cuenta para recibir mensajes.',
                },
            )
            if conn.usuario_id != user.id:
                conn.usuario = user
                conn.save(update_fields=['usuario'])
            connections.append(conn)
        return connections

    @action(detail=False, methods=['get'], url_path='estado')
    def list_connections(self, request):
        if not omnichannel_enabled():
            return Response({'enabled': False, 'connections': []})

        proveedor, content_type = get_proveedor_for_user(request.user)
        if not proveedor:
            return Response(
                {'error': 'No eres un proveedor registrado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connections = self._ensure_connections(request.user, proveedor, content_type)
        serializer = self.get_serializer(connections, many=True)
        return Response({'enabled': True, 'connections': serializer.data})

    @action(detail=False, methods=['get'], url_path='iniciar-conexion')
    def iniciar_conexion(self, request):
        if not omnichannel_enabled():
            return Response(
                {'error': 'La mensajería omnicanal no está habilitada.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        channel_param = (request.query_params.get('channel') or '').lower()
        channel = CHANNEL_MAP.get(channel_param)
        if not channel:
            return Response({'error': 'channel inválido (whatsapp|messenger|instagram)'}, status=400)

        proveedor, content_type = get_proveedor_for_user(request.user)
        if not proveedor:
            return Response({'error': 'No eres un proveedor registrado'}, status=400)

        conn, _ = ProviderChannelConnection.objects.get_or_create(
            content_type=content_type,
            object_id=proveedor.id,
            channel=channel,
            defaults={'usuario': request.user},
        )
        if conn.usuario_id != request.user.id:
            conn.usuario = request.user
            conn.save(update_fields=['usuario'])

        embedded = build_embedded_config_payload(channel)
        if channel == 'INSTAGRAM' and not embedded:
            logger.error(
                'Instagram Login for Business no configurado: falta META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM. '
                'Sin esta config Meta muestra "Invalid Scopes" al conectar.'
            )
            return Response(
                {
                    'error': (
                        'Instagram aún no está disponible. '
                        'Estamos terminando la configuración del servidor; intenta más tarde o contacta a soporte.'
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        state = generate_oauth_state()
        conn.oauth_state = state
        conn.status = 'pendiente'
        conn.mensaje_estado = 'Esperando autorización de Meta...'
        conn.save()

        auth_url = build_embedded_signup_url(state, channel)
        if not auth_url:
            conn.status = 'error'
            conn.mensaje_estado = 'Meta no está configurado en el servidor.'
            conn.save(update_fields=['status', 'mensaje_estado', 'updated_at'])
            return Response(
                {'error': 'Meta no está configurado (META_APP_ID). Contacta al administrador.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if channel == 'WHATSAPP' and not embedded:
            logger.error(
                'WhatsApp Embedded Signup no configurado: falta META_EMBEDDED_SIGNUP_CONFIG_ID en Render. '
                'Los talleres no podrán conectar WhatsApp hasta que ops lo configure (una sola vez).'
            )
        return Response({
            'success': True,
            'connection_id': str(conn.id),
            'auth_url': auth_url,
            'channel': channel_param,
            'embedded': embedded or {'enabled': False},
        })

    @action(detail=False, methods=['post'], url_path='completar-conexion')
    def completar_conexion(self, request):
        """Completa OAuth desde Embedded Signup (FB SDK) con code + IDs de sesión."""
        if not omnichannel_enabled():
            return Response(
                {'error': 'La mensajería omnicanal no está habilitada.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        connection_id = request.data.get('connection_id')
        code = (request.data.get('code') or '').strip()
        if not connection_id or not code:
            return Response({'error': 'connection_id y code son requeridos'}, status=400)

        conn = ProviderChannelConnection.objects.filter(
            pk=connection_id,
            usuario=request.user,
        ).first()
        if not conn:
            return Response({'error': 'Conexión no encontrada'}, status=404)
        if conn.status not in ('pendiente', 'error', 'no_configurada'):
            return Response(
                {'error': 'Este canal ya está conectado o no puede completarse.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        shared_waba_ids = request.data.get('shared_waba_ids') or []
        if isinstance(shared_waba_ids, str):
            shared_waba_ids = [shared_waba_ids]

        session = MetaOAuthSessionData(
            phone_number_id=(request.data.get('phone_number_id') or '').strip() or None,
            waba_id=(request.data.get('waba_id') or '').strip() or None,
            business_id=(request.data.get('business_id') or '').strip() or None,
            shared_waba_ids=[str(wid).strip() for wid in shared_waba_ids if wid],
        )
        result = complete_meta_oauth_connection(conn, code, session)
        payload = {
            'success': result.success,
            'message': result.message,
            'instruction': result.instruction,
            'needs_phone_number_id': result.needs_phone_number_id,
            'waba_id': result.waba_id,
            'channel': result.channel or conn.channel.lower(),
        }
        if result.success:
            payload['connection'] = ProviderChannelConnectionSerializer(conn).data
            return Response(payload)
        status_code = status.HTTP_400_BAD_REQUEST
        if result.needs_phone_number_id:
            payload['connection'] = ProviderChannelConnectionSerializer(conn).data
        return Response(payload, status=status_code)

    @action(detail=True, methods=['patch'])
    def toggle(self, request, pk=None):
        conn = ProviderChannelConnection.objects.filter(pk=pk, usuario=request.user).first()
        if not conn:
            return Response({'error': 'Conexión no encontrada'}, status=404)
        serializer = ProviderChannelConnectionToggleSerializer(
            conn, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if conn.enabled and conn.status != 'conectada':
            return Response(
                {'error': 'Conecta el canal antes de habilitarlo.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ProviderChannelConnectionSerializer(conn).data)

    @action(detail=True, methods=['post'])
    def desconectar(self, request, pk=None):
        conn = ProviderChannelConnection.objects.filter(pk=pk, usuario=request.user).first()
        if not conn:
            return Response({'error': 'Conexión no encontrada'}, status=404)
        conn.disconnect()
        return Response(ProviderChannelConnectionSerializer(conn).data)

    @action(detail=True, methods=['post'], url_path='resuscribir-webhooks')
    def resuscribir_webhooks(self, request, pk=None):
        """Re-suscribe webhooks de Page en Meta (Messenger / Instagram vía Page)."""
        conn = ProviderChannelConnection.objects.filter(pk=pk, usuario=request.user).first()
        if not conn:
            return Response({'error': 'Conexión no encontrada'}, status=404)
        if conn.channel not in ('MESSENGER', 'INSTAGRAM'):
            return Response(
                {'error': 'Solo aplica a Messenger o Instagram.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not conn.page_id or not conn.access_token:
            return Response(
                {'error': 'Conecta el canal primero (falta page_id o token).'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client = MetaGraphClient(conn.access_token)
        try:
            result = client.subscribe_page_webhooks(conn.page_id, conn.access_token)
            subscribed = client.get_page_subscribed_apps(conn.page_id, conn.access_token)
            logger.info(
                'Manual page webhook resubscribe conn=%s page_id=%s ig=%s apps=%s',
                conn.id,
                conn.page_id,
                conn.instagram_account_id,
                [a.get('id') for a in subscribed],
            )
            return Response({
                'ok': True,
                'page_id': conn.page_id,
                'instagram_account_id': conn.instagram_account_id,
                'subscribed_apps': subscribed,
                'meta_result': result,
            })
        except Exception as exc:
            logger.error('Manual page webhook resubscribe failed conn=%s: %s', conn.id, exc)
            return Response(
                {'error': f'No se pudo suscribir webhooks: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(detail=True, methods=['post'], url_path='configurar-whatsapp')
    def configurar_whatsapp(self, request, pk=None):
        conn = ProviderChannelConnection.objects.filter(
            pk=pk, usuario=request.user, channel='WHATSAPP',
        ).first()
        if not conn:
            return Response({'error': 'Conexión WhatsApp no encontrada'}, status=404)
        if not conn.access_token:
            return Response(
                {'error': 'Primero autoriza WhatsApp con Meta (Conectar).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        phone_number_id = (request.data.get('phone_number_id') or '').strip()
        if not phone_number_id:
            return Response({'error': 'phone_number_id es requerido'}, status=400)

        client = MetaGraphClient(conn.access_token)
        phone_meta = client.get_phone_number_by_id(phone_number_id, conn.access_token)
        if not phone_meta:
            return Response(
                {
                    'error': (
                        'Phone Number ID inválido o sin permisos. '
                        'Cópialo desde Meta Business Suite → WhatsApp → Configuración API.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        update_fields = {
            'phone_number_id': phone_number_id,
            'display_identifier': phone_meta.get('display_phone_number') or conn.display_identifier,
            'display_name': phone_meta.get('verified_name') or conn.display_name,
        }
        if conn.waba_id:
            try:
                client.subscribe_waba_webhooks(conn.waba_id, conn.access_token)
            except Exception as sub_exc:
                logger.warning('WABA webhook subscribe on configure failed: %s', sub_exc)

        conn.mark_connected(enabled=True, **update_fields)
        return Response(ProviderChannelConnectionSerializer(conn).data)


@csrf_exempt
@require_GET
def meta_webhook_verify(request):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')
    if mode == 'subscribe' and token == meta_verify_token():
        logger.info('Meta webhook verify OK (GET subscribe)')
        return HttpResponse(challenge, content_type='text/plain')
    logger.warning(
        'Meta webhook verify rejected (403): mode=%s token_ok=%s',
        mode,
        token == meta_verify_token(),
    )
    return HttpResponse(status=403)


@csrf_exempt
def meta_webhook_receive(request):
    if request.method == 'GET':
        return meta_webhook_verify(request)

    logger.info(
        'Meta webhook POST received bytes=%s signature=%s',
        len(request.body or b''),
        bool(request.headers.get('X-Hub-Signature-256')),
    )
    try:
        preview = json.loads(request.body or b'{}')
        entry = (preview.get('entry') or [{}])[0]
        logger.info(
            'Meta webhook POST object=%s entry_id=%s entries=%s',
            preview.get('object'),
            entry.get('id'),
            len(preview.get('entry') or []),
        )
    except Exception:
        pass

    if not omnichannel_enabled():
        logger.warning('Meta webhook POST ignored: OMNICHANNEL_ENABLED=False')
        return JsonResponse({'status': 'disabled'})

    signature = request.headers.get('X-Hub-Signature-256') or request.headers.get('X-Hub-Signature')
    raw_body = request.body
    if not verify_meta_signature(raw_body, signature):
        from mecanimovilapp.apps.omnichannel.utils import meta_webhook_secrets
        logger.warning(
            'Invalid Meta webhook signature (body_len=%s, secrets_configured=%s, header=%s)',
            len(raw_body or b''),
            len(meta_webhook_secrets()),
            (signature or '')[:12],
        )
        return HttpResponse(status=403)

    try:
        process_meta_webhook.delay(raw_body.decode('utf-8'))
    except Exception as exc:
        logger.error('Failed to enqueue webhook: %s', exc)
        return HttpResponse(status=500)

    return JsonResponse({'status': 'ok'})


@api_view(['GET'])
@permission_classes([AllowAny])
def meta_oauth_callback(request):
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')

    if error:
        return build_oauth_callback_html(
            success=False,
            title='Autorización cancelada',
            message='No se completó la conexión con Meta.',
            instruction='Vuelve a Mecanimovil Proveedores e intenta de nuevo.',
        )

    if not code or not state:
        return build_oauth_callback_html(
            success=False,
            title='Enlace incompleto',
            message='Faltan datos de autorización.',
            instruction='Vuelve a la app y pulsa Conectar otra vez.',
        )

    conn = ProviderChannelConnection.objects.filter(oauth_state=state).select_related('usuario').first()
    if not conn:
        return build_oauth_callback_html(
            success=False,
            title='Sesión expirada',
            message='El enlace de autorización ya no es válido.',
            instruction='Vuelve a la app e inicia la conexión de nuevo.',
        )

    session = MetaOAuthSessionData(
        phone_number_id=request.GET.get('phone_number_id'),
        waba_id=request.GET.get('waba_id'),
        business_id=request.GET.get('business_id') or conn.meta_business_id,
        shared_waba_ids=[
            wid for wid in (
                request.GET.getlist('shared_waba_id') or request.GET.getlist('shared_waba_ids')
            ) if wid
        ],
    )
    result = complete_meta_oauth_connection(conn, code, session)

    if result.success:
        return build_oauth_callback_html(
            success=True,
            title='Canal conectado',
            message=result.message,
            instruction=result.instruction,
        )

    if result.needs_phone_number_id:
        return build_oauth_callback_html(
            success=False,
            title='Casi listo',
            message=result.message,
            instruction=result.instruction,
        )

    return build_oauth_callback_html(
        success=False,
        title='No se pudo conectar',
        message=result.message,
        instruction=result.instruction,
    )

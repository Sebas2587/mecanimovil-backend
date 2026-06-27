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
from mecanimovilapp.apps.omnichannel.tasks import process_meta_webhook
from mecanimovilapp.apps.omnichannel.utils import (
    build_embedded_signup_url,
    generate_oauth_state,
    meta_oauth_redirect_uri,
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
        state = generate_oauth_state()
        conn.oauth_state = state
        conn.status = 'pendiente'
        conn.mensaje_estado = 'Esperando autorización de Meta...'
        conn.save()

        auth_url = build_embedded_signup_url(state, channel)
        if not auth_url:
            return Response(
                {'error': 'Meta no está configurado (META_APP_ID). Contacta al administrador.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({'success': True, 'auth_url': auth_url, 'channel': channel_param})

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


@csrf_exempt
@require_GET
def meta_webhook_verify(request):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')
    if mode == 'subscribe' and token == meta_verify_token():
        return HttpResponse(challenge, content_type='text/plain')
    return HttpResponse(status=403)


@csrf_exempt
def meta_webhook_receive(request):
    if request.method == 'GET':
        return meta_webhook_verify(request)

    if not omnichannel_enabled():
        return JsonResponse({'status': 'disabled'})

    signature = request.headers.get('X-Hub-Signature-256')
    raw_body = request.body
    if not verify_meta_signature(raw_body, signature):
        logger.warning('Invalid Meta webhook signature')
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
        return JsonResponse({
            'success': False,
            'message': f'Autorización cancelada: {error}',
            'instruction': 'Vuelve a la app Mecanimovil Proveedores e intenta de nuevo.',
        })

    if not code or not state:
        return JsonResponse({'success': False, 'message': 'Parámetros OAuth incompletos'}, status=400)

    conn = ProviderChannelConnection.objects.filter(oauth_state=state).select_related('usuario').first()
    if not conn:
        return JsonResponse({'success': False, 'message': 'State inválido o expirado'}, status=400)

    try:
        client = MetaGraphClient()
        token_data = client.exchange_code(code, meta_oauth_redirect_uri())
        access_token = token_data.get('access_token')
        if not access_token:
            conn.status = 'error'
            conn.mensaje_estado = 'No se recibió access token de Meta.'
            conn.save()
            return JsonResponse({'success': False, 'message': conn.mensaje_estado}, status=400)

        update_fields = {'access_token': access_token}
        pages = client.get_me_accounts(access_token)
        if pages:
            page = pages[0]
            update_fields['page_id'] = page.get('id')
            update_fields['display_name'] = page.get('name')
            page_token = page.get('access_token') or access_token
            update_fields['access_token'] = page_token

            if conn.channel == 'INSTAGRAM':
                ig = client.get_instagram_account(page.get('id'), page_token)
                if ig:
                    update_fields['instagram_account_id'] = ig.get('id')
                    update_fields['display_identifier'] = ig.get('username') or ig.get('name')
                else:
                    update_fields['display_identifier'] = page.get('name')
            elif conn.channel == 'MESSENGER':
                update_fields['display_identifier'] = page.get('name')
            elif conn.channel == 'WHATSAPP':
                update_fields['display_identifier'] = page.get('name')

        if conn.channel == 'WHATSAPP':
            business_id = request.GET.get('business_id') or conn.meta_business_id
            if business_id:
                update_fields['meta_business_id'] = business_id
                wabas = client.get_whatsapp_business_accounts(business_id, access_token)
                if wabas:
                    waba = wabas[0]
                    update_fields['waba_id'] = waba.get('id')
                    phones = client.get_phone_numbers(waba.get('id'), access_token)
                    if phones:
                        phone = phones[0]
                        update_fields['phone_number_id'] = phone.get('id')
                        update_fields['display_identifier'] = phone.get('display_phone_number')
                        update_fields['display_name'] = phone.get('verified_name') or update_fields.get('display_name')

        conn.mark_connected(enabled=True, **update_fields)
        return JsonResponse({
            'success': True,
            'message': 'Canal conectado correctamente.',
            'instruction': 'Vuelve a la app Mecanimovil Proveedores.',
            'channel': conn.channel.lower(),
        })
    except Exception as exc:
        logger.exception('OAuth callback failed: %s', exc)
        conn.status = 'error'
        conn.mensaje_estado = f'Error al conectar: {exc}'
        conn.save()
        return JsonResponse({'success': False, 'message': str(exc)}, status=500)

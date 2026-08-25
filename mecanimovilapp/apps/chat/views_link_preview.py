from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from mecanimovilapp.apps.chat.link_preview import fetch_link_preview, validate_preview_url


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def link_preview(request):
    url = (request.query_params.get('url') or '').strip()
    if not validate_preview_url(url):
        return Response({'error': 'url_invalida'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        data = fetch_link_preview(url)
    except ValueError:
        return Response({'error': 'url_invalida'}, status=status.HTTP_400_BAD_REQUEST)
    return Response(data)

"""
Utilidades para manejo de URLs de archivos almacenados en cPanel.

Este módulo proporciona funciones helper para construir URLs correctas
de archivos almacenados en cPanel desde cualquier serializer.
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def get_cpanel_file_url(file_field, request=None):
    """
    Construye la URL correcta para un archivo almacenado.
    
    Esta función detecta automáticamente si estamos usando cPanel storage
    y construye la URL apropiada.
    
    Args:
        file_field: Campo de archivo de Django (ImageField o FileField)
        request: Request HTTP opcional para construir URLs absolutas
        
    Returns:
        str: URL completa del archivo o None si no hay archivo
    """
    if not file_field:
        return None

    try:
        cpanel_media_url = getattr(settings, 'CPANEL_MEDIA_URL', '')
        media_url = getattr(settings, 'MEDIA_URL', '/media/') or '/media/'

        try:
            file_url = file_field.url
        except Exception:
            return None

        if not file_url:
            return None

        # Si la URL ya es absoluta (http/https), devolverla tal cual.
        # Esto cubre R2, S3 y cPanel correctamente configurado.
        if file_url.startswith('http://') or file_url.startswith('https://'):
            return file_url

        # Fallback legacy para cPanel cuando file_url viene como /media/...
        if file_url.startswith('/media/') and cpanel_media_url:
            relative_path = file_url.replace('/media/', '', 1)
            return f"{cpanel_media_url.rstrip('/')}/{relative_path}"

        # Si tenemos un MEDIA_URL absoluto configurado, construir desde ahí
        if file_url.startswith('/media/') and media_url.startswith(('http://', 'https://')):
            relative_path = file_url.replace('/media/', '', 1)
            return f"{media_url.rstrip('/')}/{relative_path}"

        # Si tenemos request, construir URL absoluta
        if request:
            return request.build_absolute_uri(file_url)

        return file_url

    except Exception as e:
        logger.error(f"Error construyendo URL de archivo: {e}")
        return None


def get_image_url(image_field, request=None):
    """
    Alias de get_cpanel_file_url específico para imágenes.
    
    Args:
        image_field: Campo ImageField de Django
        request: Request HTTP opcional
        
    Returns:
        str: URL completa de la imagen o None
    """
    return get_cpanel_file_url(image_field, request)

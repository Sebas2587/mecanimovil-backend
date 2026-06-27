"""
URL configuration for mecanimovilapp project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
import os
# from rest_framework.documentation import include_docs_urls

# Personalizar el admin
admin.site.site_header = "MecaniMovil Admin"
admin.site.site_title = "MecaniMovil Admin Portal"
admin.site.index_title = "Bienvenido al portal de administración de MecaniMovil"

# Vista simple para el endpoint /api/hello/
def hello_api(request):
    return JsonResponse({"message": "¡Hola desde el backend de MecaniMovil!"})

# Vista de retorno tras autorizar suscripción en MercadoPago
# MercadoPago redirige aquí (back_url) después de que el usuario autoriza el débito.
# En producción, esta página debería indicarle al usuario que vuelva a la app.
def suscripciones_resultado(request):
    estado = request.GET.get('status', '')
    return JsonResponse({
        "message": "Puedes volver a la aplicación MecaniMovil.",
        "status": estado,
        "instruccion": "Abre la app MecaniMovil para ver el estado de tu suscripción.",
    })

# Vista para servir archivos media en producción
def serve_media(request, path):
    """
    Vista para servir archivos media en producción
    Nota: En Render, el sistema de archivos es efímero, por lo que los archivos
    pueden no existir después de un deploy. Se recomienda usar S3 o disco persistente.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    file_path = os.path.join(settings.MEDIA_ROOT, path)
    
    # Log para debugging
    logger.info(f"🔍 [serve_media] Intentando servir: {path}")
    logger.info(f"🔍 [serve_media] MEDIA_ROOT: {settings.MEDIA_ROOT}")
    logger.info(f"🔍 [serve_media] Ruta completa: {file_path}")
    logger.info(f"🔍 [serve_media] ¿Existe el archivo?: {os.path.exists(file_path)}")
    
    if os.path.exists(file_path):
        logger.info(f"✅ [serve_media] Archivo encontrado, sirviendo: {path}")
        return serve(request, path, document_root=settings.MEDIA_ROOT)
    else:
        # Verificar si el directorio existe
        media_dir = os.path.dirname(file_path)
        if not os.path.exists(media_dir):
            logger.warning(f"⚠️ [serve_media] Directorio no existe: {media_dir}")
        else:
            logger.warning(f"⚠️ [serve_media] Archivo no encontrado: {file_path}")
            # Listar archivos en el directorio para debugging
            try:
                files_in_dir = os.listdir(media_dir)
                logger.info(f"📁 [serve_media] Archivos en {media_dir}: {files_in_dir[:10]}")  # Primeros 10
            except Exception as e:
                logger.error(f"❌ [serve_media] Error listando directorio: {e}")
        
        # Retornar 404 sin generar warning adicional
        from django.http import HttpResponseNotFound
        return HttpResponseNotFound("File not found")

urlpatterns = [
    path('admin/', admin.site.urls),
    # Rutas de la API
    path('api/usuarios/', include('mecanimovilapp.apps.usuarios.urls')),
    path('api/servicios/', include('mecanimovilapp.apps.servicios.urls')),
    path('api/vehiculos/', include('mecanimovilapp.apps.vehiculos.urls')),
    path('api/chat/', include('mecanimovilapp.apps.chat.urls')),
    path('api/omnichannel/', include('mecanimovilapp.apps.omnichannel.urls')),
    path('api/ordenes/', include('mecanimovilapp.apps.ordenes.urls')),
    path('api/personalizacion/', include('mecanimovilapp.apps.personalizacion.urls')),  # URLs de personalización
    path('api/checklists/', include('mecanimovilapp.apps.checklists.urls')),  # URLs de checklist correctamente ubicadas
    path('api/mercadopago/', include('mecanimovilapp.apps.pagos.urls')),  # URLs de pagos con Mercado Pago Checkout Pro
    path('api/suscripciones/', include('mecanimovilapp.apps.suscripciones.urls')),  # URLs de suscripciones
    path('api/marketplace/', include('mecanimovilapp.apps.marketplace.urls')),  # URLs de marketplace (transferencias)
    
    # Endpoint para prueba de conexión
    path('api/hello/', hello_api, name='hello_api'),
    path('suscripciones-resultado/', suscripciones_resultado, name='suscripciones-resultado'),
    # Documentación de la API
    # path('docs/', include_docs_urls(title='MecaniMovil API')),
]

# Configuración para servir archivos media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
else:
    # En producción, servir archivos media manualmente
    urlpatterns += [
        path('media/<path:path>', serve_media, name='serve_media'),
    ]
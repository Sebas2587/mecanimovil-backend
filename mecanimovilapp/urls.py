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

# Vista para servir archivos media en producción
def serve_media(request, path):
    """
    Vista para servir archivos media en producción
    """
    file_path = os.path.join(settings.MEDIA_ROOT, path)
    if os.path.exists(file_path):
        return serve(request, path, document_root=settings.MEDIA_ROOT)
    return JsonResponse({"error": "File not found"}, status=404)

urlpatterns = [
    path('admin/', admin.site.urls),
    # Rutas de la API
    path('api/usuarios/', include('mecanimovilapp.apps.usuarios.urls')),
    path('api/servicios/', include('mecanimovilapp.apps.servicios.urls')),
    path('api/vehiculos/', include('mecanimovilapp.apps.vehiculos.urls')),
    path('api/ordenes/', include('mecanimovilapp.apps.ordenes.urls')),
    path('api/personalizacion/', include('mecanimovilapp.apps.personalizacion.urls')),  # URLs de personalización
    path('api/checklists/', include('mecanimovilapp.apps.checklists.urls')),  # URLs de checklist correctamente ubicadas
    path('api/mercadopago/', include('mecanimovilapp.apps.pagos.urls')),  # URLs de pagos con Mercado Pago Checkout Pro
    path('api/suscripciones/', include('mecanimovilapp.apps.suscripciones.urls')),  # URLs de suscripciones
    
    # Endpoint para prueba de conexión
    path('api/hello/', hello_api, name='hello_api'),
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
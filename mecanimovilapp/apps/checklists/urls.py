from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ChecklistTemplateViewSet, ChecklistInstanceViewSet,
    ChecklistResponseViewSet, ChecklistPhotoViewSet
)

# Crear router para las APIs
router = DefaultRouter()
router.register(r'templates', ChecklistTemplateViewSet, basename='checklist-templates')
router.register(r'instances', ChecklistInstanceViewSet, basename='checklist-instances')
router.register(r'responses', ChecklistResponseViewSet, basename='checklist-responses')
router.register(r'photos', ChecklistPhotoViewSet, basename='checklist-photos')

app_name = 'checklists'

urlpatterns = [
    # Solo incluir las rutas del API REST
    path('', include(router.urls)),
]

# URLs específicas para el frontend de proveedores
# Estas son las rutas que utilizará la aplicación React Native:

# GET /api/checklists/templates/ - Listar templates disponibles
# GET /api/checklists/templates/by_service/?servicio_id=123 - Template por servicio
# GET /api/checklists/templates/{id}/ - Detalle de template

# POST /api/checklists/instances/ - Crear nueva instancia de checklist
# GET /api/checklists/instances/ - Listar instancias del proveedor
# GET /api/checklists/instances/{id}/ - Detalle de instancia
# POST /api/checklists/instances/{id}/start/ - Iniciar checklist
# POST /api/checklists/instances/{id}/pause/ - Pausar checklist
# POST /api/checklists/instances/{id}/resume/ - Reanudar checklist
# POST /api/checklists/instances/{id}/finalize/ - Finalizar con firmas

# POST /api/checklists/responses/ - Crear respuesta
# PUT /api/checklists/responses/{id}/ - Actualizar respuesta
# GET /api/checklists/responses/ - Listar respuestas del proveedor

# POST /api/checklists/photos/ - Subir foto
# DELETE /api/checklists/photos/{id}/ - Eliminar foto
# GET /api/checklists/photos/ - Listar fotos del proveedor 
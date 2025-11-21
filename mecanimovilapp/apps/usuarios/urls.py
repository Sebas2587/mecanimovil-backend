from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'usuarios', views.UsuarioViewSet)
router.register(r'clientes', views.ClienteViewSet)
router.register(r'talleres', views.TallerViewSet)
router.register(r'mecanicos-domicilio', views.MecanicoDomicilioViewSet)
router.register(r'zonas-cobertura', views.ZonaCoberturaViewSet)
router.register(r'resenas', views.ResenaViewSet)
router.register(r'direcciones', views.DireccionUsuarioViewSet)
router.register(r'documentos-onboarding', views.DocumentoOnboardingViewSet)
router.register(r'horarios-proveedor', views.HorarioProveedorViewSet)
router.register(r'mechanics/me/service-areas', views.MechanicServiceAreaViewSet, basename='mechanicservicearea')
router.register(r'chilean-communes', views.ChileanCommuneViewSet, basename='chileancommune')
router.register(r'taller-direcciones', views.TallerDireccionViewSet, basename='tallerdireccion')

# URLs personalizadas para reviews de proveedores
urlpatterns = [
    # URLs personalizadas primero (tienen prioridad)
    path('login/', views.custom_login, name='custom_login'),
    path('estado-proveedor/', views.EstadoProveedorView.as_view(), name='estado-proveedor'),
    path('proveedores/conectar/', views.actualizar_estado_conexion_generico, name='conectar-proveedor'),
    path('proveedores/desconectar/', views.desconectar_generico, name='desconectar-proveedor'),
    path('providers/<int:provider_id>/reviews/', views.ReviewViewSet.as_view({'get': 'list', 'post': 'create'}), name='provider-reviews-list'),
    path('providers/<int:provider_id>/reviews/stats/', views.ReviewViewSet.as_view({'get': 'stats'}), name='provider-reviews-stats'),
    path('servicios-completados-sin-resena/', views.servicios_completados_sin_resena, name='servicios-sin-resena'),
    # Endpoint para perfil de usuario
    path('profile/', views.UserProfileView.as_view(), name='user-profile'),
    path('actualizar-foto-perfil/', views.ActualizarFotoPerfilView.as_view(), name='actualizar-foto-perfil'),
    path('cliente-detail/', views.cliente_detail, name='cliente-detail'),
    # Endpoints para configuración de servicios de proveedores
    path('actualizar-especialidades/', views.actualizar_especialidades, name='actualizar-especialidades'),
    path('actualizar-marcas-taller/', views.actualizar_marcas_taller, name='actualizar-marcas-taller'),
    path('actualizar-marcas-mecanico/', views.actualizar_marcas_mecanico, name='actualizar-marcas-mecanico'),
    # Router al final
    path('', include(router.urls)),
] 
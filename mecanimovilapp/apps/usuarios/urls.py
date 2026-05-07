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
router.register(r'notificaciones', views.NotificacionViewSet, basename='notificaciones')

# URLs personalizadas para reviews de proveedores
urlpatterns = [
    # URLs personalizadas primero (tienen prioridad)
    path('login/', views.custom_login, name='custom_login'),
    path('google-login/', views.google_login, name='google_login'),
    path('login-proveedor/', views.login_proveedor, name='login_proveedor'),
    path('logout/', views.logout_user, name='logout'),
    path('change-password/', views.change_password, name='change-password'),
    path('forgot-password/', views.forgot_password, name='forgot-password'),
    path('reset-password/', views.reset_password, name='reset-password'),
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
    # Endpoints para onboarding de proveedores
    path('inicializar-onboarding/', views.inicializar_onboarding, name='inicializar-onboarding'),
    path('completar-onboarding/', views.completar_onboarding, name='completar-onboarding'),
    path('verificar-datos-onboarding/', views.verificar_datos_onboarding, name='verificar-datos-onboarding'),
    # Endpoints para push notifications
    path('register-expo-push-token/', views.RegisterPushTokenView.as_view(), name='register-expo-push-token'),
    path('registrar-push-token/', views.registrar_push_token, name='registrar-push-token'),
    path('desactivar-push-token/', views.desactivar_push_token, name='desactivar-push-token'),
    # Router al final
    path('', include(router.urls)),
] 
from rest_framework import viewsets, permissions, status, generics, filters
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.pagination import PageNumberPagination
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django_filters.rest_framework import DjangoFilterBackend
from .models import Usuario, Cliente, Taller, MecanicoDomicilio, ZonaCobertura, Resena, DireccionUsuario, DocumentoOnboarding, HorarioProveedor, MechanicServiceArea, ChileanCommune, ConnectionStatus, ProviderProfile, Review, TallerDireccion, PushToken, Notificacion
from .serializers import (
    UsuarioSerializer, ClienteSerializer, UserProfileSerializer, 
    TallerSerializer, MecanicoDomicilioSerializer, ZonaCoberturaSerializer, ResenaSerializer,
    DireccionUsuarioSerializer, DocumentoOnboardingSerializer, HorarioProveedorSerializer,
    ConfigurarSemanaCompletaSerializer, ConfigurarHorarioRapidoSerializer,
    MechanicServiceAreaSerializer, MechanicServiceAreaCreateSerializer, MechanicServiceAreaUpdateSerializer,
    ChileanCommuneSerializer, ConnectionStatusSerializer, ProviderProfileSerializer, ReviewSerializer, TallerDireccionSerializer,
    NotificacionSerializer
)
from mecanimovilapp.apps.servicios.models import CategoriaServicio
from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token
import logging
from django.db.models import Q, Avg, Count
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.db.utils import IntegrityError
from django.conf import settings
import requests
import time
from django.utils import timezone
from datetime import timedelta
import uuid
from django.core.mail import send_mail
from django.contrib.auth.hashers import make_password
from exponent_server_sdk import PushClient
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_cookie

# Configurar logger
logger = logging.getLogger(__name__)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])  # Explícitamente permitir acceso sin autenticación
def custom_login(request):
    """
    Vista personalizada para iniciar sesión y crear/obtener token
    """
    logger.info(f"🔐 custom_login llamado con método: {request.method}")
    logger.info(f"🔐 Headers: {dict(request.headers)}")
    logger.info(f"🔐 Data recibida: {request.data}")
    
    username = request.data.get('username')
    password = request.data.get('password')
    
    logger.info(f"🔐 Intento de login con usuario: {username}")
    
    if not username or not password:
        logger.warning(f"🔐 Credenciales faltantes - username: {username}, password: {'*' * len(password) if password else 'None'}")
        return Response(
            {'error': 'Se requiere nombre de usuario y contraseña'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Intentar encontrar usuario por username o email
    try:
        # Si es un email, buscar por email
        if '@' in username:
            user = Usuario.objects.get(email=username)
            username_to_auth = user.username  # Autenticar con username
        else:
            user = Usuario.objects.get(username=username)
            username_to_auth = username
        
        logger.info(f"🔐 Usuario encontrado: {user.username}")
        
        # Intentar autenticar con la función authenticate de Django 
        user_auth = authenticate(username=username_to_auth, password=password)
        
        # Variable para determinar si la autenticación fue exitosa
        autenticacion_exitosa = False
        
        if user_auth is not None:
            autenticacion_exitosa = True
        else:
            # Si authenticate falló pero el usuario existe, verificar manualmente
            if user.check_password(password):
                autenticacion_exitosa = True
        
        if autenticacion_exitosa:
            # CRÍTICO: Validar que el usuario NO sea un proveedor antes de permitir login
            # Los proveedores solo pueden iniciar sesión en la app de proveedores, no en la app de usuarios
            # Verificar si el usuario es proveedor usando múltiples indicadores
            
            es_proveedor = False
            tipo_proveedor = None
            
            # PRIMERA VERIFICACIÓN: Verificar si el campo es_mecanico indica que es proveedor
            if user.es_mecanico:
                es_proveedor = True
                logger.warning(f"⚠️ Intento de login de proveedor en app de usuarios rechazado (es_mecanico=True): {username}")
            
            # SEGUNDA VERIFICACIÓN: Verificar si tiene perfil de mecánico a domicilio
            if not es_proveedor:
                try:
                    mecanico = MecanicoDomicilio.objects.get(usuario=user)
                    es_proveedor = True
                    tipo_proveedor = 'mecánico'
                    logger.warning(f"⚠️ Intento de login de proveedor (mecánico) en app de usuarios rechazado: {username}")
                except MecanicoDomicilio.DoesNotExist:
                    pass
            
            # TERCERA VERIFICACIÓN: Verificar si tiene perfil de taller
            if not es_proveedor:
                try:
                    taller = Taller.objects.get(usuario=user)
                    es_proveedor = True
                    tipo_proveedor = 'taller'
                    logger.warning(f"⚠️ Intento de login de proveedor (taller) en app de usuarios rechazado: {username}")
                except Taller.DoesNotExist:
                    pass
            
            # Si el usuario es proveedor, rechazar el login con mensaje amigable
            if es_proveedor:
                logger.warning(f"❌ Login rechazado: Usuario {username} es proveedor ({tipo_proveedor or 'mecánico/taller'}) y no puede iniciar sesión en app de usuarios")
                return Response(
                    {
                        'non_field_errors': ['Esta cuenta es de proveedor. Por favor, utiliza la aplicación de proveedores para iniciar sesión.']
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Si llegamos aquí, el usuario NO es proveedor, continuar con el login normal
            # Obtener o crear token
            token, created = Token.objects.get_or_create(user=user)
            
            # Serializar usuario para respuesta
            user_data = UsuarioSerializer(user).data
            
            logger.info(f"✅ Login exitoso para cliente: {username}")
            
            return Response({
                'token': token.key,
                'user': user_data
            })
        else:
            logger.warning(f"🔐 Contraseña incorrecta para usuario: {username}")
            return Response(
                {'non_field_errors': ['No puede iniciar sesión con las credenciales proporcionadas.']},
                status=status.HTTP_400_BAD_REQUEST
            )
            
    except Usuario.DoesNotExist:
        logger.warning(f"Intento de login con usuario inexistente: {username}")
        return Response(
            {'non_field_errors': ['No puede iniciar sesión con las credenciales proporcionadas.']},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Error en login: {str(e)}")
        return Response(
            {'error': f'Error de servidor: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def login_proveedor(request):
    """
    Vista de login exclusiva para proveedores (Talleres y Mecánicos a Domicilio).
    Solo permite el acceso a usuarios que sean proveedores registrados.
    Incluye email en la respuesta para mostrar en el perfil.
    """
    logger.info(f"🔐 login_proveedor llamado con método: {request.method}")
    
    username = request.data.get('username')
    password = request.data.get('password')
    
    logger.info(f"🔐 Intento de login proveedor con usuario: {username}")
    
    if not username or not password:
        return Response(
            {'error': 'Se requiere nombre de usuario y contraseña'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Intentar encontrar usuario por username o email
        if '@' in username:
            user = Usuario.objects.get(email=username)
            username_to_auth = user.username
        else:
            user = Usuario.objects.get(username=username)
            username_to_auth = username
        
        logger.info(f"🔐 Usuario encontrado: {user.username}")
        
        # Intentar autenticar
        user_auth = authenticate(username=username_to_auth, password=password)
        
        autenticacion_exitosa = False
        if user_auth is not None:
            autenticacion_exitosa = True
        else:
            if user.check_password(password):
                autenticacion_exitosa = True
        
        if autenticacion_exitosa:
            # VALIDAR que el usuario SÍ sea un proveedor
            es_proveedor = False
            tipo_proveedor = None
            
            # Verificar si es mecánico a domicilio
            try:
                mecanico = MecanicoDomicilio.objects.get(usuario=user)
                es_proveedor = True
                tipo_proveedor = 'mecanico'
                logger.info(f"✅ Usuario {username} es mecánico a domicilio")
            except MecanicoDomicilio.DoesNotExist:
                pass
            
            # Verificar si es taller
            if not es_proveedor:
                try:
                    taller = Taller.objects.get(usuario=user)
                    es_proveedor = True
                    tipo_proveedor = 'taller'
                    logger.info(f"✅ Usuario {username} es taller")
                except Taller.DoesNotExist:
                    pass
            
            # Si el usuario NO es proveedor, rechazar el login
            if not es_proveedor:
                logger.warning(f"❌ Login rechazado: Usuario {username} NO es proveedor")
                return Response(
                    {
                        'non_field_errors': ['Esta cuenta no es de proveedor. Por favor, utiliza la aplicación de usuarios para iniciar sesión.']
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Si llegamos aquí, el usuario ES proveedor, continuar con el login
            token, created = Token.objects.get_or_create(user=user)
            
            # Construir respuesta con datos del usuario incluyendo email
            user_data = {
                'id': user.id,
                'username': user.username,
                'email': user.email,  # ✅ Incluir email explícitamente
                'first_name': user.first_name,
                'last_name': user.last_name,
                'telefono': user.telefono,
                'direccion': user.direccion,
                'foto_perfil': user.foto_perfil.url if user.foto_perfil else None,
                'es_mecanico': user.es_mecanico,
                'tipo_proveedor': tipo_proveedor,
            }
            
            logger.info(f"✅ Login exitoso para proveedor: {username} (email: {user.email})")
            
            return Response({
                'token': token.key,
                'user': user_data
            })
        else:
            logger.warning(f"🔐 Contraseña incorrecta para usuario: {username}")
            return Response(
                {'non_field_errors': ['No puede iniciar sesión con las credenciales proporcionadas.']},
                status=status.HTTP_400_BAD_REQUEST
            )
            
    except Usuario.DoesNotExist:
        logger.warning(f"Intento de login con usuario inexistente: {username}")
        return Response(
            {'non_field_errors': ['No puede iniciar sesión con las credenciales proporcionadas.']},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Error en login proveedor: {str(e)}")
        return Response(
            {'error': f'Error de servidor: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class UsuarioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo Usuario
    """
    queryset = Usuario.objects.all()
    serializer_class = UsuarioSerializer
    
    def get_permissions(self):
        """
        Permite creación de usuarios sin autenticación,
        pero requiere autenticación para otras operaciones
        """
        if self.action == 'create':
            return []
        return [permissions.IsAuthenticated()]
    
    def create(self, request, *args, **kwargs):
        """
        Crea un nuevo usuario estableciendo la contraseña correctamente
        """
        logger.info(f"👤 Creando usuario - Data recibida: username={request.data.get('username')}, email={request.data.get('email')}")
        
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            # Extraer datos para crear el usuario manualmente
            user_data = serializer.validated_data.copy()
            password = request.data.get('password')
            
            # Validar que hay contraseña
            if not password:
                logger.warning("❌ UsuarioViewSet.create: No se proporcionó contraseña")
                return Response(
                    {"error": "La contraseña es requerida"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verificar si el usuario ya existe
            username = user_data.get('username')
            email = user_data.get('email')
            
            if username and Usuario.objects.filter(username=username).exists():
                logger.warning(f"⚠️ Usuario con username '{username}' ya existe")
                return Response(
                    {"error": f"El usuario '{username}' ya está registrado"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if email and Usuario.objects.filter(email=email).exists():
                logger.warning(f"⚠️ Usuario con email '{email}' ya existe")
                return Response(
                    {"error": f"El email '{email}' ya está registrado"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Crear usuario
            user = Usuario(
                username=user_data.get('username'),
                email=user_data.get('email'),
                first_name=user_data.get('first_name', ''),
                last_name=user_data.get('last_name', ''),
                telefono=user_data.get('telefono', ''),
                direccion=user_data.get('direccion', ''),
                es_mecanico=user_data.get('es_mecanico', False)
            )
            
            # Establecer contraseña correctamente
            if password:
                user.set_password(password)
            
            try:
                user.save()
                logger.info(f"✅ Usuario creado exitosamente: {user.username} (ID: {user.id})")
            except IntegrityError as e:
                logger.error(f"❌ Error de integridad al crear usuario: {str(e)}")
                if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                    if 'username' in str(e).lower():
                        return Response(
                            {"error": f"El usuario '{username}' ya está registrado"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    elif 'email' in str(e).lower():
                        return Response(
                            {"error": f"El email '{email}' ya está registrado"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                return Response(
                    {"error": "Error al crear el usuario. Por favor, verifica los datos."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Serializar y devolver respuesta
            serializer = self.get_serializer(user)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
            
        except ValidationError as e:
            logger.error(f"❌ Error de validación al crear usuario: {str(e)}")
            error_details = str(e)
            if hasattr(e, 'detail'):
                error_details = e.detail
            elif hasattr(e, 'message_dict'):
                error_details = e.message_dict
            return Response(
                {"error": "Datos de usuario inválidos", "details": error_details},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"❌ Error inesperado al crear usuario: {str(e)}", exc_info=True)
            error_message = str(e)
            # Si es un error de validación del serializer, extraer detalles
            if hasattr(e, 'detail'):
                error_message = str(e.detail)
            return Response(
                {"error": f"Error interno del servidor: {error_message}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ClienteViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo Cliente
    """
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['nombre', 'apellido', 'email']
    search_fields = ['nombre', 'apellido', 'email', 'direccion']
    
    def get_permissions(self):
        """
        Permite creación de clientes sin autenticación,
        pero requiere autenticación para otras operaciones
        """
        if self.action == 'create':
            return []
        return [permissions.IsAuthenticated()]
    
    def create(self, request, *args, **kwargs):
        """
        Crea un nuevo cliente asociado a un usuario existente
        """
        logger.info(f"👤 Creando cliente - Data recibida: {request.data}")
        
        try:
            # Obtener el usuario
            usuario_id = request.data.get('usuario')
            if not usuario_id:
                logger.warning("❌ ClienteViewSet.create: No se proporcionó usuario_id")
                return Response(
                    {"error": "Se requiere un ID de usuario válido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                usuario = Usuario.objects.get(id=usuario_id)
                logger.info(f"✅ Usuario encontrado: {usuario.username} (ID: {usuario_id})")
            except Usuario.DoesNotExist:
                logger.warning(f"❌ Usuario con ID {usuario_id} no existe")
                return Response(
                    {"error": f"El usuario con ID {usuario_id} no existe"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Verificar si ya existe un cliente para este usuario
            if Cliente.objects.filter(usuario=usuario).exists():
                logger.warning(f"⚠️ Usuario {usuario.username} ya tiene un perfil de cliente")
                cliente_existente = Cliente.objects.get(usuario=usuario)
                serializer = self.get_serializer(cliente_existente)
                return Response(serializer.data, status=status.HTTP_200_OK)
            
            # Verificar si el email ya está en uso por otro cliente
            email = request.data.get('email', usuario.email)
            if email and Cliente.objects.filter(email=email).exclude(usuario=usuario).exists():
                logger.warning(f"⚠️ Email {email} ya está en uso por otro cliente")
                return Response(
                    {"error": f"El email {email} ya está registrado"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Preparar datos para crear el cliente
            data = {
                'usuario': usuario,
                'nombre': request.data.get('nombre') or usuario.first_name or '',
                'apellido': request.data.get('apellido') or usuario.last_name or '',
                'email': email or usuario.email or '',
                'telefono': request.data.get('telefono') or usuario.telefono or '',
                'direccion': request.data.get('direccion') or usuario.direccion or '',
            }
            
            # Validar campos requeridos
            if not data['nombre']:
                logger.warning("❌ Nombre es requerido pero está vacío")
                return Response(
                    {"error": "El nombre es requerido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not data['email']:
                logger.warning("❌ Email es requerido pero está vacío")
                return Response(
                    {"error": "El email es requerido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Convertir ubicación a Point si se proporcionan coordenadas
            lat = request.data.get('lat')
            lng = request.data.get('lng')
            if lat and lng:
                try:
                    data['ubicacion'] = Point(float(lng), float(lat), srid=4326)
                    logger.info(f"📍 Ubicación configurada: lat={lat}, lng={lng}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Error al procesar ubicación: {str(e)}")
                    # Continuar sin ubicación si hay error
            
            # Crear el cliente
            try:
                cliente = Cliente.objects.create(**data)
                logger.info(f"✅ Cliente creado exitosamente: {cliente.nombre} {cliente.apellido} (ID: {cliente.id})")
                serializer = self.get_serializer(cliente)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except IntegrityError as e:
                logger.error(f"❌ Error de integridad al crear cliente: {str(e)}")
                if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                    if 'email' in str(e).lower():
                        return Response(
                            {"error": f"El email {data.get('email')} ya está registrado"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    elif 'usuario' in str(e).lower():
                        # Cliente ya existe para este usuario
                        cliente_existente = Cliente.objects.get(usuario=usuario)
                        serializer = self.get_serializer(cliente_existente)
                        return Response(serializer.data, status=status.HTTP_200_OK)
                return Response(
                    {"error": "Error al crear el cliente. Por favor, verifica los datos."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
        except ValidationError as e:
            logger.error(f"❌ Error de validación al crear cliente: {str(e)}")
            return Response(
                {"error": "Datos de cliente inválidos", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"❌ Error inesperado al crear cliente: {str(e)}", exc_info=True)
            return Response(
                {"error": f"Error interno del servidor: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    """
    Vista para cambiar la contraseña del usuario autenticado
    """
    user = request.user
    
    # Verificar contraseña actual
    current_password = request.data.get('current_password')
    if not current_password:
        return Response(
            {"error": "Se requiere la contraseña actual"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not user.check_password(current_password):
        return Response(
            {"error": "La contraseña actual es incorrecta"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verificar y establecer nueva contraseña
    new_password = request.data.get('new_password')
    if not new_password:
        return Response(
            {"error": "Se requiere una nueva contraseña"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validar longitud de la contraseña
    if len(new_password) < 8:
        return Response(
            {"error": "La contraseña debe tener al menos 8 caracteres"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Cambiar contraseña
    user.set_password(new_password)
    user.save()
    
    # Crear nuevo token y devolver
    Token.objects.filter(user=user).delete()
    token, _ = Token.objects.get_or_create(user=user)
    
    return Response(
        {"message": "Contraseña cambiada exitosamente", "token": token.key},
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def forgot_password(request):
    """
    Vista para solicitar recuperación de contraseña
    Recibe un email y genera un token de reseteo
    """
    email = request.data.get('email')
    
    if not email:
        return Response(
            {"error": "Se requiere un correo electrónico"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validar formato de email
    if not email or '@' not in email:
        return Response(
            {"error": "El formato del correo electrónico no es válido"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Normalizar email (lowercase, trim)
    email = email.strip().lower()
    
    try:
        # Buscar usuario por email - Validar que el email existe en la plataforma
        user = Usuario.objects.get(email=email)
        
        # Generar token único
        reset_token = str(uuid.uuid4())
        reset_token_expires = timezone.now() + timedelta(hours=1)  # Token válido por 1 hora
        
        # Guardar token en el usuario
        user.password_reset_token = reset_token
        user.password_reset_token_expires = reset_token_expires
        user.save(update_fields=['password_reset_token', 'password_reset_token_expires'])
        
        # Enviar email con el token
        email_sent = False
        email_error = None
        
        # Verificar que las credenciales de email estén configuradas
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            logger.warning("⚠️ EMAIL_HOST_USER o EMAIL_HOST_PASSWORD no están configurados. El email NO se enviará.")
            email_error = "Configuración de email no encontrada"
        else:
            try:
                reset_url = f"{request.scheme}://{request.get_host()}/reset-password?token={reset_token}"
                
                # Usar html_message para mejor formato (opcional, Django lo maneja)
                message = f'''Hola {user.get_full_name() or user.username},

Has solicitado recuperar tu contraseña en MecaniMovil.

Usa el siguiente token para restablecer tu contraseña:

🔑 Token: {reset_token}

O visita este enlace:
{reset_url}

⏰ Este token expira en 1 hora.

Si no solicitaste este cambio, ignora este mensaje.

Saludos,
Equipo MecaniMovil'''
                
                send_mail(
                    subject='🔐 Recuperación de Contraseña - MecaniMovil',
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,  # Lanzar excepción si falla para ver el error
                )
                email_sent = True
                logger.info(f"✅ Email de recuperación enviado exitosamente a {email}")
            except Exception as e:
                email_error = str(e)
                logger.error(f"❌ Error enviando email de recuperación a {email}: {str(e)}")
                logger.error(f"📧 Configuración de email: HOST={settings.EMAIL_HOST}, PORT={settings.EMAIL_PORT}, USER={settings.EMAIL_HOST_USER[:3] + '***' if settings.EMAIL_HOST_USER else 'NOT SET'}")
        
        # Retornar éxito - NUNCA devolver el token en la respuesta por seguridad
        # El token solo debe llegar por email
        response_data = {
            "message": "Se ha enviado un token de recuperación a tu correo electrónico. Revisa tu bandeja de entrada.",
        }
        
        # Log para diagnóstico (solo en logs del servidor, nunca en respuesta al cliente)
        if email_sent:
            logger.info(f"✅ Email enviado exitosamente a {email}")
        elif email_error:
            logger.warning(f"⚠️ Email NO enviado a {email}. Error: {email_error}")
            logger.warning(f"⚠️ El token fue generado pero NO se envió por email. Token: {reset_token[:20]}...")
            # En producción, esto debería ser un error crítico
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Usuario.DoesNotExist:
        # El email no está registrado en la plataforma
        logger.warning(f"⚠️ Intento de recuperación de contraseña con email no registrado: {email}")
        return Response(
            {"error": "El correo electrónico ingresado no está registrado en la plataforma. Verifica que hayas ingresado el correo correcto."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error en forgot_password: {str(e)}")
        return Response(
            {"error": "Ocurrió un error al procesar la solicitud"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def reset_password(request):
    """
    Vista para resetear la contraseña usando un token
    """
    token = request.data.get('token')
    new_password = request.data.get('new_password')
    
    if not token or not new_password:
        return Response(
            {"error": "Se requiere el token y la nueva contraseña"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validar longitud de la contraseña
    if len(new_password) < 8:
        return Response(
            {"error": "La contraseña debe tener al menos 8 caracteres"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Buscar usuario por token de reseteo
        user = Usuario.objects.get(
            password_reset_token=token,
            password_reset_token_expires__gt=timezone.now()
        )
        
        # Validar que el token no haya expirado (doble verificación)
        if user.password_reset_token_expires and user.password_reset_token_expires < timezone.now():
            return Response(
                {"error": "El token ha expirado. Solicita un nuevo enlace de recuperación"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Guardar información para logging antes de cambiar la contraseña
        username = user.username
        email = user.email
        user_id = user.id
        
        logger.info(f"🔄 Iniciando reset de contraseña para usuario: {username} (ID: {user_id}, Email: {email})")
        
        # Establecer nueva contraseña (esto hashea la contraseña correctamente)
        user.set_password(new_password)
        
        # Limpiar token de reseteo
        user.password_reset_token = None
        user.password_reset_token_expires = None
        
        # Guardar TODOS los cambios explícitamente (sin update_fields para forzar guardado completo)
        user.save()
        logger.info(f"💾 Usuario guardado en BD con nueva contraseña")
        
        # Obtener el usuario nuevamente desde la BD (nueva instancia) para verificar
        # NO usar refresh_from_db() porque puede usar caché del objeto
        user_from_db = Usuario.objects.get(id=user_id)
        
        # Verificar que la contraseña se guardó correctamente
        if not user_from_db.check_password(new_password):
            logger.error(f"❌ ERROR CRÍTICO: La contraseña NO se guardó correctamente para usuario {username}")
            logger.error(f"❌ Intentando guardar nuevamente con método directo...")
            
            # Intentar guardar directamente usando update() como último recurso
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE usuarios_usuario SET password = %s WHERE id = %s",
                    [make_password(new_password), user_id]
                )
            
            # Verificar nuevamente
            user_from_db = Usuario.objects.get(id=user_id)
            if not user_from_db.check_password(new_password):
                logger.error(f"❌ ERROR CRÍTICO PERSISTENTE: La contraseña NO se guardó después de múltiples intentos")
                return Response(
                    {"error": "Error crítico al guardar la nueva contraseña. Por favor, contacta al soporte."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            else:
                logger.info(f"✅ Contraseña guardada correctamente después de intento directo en BD")
        else:
            logger.info(f"✅ Contraseña verificada correctamente con check_password()")
        
        # Invalidar todos los tokens de autenticación antiguos del usuario
        # Esto fuerza al usuario a iniciar sesión con la nueva contraseña
        deleted_count = Token.objects.filter(user=user_from_db).count()
        Token.objects.filter(user=user_from_db).delete()
        logger.info(f"🗑️ {deleted_count} token(s) antiguo(s) eliminado(s)")
        
        logger.info(f"✅ Contraseña reseteada exitosamente para usuario: {username} (Email: {email})")
        logger.info(f"✅ Nueva contraseña verificada y funcionando. Tokens antiguos invalidados.")
        
        return Response(
            {"message": "Contraseña restablecida exitosamente. Puedes iniciar sesión con tu nueva contraseña"},
            status=status.HTTP_200_OK
        )
        
    except Usuario.DoesNotExist:
        return Response(
            {"error": "Token inválido o expirado"},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Error en reset_password: {str(e)}")
        return Response(
            {"error": "Ocurrió un error al restablecer la contraseña"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    Vista para obtener y actualizar el perfil del usuario autenticado.
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        return self.request.user
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class ActualizarFotoPerfilView(APIView):
    """
    Vista para actualizar la foto de perfil del usuario.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request, *args, **kwargs):
        usuario = request.user
        
        # Debug: Imprimir información de la petición
        print(f"🔍 ActualizarFotoPerfilView - Headers: {dict(request.headers)}")
        print(f"🔍 ActualizarFotoPerfilView - FILES: {dict(request.FILES)}")
        print(f"🔍 ActualizarFotoPerfilView - DATA: {dict(request.data)}")
        
        if 'foto_perfil' not in request.FILES:
            return Response(
                {"error": "No se proporcionó ninguna imagen"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Validar que el archivo sea una imagen
            uploaded_file = request.FILES['foto_perfil']
            
            # Verificar el tipo de contenido
            content_type = uploaded_file.content_type
            print(f"🔍 Tipo de contenido del archivo: {content_type}")
            
            # Validar tipos de imagen permitidos
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
            if content_type not in allowed_types:
                return Response(
                    {"error": f"Tipo de archivo no permitido. Tipos permitidos: {', '.join(allowed_types)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verificar tamaño del archivo (máximo 10MB)
            max_size = 10 * 1024 * 1024  # 10MB
            if uploaded_file.size > max_size:
                return Response(
                    {"error": "El archivo es demasiado grande. Tamaño máximo: 10MB"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Guardar la foto de perfil
            usuario.foto_perfil = uploaded_file
            usuario.save()
            
            print(f"✅ Foto de perfil actualizada exitosamente para usuario: {usuario.username}")
            
            return Response(
                {"message": "Foto de perfil actualizada exitosamente"},
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            print(f"❌ Error actualizando foto de perfil: {e}")
            return Response(
                {"error": f"Error al procesar la imagen: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UsuarioDetail(generics.RetrieveUpdateAPIView):
    """
    Vista para obtener y actualizar detalles de un usuario específico.
    """
    queryset = Usuario.objects.all()
    serializer_class = UsuarioSerializer
    permission_classes = [permissions.IsAuthenticated]


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def cliente_detail(request):
    """
    Obtiene los detalles del cliente asociado al usuario autenticado
    """
    usuario = request.user
    
    try:
        cliente = Cliente.objects.get(usuario=usuario)
    except Cliente.DoesNotExist:
        return Response(
            {"error": "No se encontró un cliente asociado a este usuario"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    serializer = ClienteSerializer(cliente)
    return Response(serializer.data)


class TallerViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo Taller
    """
    queryset = Taller.objects.all()
    serializer_class = TallerSerializer
    # permission_classes = [permissions.IsAuthenticated]  # Comentado para usar get_permissions()
    
    def get_queryset(self):
        """
        Filtrar talleres según el contexto:
        - Para usuarios normales: solo talleres verificados y activos
        - Para administradores: todos los talleres
        """
        # Base queryset con prefetch_related para cargar especialidades y marcas
        queryset = Taller.objects.select_related('usuario').prefetch_related(
            'especialidades',
            'marcas_atendidas'
        )
        
        if self.request.user.is_staff or self.request.user.is_superuser:
            return queryset
        else:
            # Solo mostrar talleres verificados y activos para usuarios normales
            return queryset.filter(verificado=True, activo=True)
    
    def get_permissions(self):
        """
        Permitir GET y CREATE sin autenticación, pero requerir 
        autenticación y admin para otras operaciones
        """
        if self.action in ['list', 'retrieve', 'horarios_disponibles', 'create', 'actualizar_propio', 'cerca', 'actualizar_ubicacion_domicilio', 'proveedores_filtrados', 'reviews']:
            if self.action in ['actualizar_propio', 'actualizar_ubicacion_domicilio']:
                # Solo requiere autenticación para actualizar propio perfil o ubicación
                return [permissions.IsAuthenticated()]
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]
    
    @action(detail=True, methods=['get'])
    def horarios_disponibles(self, request, pk=None):
        """
        Obtener los horarios disponibles de un taller para una fecha específica
        """
        from datetime import datetime, timedelta
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        from mecanimovilapp.apps.usuarios.models import HorarioProveedor
        
        taller = self.get_object()
        fecha_str = request.query_params.get('fecha')
        
        if not fecha_str:
            return Response(
                {"error": "Se requiere el parámetro 'fecha' en formato YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {"error": "Formato de fecha inválido. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener el día de la semana (0=Lunes, 6=Domingo)
        dia_semana = fecha.weekday()
        
        # Buscar la configuración de horario para este día usando el nuevo modelo
        try:
            horario_config = HorarioProveedor.objects.get(
                taller=taller,
                dia_semana=dia_semana,
                activo=True
            )
        except HorarioProveedor.DoesNotExist:
            # Si no hay configuración específica, usar horarios por defecto
            horario_config = self._generar_horario_defecto_taller(dia_semana)
            if not horario_config:
                return Response({
                    "fecha": fecha_str,
                    "dia_semana": dia_semana,
                    "dia_nombre": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dia_semana],
                    "taller_disponible": False,
                    "mensaje": "El taller no atiende este día",
                    "slots_disponibles": []
                })
        
        # Generar slots base
        slots_base = horario_config.generar_slots_disponibles(fecha)
        
        # Verificar disponibilidad real consultando las citas existentes
        solicitudes_existentes = SolicitudServicio.objects.filter(
            taller=taller,
            fecha_servicio=fecha,
            estado__in=['pendiente', 'en_proceso', 'confirmado', 'aceptada_por_proveedor']
        ).values_list('hora_servicio', flat=True)
        
        # Marcar slots ocupados
        for slot in slots_base:
            hora_inicio_24h = slot['hora_inicio_24h']
            if hora_inicio_24h in solicitudes_existentes:
                slot['disponible'] = False
                slot['motivo'] = 'Ocupado'
        
        return Response({
            "fecha": fecha_str,
            "dia_semana": dia_semana,
            "dia_nombre": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dia_semana],
            "taller_disponible": True,
            "taller": TallerSerializer(taller).data,
            "horario_configurado": HorarioProveedorSerializer(horario_config).data,
            "slots_disponibles": slots_base,
            "total_slots": len(slots_base),
            "slots_disponibles_count": len([s for s in slots_base if s['disponible']]),
            "tipo_servicio": "taller"
        })
    
    def _generar_horario_defecto_taller(self, dia_semana):
        """
        Genera un horario por defecto para talleres si no tienen configuración específica
        """
        from datetime import time
        from mecanimovilapp.apps.usuarios.models import HorarioProveedor
        
        # Los talleres típicamente no trabajan domingos
        if dia_semana == 6:  # Domingo
            return None
        
        # Crear objeto temporal con horarios por defecto (no se guarda en BD)
        class HorarioTemporal:
            def __init__(self, dia_semana):
                self.dia_semana = dia_semana
                self.activo = True
                if dia_semana == 5:  # Sábado
                    self.hora_inicio = time(8, 0)
                    self.hora_fin = time(13, 0)
                else:  # Lunes a Viernes
                    self.hora_inicio = time(8, 0)
                    self.hora_fin = time(18, 0)
                self.duracion_slot = 60
                self.tiempo_descanso = 0
            
            def generar_slots_disponibles(self, fecha=None):
                from datetime import datetime, timedelta
                
                slots = []
                hora_actual = datetime.combine(fecha or datetime.today().date(), self.hora_inicio)
                hora_fin = datetime.combine(fecha or datetime.today().date(), self.hora_fin)
                
                while hora_actual + timedelta(minutes=self.duracion_slot) <= hora_fin:
                    slot_fin = hora_actual + timedelta(minutes=self.duracion_slot)
                    slots.append({
                        'hora_inicio': hora_actual.time().strftime('%H:%M'),
                        'hora_fin': slot_fin.time().strftime('%H:%M'),
                        'hora_inicio_24h': hora_actual.time(),
                        'hora_fin_24h': slot_fin.time(),
                        'disponible': True
                    })
                    hora_actual = slot_fin + timedelta(minutes=self.tiempo_descanso)
                
                return slots
        
        return HorarioTemporal(dia_semana)

    @action(detail=False, methods=['get'])
    def cerca(self, request):
        """
        Filtrar talleres por proximidad a una ubicación dada
        """
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        max_distance = request.query_params.get('dist', 5)  # default 5km
        
        if not lat or not lng:
            return Response(
                {"error": "Se requieren los parámetros lat y lng"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            lat = float(lat)
            lng = float(lng)
            max_distance = float(max_distance)
        except ValueError:
            return Response(
                {"error": "Los parámetros lat, lng y dist deben ser números válidos"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Crear un punto a partir de las coordenadas
        user_location = Point(lng, lat, srid=4326)
        
        # Filtrar talleres cercanos
        # ✅ CORREGIDO: Usar SphericalDistance para cálculos precisos en kilómetros
        from django.contrib.gis.db.models.functions import Distance
        from django.contrib.gis.measure import D
        
        queryset = Taller.objects.annotate(
            distance=Distance('ubicacion', user_location, spheroid=True)
        ).filter(
            ubicacion__distance_lte=(user_location, D(km=max_distance))
        ).order_by('distance')
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """
        Crear nuevo taller con validaciones específicas
        """
        try:
            user = request.user
            
            # Verificar si ya existe un taller para este usuario
            if hasattr(user, 'taller'):
                return Response({
                    'codigo': 'TALLER_DUPLICADO',
                    'error': 'Ya existe un perfil de taller para este usuario.',
                    'taller_id': user.taller.id
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validar datos requeridos
            required_fields = ['nombre', 'telefono', 'descripcion']
            missing_fields = [field for field in required_fields if not request.data.get(field)]
            
            if missing_fields:
                return Response({
                    'error': f'Campos requeridos faltantes: {", ".join(missing_fields)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Crear el taller
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            # Asignar el usuario y marcar onboarding como iniciado
            taller = serializer.save(
                usuario=user,
                onboarding_iniciado=True,
                estado_verificacion='pendiente',
                verificado=False,
                activo=True  # Activo para permitir completar onboarding
            )
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except ValidationError as e:
            return Response({
                'error': 'Datos de taller inválidos',
                'details': e.detail
            }, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as e:
            return Response({
                'codigo': 'TALLER_DUPLICADO',
                'error': 'Ya existe un perfil de taller para este usuario.'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creando taller: {str(e)}")
            return Response({
                'error': 'Error interno del servidor al crear taller'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['patch'], permission_classes=[permissions.IsAuthenticated])
    def actualizar_propio(self, request):
        """
        Actualizar el perfil del taller del usuario autenticado
        """
        try:
            user = request.user
            
            # Buscar el taller del usuario autenticado
            try:
                taller = Taller.objects.get(usuario=user)
            except Taller.DoesNotExist:
                return Response({
                    'error': 'No se encontró perfil de taller para este usuario'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Extraer datos de dirección si están presentes
            direccion_data = {}
            if 'direccion' in request.data:
                # Parsear la dirección completa para extraer componentes
                direccion_completa = request.data.get('direccion', '').strip()
                
                print(f"🔍 Procesando dirección: '{direccion_completa}'")
                print(f"🔍 Datos recibidos: {dict(request.data)}")
                
                if direccion_completa:
                    # Extraer componentes directos si vienen por separado
                    calle = request.data.get('calle', '')
                    numero = request.data.get('numero', '')
                    comuna = request.data.get('comuna', '')
                    ciudad = request.data.get('ciudad', '')
                    region = request.data.get('region', '')
                    
                    # Si no vienen por separado, intentar parsear la dirección completa
                    if not calle or not comuna:
                        # Parsear dirección completa: "Calle Número, Comuna, Ciudad, Chile"
                        partes = direccion_completa.split(',')
                        if len(partes) >= 2:
                            # Primera parte: "Calle Número"
                            calle_numero = partes[0].strip()
                            
                            # Extraer número de la primera parte
                            import re
                            numero_match = re.search(r'\d+', calle_numero)
                            if numero_match:
                                numero = numero_match.group()
                                calle = calle_numero.replace(numero, '').strip()
                            else:
                                calle = calle_numero
                            
                            # Segunda parte: Comuna
                            if len(partes) > 1:
                                comuna = partes[1].strip()
                            
                            # Tercera parte: Ciudad
                            if len(partes) > 2:
                                ciudad = partes[2].strip()
                            
                            # Cuarta parte: Región/País
                            if len(partes) > 3:
                                parte_final = partes[3].strip()
                                # Si la última parte es "Chile", usar la anterior como región
                                if parte_final.lower() == 'chile':
                                    region = ciudad  # La ciudad se convierte en región
                                    # No cambiar ciudad, mantener la que ya se asignó
                                else:
                                    region = parte_final
                    
                    # Crear datos de dirección
                    direccion_data = {
                        'calle': calle,
                        'numero': numero,
                        'comuna': comuna,
                        'ciudad': ciudad,
                        'region': region,
                        'codigo_postal': request.data.get('codigo_postal', ''),
                        'detalles_adicionales': request.data.get('detalles_adicionales', '')
                    }
                    
                    print(f"📍 Datos de dirección parseados: {direccion_data}")
                    
                    # Si hay datos de dirección válidos, crear o actualizar TallerDireccion
                    if any([calle, numero, comuna, ciudad]):
                        try:
                            # Intentar obtener dirección existente
                            direccion_fisica = TallerDireccion.objects.get(taller=taller)
                            # Actualizar dirección existente
                            for key, value in direccion_data.items():
                                if value:  # Solo actualizar si hay valor
                                    setattr(direccion_fisica, key, value)
                            direccion_fisica.save()
                            print(f"✅ Dirección actualizada para taller {taller.nombre}")
                        except TallerDireccion.DoesNotExist:
                            # Crear nueva dirección
                            direccion_fisica = TallerDireccion.objects.create(
                                taller=taller,
                                **direccion_data
                            )
                            print(f"✅ Nueva dirección creada para taller {taller.nombre}")
            
            # Actualizar el taller con los datos proporcionados (excluyendo dirección)
            datos_taller = {k: v for k, v in request.data.items() if k not in ['direccion', 'calle', 'numero', 'comuna', 'ciudad', 'region', 'codigo_postal', 'detalles_adicionales']}
            
            if datos_taller:
                serializer = self.get_serializer(taller, data=datos_taller, partial=True)
                serializer.is_valid(raise_exception=True)
                serializer.save()
            
            # Obtener datos actualizados del taller
            serializer = self.get_serializer(taller)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except ValidationError as e:
            return Response({
                'error': 'Datos de taller inválidos',
                'details': e.detail
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error actualizando perfil de taller: {str(e)}")
            return Response({
                'error': 'Error interno del servidor al actualizar taller'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['patch'], permission_classes=[permissions.IsAuthenticated])
    def actualizar_ubicacion_domicilio(self, request):
        """
        Actualizar la ubicación de domicilio del taller con geocodificación automática
        """
        try:
            user = request.user
            
            # Buscar el taller del usuario autenticado
            try:
                taller = Taller.objects.get(usuario=user)
            except Taller.DoesNotExist:
                return Response({
                    'error': 'No se encontró perfil de taller para este usuario'
                }, status=status.HTTP_404_NOT_FOUND)
            
            direccion = request.data.get('direccion')
            latitud = request.data.get('latitud')
            longitud = request.data.get('longitud')
            
            if not direccion and not (latitud and longitud):
                return Response({
                    'error': 'Se requiere una dirección o coordenadas (latitud y longitud)'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Si se proporcionan coordenadas directamente
            if latitud and longitud:
                try:
                    lat = float(latitud)
                    lng = float(longitud)
                    ubicacion = Point(lng, lat, srid=4326)
                    taller.ubicacion = ubicacion
                    taller.save()
                    
                    return Response({
                        'mensaje': 'Ubicación actualizada exitosamente con coordenadas proporcionadas',
                        'ubicacion': {
                            'latitud': lat,
                            'longitud': lng
                        }
                    }, status=status.HTTP_200_OK)
                    
                except (ValueError, TypeError):
                    return Response({
                        'error': 'Las coordenadas deben ser números válidos'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Si solo se proporciona dirección, geocodificar
            if direccion:
                try:
                    # Geocodificar usando Nominatim
                    geocode_url = "https://nominatim.openstreetmap.org/search"
                    params = {
                        'q': f"{direccion}, Chile",
                        'format': 'json',
                        'limit': 1,
                        'countrycodes': 'cl'
                    }
                    
                    headers = {
                        'User-Agent': 'MecaniMovil/1.0'
                    }
                    
                    response = requests.get(geocode_url, params=params, headers=headers, timeout=10)
                    time.sleep(1)  # Respetar rate limiting
                    
                    if response.status_code == 200:
                        results = response.json()
                        if results:
                            result = results[0]
                            lat = float(result['lat'])
                            lng = float(result['lon'])
                            
                            # Validar que esté en Chile
                            if -56 <= lat <= -17 and -76 <= lng <= -66:
                                ubicacion = Point(lng, lat, srid=4326)
                                taller.ubicacion = ubicacion
                                taller.save()
                                
                                return Response({
                                    'mensaje': 'Ubicación actualizada exitosamente mediante geocodificación',
                                    'ubicacion': {
                                        'latitud': lat,
                                        'longitud': lng,
                                        'direccion_geocodificada': result.get('display_name', '')
                                    }
                                }, status=status.HTTP_200_OK)
                            else:
                                return Response({
                                    'error': 'La dirección no parece estar en Chile'
                                }, status=status.HTTP_400_BAD_REQUEST)
                        else:
                            return Response({
                                'error': 'No se pudo encontrar la dirección especificada'
                            }, status=status.HTTP_400_BAD_REQUEST)
                    else:
                        return Response({
                            'error': 'Error en el servicio de geocodificación'
                        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                        
                except Exception as geocode_error:
                    logger.error(f"Error en geocodificación: {str(geocode_error)}")
                    return Response({
                        'error': 'Error al procesar la dirección. Intente con coordenadas específicas.'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f"Error actualizando ubicación de taller: {str(e)}")
            return Response({
                'error': 'Error interno del servidor al actualizar ubicación'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @action(detail=True, methods=['get'], permission_classes=[permissions.AllowAny])
    def reviews(self, request, pk=None):
        """
        Obtiene el resumen de reseñas y la lista detallada
        """
        taller = self.get_object()
        resenas = Resena.objects.filter(taller=taller).select_related(
            'cliente', 'cliente__usuario', 'solicitud', 'solicitud__vehiculo', 
            'solicitud__vehiculo__marca', 'solicitud__vehiculo__modelo'
        ).prefetch_related('fotos').order_by('-fecha_hora_resena')
        
        # Calcular estadísticas
        total_reviews = resenas.count()
        average_rating = resenas.aggregate(Avg('calificacion'))['calificacion__avg'] or 0.0
        
        # Calcular breakdown
        breakdown = {
            '5': resenas.filter(calificacion=5).count(),
            '4': resenas.filter(calificacion=4).count(),
            '3': resenas.filter(calificacion=3).count(),
            '2': resenas.filter(calificacion=2).count(),
            '1': resenas.filter(calificacion=1).count(),
        }
        
        # Serializar respuesta
        from .serializers import ProviderReviewsSummarySerializer
        serializer = ProviderReviewsSummarySerializer({
            'rating_average': round(average_rating, 1),
            'total_reviews': total_reviews,
            'rating_breakdown': breakdown,
            'reviews': resenas
        }, context={'request': request})
        
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def proveedores_filtrados(self, request):
        """
        Obtiene proveedores (talleres) filtrados por marca de vehículo y servicios seleccionados
        Parámetros:
        - vehiculo_id: ID del vehículo (obligatorio)
        - servicio_ids: IDs de servicios (opcional, puede ser múltiple como servicio_ids[]=1&servicio_ids[]=2)
        """
        from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo
        from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
        
        logger.info(f"🔍 proveedores_filtrados (talleres) - Query params: {dict(request.query_params)}")
        
        vehiculo_id = request.query_params.get('vehiculo_id')
        # Intentar obtener servicio_ids en diferentes formatos
        servicio_ids = request.query_params.getlist('servicio_ids[]')  # Array de IDs con []
        if not servicio_ids:
            # Intentar sin []
            servicio_ids = request.query_params.getlist('servicio_ids')
        if not servicio_ids:
            # Intentar formato servicio_ids[0], servicio_ids[1], etc.
            servicio_ids = []
            i = 0
            while True:
                servicio_id = request.query_params.get(f'servicio_ids[{i}]')
                if servicio_id:
                    servicio_ids.append(servicio_id)
                    i += 1
                else:
                    break
        
        logger.info(f"🔍 Vehículo ID: {vehiculo_id}, Servicio IDs: {servicio_ids}")
        
        if not vehiculo_id:
            return Response(
                {"error": "Se requiere el parámetro 'vehiculo_id'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(id=vehiculo_id)
        except Vehiculo.DoesNotExist:
            return Response(
                {"error": f"El vehículo con ID {vehiculo_id} no existe"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Obtener la marca del vehículo
        marca_vehiculo = vehiculo.marca
        if not marca_vehiculo:
            return Response(
                {"error": "El vehículo no tiene una marca asociada"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Filtrar talleres por marca atendida
        queryset = Taller.objects.filter(
            marcas_atendidas=marca_vehiculo,
            verificado=True,
            activo=True
        ).select_related(
            'usuario',
            'direccion_fisica',   # OneToOne relationship
            'connection_status'   # OneToOne relationship
        ).prefetch_related(
            'especialidades',
            'marcas_atendidas'
        ).annotate(
            servicios_completados_count=Count(
                'solicitudes',
                filter=Q(solicitudes__estado='completado')
            )
        )
        
        logger.info(f"🔍 Talleres con marca {marca_vehiculo.nombre}: {queryset.count()}")
        
        # Si hay servicios seleccionados, filtrar también por proveedores que ofrecen esos servicios
        if servicio_ids:
            try:
                servicio_ids_int = [int(sid) for sid in servicio_ids]
                servicios = Servicio.objects.filter(id__in=servicio_ids_int)
                
                if not servicios.exists():
                    return Response(
                        {"error": "Ninguno de los servicios especificados existe"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Obtener IDs de talleres que tienen OfertaServicio para estos servicios
                # Opción 1: Filtrar por OfertaServicio directo
                # Considerar ofertas con marca específica O sin marca específica (NULL) si el taller atiende la marca
                talleres_con_ofertas = OfertaServicio.objects.filter(
                    servicio__in=servicios,
                    tipo_proveedor='taller',
                    disponible=True,
                    taller__marcas_atendidas=marca_vehiculo,
                    taller__verificado=True,
                    taller__activo=True
                ).filter(
                    # Oferta con marca específica que coincide O sin marca específica (NULL)
                    Q(marca_vehiculo_seleccionada=marca_vehiculo) | Q(marca_vehiculo_seleccionada__isnull=True)
                ).values_list('taller_id', flat=True).distinct()
                
                logger.info(f"🔍 Talleres con ofertas directas: {len(talleres_con_ofertas)}")
                
                # Opción 2: Filtrar por especialidades (si el servicio pertenece a una categoría que el taller tiene)
                # Obtener categorías de los servicios
                categorias_servicios = set()
                for servicio in servicios:
                    categorias_servicios.update(servicio.categorias.values_list('id', flat=True))
                
                logger.info(f"🔍 Categorías de servicios: {categorias_servicios}")
                
                talleres_con_especialidades = Taller.objects.filter(
                    marcas_atendidas=marca_vehiculo,
                    verificado=True,
                    activo=True,
                    especialidades__id__in=categorias_servicios
                ).values_list('id', flat=True).distinct()
                
                logger.info(f"🔍 Talleres con especialidades: {len(talleres_con_especialidades)}")
                
                # Combinar ambas opciones (OR): talleres con ofertas O talleres con especialidades
                talleres_ids = set(talleres_con_ofertas) | set(talleres_con_especialidades)
                
                logger.info(f"🔍 Total talleres únicos: {len(talleres_ids)}")
                
                if not talleres_ids:
                    return Response({
                        "talleres": [],
                        "mensaje": "No se encontraron talleres que atiendan esta marca y ofrezcan los servicios seleccionados"
                    })
                
                queryset = queryset.filter(id__in=talleres_ids)
                
            except ValueError:
                return Response(
                    {"error": "Los IDs de servicios deben ser números válidos"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Serializar resultados
        logger.info(f"✅ Talleres encontrados: {queryset.count()}")
        serializer = TallerSerializer(queryset, many=True)
        return Response({
            "talleres": serializer.data,
            "total": queryset.count(),
            "filtros_aplicados": {
                "marca_vehiculo": marca_vehiculo.nombre,
                "servicios": servicio_ids if servicio_ids else "todos"
            }
        })


class MecanicoDomicilioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para los mecánicos a domicilio
    """
    queryset = MecanicoDomicilio.objects.all()
    serializer_class = MecanicoDomicilioSerializer
    
    def get_queryset(self):
        """
        Filtrar mecánicos según el contexto:
        - Para usuarios normales: solo mecánicos verificados y activos
        - Para administradores: todos los mecánicos
        """
        # Base queryset con prefetch_related para cargar especialidades y marcas
        queryset = MecanicoDomicilio.objects.select_related('usuario').prefetch_related(
            'especialidades',
            'marcas_atendidas'
        )
        
        if self.request.user.is_staff or self.request.user.is_superuser:
            return queryset
        else:
            # Solo mostrar mecánicos verificados y activos para usuarios normales
            return queryset.filter(verificado=True, activo=True)
    
    def get_permissions(self):
        """
        Permitir GET y CREATE sin autenticación, pero requerir 
        autenticación y admin para otras operaciones
        """
        if self.action in ['list', 'retrieve', 'horarios_disponibles', 'create', 'actualizar_propio', 'cerca', 'actualizar_ubicacion_domicilio', 'proveedores_filtrados', 'reviews']:
            if self.action in ['actualizar_propio', 'actualizar_ubicacion_domicilio']:
                # Solo requiere autenticación para actualizar propio perfil o ubicación
                return [permissions.IsAuthenticated()]
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]
    
    @action(detail=True, methods=['get'])
    def horarios_disponibles(self, request, pk=None):
        """
        Obtener los horarios disponibles de un mecánico a domicilio para una fecha específica
        """
        from datetime import datetime, timedelta
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        from mecanimovilapp.apps.usuarios.models import HorarioProveedor
        
        mecanico = self.get_object()
        fecha_str = request.query_params.get('fecha')
        
        if not fecha_str:
            return Response(
                {"error": "Se requiere el parámetro 'fecha' en formato YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {"error": "Formato de fecha inválido. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener el día de la semana (0=Lunes, 6=Domingo)
        dia_semana = fecha.weekday()
        
        # Buscar la configuración de horario para este día usando el nuevo modelo
        try:
            horario_config = HorarioProveedor.objects.get(
                mecanico=mecanico,
                dia_semana=dia_semana,
                activo=True
            )
        except HorarioProveedor.DoesNotExist:
            # Si no hay configuración específica, usar horarios por defecto
            horario_config = self._generar_horario_defecto_mecanico(dia_semana)
            if not horario_config:
                return Response({
                    "fecha": fecha_str,
                    "dia_semana": dia_semana,
                    "dia_nombre": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dia_semana],
                    "mecanico_disponible": False,
                    "mensaje": "El mecánico no atiende este día",
                    "slots_disponibles": []
                })
        
        # Generar slots base
        slots_base = horario_config.generar_slots_disponibles(fecha)
        
        # Verificar disponibilidad real consultando las citas existentes
        solicitudes_existentes = SolicitudServicio.objects.filter(
            mecanico=mecanico,
            fecha_servicio=fecha,
            estado__in=['pendiente', 'en_proceso', 'confirmado', 'aceptada_por_proveedor']
        ).values_list('hora_servicio', flat=True)
        
        # Marcar slots ocupados
        for slot in slots_base:
            hora_inicio_time = slot['hora_inicio_24h']
            if hora_inicio_time in solicitudes_existentes:
                slot['disponible'] = False
                slot['motivo'] = 'Ocupado'
        
        return Response({
            "fecha": fecha_str,
            "dia_semana": dia_semana,
            "dia_nombre": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dia_semana],
            "mecanico_disponible": True,
            "mecanico": MecanicoDomicilioSerializer(mecanico).data,
            "horario_configurado": HorarioProveedorSerializer(horario_config).data,
            "slots_disponibles": slots_base,
            "total_slots": len(slots_base),
            "slots_disponibles_count": len([s for s in slots_base if s['disponible']]),
            "tipo_servicio": "domicilio"
        })
    
    def _generar_horario_defecto_mecanico(self, dia_semana):
        """
        Genera un horario por defecto para mecánicos si no tienen configuración específica
        """
        from datetime import time
        
        # Los mecánicos típicamente no trabajan domingos
        if dia_semana == 6:  # Domingo
            return None
        
        # Crear objeto temporal con horarios por defecto (no se guarda en BD)
        class HorarioTemporal:
            def __init__(self, dia_semana):
                self.dia_semana = dia_semana
                self.activo = True
                if dia_semana == 5:  # Sábado
                    self.hora_inicio = time(9, 0)
                    self.hora_fin = time(16, 0)
                else:  # Lunes a Viernes
                    self.hora_inicio = time(8, 0)
                    self.hora_fin = time(18, 0)
                self.duracion_slot = 120  # 2 horas por servicio a domicilio
                self.tiempo_descanso = 30  # 30 min entre servicios para traslado
            
            def generar_slots_disponibles(self, fecha=None):
                from datetime import datetime, timedelta
                
                slots = []
                hora_actual = datetime.combine(fecha or datetime.today().date(), self.hora_inicio)
                hora_fin = datetime.combine(fecha or datetime.today().date(), self.hora_fin)
                
                while hora_actual + timedelta(minutes=self.duracion_slot) <= hora_fin:
                    slot_fin = hora_actual + timedelta(minutes=self.duracion_slot)
                    slots.append({
                        'hora_inicio': hora_actual.time().strftime('%H:%M'),
                        'hora_fin': slot_fin.time().strftime('%H:%M'),
                        'hora_inicio_24h': hora_actual.time(),
                        'hora_fin_24h': slot_fin.time(),
                        'disponible': True
                    })
                    hora_actual = slot_fin + timedelta(minutes=self.tiempo_descanso)
                
                return slots
        
        return HorarioTemporal(dia_semana)
    
    def create(self, request, *args, **kwargs):
        """
        Crear nuevo mecánico a domicilio con validaciones específicas
        """
        try:
            # Obtener usuario_id de los datos
            usuario_id = request.data.get('usuario_id')
            dni = request.data.get('dni')
            
            # Validar si ya existe un mecánico para este usuario
            if usuario_id:
                mecanico_existente = MecanicoDomicilio.objects.filter(usuario_id=usuario_id).first()
                if mecanico_existente:
                    return Response({
                        'codigo': 'MECANICO_DUPLICADO',
                        'error': 'Ya existe un perfil de mecánico para este usuario.',
                        'mecanico_id': mecanico_existente.id
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validar datos requeridos
            required_fields = ['nombre', 'telefono', 'descripcion', 'dni', 'experiencia_anos', 'usuario_id']
            missing_fields = [field for field in required_fields if not request.data.get(field)]
            
            if missing_fields:
                return Response({
                    'error': f'Campos requeridos faltantes: {", ".join(missing_fields)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validar DNI único
            if dni:
                mecanico_dni_existente = MecanicoDomicilio.objects.filter(dni=dni).first()
                if mecanico_dni_existente:
                    return Response({
                        'codigo': 'DNI_DUPLICADO',
                        'error': f'Ya existe un mecánico registrado con el DNI "{dni}".'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Crear el mecánico
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            # Asignar datos adicionales y marcar onboarding como iniciado
            mecanico = serializer.save(
                onboarding_iniciado=True,
                estado_verificacion='pendiente',
                verificado=False,
                activo=True  # Activo para permitir completar onboarding
            )
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except ValidationError as e:
            return Response({
                'error': 'Datos de mecánico inválidos',
                'details': e.detail
            }, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as e:
            return Response({
                'codigo': 'MECANICO_DUPLICADO',
                'error': 'Ya existe un perfil de mecánico para este usuario.'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creando mecánico: {str(e)}")
            return Response({
                'error': 'Error interno del servidor al crear mecánico'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['patch'], permission_classes=[permissions.IsAuthenticated])
    def actualizar_propio(self, request):
        """
        Actualizar el perfil del mecánico del usuario autenticado
        """
        try:
            user = request.user
            
            # Buscar el mecánico del usuario autenticado
            try:
                mecanico = MecanicoDomicilio.objects.get(usuario=user)
            except MecanicoDomicilio.DoesNotExist:
                return Response({
                    'error': 'No se encontró perfil de mecánico para este usuario'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Validar experiencia_anos si viene en el request
            experiencia_raw = request.data.get('experiencia_anos')
            if experiencia_raw is not None:
                # Convertir a int si viene como string
                if isinstance(experiencia_raw, str):
                    experiencia_raw = int(experiencia_raw) if experiencia_raw.strip() else None
                request.data['experiencia_anos'] = experiencia_raw
            
            # Actualizar el mecánico con los datos proporcionados
            serializer = self.get_serializer(mecanico, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except ValidationError as e:
            return Response({
                'error': 'Datos de mecánico inválidos',
                'details': e.detail
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error actualizando perfil de mecánico: {str(e)}")
            return Response({
                'error': 'Error interno del servidor al actualizar mecánico'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def cerca(self, request):
        """
        Filtrar mecánicos a domicilio por proximidad a una ubicación dada
        y opcionalmente por compatibilidad con marcas de vehículos del usuario
        """
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        max_distance = request.query_params.get('dist', 10)  # default 10km para mecánicos
        marca_vehiculo = request.query_params.get('marca')  # opcional: filtrar por marca
        
        if not lat or not lng:
            return Response(
                {"error": "Se requieren los parámetros lat y lng"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            lat = float(lat)
            lng = float(lng)
            max_distance = float(max_distance)
        except ValueError:
            return Response(
                {"error": "Los parámetros lat, lng y dist deben ser números válidos"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Crear un punto a partir de las coordenadas
        user_location = Point(lng, lat, srid=4326)
        
        # Filtrar mecánicos cercanos, verificados y activos
        queryset = MecanicoDomicilio.objects.select_related('usuario').prefetch_related(
            'especialidades',
            'marcas_atendidas'
        ).filter(
            verificado=True,
            activo=True,
            ubicacion__isnull=False  # Solo mecánicos con ubicación registrada
        ).annotate(
            # ✅ CORREGIDO: Usar SphericalDistance para cálculos precisos en kilómetros
            distance=Distance('ubicacion', user_location, spheroid=True)
        ).filter(
            ubicacion__distance_lte=(user_location, D(km=max_distance))
        )
        
        # Filtrar por marca de vehículo si se especifica
        if marca_vehiculo:
            try:
                marca_id = int(marca_vehiculo)
                queryset = queryset.filter(marcas_atendidas__id=marca_id)
            except ValueError:
                # Si no es un ID numérico, buscar por nombre de marca
                queryset = queryset.filter(marcas_atendidas__nombre__icontains=marca_vehiculo)
        
        # Ordenar por distancia
        queryset = queryset.order_by('distance')
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['patch'], permission_classes=[permissions.IsAuthenticated])
    def actualizar_ubicacion_domicilio(self, request):
        """
        Endpoint para que los mecánicos a domicilio actualicen su ubicación
        """
        try:
            # Obtener el mecánico autenticado
            mecanico = MecanicoDomicilio.objects.get(usuario=request.user)
            
            # Obtener datos de la solicitud
            latitud = request.data.get('latitud')
            longitud = request.data.get('longitud')
            direccion = request.data.get('direccion')
            
            if not all([latitud, longitud, direccion]):
                return Response({
                    'error': 'Se requieren latitud, longitud y dirección'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Actualizar ubicación
            mecanico.latitud = float(latitud)
            mecanico.longitud = float(longitud)
            mecanico.direccion = direccion
            
            # Crear punto geográfico
            from django.contrib.gis.geos import Point
            mecanico.ubicacion = Point(float(longitud), float(latitud), srid=4326)
            
            mecanico.save()
            
            print(f"✅ Ubicación actualizada para {mecanico.nombre}: {latitud}, {longitud}")
            
            return Response({
                'message': 'Ubicación actualizada correctamente',
                'mecanico': mecanico.nombre,
                'latitud': latitud,
                'longitud': longitud,
                'direccion': direccion
            })
            
        except MecanicoDomicilio.DoesNotExist:
            return Response({
                'error': 'No se encontró un mecánico asociado a tu cuenta'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"❌ Error actualizando ubicación: {str(e)}")
            return Response({
                'error': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @action(detail=True, methods=['get'], permission_classes=[permissions.AllowAny])
    def reviews(self, request, pk=None):
        """
        Obtiene el resumen de reseñas y la lista detallada para mecánicos
        """
        mecanico = self.get_object()
        resenas = Resena.objects.filter(mecanico=mecanico).select_related(
            'cliente', 'cliente__usuario', 'solicitud', 'solicitud__vehiculo', 
            'solicitud__vehiculo__marca', 'solicitud__vehiculo__modelo'
        ).prefetch_related('fotos').order_by('-fecha_hora_resena')
        
        # Calcular estadísticas
        total_reviews = resenas.count()
        average_rating = resenas.aggregate(Avg('calificacion'))['calificacion__avg'] or 0.0
        
        # Calcular breakdown
        breakdown = {
            '5': resenas.filter(calificacion=5).count(),
            '4': resenas.filter(calificacion=4).count(),
            '3': resenas.filter(calificacion=3).count(),
            '2': resenas.filter(calificacion=2).count(),
            '1': resenas.filter(calificacion=1).count(),
        }
        
        # Serializar respuesta
        from .serializers import ProviderReviewsSummarySerializer
        serializer = ProviderReviewsSummarySerializer({
            'rating_average': round(average_rating, 1),
            'total_reviews': total_reviews,
            'rating_breakdown': breakdown,
            'reviews': resenas
        }, context={'request': request})
        
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def proveedores_filtrados(self, request):
        """
        Obtiene proveedores (mecánicos) filtrados por marca de vehículo y servicios seleccionados
        Parámetros:
        - vehiculo_id: ID del vehículo (obligatorio)
        - servicio_ids: IDs de servicios (opcional, puede ser múltiple como servicio_ids[]=1&servicio_ids[]=2)
        """
        from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo
        from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
        
        logger.info(f"🔍 proveedores_filtrados (mecánicos) - Query params: {dict(request.query_params)}")
        
        vehiculo_id = request.query_params.get('vehiculo_id')
        # Intentar obtener servicio_ids en diferentes formatos
        servicio_ids = request.query_params.getlist('servicio_ids[]')  # Array de IDs con []
        if not servicio_ids:
            # Intentar sin []
            servicio_ids = request.query_params.getlist('servicio_ids')
        if not servicio_ids:
            # Intentar formato servicio_ids[0], servicio_ids[1], etc.
            servicio_ids = []
            i = 0
            while True:
                servicio_id = request.query_params.get(f'servicio_ids[{i}]')
                if servicio_id:
                    servicio_ids.append(servicio_id)
                    i += 1
                else:
                    break
        
        logger.info(f"🔍 Vehículo ID: {vehiculo_id}, Servicio IDs: {servicio_ids}")
        
        if not vehiculo_id:
            return Response(
                {"error": "Se requiere el parámetro 'vehiculo_id'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(id=vehiculo_id)
        except Vehiculo.DoesNotExist:
            return Response(
                {"error": f"El vehículo con ID {vehiculo_id} no existe"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Obtener la marca del vehículo
        marca_vehiculo = vehiculo.marca
        if not marca_vehiculo:
            return Response(
                {"error": "El vehículo no tiene una marca asociada"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Filtrar mecánicos por marca atendida
        queryset = MecanicoDomicilio.objects.filter(
            marcas_atendidas=marca_vehiculo,
            verificado=True,
            activo=True
        ).select_related(
            'usuario',
            'connection_status'   # OneToOne relationship - use select_related
        ).prefetch_related(
            'especialidades',
            'marcas_atendidas',
            'service_areas',      # Zonas de servicio (comunas)
            'resenas'             # Reseñas para calcular rating real si es necesario
        ).annotate(
            servicios_completados_count=Count(
                'solicitudes',
                filter=Q(solicitudes__estado='completado')
            )
        )
        
        logger.info(f"🔍 Mecánicos con marca {marca_vehiculo.nombre}: {queryset.count()}")
        
        # Si hay servicios seleccionados, filtrar también por proveedores que ofrecen esos servicios
        if servicio_ids:
            try:
                servicio_ids_int = [int(sid) for sid in servicio_ids]
                servicios = Servicio.objects.filter(id__in=servicio_ids_int)
                
                if not servicios.exists():
                    return Response(
                        {"error": "Ninguno de los servicios especificados existe"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Obtener IDs de mecánicos que tienen OfertaServicio para estos servicios
                # Opción 1: Filtrar por OfertaServicio directo
                # Considerar ofertas con marca específica O sin marca específica (NULL) si el mecánico atiende la marca
                mecanicos_con_ofertas = OfertaServicio.objects.filter(
                    servicio__in=servicios,
                    tipo_proveedor='mecanico',
                    disponible=True,
                    mecanico__marcas_atendidas=marca_vehiculo,
                    mecanico__verificado=True,
                    mecanico__activo=True
                ).filter(
                    # Oferta con marca específica que coincide O sin marca específica (NULL)
                    Q(marca_vehiculo_seleccionada=marca_vehiculo) | Q(marca_vehiculo_seleccionada__isnull=True)
                ).values_list('mecanico_id', flat=True).distinct()
                
                logger.info(f"🔍 Mecánicos con ofertas directas: {len(mecanicos_con_ofertas)}")
                
                # Opción 2: Filtrar por especialidades (si el servicio pertenece a una categoría que el mecánico tiene)
                # Obtener categorías de los servicios
                categorias_servicios = set()
                for servicio in servicios:
                    categorias_servicios.update(servicio.categorias.values_list('id', flat=True))
                
                logger.info(f"🔍 Categorías de servicios: {categorias_servicios}")
                
                mecanicos_con_especialidades = MecanicoDomicilio.objects.filter(
                    marcas_atendidas=marca_vehiculo,
                    verificado=True,
                    activo=True,
                    especialidades__id__in=categorias_servicios
                ).values_list('id', flat=True).distinct()
                
                logger.info(f"🔍 Mecánicos con especialidades: {len(mecanicos_con_especialidades)}")
                
                # Combinar ambas opciones (OR): mecánicos con ofertas O mecánicos con especialidades
                mecanicos_ids = set(mecanicos_con_ofertas) | set(mecanicos_con_especialidades)
                
                logger.info(f"🔍 Total mecánicos únicos: {len(mecanicos_ids)}")
                
                if not mecanicos_ids:
                    return Response({
                        "mecanicos": [],
                        "mensaje": "No se encontraron mecánicos que atiendan esta marca y ofrezcan los servicios seleccionados"
                    })
                
                queryset = queryset.filter(id__in=mecanicos_ids)
                
            except ValueError:
                return Response(
                    {"error": "Los IDs de servicios deben ser números válidos"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Serializar resultados
        logger.info(f"✅ Mecánicos encontrados: {queryset.count()}")
        serializer = MecanicoDomicilioSerializer(queryset, many=True)
        return Response({
            "mecanicos": serializer.data,
            "total": queryset.count(),
            "filtros_aplicados": {
                "marca_vehiculo": marca_vehiculo.nombre,
                "servicios": servicio_ids if servicio_ids else "todos"
            }
        })


class ZonaCoberturaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo ZonaCobertura
    """
    queryset = ZonaCobertura.objects.all()
    serializer_class = ZonaCoberturaSerializer
    
    def get_permissions(self):
        """
        Solo los administradores pueden manipular las zonas de cobertura
        """
        return [permissions.IsAdminUser()]
    
    @action(detail=False, methods=['get'])
    def por_mecanico(self, request):
        """
        Obtener zonas de cobertura de un mecánico específico
        """
        mecanico_id = request.query_params.get('mecanico_id')
        
        if not mecanico_id:
            return Response(
                {"error": "Se requiere el parámetro mecanico_id"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = ZonaCobertura.objects.filter(mecanico_id=mecanico_id)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ResenaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo Resena
    """
    queryset = Resena.objects.all()
    serializer_class = ResenaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['taller', 'mecanico', 'cliente', 'calificacion']
    search_fields = ['comentario']
    ordering_fields = ['fecha_hora_resena', 'calificacion']
    ordering = ['-fecha_hora_resena']
    pagination_class = PageNumberPagination
    
    def get_permissions(self):
        """
        Permitir GET sin autenticación, pero requerir 
        autenticación para crear, actualizar o eliminar
        """
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        
        # Para create, update, delete
        return [permissions.IsAuthenticated()]
    
    def create(self, request, *args, **kwargs):
        """
        Crear reseña asociada al cliente del usuario autenticado
        """
        try:
            # Verificar que el usuario tenga un perfil de cliente
            try:
                cliente = Cliente.objects.get(usuario=request.user)
            except Cliente.DoesNotExist:
                return Response(
                    {"error": "Debe tener un perfil de cliente para crear reseñas"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Crear reseña
            data = request.data.copy()
            data['cliente'] = cliente.id
            
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def por_taller(self, request):
        """
        Obtener reseñas de un taller específico
        """
        taller_id = request.query_params.get('taller_id')
        
        if not taller_id:
            return Response(
                {"error": "Se requiere el parámetro taller_id"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = Resena.objects.filter(taller_id=taller_id).order_by('-fecha_hora_resena')
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def por_mecanico(self, request):
        """
        Obtener reseñas de un mecánico específico
        """
        mecanico_id = request.query_params.get('mecanico_id')
        
        if not mecanico_id:
            return Response(
                {"error": "Se requiere el parámetro mecanico_id"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = Resena.objects.filter(mecanico_id=mecanico_id).order_by('-fecha_hora_resena')
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def mis_resenas(self, request):
        """
        Obtener reseñas del cliente autenticado
        """
        try:
            cliente = Cliente.objects.get(usuario=request.user)
        except Cliente.DoesNotExist:
            return Response(
                {"error": "No se encontró un perfil de cliente para este usuario"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        queryset = Resena.objects.filter(cliente=cliente).order_by('-fecha_hora_resena')
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class DireccionUsuarioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo DireccionUsuario
    """
    queryset = DireccionUsuario.objects.all()
    serializer_class = DireccionUsuarioSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['usuario', 'etiqueta', 'es_principal']
    search_fields = ['direccion', 'detalles']
    pagination_class = PageNumberPagination
    
    def get_permissions(self):
        """
        Requiere autenticación para todas las operaciones
        """
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        """
        Filtra para mostrar solo direcciones del usuario autenticado
        """
        usuario = self.request.user
        return DireccionUsuario.objects.filter(usuario=usuario)
    
    def perform_create(self, serializer):
        """
        Asigna automáticamente el usuario actual
        """
        print(f"Creando dirección para usuario: {self.request.user.id} - {self.request.user.username}")
        serializer.save(usuario=self.request.user)
    
    def create(self, request, *args, **kwargs):
        """
        Crea una nueva dirección asignando el usuario actual
        """
        try:
            # Añadir usuario al request.data (sin modificar el objeto original)
            data = request.data.copy()
            
            # No añadir el usuario si ya está presente en los datos
            if 'usuario' not in data:
                data['usuario'] = request.user.id
                
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception as e:
            print(f"Error al crear dirección: {str(e)}")
            return Response(
                {"error": f"Error al crear dirección: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def principal(self, request):
        """
        Obtiene la dirección principal del usuario autenticado
        """
        usuario = request.user
        try:
            direccion_principal = DireccionUsuario.objects.filter(
                usuario=usuario,
                es_principal=True
            ).first()
            
            if not direccion_principal:
                # Si no hay dirección principal, obtener la más reciente
                direccion_principal = DireccionUsuario.objects.filter(
                    usuario=usuario
                ).order_by('-fecha_actualizacion').first()
            
            if direccion_principal:
                serializer = self.get_serializer(direccion_principal)
                return Response(serializer.data)
            else:
                # Devolver respuesta exitosa con objeto vacío en lugar de error 404
                return Response(
                    {"mensaje": "No hay direcciones guardadas", "datos": {}},
                    status=status.HTTP_200_OK
                )
                
        except Exception as e:
            return Response(
                {"error": f"Error al obtener la dirección principal: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def establecer_principal(self, request, pk=None):
        """
        Establece una dirección como principal
        """
        try:
            direccion = self.get_object()
            direccion.es_principal = True
            direccion.save()
            
            # La lógica para quitar el flag de otras direcciones está en el modelo
            
            serializer = self.get_serializer(direccion)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {"error": f"Error al establecer la dirección como principal: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class EstadoProveedorView(APIView):
    """
    Vista para obtener el estado de verificación del proveedor autenticado
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """
        Obtener el estado de verificación del proveedor
        """
        usuario = request.user
        
        # Buscar si el usuario tiene un perfil de taller o mecánico usando relaciones directas
        taller = None
        mecanico = None
        
        # Buscar mecánico (relación directa)
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=usuario)
        except MecanicoDomicilio.DoesNotExist:
            pass
        
        # Buscar taller (relación directa - recién agregada)
        try:
            taller = Taller.objects.get(usuario=usuario)
        except Taller.DoesNotExist:
            pass
        
        # Determinar el proveedor principal
        proveedor = mecanico or taller
        
        if not proveedor:
            return Response({
                'error': 'No se encontró perfil de proveedor para este usuario',
                'tiene_perfil': False
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Preparar datos del proveedor
        datos_proveedor = {
            'descripcion': proveedor.descripcion,
            'telefono': proveedor.telefono,
            'calificacion_promedio': proveedor.calificacion_promedio,
            'numero_de_calificaciones': proveedor.numero_de_calificaciones,
        }
        
        # Si es un taller, agregar información de dirección física
        if taller and hasattr(taller, 'direccion_fisica'):
            datos_proveedor['direccion_fisica'] = {
                'direccion_completa': taller.direccion_fisica.direccion_completa,
                'calle': taller.direccion_fisica.calle,
                'numero': taller.direccion_fisica.numero,
                'comuna': taller.direccion_fisica.comuna,
                'ciudad': taller.direccion_fisica.ciudad,
                'region': taller.direccion_fisica.region,
            }
        
        return Response({
            'tiene_perfil': True,
            'tipo_proveedor': 'mecanico' if mecanico else 'taller',
            'nombre': proveedor.nombre,
            'estado_verificacion': proveedor.estado_verificacion,
            'verificado': proveedor.verificado,
            'onboarding_completado': proveedor.onboarding_completado,
            'onboarding_iniciado': proveedor.onboarding_iniciado,
            'fecha_registro': proveedor.fecha_registro,
            'fecha_verificacion': proveedor.fecha_verificacion,
            'activo': proveedor.activo,
            'datos_proveedor': datos_proveedor
        })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def inicializar_onboarding(request):
    """
    Vista para inicializar el proceso de onboarding para un usuario
    """
    usuario = request.user
    tipo_proveedor = request.data.get('tipo_proveedor')  # 'taller' o 'mecanico'
    
    if not tipo_proveedor or tipo_proveedor not in ['taller', 'mecanico']:
        return Response({
            'error': 'Debe especificar tipo_proveedor: "taller" o "mecanico"'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    print(f"🔍 DEBUG inicializar_onboarding:")
    print(f"   Usuario: {usuario.username}")
    print(f"   Tipo proveedor: {tipo_proveedor}")
    print(f"   Datos recibidos: {request.data}")
    
    try:
        if tipo_proveedor == 'taller':
            # Verificar si ya tiene un taller
            if hasattr(usuario, 'taller'):
                taller = usuario.taller
                
                # Actualizar taller con datos del request
                taller.nombre = request.data.get('nombre', taller.nombre)
                taller.telefono = request.data.get('telefono', taller.telefono)
                taller.rut = request.data.get('rut', taller.rut)
                taller.descripcion = request.data.get('descripcion', taller.descripcion)
                taller.onboarding_iniciado = True
                taller.save()
                
                print(f"   ✅ Taller existente actualizado: {taller.nombre}")
                
                return Response({
                    'mensaje': 'Onboarding de taller inicializado',
                    'tipo_proveedor': 'taller'
                })
            else:
                # Crear taller básico con datos del request
                taller = Taller.objects.create(
                    usuario=usuario,
                    nombre=request.data.get('nombre', f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username),
                    telefono=request.data.get('telefono', usuario.telefono or ''),
                    rut=request.data.get('rut', ''),
                    descripcion=request.data.get('descripcion', f"Taller mecánico"),
                    ubicacion=Point(-70.6693, -33.4489),  # Santiago por defecto
                    onboarding_iniciado=True
                )
                
                print(f"   ✅ Taller creado: {taller.nombre}")
                
                return Response({
                    'mensaje': 'Perfil de taller creado y onboarding inicializado',
                    'tipo_proveedor': 'taller'
                })
                
        else:  # mecanico
            # Verificar si ya tiene un mecánico
            if hasattr(usuario, 'mecanico_domicilio'):
                mecanico = usuario.mecanico_domicilio
                
                # Actualizar mecánico con datos del request
                experiencia_raw = request.data.get('experiencia_anos', mecanico.experiencia_anos)
                mecanico.nombre = request.data.get('nombre', mecanico.nombre)
                mecanico.telefono = request.data.get('telefono', mecanico.telefono)
                mecanico.dni = request.data.get('dni', mecanico.dni)
                mecanico.experiencia_anos = experiencia_raw if isinstance(experiencia_raw, int) else (int(experiencia_raw) if experiencia_raw and str(experiencia_raw).strip() else mecanico.experiencia_anos)
                mecanico.descripcion = request.data.get('descripcion', mecanico.descripcion)
                mecanico.onboarding_iniciado = True
                mecanico.save()
                
                print(f"   ✅ Mecánico existente actualizado: {mecanico.nombre}")
                
                return Response({
                    'mensaje': 'Onboarding de mecánico inicializado',
                    'tipo_proveedor': 'mecanico'
                })
            else:
                # Crear mecánico básico con datos del request
                experiencia_raw = request.data.get('experiencia_anos', 0)
                experiencia_final = experiencia_raw if isinstance(experiencia_raw, int) else (int(experiencia_raw) if experiencia_raw and str(experiencia_raw).strip() else 0)
                mecanico = MecanicoDomicilio.objects.create(
                    usuario=usuario,
                    nombre=request.data.get('nombre', f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username),
                    telefono=request.data.get('telefono', usuario.telefono or ''),
                    dni=request.data.get('dni', ''),
                    experiencia_anos=experiencia_final,
                    descripcion=request.data.get('descripcion', f"Mecánico a domicilio"),
                    ubicacion=Point(-70.6693, -33.4489),  # Santiago por defecto
                    onboarding_iniciado=True
                )
                
                print(f"   ✅ Mecánico creado: {mecanico.nombre}")
                
                return Response({
                    'mensaje': 'Perfil de mecánico creado y onboarding inicializado',
                    'tipo_proveedor': 'mecanico'
                })
                
    except Exception as e:
        error_message = str(e)
        print(f"   ❌ Error en inicializar_onboarding: {str(e)}")
        logger.error(f"Error al inicializar onboarding: {str(e)}", exc_info=True)
        # Si es un error de integridad, proporcionar mensaje más claro
        if 'unique constraint' in error_message.lower() or 'duplicate key' in error_message.lower() or isinstance(e, IntegrityError):
            if 'taller' in error_message.lower() or tipo_proveedor == 'taller':
                return Response({
                    'error': 'Ya existe un taller asociado a este usuario',
                    'codigo': 'TALLER_DUPLICADO'
                }, status=status.HTTP_400_BAD_REQUEST)
            elif 'mecanico' in error_message.lower() or 'mecánico' in error_message.lower() or tipo_proveedor == 'mecanico':
                return Response({
                    'error': 'Ya existe un mecánico asociado a este usuario',
                    'codigo': 'MECANICO_DUPLICADO'
                }, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'error': f'Error al inicializar onboarding: {error_message}',
            'details': str(e) if str(e) != error_message else None
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cancelar_onboarding(request):
    """
    Vista para cancelar el onboarding (no borra el perfil, solo marca como no iniciado)
    """
    usuario = request.user
    
    # Buscar taller o mecánico
    proveedor = None
    tipo_proveedor = None
    
    if hasattr(usuario, 'taller'):
        proveedor = usuario.taller
        tipo_proveedor = 'taller'
    elif hasattr(usuario, 'mecanico_domicilio'):
        proveedor = usuario.mecanico_domicilio
        tipo_proveedor = 'mecanico'
    
    if not proveedor:
        return Response({
            'error': 'No se encontró perfil de proveedor para cancelar'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # Solo permitir cancelar si no está completado
    if proveedor.onboarding_completado:
        return Response({
            'error': 'No se puede cancelar un onboarding ya completado'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # "Cancelar" marcando como no iniciado (esto hará que aparezca de nuevo)
    proveedor.onboarding_iniciado = False
    proveedor.save(update_fields=['onboarding_iniciado'])
    
    return Response({
        'mensaje': f'Onboarding de {tipo_proveedor} cancelado. Aparecerá nuevamente en el próximo login.',
        'tipo_proveedor': tipo_proveedor
    })


class DocumentoOnboardingViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo DocumentoOnboarding
    """
    queryset = DocumentoOnboarding.objects.all()
    serializer_class = DocumentoOnboardingSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['tipo_documento', 'verificado', 'taller', 'mecanico']
    search_fields = ['nombre_original', 'comentarios_verificacion']
    ordering = ['-fecha_subida']
    
    def get_queryset(self):
        """
        Filtrar documentos según el usuario autenticado
        """
        user = self.request.user
        queryset = DocumentoOnboarding.objects.all()
        
        # Solo mostrar documentos del proveedor actual
        if hasattr(user, 'taller'):
            queryset = queryset.filter(taller=user.taller)
        elif hasattr(user, 'mecanico_domicilio'):
            queryset = queryset.filter(mecanico=user.mecanico_domicilio)
        else:
            # Si no es proveedor, no mostrar documentos
            queryset = queryset.none()
        
        return queryset
    
    def get_permissions(self):
        """
        Permisos específicos según la acción
        """
        if self.action in ['list', 'retrieve', 'create', 'update', 'partial_update', 'destroy']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAuthenticated]
        return [permission() for permission in permission_classes]
    
    def perform_create(self, serializer):
        """
        Establecer automáticamente el proveedor según el usuario autenticado
        """
        user = self.request.user
        
        # Determinar el proveedor automáticamente
        if hasattr(user, 'taller'):
            serializer.save(taller=user.taller, mecanico=None)
        elif hasattr(user, 'mecanico_domicilio'):
            serializer.save(mecanico=user.mecanico_domicilio, taller=None)
        else:
            raise ValidationError("El usuario debe tener un perfil de taller o mecánico para subir documentos.")
    
    def create(self, request, *args, **kwargs):
        """
        Crear nuevo documento con validaciones específicas
        """
        try:
            # Validar que el usuario tenga un perfil de proveedor
            user = request.user
            
            # Refrescar el usuario desde la base de datos para obtener relaciones actualizadas
            user.refresh_from_db()
            
            proveedor = None
            tipo_proveedor = None
            
            if hasattr(user, 'taller'):
                proveedor = user.taller
                tipo_proveedor = 'taller'
            elif hasattr(user, 'mecanico_domicilio'):
                proveedor = user.mecanico_domicilio
                tipo_proveedor = 'mecanico'
            
            if not proveedor:
                # Intentar obtener el proveedor directamente por FK si hasattr no funciona
                try:
                    from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
                    
                    # Buscar taller
                    taller = Taller.objects.filter(usuario=user).first()
                    if taller:
                        proveedor = taller
                        tipo_proveedor = 'taller'
                    else:
                        # Buscar mecánico
                        mecanico = MecanicoDomicilio.objects.filter(usuario=user).first()
                        if mecanico:
                            proveedor = mecanico
                            tipo_proveedor = 'mecanico'
                except Exception as e:
                    logger.error(f"Error buscando proveedor: {str(e)}")
            
            if not proveedor:
                return Response({
                    'error': 'Debe tener un perfil de taller o mecánico para subir documentos',
                    'debug_info': {
                        'user_id': user.id,
                        'tiene_taller': hasattr(user, 'taller'),
                        'tiene_mecanico': hasattr(user, 'mecanico_domicilio'),
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validar que el archivo esté presente
            if 'archivo' not in request.data:
                return Response({
                    'error': 'Debe proporcionar un archivo'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Extraer nombre original del archivo
            archivo = request.data['archivo']
            nombre_original = getattr(archivo, 'name', 'archivo_sin_nombre')
            
            # Crear el serializer con los datos
            serializer_data = request.data.copy()
            serializer_data['nombre_original'] = nombre_original
            
            # Incluir el proveedor en los datos para que pase la validación del serializer
            if tipo_proveedor == 'taller':
                serializer_data['taller'] = proveedor.id
                serializer_data['mecanico'] = None
            else:
                serializer_data['mecanico'] = proveedor.id
                serializer_data['taller'] = None
            
            serializer = self.get_serializer(data=serializer_data)
            serializer.is_valid(raise_exception=True)
            
            # Guardar con el proveedor correspondiente (ya están en los datos)
            serializer.save()
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except ValidationError as e:
            return Response({
                'error': 'Datos de documento inválidos',
                'details': e.detail
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error subiendo documento: {str(e)}")
            return Response({
                'error': 'Error interno del servidor al subir documento',
                'details': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def mis_documentos(self, request):
        """
        Obtener todos los documentos del proveedor autenticado
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def tipos_documento(self, request):
        """
        Obtener los tipos de documento disponibles según el tipo de proveedor
        """
        user = request.user
        
        # Tipos básicos para ambos
        tipos_basicos = [
            ('dni_frontal', 'DNI/ID Personal (Frontal)'),
            ('dni_trasero', 'DNI/ID Personal (Trasero)'),
            ('licencia_conducir', 'Licencia de Conducir'),
        ]
        
        # Tipos específicos según el proveedor
        if hasattr(user, 'taller'):
            tipos_especificos = [
                ('rut_fiscal', 'RUT/CUIT/ID Fiscal del Negocio'),
                ('foto_fachada', 'Foto de la Fachada del Taller'),
                ('foto_interior', 'Foto del Interior del Taller'),
                ('foto_equipos', 'Foto de Equipos/Herramientas'),
            ]
        elif hasattr(user, 'mecanico_domicilio'):
            tipos_especificos = [
                ('foto_herramientas', 'Foto de Herramientas Portátiles'),
                ('foto_vehiculo', 'Foto de Vehículo de Trabajo'),
            ]
        else:
            tipos_especificos = []
        
        todos_los_tipos = tipos_basicos + tipos_especificos
        
        return Response({
            'tipos_documento': [{'key': key, 'label': label} for key, label in todos_los_tipos]
        })
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def proveedor_documentos(self, request):
        """
        Obtener documentos públicos (verificados) de un proveedor
        Query params: provider_id, provider_type (taller|mecanico)
        """
        provider_id = request.query_params.get('provider_id')
        provider_type = request.query_params.get('provider_type')
        
        if not provider_id or not provider_type:
            return Response({
                'error': 'Se requieren los parámetros provider_id y provider_type'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            provider_id = int(provider_id)
        except ValueError:
            return Response({
                'error': 'provider_id debe ser un número válido'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if provider_type not in ['taller', 'mecanico']:
            return Response({
                'error': 'provider_type debe ser "taller" o "mecanico"'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Filtrar documentos por proveedor y solo mostrar verificados
        queryset = DocumentoOnboarding.objects.filter(verificado=True)
        
        if provider_type == 'taller':
            queryset = queryset.filter(taller_id=provider_id)
        else:
            queryset = queryset.filter(mecanico_id=provider_id)
        
        # Filtrar solo documentos legales relevantes para mostrar al público
        tipos_documentos_publicos = [
            'curriculum',
            'certificado_antecedentes',
            'rut_fiscal',  # RUT fiscal como certificado de antecedentes del negocio
            'licencia_conducir'
        ]
        queryset = queryset.filter(tipo_documento__in=tipos_documentos_publicos)
        
        # Serializar solo los campos necesarios
        documentos_data = []
        for documento in queryset:
            request_context = {'request': request}
            archivo_url = None
            if documento.archivo:
                archivo_url = request.build_absolute_uri(documento.archivo.url)
            
            documentos_data.append({
                'id': documento.id,
                'tipo_documento': documento.tipo_documento,
                'tipo_documento_display': documento.get_tipo_documento_display(),
                'archivo_url': archivo_url,
                'nombre_original': documento.nombre_original
            })
        
        return Response(documentos_data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def actualizar_especialidades(request):
    """
    Vista para actualizar las especialidades de un mecánico a domicilio o taller
    """
    usuario = request.user
    especialidades_ids = request.data.get('especialidades', [])
    
    print(f"🔍 DEBUG actualizar_especialidades:")
    print(f"   Usuario: {usuario.username}")
    print(f"   Especialidades IDs recibidos: {especialidades_ids}")
    print(f"   Tipo de especialidades_ids: {type(especialidades_ids)}")
    
    # Buscar el proveedor (mecánico o taller)
    proveedor = None
    tipo_proveedor = None
    
    if hasattr(usuario, 'mecanico_domicilio'):
        proveedor = usuario.mecanico_domicilio
        tipo_proveedor = 'mecanico'
        print(f"   ✅ Proveedor encontrado: Mecánico {proveedor.nombre}")
    elif hasattr(usuario, 'taller'):
        proveedor = usuario.taller
        tipo_proveedor = 'taller'
        print(f"   ✅ Proveedor encontrado: Taller {proveedor.nombre}")
    else:
        print(f"   ❌ No se encontró proveedor para usuario {usuario.username}")
        print(f"   Atributos del usuario: {dir(usuario)}")
    
    if not proveedor:
        return Response({
            'error': 'Debes tener un perfil de mecánico o taller para actualizar especialidades'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Validar que las especialidades existen
        print(f"   🔍 Buscando especialidades en CategoriaServicio...")
        especialidades = CategoriaServicio.objects.filter(id__in=especialidades_ids)
        especialidades_encontradas = list(especialidades.values_list('id', flat=True))
        
        print(f"   📋 Especialidades encontradas: {especialidades_encontradas}")
        print(f"   📋 Especialidades solicitadas: {especialidades_ids}")
        print(f"   📋 Cantidad encontrada: {len(especialidades)} vs solicitada: {len(especialidades_ids)}")
        
        if len(especialidades) != len(especialidades_ids):
            especialidades_faltantes = set(especialidades_ids) - set(especialidades_encontradas)
            print(f"   ❌ Especialidades faltantes: {especialidades_faltantes}")
            return Response({
                'error': 'Algunas especialidades no existen',
                'especialidades_faltantes': list(especialidades_faltantes),
                'especialidades_encontradas': especialidades_encontradas
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Actualizar las especialidades
        print(f"   ✅ Actualizando especialidades para {tipo_proveedor} {proveedor.nombre}")
        proveedor.especialidades.set(especialidades)
        
        # Serializar las especialidades actualizadas
        especialidades_data = [
            {'id': esp.id, 'nombre': esp.nombre, 'descripcion': esp.descripcion}
            for esp in especialidades
        ]
        
        print(f"   🎉 Especialidades actualizadas exitosamente: {len(especialidades_data)} items")
        
        return Response({
            'mensaje': f'Especialidades de {tipo_proveedor} actualizadas exitosamente',
            'especialidades': especialidades_data
        })
        
    except Exception as e:
        print(f"   ❌ Error en actualizar_especialidades: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response({
            'error': f'Error al actualizar especialidades: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def actualizar_marcas_taller(request):
    """
    Vista para actualizar las marcas atendidas de un taller
    """
    usuario = request.user
    marcas_ids = request.data.get('marcas', [])
    
    # Verificar que el usuario tiene un perfil de taller
    if not hasattr(usuario, 'taller'):
        return Response({
            'error': 'Solo los talleres pueden actualizar marcas atendidas'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    taller = usuario.taller
    
    try:
        # Importar el modelo dinámicamente para evitar circular import
        from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo
        
        # Validar que las marcas existen
        marcas = MarcaVehiculo.objects.filter(id__in=marcas_ids)
        
        if len(marcas) != len(marcas_ids):
            return Response({
                'error': 'Algunas marcas no existen'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Actualizar las marcas atendidas
        taller.marcas_atendidas.set(marcas)
        
        # Serializar las marcas actualizadas
        marcas_data = [
            {'id': marca.id, 'nombre': marca.nombre}
            for marca in marcas
        ]
        
        return Response({
            'mensaje': 'Marcas del taller actualizadas exitosamente',
            'marcas': marcas_data
        })
        
    except Exception as e:
        return Response({
            'error': f'Error al actualizar marcas del taller: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def actualizar_marcas_mecanico(request):
    """
    Vista para actualizar las marcas atendidas de un mecánico a domicilio
    """
    usuario = request.user
    marcas_ids = request.data.get('marcas', [])
    
    # Verificar que el usuario tiene un perfil de mecánico
    if not hasattr(usuario, 'mecanico_domicilio'):
        return Response({
            'error': 'Solo los mecánicos a domicilio pueden actualizar marcas atendidas'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    mecanico = usuario.mecanico_domicilio
    
    try:
        # Importar el modelo dinámicamente para evitar circular import
        from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo
        
        # Validar que las marcas existen
        marcas = MarcaVehiculo.objects.filter(id__in=marcas_ids)
        
        if len(marcas) != len(marcas_ids):
            return Response({
                'error': 'Algunas marcas no existen'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Actualizar las marcas atendidas
        mecanico.marcas_atendidas.set(marcas)
        
        # Serializar las marcas actualizadas
        marcas_data = [
            {'id': marca.id, 'nombre': marca.nombre}
            for marca in marcas
        ]
        
        return Response({
            'mensaje': 'Marcas del mecánico actualizadas exitosamente',
            'marcas': marcas_data
        })
        
    except Exception as e:
        return Response({
            'error': f'Error al actualizar marcas del mecánico: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def completar_onboarding(request):
    """
    Vista para marcar el onboarding como completado.
    Los proveedores quedarán en estado 'pendiente' para revisión manual por administradores.
    """
    usuario = request.user
    
    # Buscar el proveedor (taller o mecánico)
    proveedor = None
    tipo_proveedor = None
    
    if hasattr(usuario, 'taller'):
        proveedor = usuario.taller
        tipo_proveedor = 'taller'
    elif hasattr(usuario, 'mecanico_domicilio'):
        proveedor = usuario.mecanico_domicilio
        tipo_proveedor = 'mecanico'
    
    if not proveedor:
        return Response({
            'error': 'No se encontró perfil de proveedor'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # Validar que tenga los datos mínimos requeridos
    errores = []
    
    if not proveedor.nombre:
        errores.append('Nombre es requerido')
    
    if not proveedor.telefono:
        errores.append('Teléfono es requerido')
    
    if not proveedor.descripcion:
        errores.append('Descripción es requerida')
    
    if tipo_proveedor == 'taller':
        if not proveedor.rut:
            errores.append('RUT es requerido para talleres')
    
    if tipo_proveedor == 'mecanico':
        if not proveedor.dni:
            errores.append('DNI es requerido para mecánicos')
        experiencia_anos = getattr(proveedor, 'experiencia_anos', None)
        if not experiencia_anos and experiencia_anos != 0:
            errores.append('Años de experiencia son requeridos para mecánicos')
    
    # Validar que tenga al menos un documento básico (OPCIONAL)
    documentos_count = DocumentoOnboarding.objects.filter(
        **{tipo_proveedor: proveedor}
    ).count()
    
    # Los documentos son opcionales, solo mostrar advertencia si no hay
    if documentos_count == 0:
        print(f"Advertencia: {tipo_proveedor} {proveedor.nombre} completó onboarding sin documentos")
    
    if errores:
        return Response({
            'error': 'Faltan datos requeridos para completar el onboarding',
            'errores': errores
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Marcar onboarding como completado
        proveedor.onboarding_completado = True
        proveedor.onboarding_iniciado = True  # Asegurar que esté marcado como iniciado
        
        # IMPORTANTE: NO verificar automáticamente
        # Los proveedores deben ser revisados manualmente por administradores
        print(f"📋 {tipo_proveedor} {proveedor.nombre} completó onboarding - quedará pendiente de revisión manual")
        
        # 🎯 NUEVO: Crear ofertas automáticas basadas en especialidades
        ofertas_creadas = 0
        try:
            if proveedor.especialidades.count() > 0:
                print(f"🔧 Creando ofertas automáticas para {proveedor.nombre}...")
                ofertas_creadas = crear_ofertas_automaticas(proveedor, tipo_proveedor)
                print(f"✅ {ofertas_creadas} ofertas automáticas creadas para {proveedor.nombre}")
            else:
                print(f"⚠️ {proveedor.nombre} no tiene especialidades - sin ofertas automáticas")
        except Exception as e:
            # No fallar el onboarding si hay error creando ofertas automáticas
            logger.warning(f"⚠️ Error creando ofertas automáticas para {proveedor.nombre}: {str(e)}")
            print(f"⚠️ Error creando ofertas automáticas (no crítico): {str(e)}")
        
        # Verificar datos para mensaje informativo al usuario
        puede_verificar_automaticamente = True
        razon_advertencia = ""
        
        # Verificar especialidades
        especialidades_count = proveedor.especialidades.count()
        if especialidades_count == 0:
            puede_verificar_automaticamente = False
            razon_advertencia = "Sin especialidades definidas"
        
        # Verificar marcas atendidas
        marcas_count = proveedor.marcas_atendidas.count()
        if marcas_count == 0:
            puede_verificar_automaticamente = False
            razon_advertencia = "Sin marcas de vehículos atendidas"
        
        # Verificar documentos
        documentos_count = DocumentoOnboarding.objects.filter(
            **{tipo_proveedor: proveedor}
        ).count()
        if documentos_count == 0:
            puede_verificar_automaticamente = False
            razon_advertencia = "Sin documentos subidos"
        
        # Preparar mensaje para el usuario
        if puede_verificar_automaticamente:
            mensaje_verificacion = f"Tu registro está completo y será revisado por nuestro equipo. Te notificaremos cuando esté aprobado para recibir órdenes de servicio."
        else:
            mensaje_verificacion = f"Tu registro ha sido recibido pero requiere completar información faltante: {razon_advertencia}. Te notificaremos sobre el estado de tu verificación."
        
        proveedor.save(update_fields=['onboarding_completado', 'onboarding_iniciado'])
        
        return Response({
            'mensaje': f'Onboarding de {tipo_proveedor} completado exitosamente',
            'tipo_proveedor': tipo_proveedor,
            'onboarding_completado': True,
            'estado_verificacion': proveedor.estado_verificacion,  # Debería seguir siendo 'pendiente'
            'verificado': proveedor.verificado,  # Debería seguir siendo False
            'mensaje_verificacion': mensaje_verificacion,
            'requiere_revision_manual': True,
            'datos_completos': puede_verificar_automaticamente
        })
        
    except Exception as e:
        logger.error(f"❌ Error al completar onboarding: {str(e)}", exc_info=True)
        error_message = str(e)
        # Proporcionar mensajes de error más específicos
        if 'IntegrityError' in str(type(e)) or isinstance(e, IntegrityError):
            error_message = 'Error de integridad en la base de datos. Por favor, verifica los datos.'
        elif 'ValidationError' in str(type(e)) or isinstance(e, ValidationError):
            error_message = f'Error de validación: {str(e)}'
        return Response({
            'error': f'Error al completar onboarding: {error_message}',
            'details': str(e) if str(e) != error_message else None
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HorarioProveedorViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo HorarioProveedor - Gestión unificada de horarios
    """
    queryset = HorarioProveedor.objects.all()
    serializer_class = HorarioProveedorSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['dia_semana', 'activo', 'taller', 'mecanico']
    ordering_fields = ['dia_semana']
    ordering = ['dia_semana']
    
    def get_queryset(self):
        """
        Filtrar horarios según el usuario autenticado
        """
        user = self.request.user
        queryset = HorarioProveedor.objects.all()
        
        # Solo mostrar horarios del proveedor actual
        if hasattr(user, 'taller'):
            queryset = queryset.filter(taller=user.taller)
        elif hasattr(user, 'mecanico_domicilio'):
            queryset = queryset.filter(mecanico=user.mecanico_domicilio)
        else:
            # Si no es proveedor, no mostrar horarios
            queryset = queryset.none()
        
        return queryset
    
    def perform_create(self, serializer):
        """
        Establecer automáticamente el proveedor según el usuario autenticado
        """
        user = self.request.user
        
        # Determinar el proveedor automáticamente
        if hasattr(user, 'taller'):
            serializer.save(taller=user.taller, mecanico=None)
        elif hasattr(user, 'mecanico_domicilio'):
            serializer.save(mecanico=user.mecanico_domicilio, taller=None)
        else:
            raise ValidationError("El usuario debe tener un perfil de taller o mecánico para configurar horarios.")
    
    @action(detail=False, methods=['get'])
    def mis_horarios(self, request):
        """
        Obtener todos los horarios configurados del proveedor autenticado
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def configurar_semana_completa(self, request):
        """
        Configurar los horarios para toda la semana de una vez
        Acepta configuración global o configuración específica por día
        """
        user = request.user
        
        # Validar que el usuario tenga un perfil de proveedor
        proveedor = None
        if hasattr(user, 'taller'):
            proveedor = user.taller
            tipo_proveedor = 'taller'
        elif hasattr(user, 'mecanico_domicilio'):
            proveedor = user.mecanico_domicilio
            tipo_proveedor = 'mecanico'
        else:
            return Response({
                'error': 'Debe tener un perfil de taller o mecánico para configurar horarios'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validar datos con el serializer
        serializer = ConfigurarSemanaCompletaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        
        # Eliminar configuraciones existentes si se solicita
        if data.get('eliminar_existente', True):
            HorarioProveedor.objects.filter(**{tipo_proveedor: proveedor}).delete()
        
        # Crear nuevas configuraciones
        horarios_creados = []
        configuracion_por_dia = data.get('configuracion_por_dia', {})
        
        for dia in range(7):  # 0 = Lunes, 6 = Domingo
            activo = dia in data['dias_habilitados']
            
            # Usar configuración específica del día si existe, sino usar global
            if str(dia) in configuracion_por_dia:
                config_dia = configuracion_por_dia[str(dia)]
                hora_inicio = config_dia['hora_inicio']
                hora_fin = config_dia['hora_fin']
                duracion_slot = config_dia.get('duracion_slot', data['duracion_slot_global'])
                tiempo_descanso = config_dia.get('tiempo_descanso', data['tiempo_descanso_global'])
            else:
                hora_inicio = data['hora_inicio_global'].strftime('%H:%M')
                hora_fin = data['hora_fin_global'].strftime('%H:%M')
                duracion_slot = data['duracion_slot_global']
                tiempo_descanso = data['tiempo_descanso_global']
            
            horario_data = {
                tipo_proveedor: proveedor,
                'dia_semana': dia,
                'activo': activo,
                'hora_inicio': hora_inicio,
                'hora_fin': hora_fin,
                'duracion_slot': duracion_slot,
                'tiempo_descanso': tiempo_descanso
            }
            
            horario = HorarioProveedor.objects.create(**horario_data)
            horarios_creados.append(horario)
        
        # Serializar y devolver
        horarios_serializer = self.get_serializer(horarios_creados, many=True)
        
        return Response({
            'mensaje': f'Horarios configurados exitosamente para {tipo_proveedor}: {proveedor.nombre}',
            'tipo_proveedor': tipo_proveedor,
            'total_dias_configurados': len(horarios_creados),
            'dias_activos': len([h for h in horarios_creados if h.activo]),
            'horarios': horarios_serializer.data
        })
    
    @action(detail=False, methods=['post'])
    def configuracion_rapida(self, request):
        """
        Configuración rápida usando presets predefinidos
        """
        user = request.user
        
        # Validar que el usuario tenga un perfil de proveedor
        proveedor = None
        if hasattr(user, 'taller'):
            proveedor = user.taller
            tipo_proveedor = 'taller'
        elif hasattr(user, 'mecanico_domicilio'):
            proveedor = user.mecanico_domicilio
            tipo_proveedor = 'mecanico'
        else:
            return Response({
                'error': 'Debe tener un perfil de taller o mecánico para configurar horarios'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validar datos con el serializer
        serializer = ConfigurarHorarioRapidoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Obtener configuración del preset
        config = serializer.get_configuracion()
        
        # Eliminar configuraciones existentes
        HorarioProveedor.objects.filter(**{tipo_proveedor: proveedor}).delete()
        
        # Crear nuevas configuraciones
        horarios_creados = []
        for dia in range(7):
            activo = dia in config['dias_habilitados']
            
            horario_data = {
                tipo_proveedor: proveedor,
                'dia_semana': dia,
                'activo': activo,
                'hora_inicio': config['hora_inicio'],
                'hora_fin': config['hora_fin'],
                'duracion_slot': config['duracion_slot'],
                'tiempo_descanso': config['tiempo_descanso']
            }
            
            horario = HorarioProveedor.objects.create(**horario_data)
            horarios_creados.append(horario)
        
        # Serializar y devolver
        horarios_serializer = self.get_serializer(horarios_creados, many=True)
        
        return Response({
            'mensaje': f'Configuración rápida aplicada para {tipo_proveedor}: {proveedor.nombre}',
            'preset_utilizado': serializer.validated_data['preset'],
            'configuracion_aplicada': config,
            'tipo_proveedor': tipo_proveedor,
            'total_dias_configurados': len(horarios_creados),
            'dias_activos': len([h for h in horarios_creados if h.activo]),
            'horarios': horarios_serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def presets_disponibles(self, request):
        """
        Obtener lista de presets de configuración disponibles
        """
        presets = []
        for valor, descripcion in ConfigurarHorarioRapidoSerializer.PRESETS_CHOICES:
            presets.append({
                'valor': valor,
                'descripcion': descripcion
            })
        
        return Response({
            'presets': presets,
            'descripcion': 'Presets de configuración rápida disponibles'
        })


def crear_ofertas_automaticas(proveedor, tipo_proveedor):
    """
    Crear automáticamente ofertas de servicios basadas en las especialidades del proveedor
    """
    from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
    from decimal import Decimal
    
    especialidades = proveedor.especialidades.all()
    
    if not especialidades:
        print(f"⚠️ {proveedor.nombre} no tiene especialidades definidas - sin ofertas automáticas")
        return 0
    
    print(f"🔧 Creando ofertas automáticas para {proveedor.nombre} con {len(especialidades)} especialidades")
    
    # Precios por defecto por tipo de servicio
    precios_defecto = {
        'Mantenimiento preventivo': {'sin_repuestos': 15000, 'con_repuestos': 25000},
        'Afinaciones': {'sin_repuestos': 25000, 'con_repuestos': 45000},
        'Aire acondicionado': {'sin_repuestos': 20000, 'con_repuestos': 35000},
        'Frenos': {'sin_repuestos': 18000, 'con_repuestos': 40000},
        'Suspensión': {'sin_repuestos': 20000, 'con_repuestos': 50000},
        'Electricidad automotriz': {'sin_repuestos': 22000, 'con_repuestos': 40000},
        'Motor': {'sin_repuestos': 30000, 'con_repuestos': 80000},
        'Transmisión': {'sin_repuestos': 25000, 'con_repuestos': 70000},
        'Diagnóstico general': {'sin_repuestos': 12000, 'con_repuestos': 12000},
        'Alineación y balanceo': {'sin_repuestos': 15000, 'con_repuestos': 18000},
        'Neumáticos': {'sin_repuestos': 8000, 'con_repuestos': 50000},
        'Escape': {'sin_repuestos': 12000, 'con_repuestos': 35000},
        'Carrocería': {'sin_repuestos': 25000, 'con_repuestos': 60000},
        'Pintura': {'sin_repuestos': 40000, 'con_repuestos': 80000},
        'Vidrios': {'sin_repuestos': 15000, 'con_repuestos': 45000},
        'Tapicería': {'sin_repuestos': 18000, 'con_repuestos': 35000},
        'Servicios generales': {'sin_repuestos': 15000, 'con_repuestos': 25000},
    }
    
    ofertas_creadas = 0
    
    for especialidad in especialidades:
        # Buscar servicios que pertenezcan a esta especialidad (categoría)
        servicios = Servicio.objects.filter(categorias=especialidad)
        
        print(f"   📋 Especialidad: {especialidad.nombre} - {len(servicios)} servicios disponibles")
        
        for servicio in servicios:
            # Verificar si ya existe una oferta para este servicio
            filtro_existente = {
                'servicio': servicio,
                tipo_proveedor: proveedor
            }
            
            if OfertaServicio.objects.filter(**filtro_existente).exists():
                print(f"   ⚠️ Oferta ya existe para {servicio.nombre} - omitiendo")
                continue
            
            # Obtener precios por defecto
            precio_info = precios_defecto.get(especialidad.nombre, precios_defecto['Servicios generales'])
            
            # Crear la oferta
            oferta_data = {
                'tipo_proveedor': tipo_proveedor,
                'servicio': servicio,
                'disponible': True,
                'precio_sin_repuestos': Decimal(str(precio_info['sin_repuestos'])),
                'precio_con_repuestos': Decimal(str(precio_info['con_repuestos'])),
                'incluye_garantia': True,
                'duracion_garantia': 30,
                'detalles_adicionales': f'Oferta creada automáticamente durante el onboarding de {proveedor.nombre}'
            }
            
            # Asignar el proveedor específico
            oferta_data[tipo_proveedor] = proveedor
            
            try:
                oferta = OfertaServicio.objects.create(**oferta_data)
                print(f"   ✅ Oferta creada: {servicio.nombre} - ${precio_info['sin_repuestos']}")
                ofertas_creadas += 1
                
            except Exception as e:
                print(f"   ❌ Error creando oferta para {servicio.nombre}: {str(e)}")
    
    print(f"🎉 {ofertas_creadas} ofertas automáticas creadas para {proveedor.nombre}")
    return ofertas_creadas


# NUEVO: ViewSet para Comunas Chilenas (Maestro)
class ChileanCommuneViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo lectura para las comunas chilenas
    Proporciona el listado maestro de comunas para selección
    """
    queryset = ChileanCommune.objects.filter(is_active=True).order_by('region_code', 'name')
    serializer_class = ChileanCommuneSerializer
    permission_classes = [permissions.AllowAny]  # Público para todos
    pagination_class = None  # Sin paginación para una respuesta completa
    
    @method_decorator(cache_page(60*60*24*7)) # Cache por 7 días
    def list(self, request, *args, **kwargs):
        """
        Sobrescribimos list para cachear los resultados por 7 días
        """
        return super().list(request, *args, **kwargs)
    
    def get_queryset(self):
        """Filtrar comunas por región si se especifica"""
        queryset = super().get_queryset()
        region_code = self.request.query_params.get('region', None)
        
        if region_code:
            queryset = queryset.filter(region_code=region_code)
        
        # Búsqueda por nombre
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(name__icontains=search)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def regions(self, request):
        """Endpoint para obtener la lista de regiones disponibles"""
        regions = ChileanCommune.objects.filter(is_active=True).values(
            'region_code', 'region_name'
        ).distinct().order_by('region_code')
        
        return Response(list(regions))


# NUEVO: ViewSet para Zonas de Servicio de Mecánicos
class MechanicServiceAreaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar las zonas de servicio de mecánicos a domicilio
    Solo el mecánico autenticado puede gestionar sus propias zonas
    """
    serializer_class = MechanicServiceAreaSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Retornar solo las zonas del mecánico autenticado"""
        try:
            mechanic = MecanicoDomicilio.objects.get(usuario=self.request.user)
            return MechanicServiceArea.objects.filter(
                mechanic=mechanic
            ).order_by('-created_at')
        except MecanicoDomicilio.DoesNotExist:
            return MechanicServiceArea.objects.none()
    
    def get_serializer_class(self):
        """Usar serializers específicos según la acción"""
        if self.action == 'create':
            return MechanicServiceAreaCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return MechanicServiceAreaUpdateSerializer
        return MechanicServiceAreaSerializer
    
    def get_serializer_context(self):
        """Agregar contexto adicional al serializer"""
        context = super().get_serializer_context()
        # Permitir validación de comunas por defecto, pero permitir omitirla en desarrollo
        context['validate_communes'] = self.request.query_params.get('validate_communes', 'true').lower() == 'true'
        return context
    
    def perform_create(self, serializer):
        """Personalizar la creación"""
        try:
            mechanic = MecanicoDomicilio.objects.get(usuario=self.request.user)
            serializer.save(mechanic=mechanic)
        except MecanicoDomicilio.DoesNotExist:
            raise ValidationError("Usuario no es un mecánico a domicilio.")
    
    def perform_update(self, serializer):
        """Personalizar la actualización"""
        instance = self.get_object()
        try:
            mechanic = MecanicoDomicilio.objects.get(usuario=self.request.user)
            if instance.mechanic != mechanic:
                raise PermissionDenied("No tiene permisos para modificar esta zona.")
            serializer.save()
        except MecanicoDomicilio.DoesNotExist:
            raise ValidationError("Usuario no es un mecánico a domicilio.")
    
    def perform_destroy(self, instance):
        """Personalizar la eliminación"""
        try:
            mechanic = MecanicoDomicilio.objects.get(usuario=self.request.user)
            if instance.mechanic != mechanic:
                raise PermissionDenied("No tiene permisos para eliminar esta zona.")
            instance.delete()
        except MecanicoDomicilio.DoesNotExist:
            raise ValidationError("Usuario no es un mecánico a domicilio.")
    
    @action(detail=True, methods=['patch'])
    def toggle_active(self, request, pk=None):
        """Activar/desactivar una zona de servicio"""
        instance = self.get_object()
        
        try:
            mechanic = MecanicoDomicilio.objects.get(usuario=request.user)
            if instance.mechanic != mechanic:
                return Response({
                    'error': 'No tiene permisos para modificar esta zona.'
                }, status=status.HTTP_403_FORBIDDEN)
        except MecanicoDomicilio.DoesNotExist:
            return Response({
                'error': 'Usuario no es un mecánico a domicilio.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Cambiar estado
        instance.is_active = not instance.is_active
        instance.save()
        
        serializer = self.get_serializer(instance)
        
        return Response({
            'message': f'Zona {"activada" if instance.is_active else "desactivada"} exitosamente.',
            'zona': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Estadísticas de las zonas del mecánico"""
        try:
            mechanic = MecanicoDomicilio.objects.get(usuario=request.user)
            queryset = self.get_queryset()
            
            total_zones = queryset.count()
            active_zones = queryset.filter(is_active=True).count()
            total_communes = sum(
                zone.get_commune_count() for zone in queryset.filter(is_active=True)
            )
            
            return Response({
                'total_zones': total_zones,
                'active_zones': active_zones,
                'inactive_zones': total_zones - active_zones,
                'total_communes_covered': total_communes,
                'coverage_summary': f"{total_communes} comunas en {active_zones} zonas activas"
            })
        except MecanicoDomicilio.DoesNotExist:
            return Response({
                'error': 'Usuario no es un mecánico a domicilio.'
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def cerca(self, request):
        """
        Obtener mecánicos a domicilio cercanos al usuario
        Filtra por distancia y por zonas de servicio (comunas)
        """
        try:
            lat = request.query_params.get('lat')
            lng = request.query_params.get('lng')
            dist = request.query_params.get('dist', 10)  # Radio por defecto: 10km
            marca = request.query_params.get('marca')  # Filtro opcional por marca

            if not lat or not lng:
                return Response({
                    'error': 'Se requieren parámetros lat y lng'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Crear punto de ubicación del usuario
            user_location = Point(float(lng), float(lat), srid=4326)
            
            # Obtener mecánicos base (activos y verificados)
            base_queryset = MecanicoDomicilio.objects.filter(
                activo=True,
                usuario__is_active=True,
                verificado=True,
                ubicacion__isnull=False
            ).select_related('usuario').prefetch_related('especialidades', 'marcas_atendidas')

            # **NUEVA LÓGICA**: Filtro por zonas de servicio (comunas)
            try:
                # Geocodificación inversa para obtener la comuna del usuario
                import requests
                geocoding_url = f"https://nominatim.openstreetmap.org/reverse"
                params = {
                    'lat': lat,
                    'lon': lng,
                    'format': 'json',
                    'addressdetails': 1,
                    'accept-language': 'es'
                }
                
                response = requests.get(geocoding_url, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    address_components = data.get('address', {})
                    
                    # Intentar extraer la comuna/distrito de diferentes campos
                    user_commune = None
                    possible_commune_fields = [
                        'municipality', 'city_district', 'suburb', 
                        'neighbourhood', 'city', 'town', 'village'
                    ]
                    
                    for field in possible_commune_fields:
                        if field in address_components and address_components[field]:
                            user_commune = address_components[field]
                            break
                    
                    if user_commune:
                        # Normalizar nombre de comuna (eliminar espacios extra, capitalizar)
                        user_commune = user_commune.strip().title()
                        
                        # Filtrar mecánicos que tengan zonas de servicio activas que cubran esta comuna
                        from .models import MechanicServiceArea
                        
                        # Obtener IDs de mecánicos que cubren esta comuna
                        mechanic_ids_with_coverage = MechanicServiceArea.objects.filter(
                            is_active=True,
                            commune_names__icontains=user_commune  # JSONField contiene la comuna
                        ).values_list('mechanic_id', flat=True)
                        
                        if mechanic_ids_with_coverage:
                            # Solo incluir mecánicos que tienen cobertura en esta comuna
                            base_queryset = base_queryset.filter(
                                id__in=mechanic_ids_with_coverage
                            )
                            print(f"🎯 Comuna del usuario: {user_commune}")
                            print(f"🔧 Mecánicos con cobertura: {len(mechanic_ids_with_coverage)}")
                        else:
                            # Si no hay mecánicos con cobertura en esta comuna, retornar vacío
                            print(f"❌ No hay mecánicos con cobertura en comuna: {user_commune}")
                            return Response({
                                'count': 0,
                                'results': [],
                                'message': f'No hay mecánicos disponibles en {user_commune}'
                            })
                    else:
                        print("⚠️ No se pudo determinar la comuna del usuario")
                        
            except Exception as geocoding_error:
                print(f"⚠️ Error en geocodificación: {geocoding_error}")
                # Continuar sin filtro de comuna si hay error
                pass

            # Filtro por distancia geográfica
            # ✅ CORREGIDO: Usar SphericalDistance para cálculos precisos en kilómetros
            mechanics = base_queryset.annotate(
                distance=Distance('ubicacion', user_location, spheroid=True)
            ).filter(
                distance__lte=D(km=float(dist))
            )

            # Filtro opcional por marca de vehículo
            if marca:
                mechanics = mechanics.filter(marcas_atendidas__nombre__icontains=marca)

            # Ordenar por distancia
            mechanics = mechanics.order_by('distance')

            # Serializar con información de distancia
            serializer = self.get_serializer(mechanics, many=True, context={
                'user_location': user_location,
                'request': request
            })

            return Response({
                'count': len(serializer.data),
                'results': serializer.data,
                'user_location': {
                    'lat': float(lat),
                    'lng': float(lng)
                },
                'search_radius_km': float(dist)
            })

        except Exception as e:
            print(f"Error en cerca: {str(e)}")
            return Response({
                'error': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def buscar_cerca(self, request):
        """
        Endpoint público para buscar mecánicos a domicilio por comuna del usuario
        Filtra por zonas de servicio (comunas) y muestra estado de conexión
        """
        try:
            lat = request.query_params.get('lat')
            lng = request.query_params.get('lng')
            marca = request.query_params.get('marca')  # Filtro opcional por marca
            comuna_extraida = request.query_params.get('comuna_extraida')  # Nueva: comuna extraída del frontend
            comunas_extraidas = request.query_params.getlist('comunas_extraidas')  # **NUEVO**: Múltiples comunas

            if not lat or not lng:
                return Response({
                    'error': 'Se requieren parámetros lat y lng'
                }, status=status.HTTP_400_BAD_REQUEST)

            print(f"🔍 Buscando mecánicos por comuna en lat: {lat}, lng: {lng}")
            if comuna_extraida:
                print(f"🏙️ Comuna extraída del frontend: {comuna_extraida}")
            if comunas_extraidas:
                print(f"🏙️ Comunas extraídas del frontend: {comunas_extraidas}")

            # **LÓGICA MEJORADA DE ZONAS DE SERVICIO**
            user_communes = []
            
            # **DEBUG**: Verificar si hay comunas extraídas del frontend
            print(f"🔍 DEBUG: comunas_extraidas es {type(comunas_extraidas)}: {comunas_extraidas}")
            print(f"🔍 DEBUG: len(comunas_extraidas): {len(comunas_extraidas) if comunas_extraidas else 0}")
            
            # **CORREGIDO**: Procesar múltiples comunas extraídas del frontend
            if comunas_extraidas:
                print(f"🎯 Procesando múltiples comunas extraídas del frontend: {comunas_extraidas}")
                for comuna in comunas_extraidas:
                    if comuna not in user_communes:
                        user_communes.append(comuna)
                        print(f"🎯 Agregando comuna extraída: {comuna}")
            
            # **CORREGIDO**: Si el frontend envía comuna extraída individual, agregarla también
            if comuna_extraida and comuna_extraida not in user_communes:
                print(f"🎯 Agregando comuna extraída individual: {comuna_extraida}")
                user_communes.append(comuna_extraida)
            
            print(f"🏙️ Comunas finales a procesar: {user_communes}")
            print(f"🔍 DEBUG: user_communes después de procesar comunas extraídas: {user_communes}")

            # **OPTIMIZACIÓN**: Solo geocodificar si NO se proporcionaron comunas desde el frontend
            if not user_communes:
                try:
                    print(f"🌍 Iniciando geocodificación fallback para lat: {lat}, lng: {lng}")
                    # Usar timeout muy corto para no bloquear workers
                    geocoding_url = "https://nominatim.openstreetmap.org/reverse"
                    params = {
                        'lat': lat,
                        'lon': lng,
                        'format': 'json',
                        'addressdetails': 1,
                        'accept-language': 'es'
                    }
                    
                    response = requests.get(geocoding_url, params=params, timeout=2)
                    if response.status_code == 200:
                        data = response.json()
                        address_components = data.get('address', {})
                        
                        print(f"🗺️ Respuesta de geocodificación: {data.get('display_name', 'N/A')}")
                        
                        # **MEJORADA**: Buscar comuna en diferentes campos con prioridad
                        commune_priority = [
                            'municipality', 'city_district', 'suburb', 
                            'neighbourhood', 'city', 'town', 'village'
                        ]
                        
                        for field in commune_priority:
                            if field in address_components and address_components[field]:
                                potential_commune = address_components[field].strip().title()
                                print(f"🔍 Campo '{field}' encontrado: {potential_commune}")
                                
                                # **NUEVO**: Verificar si esta comuna tiene mecánicos con cobertura
                                mechanic_ids_with_coverage = MechanicServiceArea.objects.filter(
                                    is_active=True,
                                    commune_names__icontains=potential_commune
                                ).values_list('mechanic_id', flat=True)
                                
                                if mechanic_ids_with_coverage and potential_commune not in user_communes:
                                    user_communes.append(potential_commune)
                                    print(f"🎯 Comuna válida detectada: {potential_commune} (con {len(mechanic_ids_with_coverage)} mecánicos)")
                        
                        if not user_communes:
                            print("⚠️ No se encontró comuna válida en la geocodificación")
                            
                except Exception as geocoding_error:
                    print(f"⚠️ Error en geocodificación: {geocoding_error}")
            
            # **MEJORADO**: Fallback más inteligente con comunas comunes
            if not user_communes:
                print("🔄 Usando fallback de comunas comunes")
                # **NUEVO**: Lista de comunas comunes ordenadas por probabilidad
                comunas_fallback = [
                    'Santiago', 'Providencia', 'Las Condes', 'Ñuñoa', 
                    'Cerrillos', 'Cerro Navia', 'Independencia', 'Recoleta',
                    'Quinta Normal', 'Estación Central', 'Lo Prado',
                    'Conchalí', 'Huechuraba', 'Renca', 'Vitacura'
                ]
                
                for comuna in comunas_fallback:
                    mechanic_ids_with_coverage = MechanicServiceArea.objects.filter(
                        is_active=True,
                        commune_names__icontains=comuna
                    ).values_list('mechanic_id', flat=True)
                    
                    if mechanic_ids_with_coverage:
                        user_communes.append(comuna)
                        print(f"🎯 Comuna encontrada en fallback: {comuna} (con {len(mechanic_ids_with_coverage)} mecánicos)")
                        break
                
                if not user_communes:
                    print("❌ No se encontró ninguna comuna con mecánicos disponibles")
                    return Response({
                        'count': 0,
                        'results': [],
                        'message': 'No hay mecánicos disponibles en tu área',
                        'debug_info': {
                            'lat': lat,
                            'lng': lng,
                            'geocoding_failed': True
                        }
                    })
            
            # **FILTRO CRÍTICO**: Solo mostrar mecánicos que tengan zonas de servicio activas
            mechanic_ids_with_active_areas = MechanicServiceArea.objects.filter(
                is_active=True
            ).values_list('mechanic_id', flat=True).distinct()
            
            print(f"🔧 Mecánicos con zonas de servicio activas: {len(mechanic_ids_with_active_areas)}")
            
            if not mechanic_ids_with_active_areas:
                print("❌ No hay mecánicos con zonas de servicio activas")
                return Response({
                    'count': 0,
                    'results': [],
                    'message': 'No hay mecánicos disponibles con zonas de servicio configuradas'
                })
            
            # Obtener mecánicos base (activos y verificados)
            base_queryset = MecanicoDomicilio.objects.filter(
                activo=True,
                usuario__is_active=True,
                verificado=True,
                ubicacion__isnull=False,
                id__in=mechanic_ids_with_active_areas
            ).select_related('usuario').prefetch_related('especialidades', 'marcas_atendidas')
            
            print(f"🔧 Mecánicos con zonas de servicio activas (filtrado): {base_queryset.count()}")
            
            # **NUEVA LÓGICA**: Buscar mecánicos para TODAS las comunas detectadas
            mechanic_ids_with_coverage = set()
            
            for user_commune in user_communes:
                print(f"🏙️ Buscando mecánicos para comuna: {user_commune}")
                
                commune_mechanic_ids = MechanicServiceArea.objects.filter(
                    is_active=True,
                    commune_names__icontains=user_commune
                ).values_list('mechanic_id', flat=True)
                
                mechanic_ids_with_coverage.update(commune_mechanic_ids)
                print(f"🔧 IDs de mecánicos con cobertura en {user_commune}: {list(commune_mechanic_ids)}")
            
            if mechanic_ids_with_coverage:
                base_queryset = base_queryset.filter(id__in=mechanic_ids_with_coverage)
                print(f"🎯 Mecánicos con cobertura en comunas {user_communes}: {base_queryset.count()}")
            else:
                print(f"⚠️ No hay mecánicos con cobertura específica en las comunas: {user_communes}")
                return Response({
                    'count': 0,
                    'results': [],
                    'message': f'No hay mecánicos disponibles en las comunas: {", ".join(user_communes)}',
                    'comunas_buscadas': user_communes
                })

            # Filtro opcional por marca de vehículo
            if marca:
                base_queryset = base_queryset.filter(marcas_atendidas__nombre__icontains=marca)
                print(f"🔧 Mecánicos después de filtro de marca: {base_queryset.count()}")

            # **CALCULAR DISTANCIA SOLO PARA INFORMACIÓN, NO PARA FILTRAR**
            user_location = Point(float(lng), float(lat), srid=4326)
            # ✅ CORREGIDO: Usar SphericalDistance para cálculos precisos en kilómetros
            mechanics = base_queryset.annotate(
                distance=Distance('ubicacion', user_location, spheroid=True)
            ).order_by('distance')  # Ordenar por distancia para mostrar los más cercanos primero

            print(f"🔧 Mecánicos finales encontrados: {mechanics.count()}")

            # Serializar
            from .serializers import MecanicoDomicilioSerializer
            serializer = MecanicoDomicilioSerializer(mechanics, many=True, context={
                'user_location': user_location,
                'request': request
            })

            print(f"✅ Mecánicos serializados: {len(serializer.data)}")

            return Response({
                'count': len(serializer.data),
                'results': serializer.data,
                'comunas_detectadas': user_communes,
                'debug_info': {
                    'lat': lat,
                    'lng': lng,
                    'comunas_buscadas': user_communes,
                    'total_mecanicos_con_zonas': len(mechanic_ids_with_active_areas),
                    'mecanicos_en_comunas': len(mechanic_ids_with_coverage)
                }
            })

        except Exception as e:
            print(f"❌ Error en buscar_cerca: {e}")
            return Response({
                'error': 'Error interno del servidor',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def actualizar_estado_conexion_generico(request):
    """
    Endpoint genérico para que cualquier proveedor actualice su estado de conexión
    """
    try:
        # Obtener el proveedor autenticado
        user = request.user
        print(f"🔍 Buscando proveedor para usuario: {user.username} (ID: {user.id})")
        
        # Buscar si es un mecánico a domicilio
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            proveedor = mecanico
            tipo_proveedor = 'mecanico'
            print(f"✅ Encontrado como mecánico a domicilio: {proveedor.nombre}")
        except MecanicoDomicilio.DoesNotExist:
            print(f"❌ No encontrado como mecánico a domicilio")
            # Buscar si es un taller
            try:
                taller = Taller.objects.get(usuario=user)
                proveedor = taller
                tipo_proveedor = 'taller'
                print(f"✅ Encontrado como taller: {proveedor.nombre}")
            except Taller.DoesNotExist:
                print(f"❌ No encontrado como taller")
                return Response({
                    'error': 'No se encontró un proveedor asociado a tu cuenta'
                }, status=status.HTTP_404_NOT_FOUND)
        
        # Actualizar estado de conexión usando ConnectionStatus
        from django.utils import timezone
        
        # Crear filtro según el tipo de proveedor
        if tipo_proveedor == 'mecanico':
            filter_kwargs = {'proveedor': proveedor}
        else:  # taller
            filter_kwargs = {'taller': proveedor}
        
        # Obtener información del cliente
        client_info = request.META.get('REMOTE_ADDR', '')
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        connection_status, created = ConnectionStatus.objects.get_or_create(
            **filter_kwargs,
            defaults={
                'esta_conectado': True,
                'ultima_conexion': timezone.now(),
                'ip_address': client_info,
                'user_agent': user_agent
            }
        )
        
        if not created:
            connection_status.esta_conectado = True
            connection_status.ultima_conexion = timezone.now()
            connection_status.ip_address = client_info
            connection_status.user_agent = user_agent
            connection_status.save()
        
        print(f"✅ Proveedor {proveedor.nombre} ({tipo_proveedor}) marcado como conectado")
        
        return Response({
            'message': 'Estado de conexión actualizado',
            'proveedor': proveedor.nombre,
            'tipo': tipo_proveedor,
            'esta_conectado': True,
            'ultima_conexion': connection_status.ultima_conexion
        })
        
    except Exception as e:
        print(f"❌ Error actualizando estado de conexión: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response({
            'error': 'Error interno del servidor'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def desconectar_generico(request):
    """
    Endpoint genérico para que cualquier proveedor se marque como desconectado
    """
    try:
        # Obtener el proveedor autenticado
        user = request.user
        print(f"🔍 Buscando proveedor para desconectar: {user.username} (ID: {user.id})")
        
        # Buscar si es un mecánico a domicilio
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            proveedor = mecanico
            tipo_proveedor = 'mecanico'
            print(f"✅ Encontrado como mecánico a domicilio: {proveedor.nombre}")
        except MecanicoDomicilio.DoesNotExist:
            print(f"❌ No encontrado como mecánico a domicilio")
            # Buscar si es un taller
            try:
                taller = Taller.objects.get(usuario=user)
                proveedor = taller
                tipo_proveedor = 'taller'
                print(f"✅ Encontrado como taller: {proveedor.nombre}")
            except Taller.DoesNotExist:
                print(f"❌ No encontrado como taller")
                return Response({
                    'error': 'No se encontró un proveedor asociado a tu cuenta'
                }, status=status.HTTP_404_NOT_FOUND)
        
        # Actualizar estado de conexión usando ConnectionStatus
        from django.utils import timezone
        
        # Crear filtro según el tipo de proveedor
        if tipo_proveedor == 'mecanico':
            filter_kwargs = {'proveedor': proveedor}
        else:  # taller
            filter_kwargs = {'taller': proveedor}
        
        connection_status = ConnectionStatus.objects.filter(**filter_kwargs).first()
        
        if connection_status:
            connection_status.esta_conectado = False
            connection_status.ultima_desconexion = timezone.now()
            connection_status.save()
        
        print(f"✅ Proveedor {proveedor.nombre} ({tipo_proveedor}) marcado como desconectado")
        
        return Response({
            'message': 'Estado de desconexión actualizado',
            'proveedor': proveedor.nombre,
            'tipo': tipo_proveedor,
            'esta_conectado': False
        })
        
    except Exception as e:
        print(f"❌ Error actualizando estado de desconexión: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response({
            'error': 'Error interno del servidor'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def completar_onboarding_con_documentos_pendientes(request):
    """
    Vista para permitir a proveedores completar su onboarding incluso si no pudieron subir documentos inicialmente.
    Esto resuelve el problema de proveedores que quedaron bloqueados en estado de revisión.
    """
    usuario = request.user
    
    # Buscar el proveedor (taller o mecánico)
    proveedor = None
    tipo_proveedor = None
    
    if hasattr(usuario, 'taller'):
        proveedor = usuario.taller
        tipo_proveedor = 'taller'
    elif hasattr(usuario, 'mecanico_domicilio'):
        proveedor = usuario.mecanico_domicilio
        tipo_proveedor = 'mecanico'
    
    if not proveedor:
        return Response({
            'error': 'No se encontró perfil de proveedor'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # Verificar que el onboarding ya esté completado pero no verificado
    if not proveedor.onboarding_completado:
        return Response({
            'error': 'El onboarding debe estar completado antes de usar esta función'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if proveedor.verificado:
        return Response({
            'error': 'El proveedor ya está verificado'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Contar documentos existentes
        documentos_count = DocumentoOnboarding.objects.filter(
            **{tipo_proveedor: proveedor}
        ).count()
        
        # Si no hay documentos, cambiar estado a 'pendiente' para permitir subida
        if documentos_count == 0:
            proveedor.estado_verificacion = 'pendiente'
            proveedor.save(update_fields=['estado_verificacion'])
            
            return Response({
                'mensaje': 'Estado actualizado para permitir subida de documentos',
                'tipo_proveedor': tipo_proveedor,
                'estado_verificacion': 'pendiente',
                'verificado': False,
                'documentos_count': documentos_count,
                'puede_subir_documentos': True,
                'mensaje_verificacion': 'Ahora puedes subir tus documentos para completar tu verificación.'
            })
        else:
            return Response({
                'mensaje': 'Ya tienes documentos subidos',
                'tipo_proveedor': tipo_proveedor,
                'estado_verificacion': proveedor.estado_verificacion,
                'verificado': False,
                'documentos_count': documentos_count,
                'puede_subir_documentos': False,
                'mensaje_verificacion': 'Tus documentos ya están en revisión.'
            })
        
    except Exception as e:
        return Response({
            'error': f'Error al actualizar estado: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para manejar las reseñas de proveedores
    Permite lectura (GET) y creación (POST) para los clientes
    """
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['rating']
    ordering_fields = ['created_at', 'rating']
    ordering = ['-created_at']
    pagination_class = PageNumberPagination
    
    def get_queryset(self):
        """Obtener reseñas de un proveedor específico"""
        provider_id = self.kwargs.get('provider_id')
        if provider_id:
            # Buscar en ambos modelos: Taller y MecanicoDomicilio
            from .models import Taller, MecanicoDomicilio
            
            # Intentar encontrar el proveedor
            try:
                taller = Taller.objects.get(id=provider_id)
                return Review.objects.filter(provider_type='taller', provider_id=provider_id)
            except Taller.DoesNotExist:
                try:
                    mecanico = MecanicoDomicilio.objects.get(id=provider_id)
                    return Review.objects.filter(provider_type='mecanico', provider_id=provider_id)
                except MecanicoDomicilio.DoesNotExist:
                    return Review.objects.none()
        return Review.objects.none()
    
    def create(self, request, *args, **kwargs):
        """Crear una nueva reseña"""
        # Importar el modelo al inicio del método
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        
        try:
            
            # Verificar que el usuario esté autenticado
            if not request.user or request.user.is_anonymous:
                return Response(
                    {"error": "Debe estar autenticado para crear reseñas"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Verificar que el usuario tenga un perfil de cliente
            try:
                cliente = Cliente.objects.get(usuario=request.user)
            except Cliente.DoesNotExist:
                return Response(
                    {"error": "Debe tener un perfil de cliente para crear reseñas"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Validar que el servicio esté completado
            service_order_id = request.data.get('service_order_id')
            if not service_order_id:
                return Response(
                    {"error": "Se requiere service_order_id"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Buscar la solicitud de servicio
            try:
                service_order = SolicitudServicio.objects.get(id=service_order_id)
            except SolicitudServicio.DoesNotExist:
                return Response(
                    {"error": "Servicio no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Verificar que el servicio esté completado
            if service_order.estado != 'completado':
                return Response(
                    {"error": "Solo se pueden crear reseñas para servicios completados"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verificar que el cliente sea el propietario del servicio
            if service_order.cliente.usuario != request.user:
                return Response(
                    {"error": "No puede crear reseñas para servicios que no le pertenecen"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Verificar que no exista ya una reseña para este servicio
            existing_review = Review.objects.filter(
                client=request.user,
                service_order=service_order
            ).exists()
            
            if existing_review:
                return Response(
                    {"error": "Ya existe una reseña para este servicio"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Determinar el tipo de proveedor y su ID
            provider_type = None
            provider_id = None
            
            if hasattr(service_order, 'taller') and service_order.taller:
                provider_type = 'taller'
                provider_id = service_order.taller.id
            elif hasattr(service_order, 'mecanico') and service_order.mecanico:
                provider_type = 'mecanico'
                provider_id = service_order.mecanico.id
            else:
                return Response(
                    {"error": "No se pudo determinar el proveedor del servicio"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Crear la reseña
            review_data = {
                'client': request.user.id,
                'provider_type': provider_type,
                'provider_id': provider_id,
                'service_order': service_order.id,
                'rating': request.data.get('rating'),
                'comment': request.data.get('comment', '')
            }
            
            serializer = self.get_serializer(data=review_data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            return Response(
                {"error": f"Error al crear reseña: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def list(self, request, *args, **kwargs):
        """Listar reseñas con filtros opcionales"""
        queryset = self.get_queryset()
        
        # Aplicar filtros automáticos de DRF
        queryset = self.filter_queryset(queryset)
        
        # Paginación
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request, *args, **kwargs):
        """Obtener estadísticas de reseñas del proveedor"""
        provider_id = self.kwargs.get('provider_id')
        if not provider_id:
            return Response(
                {'error': 'Se requiere provider_id'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from .models import Taller, MecanicoDomicilio
            
            # Intentar encontrar el proveedor
            try:
                provider = Taller.objects.get(id=provider_id)
                provider_name = provider.nombre
                provider_type = 'taller'
            except Taller.DoesNotExist:
                try:
                    provider = MecanicoDomicilio.objects.get(id=provider_id)
                    provider_name = provider.nombre
                    provider_type = 'mecanico'
                except MecanicoDomicilio.DoesNotExist:
                    return Response(
                        {'error': 'Proveedor no encontrado'}, 
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            # Obtener estadísticas de las reseñas
            reviews = Review.objects.filter(provider_type=provider_type, provider_id=provider_id)
            stats = reviews.aggregate(
                avg_rating=Avg('rating'),
                total_reviews=Count('id'),
                five_star=Count('id', filter=Q(rating=5)),
                four_star=Count('id', filter=Q(rating=4)),
                three_star=Count('id', filter=Q(rating=3)),
                two_star=Count('id', filter=Q(rating=2)),
                one_star=Count('id', filter=Q(rating=1))
            )
            
            return Response({
                'provider_id': provider_id,
                'provider_name': provider_name,
                'provider_type': provider_type,
                'rating_average': float(stats['avg_rating'] or 0.00),
                'total_reviews': stats['total_reviews'] or 0,
                'rating_breakdown': {
                    '5': stats['five_star'] or 0,
                    '4': stats['four_star'] or 0,
                    '3': stats['three_star'] or 0,
                    '2': stats['two_star'] or 0,
                    '1': stats['one_star'] or 0,
                }
            })
        except Exception as e:
            return Response(
                {'error': f'Error al obtener estadísticas: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def perform_create(self, serializer):
        """Crear la reseña"""
        serializer.save()


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def servicios_completados_sin_resena(request):
    """
    Obtener servicios completados del cliente que no tienen reseña
    """
    try:
        # Verificar que el usuario tenga un perfil de cliente
        try:
            cliente = Cliente.objects.get(usuario=request.user)
        except Cliente.DoesNotExist:
            return Response(
                {"error": "Debe tener un perfil de cliente"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Obtener servicios completados del cliente
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        servicios_completados = SolicitudServicio.objects.filter(
            cliente=cliente,
            estado='completado'
        ).order_by('-fecha_hora_solicitud')
        
        # Filtrar servicios que no tienen reseña
        servicios_sin_resena = []
        for servicio in servicios_completados:
            # Verificar si ya existe una reseña para este servicio
            existing_review = Review.objects.filter(
                client=request.user,
                service_order=servicio
            ).exists()
            
            if not existing_review:
                # Determinar información del proveedor
                provider_info = {}
                if servicio.taller:
                    provider_info = {
                        'provider_type': 'taller',
                        'provider_id': servicio.taller.id,
                        'provider_name': servicio.taller.nombre,
                        'provider_photo': servicio.taller.foto_perfil.url if servicio.taller.foto_perfil else None
                    }
                elif servicio.mecanico:
                    provider_info = {
                        'provider_type': 'mecanico',
                        'provider_id': servicio.mecanico.id,
                        'provider_name': servicio.mecanico.nombre,
                        'provider_photo': servicio.mecanico.foto_perfil.url if servicio.mecanico.foto_perfil else None
                    }
                
                # Información del vehículo
                vehicle_info = {}
                if servicio.vehiculo:
                    vehicle_info = {
                        'brand': servicio.vehiculo.marca.nombre if servicio.vehiculo.marca else 'N/A',
                        'model': servicio.vehiculo.modelo.nombre if servicio.vehiculo.modelo else 'N/A',
                        'full_name': f"{servicio.vehiculo.marca.nombre} {servicio.vehiculo.modelo.nombre}" if servicio.vehiculo.marca and servicio.vehiculo.modelo else 'N/A'
                    }
                
                # Obtener información del servicio desde las líneas
                service_name = 'Servicio'
                if servicio.lineas.exists():
                    first_line = servicio.lineas.first()
                    if first_line.oferta_servicio and first_line.oferta_servicio.servicio:
                        service_name = first_line.oferta_servicio.servicio.nombre
                
                servicios_sin_resena.append({
                    'service_order_id': servicio.id,
                    'service_name': service_name,
                    'completion_date': servicio.fecha_hora_solicitud.isoformat(),
                    'provider': provider_info,
                    'vehicle': vehicle_info
                })
        
        return Response({
            'services_without_review': servicios_sin_resena,
            'total_count': len(servicios_sin_resena)
        })
        
    except Exception as e:
        return Response(
            {"error": f"Error al obtener servicios: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class TallerDireccionViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo TallerDireccion
    """
    queryset = TallerDireccion.objects.all()
    serializer_class = TallerDireccionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """
        Solo mostrar direcciones del taller del usuario autenticado
        """
        user = self.request.user
        if hasattr(user, 'taller'):
            return TallerDireccion.objects.filter(taller=user.taller)
        return TallerDireccion.objects.none()
    
    def perform_create(self, serializer):
        """
        Asignar automáticamente el taller del usuario autenticado
        """
        user = self.request.user
        if hasattr(user, 'taller'):
            serializer.save(taller=user.taller)
        else:
            raise serializers.ValidationError("El usuario no tiene un taller asociado")


class RegisterPushTokenView(APIView):
    """
    Vista para registrar el token de Expo Push Notifications en el modelo Usuario
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = request.data.get('token')
        
        if not token:
            return Response(
                {"error": "El token es requerido"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validar si el token es un token de Expo válido
        try:
            # Algunas versiones del SDK tienen este método
            is_valid = PushClient().is_exponent_push_token(token)
            if not is_valid:
                return Response(
                    {"error": "El token proporcionado no es un token de Expo válido"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception:
            # Fallback a validación básica si el método no existe
            if not token.startswith('ExponentPushToken['):
                return Response(
                    {"error": "Formato de token de Expo inválido"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        try:
            user = request.user
            user.expo_push_token = token
            user.save(update_fields=['expo_push_token'])
            
            logger.info(f"✅ RegisterPushTokenView: Token guardado para usuario {user.id}")
            
            return Response(
                {"message": "Token de notificaciones registrado exitosamente"}, 
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"❌ Error en RegisterPushTokenView: {str(e)}")
            return Response(
                {"error": "Error interno al guardar el token"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def registrar_push_token(request):
    """
    Registrar o actualizar push token del usuario para notificaciones push
    """
    try:
        token = request.data.get('push_token')
        if not token:
            return Response({'error': 'push_token es requerido'}, status=status.HTTP_400_BAD_REQUEST)
        
        dispositivo = request.data.get('dispositivo', '')
        plataforma = request.data.get('plataforma', 'unknown')
        
        # Actualizar o crear el token en el modelo PushToken (legacy compatibility)
        push_token, created = PushToken.objects.update_or_create(
            token=token,
            defaults={
                'usuario': request.user,
                'activo': True,
                'dispositivo': dispositivo,
                'plataforma': plataforma
            }
        )

        # ✅ ACTUALIZAR TAMBIÉN EN EL MODELO USUARIO (Para el nuevo sistema de Celery)
        request.user.expo_push_token = token
        request.user.save(update_fields=['expo_push_token'])
        
        logger.info(f"✅ Push token {'registrado' if created else 'actualizado'} para usuario {request.user.id} (Sincronizado con Usuario model)")
        
        return Response({
            'mensaje': 'Token registrado correctamente',
            'token_id': push_token.id,
            'creado': created
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"❌ Error registrando push token: {e}", exc_info=True)
        return Response({
            'error': 'Error al registrar el token',
            'detalle': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def desactivar_push_token(request):
    """
    Desactivar un push token específico (útil cuando el usuario cierra sesión o desinstala la app)
    """
    try:
        token = request.data.get('push_token')
        if not token:
            return Response({'error': 'push_token es requerido'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Desactivar el token del usuario actual
        tokens_desactivados = PushToken.objects.filter(
            token=token,
            usuario=request.user
        ).update(activo=False)
        
        if tokens_desactivados > 0:
            logger.info(f"✅ Push token desactivado para usuario {request.user.id}")
            return Response({'mensaje': 'Token desactivado correctamente'}, status=status.HTTP_200_OK)
        else:
            return Response({'mensaje': 'Token no encontrado'}, status=status.HTTP_404_NOT_FOUND)
            
    except Exception as e:
        logger.error(f"❌ Error desactivando push token: {e}", exc_info=True)
        return Response({
            'error': 'Error al desactivar el token',
            'detalle': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class NotificacionViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar notificaciones del usuario
    Endpoints:
    - GET /notificaciones/ - Listar notificaciones del usuario
    - POST /notificaciones/{id}/marcar_leida/ - Marcar como leída
    - POST /notificaciones/marcar_todas_leidas/ - Marcar todas como leídas
    - GET /notificaciones/no_leidas_count/ - Contador de no leídas
    """
    serializer_class = NotificacionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Obtener solo las notificaciones del usuario autenticado"""
        return Notificacion.objects.filter(
            usuario=self.request.user
        ).select_related('usuario')
    
    @action(detail=True, methods=['post'])
    def marcar_leida(self, request, pk=None):
        """
        Marcar una notificación como leída
        POST /notificaciones/{id}/marcar_leida/
        """
        notificacion = self.get_object()
        notificacion.leida = True
        notificacion.fecha_leida = timezone.now()
        notificacion.save(update_fields=['leida', 'fecha_leida'])
        
        return Response({
            'status': 'success',
            'message': 'Notificación marcada como leída',
            'notification_id': notificacion.id
        })
    
    @action(detail=False, methods=['post'])
    def marcar_todas_leidas(self, request):
        """
        Marcar todas las notificaciones no leídas como leídas
        POST /notificaciones/marcar_todas_leidas/
        """
        count = self.get_queryset().filter(leida=False).update(
            leida=True,
            fecha_leida=timezone.now()
        )
        
        return Response({
            'status': 'success',
            'message': f'{count} notificaciones marcadas como leídas',
            'marked_count': count
        })
    
    @action(detail=False, methods=['get'])
    def no_leidas_count(self, request):
        """
        Obtener contador de notificaciones no leídas
        GET /notificaciones/no_leidas_count/
        """
        count = self.get_queryset().filter(leida=False).count()
        
        return Response({
            'unread_count': count
        })

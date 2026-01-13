from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from .models import Vehiculo, Marca, MarcaVehiculo, Modelo
from .serializers import VehiculoSerializer, MarcaSerializer, MarcaVehiculoSerializer, ModeloSerializer


class MarcaVehiculoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para el modelo MarcaVehiculo (solo lectura)
    """
    queryset = MarcaVehiculo.objects.all()
    serializer_class = MarcaVehiculoSerializer
    permission_classes = [permissions.IsAuthenticated]


class MarcaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para el modelo Marca (solo lectura)
    """
    queryset = Marca.objects.all()
    serializer_class = MarcaSerializer
    permission_classes = [permissions.AllowAny()]


class ModeloViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para el modelo Modelo (solo lectura)
    """
    queryset = Modelo.objects.all()
    serializer_class = ModeloSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """
        Filtra los modelos por marca si se proporciona el parámetro marca
        """
        queryset = super().get_queryset()
        marca_id = self.request.query_params.get('marca', None)
        
        if marca_id is not None:
            queryset = queryset.filter(marca_id=marca_id)
        
        return queryset


class VehiculoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo Vehiculo
    """
    queryset = Vehiculo.objects.all()
    serializer_class = VehiculoSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_context(self):
        """
        Pasa el request al serializer para que pueda construir URLs completas
        """
        import logging
        logger = logging.getLogger(__name__)
        
        context = super().get_serializer_context()
        context['request'] = self.request
        
        # Log para verificar que el serializer se está ejecutando
        logger.info(f"🔍 [VehiculoViewSet] get_serializer_context llamado para acción: {self.action}")
        
        return context
    
    def get_permissions(self):
        """
        Permitir acceso público al endpoint de marcas
        """
        if self.action == 'get_marcas':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        """
        Filtra los vehículos por cliente (usuario autenticado)
        """
        user = self.request.user
        
        # Solo devolver vehículos del usuario actual
        if hasattr(user, 'cliente'):
            return Vehiculo.objects.filter(cliente=user.cliente)
        
        # Si el usuario no es un cliente (admin/staff), devolver todos los vehículos
        if user.is_staff:
            return Vehiculo.objects.all()
            
        # Si el usuario no es un cliente ni staff, no devolver nada
        return Vehiculo.objects.none()
    
    def perform_create(self, serializer):
        """
        Asigna automáticamente el cliente (usuario actual) al vehiculo creado
        """
        import logging
        from django.conf import settings
        
        logger = logging.getLogger(__name__)
        
        user = self.request.user
        
        if hasattr(user, 'cliente'):
            logger.warning(f"🔄 [VehiculoViewSet.perform_create] Creando vehículo para cliente {user.cliente.id}")
            
            # Forzar el uso del storage configurado si hay una foto
            if 'foto' in serializer.validated_data and serializer.validated_data.get('foto'):
                storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
                if storage_class:
                    from django.utils.module_loading import import_string
                    try:
                        correct_storage = import_string(storage_class)()
                        logger.warning(f"📸 [VehiculoViewSet.perform_create] Forzando uso de storage: {type(correct_storage).__name__}")
                        serializer.validated_data['foto'].storage = correct_storage
                    except (ImportError, AttributeError) as e:
                        logger.error(f"❌ [VehiculoViewSet.perform_create] Error cargando storage: {e}")
            
            vehiculo = serializer.save(cliente=user.cliente)
            logger.warning(f"✅ [VehiculoViewSet.perform_create] Vehículo {vehiculo.id} creado. Foto: {vehiculo.foto.name if vehiculo.foto else 'Sin foto'}")
            if vehiculo.foto:
                logger.warning(f"📸 [VehiculoViewSet.perform_create] Storage usado: {type(vehiculo.foto.storage).__name__}")
        else:
            # Si el usuario no tiene un cliente asociado, lanzar error
            raise permissions.PermissionDenied(
                "Solo los clientes pueden crear vehículos."
            )
    
    def perform_update(self, serializer):
        """
        Log para verificar actualización de vehículo y forzar el uso del storage correcto
        """
        import logging
        from django.conf import settings
        from django.core.files.storage import default_storage
        
        logger = logging.getLogger(__name__)
        
        logger.warning(f"🔄 [VehiculoViewSet.perform_update] Actualizando vehículo {serializer.instance.id}")
        
        # Verificar si hay una nueva foto en los datos
        if 'foto' in serializer.validated_data:
            logger.warning(f"📸 [VehiculoViewSet.perform_update] Nueva foto detectada para vehículo {serializer.instance.id}")
            
            # Forzar el uso del storage configurado en settings
            storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            if storage_class:
                from django.utils.module_loading import import_string
                try:
                    correct_storage = import_string(storage_class)()
                    logger.warning(f"📸 [VehiculoViewSet.perform_update] Forzando uso de storage: {type(correct_storage).__name__}")
                    # Asignar el storage correcto al campo foto antes de guardar
                    serializer.validated_data['foto'].storage = correct_storage
                except (ImportError, AttributeError) as e:
                    logger.error(f"❌ [VehiculoViewSet.perform_update] Error cargando storage: {e}")
        
        vehiculo = serializer.save()
        
        if vehiculo.foto:
            logger.warning(f"✅ [VehiculoViewSet.perform_update] Vehículo {vehiculo.id} actualizado. Foto: {vehiculo.foto.name}")
            logger.warning(f"📸 [VehiculoViewSet.perform_update] Storage usado: {type(vehiculo.foto.storage).__name__}")
    
    @action(detail=False, methods=['get'], url_path='marcas')
    def get_marcas(self, request):
        """
        Endpoint para obtener todas las marcas
        """
        marcas = MarcaVehiculo.objects.all()
        serializer = MarcaVehiculoSerializer(marcas, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='modelos')
    def get_modelos(self, request):
        """
        Endpoint para obtener modelos, opcionalmente filtrados por marca
        """
        marca_id = request.query_params.get('marca', None)
        
        if marca_id:
            modelos = Modelo.objects.filter(marca_id=marca_id)
        else:
            modelos = Modelo.objects.all()
            
        serializer = ModeloSerializer(modelos, many=True)
        return Response(serializer.data) 
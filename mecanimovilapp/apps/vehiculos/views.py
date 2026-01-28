from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from .models import Vehiculo, Marca, MarcaVehiculo, Modelo
from .models_health import ComponenteSaludConfig
from .serializers import (
    VehiculoSerializer, VehiculoLiteSerializer, MarcaSerializer, 
    MarcaVehiculoSerializer, ModeloSerializer, VehiculoMarketplaceSerializer,
    VehiculoMarketplaceDetailSerializer
)


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
    permission_classes = [permissions.AllowAny]

    @method_decorator(cache_page(60*60*24)) # Cache por 24 horas
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class ModeloViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para el modelo Modelo (solo lectura)
    """
    queryset = Modelo.objects.all()
    serializer_class = ModeloSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @method_decorator(cache_page(60*60*24)) # Cache por 24 horas
    def list(self, request, *args, **kwargs):
        """
        Sobrescribimos list para cachear, pero debemos tener cuidado con el filtro por marca.
        La cache varía por URL completa (incluyendo query params), así que funciona bien.
        """
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """
        Filtra los modelos por marca si se proporciona el parámetro marca
        """
        # Optimizamos con select_related para traer la marca
        queryset = Modelo.objects.select_related('marca').all()
        marca_id = self.request.query_params.get('marca', None)
        
        if marca_id is not None:
            queryset = queryset.filter(marca_id=marca_id)
        
        return queryset


from mecanimovilapp.apps.ordenes.models import SolicitudServicio, SolicitudServicioPublica

class VehiculoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo Vehiculo
    """
    queryset = Vehiculo.objects.all()
    serializer_class = VehiculoSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    # ... (existing methods omitted for brevity in prompt, but in real code I verify context)
    
    
    # def destroy(self, request, *args, **kwargs):
    #     """
    #     Sobrescribir destroy para validar que no haya servicios pendientes
    #     """
    #     # Se elimina la validación para permitir borrado en cascada
    #     return super().destroy(request, *args, **kwargs)

    def get_serializer_class(self):
        """
        Usar VehiculoLiteSerializer para list (optimización)
        y VehiculoSerializer completo para retrieve/create/update/delete
        """
        if self.action == 'list':
            return VehiculoLiteSerializer
        return VehiculoSerializer
    
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
            # Optimización N+1: Traer marca, modelo y cliente en la misma consulta
            return Vehiculo.objects.filter(cliente=user.cliente).select_related('marca', 'modelo', 'cliente')
        
        # Si el usuario no es un cliente (admin/staff), devolver todos los vehículos
        if user.is_staff:
            return Vehiculo.objects.all()
            
        # Si el usuario no es un cliente ni staff, no devolver nada
        return Vehiculo.objects.none()
    
    def list(self, request, *args, **kwargs):
        """
        Sobrescribir list para agregar Cache-Control headers
        """
        response = super().list(request, *args, **kwargs)
        # Cache-Control: public, max-age=300 (5 minutos)
        # El cliente puede cachear esta respuesta por 5 minutos
        response['Cache-Control'] = 'public, max-age=300'
        return response
    
    def retrieve(self, request, *args, **kwargs):
        """
        Sobrescribir retrieve para agregar Cache-Control headers
        """
        response = super().retrieve(request, *args, **kwargs)
        # Cache-Control: public, max-age=300 (5 minutos)
        response['Cache-Control'] = 'public, max-age=300'
        return response
    
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
            from rest_framework import exceptions
            raise exceptions.PermissionDenied(
                "Solo los clientes pueden crear vehículos."
            )

    def create(self, request, *args, **kwargs):
        """
        Sobrescribe create para:
        1. Manejar Update si el vehículo ya existe para este cliente (por patente)
        2. Resolver o Crear Marca/Modelo si faltan IDs pero hay nombres
        """
        print(f"DEBUG: Create Vehicle - Data received: {request.data}")
        data = request.data.copy()
        user = request.user
        
        if not hasattr(user, 'cliente'):
             return Response({"error": "Usuario sin perfil de cliente"}, status=status.HTTP_403_FORBIDDEN)
             
        if not hasattr(user, 'cliente'):
             return Response({"error": "Usuario sin perfil de cliente"}, status=status.HTTP_403_FORBIDDEN)
             
        # 1. Resolver Marca
        marca_id = data.get('marca')
        marca_obj = None
        
        if marca_id:
             marca_obj = Marca.objects.filter(id=marca_id).first()
             
        if not marca_obj and data.get('marca_nombre'):
            marca_nombre = data.get('marca_nombre')
            print(f"DEBUG: Resolving Brand by name: {marca_nombre}")
            marca_obj, _ = Marca.objects.get_or_create(nombre=marca_nombre.upper())
            data['marca'] = marca_obj.id
            print(f"DEBUG: Resolved Brand ID: {marca_obj.id}")
        
        # 2. Resolver Modelo
        modelo_id = data.get('modelo')
        
        if not modelo_id and marca_obj and data.get('modelo_nombre'):
                modelo_nombre = data.get('modelo_nombre')
                print(f"DEBUG: Resolving Model by name: {modelo_nombre}")
                # Buscamos o creamos el modelo bajo esa marca
                try:
                    modelo_obj, created = Modelo.objects.get_or_create(
                        marca=marca_obj, 
                        nombre=modelo_nombre.upper()
                    )
                    data['modelo'] = modelo_obj.id
                    print(f"DEBUG: Resolved Model ID: {modelo_obj.id} (Created: {created})")
                except Exception as e:
                    print(f"DEBUG: Error creating model: {e}")

        # 3. Verificar existencia por Patente para este Cliente
        patente = data.get('patente', '').upper().strip()
        data['patente'] = patente # Asegurar que esté saneada en los datos

        if not patente:
             return Response({"patente": ["Este campo es obligatorio."]}, status=status.HTTP_400_BAD_REQUEST)

        if patente:
            existing_vehicle = Vehiculo.objects.filter(cliente=user.cliente, patente=patente).first()
            if existing_vehicle:
                print(f"DEBUG: Updating existing vehicle {existing_vehicle.id}")
                # Update logic
                # Necesitamos un serializer para update con instance=existing_vehicle
                serializer = self.get_serializer(existing_vehicle, data=data, partial=True)
                if not serializer.is_valid():
                    print(f"DEBUG: Update Serializer Errors: {serializer.errors}")
                serializer.is_valid(raise_exception=True)
                self.perform_update(serializer)
                return Response(serializer.data)

        # 3. Create normal
        print("DEBUG: Creating new vehicle")
        serializer = self.get_serializer(data=data)
        if not serializer.is_valid():
             print(f"DEBUG: Create Serializer Errors: {serializer.errors}")
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
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
        if 'foto' in serializer.validated_data and serializer.validated_data.get('foto'):
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

    @action(detail=False, methods=['get'], url_path='checklist-inicial')
    def checklist_inicial(self, request):
        """
        Devuelve la lista de componentes configurados para mostrar en el checklist inicial
        Se filtra por tipo de motor (Gasolina/Diesel)
        """
        tipo_motor_param = request.query_params.get('tipo_motor', 'Gasolina')
        
        # Mapear el parámetro a los valores del modelo (GASOLINA, DIESEL)
        # El frontend puede enviar 'Gasolina', 'Diésel', 'GASOLINA', 'DIESEL'
        tipo_motor_map = {
            'gasolina': 'GASOLINA',
            'diesel': 'DIESEL',
            'diésel': 'DIESEL'
        }
        
        tipo_motor = tipo_motor_map.get(tipo_motor_param.lower(), 'GASOLINA')
        
        # Filtrar componentes activos que apliquen al motor o a TODOS
        componentes = ComponenteSaludConfig.objects.filter(
            activo=True
        ).filter(
            Q(tipo_motor_aplicable='TODOS') | Q(tipo_motor_aplicable=tipo_motor)
        ).values('id', 'nombre', 'descripcion')
        
        return Response(list(componentes))
    
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

    @action(detail=False, methods=['get'], url_path='consultar-patente')
    def consultar_patente(self, request):
        """
        Consulta una patente en GetAPI.cl y normaliza la respuesta
        """
        import requests
        
        patente = request.query_params.get('patente', '').upper()
        if not patente:
            return Response({"error": "Debe proporcionar una patente"}, status=status.HTTP_400_BAD_REQUEST)
            
        API_KEY = "28054a51-09f6-4687-a4a7-ecf3ead55ef4"
        URL = f"https://chile.getapi.cl/v1/vehicles/plate/{patente}"
        
        try:
            # Using endpoint /v1/vehicles/plate/{plate}
            # API requires x-api-key header based on 401 response
            headers = {
                "x-api-key": API_KEY,
                "Content-Type": "application/json"
            }
            response = requests.get(URL, headers=headers, timeout=10)
            
            if response.status_code == 200:
                json_response = response.json()
                
                # Check for success flag if present in wrapper
                # User example: { "success": true, "data": { ... } }
                if json_response.get("success") is False:
                     return Response({"error": "Vehículo no encontrado"}, status=status.HTTP_404_NOT_FOUND)

                data = json_response.get("data", json_response)
                
                # Map nested fields
                # structure: data.model.brand.name, data.model.name, etc.
                
                marca_nombre = data.get("model", {}).get("brand", {}).get("name", "")
                modelo_nombre = data.get("model", {}).get("name", "")
                
                normalized_data = {
                    "patente": data.get("licensePlate", patente),
                    "marca_nombre": marca_nombre,
                    "modelo_nombre": modelo_nombre,
                    "year": data.get("year", ""),
                    "color": data.get("color", ""),
                    "motor": data.get("engine", ""),
                    "vin": data.get("vinNumber", ""),
                    "tipo_motor": data.get("fuel", "GASOLINA"), # e.g. "BENCINA" -> mapping might be needed later
                    "cilindraje": data.get("engine", ""), 
                    "raw_data": data
                }
                
                # Try to map Marca/Modelo to internal IDs
                try:
                    marca_obj = Marca.objects.filter(nombre__iexact=normalized_data["marca_nombre"]).first()
                    if marca_obj:
                        normalized_data["marca_id"] = marca_obj.id
                        
                        # Fuzzy or exact match for model might be tricky due to versions
                        # e.g. API: "BRAVO SPORT TJET", Internal: "Bravo"
                        # We try contains or exact
                        modelo_obj = Modelo.objects.filter(marca=marca_obj, nombre__iexact=normalized_data["modelo_nombre"]).first()
                        if not modelo_obj:
                             modelo_obj = Modelo.objects.filter(marca=marca_obj, nombre__icontains=normalized_data["modelo_nombre"].split()[0]).first()
                             
                        if modelo_obj:
                            normalized_data["modelo_id"] = modelo_obj.id
                except Exception as e:
                    print(f"Error mapping marca/modelo: {e}")

                return Response(normalized_data)
            else:
                return Response({"error": "Vehículo no encontrado en registro nacional"}, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            print(f"Error connecting to GetAPI: {e}")
            return Response({"error": "Error al consultar servicio externo"}, status=status.HTTP_503_SERVICE_UNAVAILABLE) 

    @action(detail=True, methods=['get'], url_path='tasacion')
    def tasacion(self, request, pk=None):
        """
        Endpoint para obtener la tasación detallada del vehículo
        """
        vehiculo = self.get_object()
        
        # Calcular bonus salud (Mock logic por ahora, igual que en serializer)
        # TODO: Centralizar cálculo
        from mecanimovilapp.apps.marketplace.valuation_engine import calculate_potential_gain
        health_bonus_percentage = calculate_potential_gain(vehiculo) 
        
        data = {
            'tasacion_fiscal': vehiculo.tasacion_fiscal,
            'permiso_circulacion': vehiculo.permiso_circulacion,
            'year_tasacion_fiscal': vehiculo.year_tasacion_fiscal,
            'precio_mercado_min': vehiculo.precio_mercado_min,
            'precio_mercado_max': vehiculo.precio_mercado_max,
            'precio_mercado_promedio': vehiculo.precio_mercado_promedio,
            'precio_retoma': vehiculo.precio_retoma,
            'suggested_price': vehiculo.precio_sugerido_final,
            'bonus_percentage': health_bonus_percentage,
            'currency': 'CLP'
        }
        return Response(data)

    @action(detail=True, methods=['get', 'patch'], url_path='marketplace')
    def marketplace(self, request, pk=None):
        """
        Endpoint para gestionar la venta del vehículo (Publicar, Precio, etc.)
        """
        vehiculo = self.get_object()
        
        if request.method == 'GET':
            serializer = VehiculoMarketplaceSerializer(vehiculo)
            return Response(serializer.data)
        
        elif request.method == 'PATCH':
            print(f"DEBUG: Updating marketplace data for {vehiculo.id}")
            print(f"DEBUG: Request Data: {request.data}")
            serializer = VehiculoMarketplaceSerializer(vehiculo, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                print(f"DEBUG: Saved data. New precio_venta: {vehiculo.precio_venta}")
                return Response(serializer.data)
            print(f"DEBUG: Serializer Errors: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='marketplace-stats')
    def marketplace_stats(self, request, pk=None):
        """
        Endpoint para obtener estadísticas del vehículo en marketplace
        """
        vehiculo = self.get_object()
        # Aquí eventualmente podríamos agregar lógica real de conteo si está en otra tabla
        # Por ahora devolvemos los campos del modelo
        data = {
            'views': vehiculo.views_count,
            'favorites': vehiculo.favorites_count,
            'leads': vehiculo.leads_count
        }
        return Response(data)

    @action(detail=False, methods=['get'], url_path='marketplace-listings', permission_classes=[permissions.AllowAny])
    def marketplace_listings(self, request):
        """
        Endpoint público para listar vehículos publicados en el marketplace
        """
        queryset = Vehiculo.objects.filter(is_published=True).order_by('-fecha_actualizacion')
        serializer = VehiculoMarketplaceSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='marketplace-public-detail', permission_classes=[permissions.AllowAny])
    def marketplace_public_detail(self, request, pk=None):
        """
        Endpoint público para ver el detalle de un vehículo en marketplace (incluye historial)
        """
        try:
            vehiculo = Vehiculo.objects.get(pk=pk, is_published=True)
        except Vehiculo.DoesNotExist:
            return Response({"error": "Vehículo no disponible"}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = VehiculoMarketplaceDetailSerializer(vehiculo, context={'request': request})
        return Response(serializer.data)
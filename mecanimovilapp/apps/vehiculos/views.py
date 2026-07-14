from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from .models import Vehiculo, Marca, MarcaVehiculo, Modelo, OfertaVehiculo, ViajeRegistrado, FotoVehiculoMarketplace
from .models_health import ComponenteSalud, ReglaMantenimientoGenerica, ComponenteSaludVehiculo
from .serializers import (
    VehiculoSerializer, VehiculoLiteSerializer, MarcaSerializer,
    MarcaVehiculoSerializer, ModeloSerializer, VehiculoMarketplaceSerializer,
    VehiculoMarketplaceDetailSerializer, OfertaVehiculoSerializer,
    RegistrarViajeSerializer, FotoVehiculoMarketplaceSerializer,
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
from .getapi_client import fetch_appraisal_for_plate
from .kilometraje_validation import merge_mileage_metadata, validar_kilometraje_usuario

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
        # componentes_historial (mantenimientos) se pasa para create, evita validación FormData
        if hasattr(self, '_componentes_historial'):
            context['componentes_historial'] = self._componentes_historial
            del self._componentes_historial
        
        # Log para verificar que el serializer se está ejecutando
        logger.info(f"🔍 [VehiculoViewSet] get_serializer_context llamado para acción: {self.action}")
        
        return context
    
    def get_permissions(self):
        """
        Permitir acceso público donde corresponda.
        Nota: @action(permission_classes=[AllowAny]) no aplica si este método
        no lo refleja — antes marketplace_public_detail quedaba bloqueado para anónimos.
        """
        if self.action == 'get_marcas':
            return [permissions.AllowAny()]
        if self.action in ('marketplace_listings', 'marketplace_public_detail'):
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
                from django.core.files.storage import default_storage
                try:
                    logger.warning(f"📸 [VehiculoViewSet.perform_create] Forzando uso de storage: {type(default_storage).__name__}")
                    serializer.validated_data['foto'].storage = default_storage
                except AttributeError as e:
                    logger.error(f"❌ [VehiculoViewSet.perform_create] Error asignando storage: {e}")
            
            vehiculo = serializer.save(cliente=user.cliente)
            logger.warning(f"✅ [VehiculoViewSet.perform_create] Vehículo {vehiculo.id} creado. Foto: {vehiculo.foto.name if vehiculo.foto else 'Sin foto'}")
            if vehiculo.foto:
                logger.warning(f"📸 [VehiculoViewSet.perform_create] Storage usado: {type(vehiculo.foto.storage).__name__}")
            try:
                from mecanimovilapp.apps.valoracion_mercado.services.valoracion_service import (
                    maybe_enqueue_market_scrape,
                )
                maybe_enqueue_market_scrape(vehiculo, force=True)
            except Exception as scrape_exc:
                logger.warning(
                    'No se pudo encolar scrape de mercado para vehículo %s: %s',
                    vehiculo.id,
                    scrape_exc,
                )
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
        import json
        print(f"DEBUG: Create Vehicle - Data received: {request.data}")
        data = request.data.copy()
        user = request.user

        # Parse componentes_historial if sent as JSON string (FormData)
        # Se pasa por context al serializer para evitar validación ListField/DictField con FormData
        componentes_historial = []
        ch = data.pop('componentes_historial', None)
        if ch is not None:
            if isinstance(ch, str):
                try:
                    parsed = json.loads(ch)
                    componentes_historial = list(parsed) if isinstance(parsed, list) else []
                except (json.JSONDecodeError, TypeError):
                    componentes_historial = []
            elif isinstance(ch, list):
                # QueryDict puede devolver lista con un string JSON, ej: ['[{"componente_id":1,...}]']
                for x in ch:
                    if isinstance(x, dict):
                        componentes_historial.append(x)
                    elif isinstance(x, str):
                        try:
                            parsed = json.loads(x)
                            if isinstance(parsed, list):
                                componentes_historial.extend(p for p in parsed if isinstance(p, dict))
                            elif isinstance(parsed, dict):
                                componentes_historial.append(parsed)
                        except (json.JSONDecodeError, TypeError):
                            pass
        if componentes_historial:
            print(f"DEBUG: componentes_historial parseado: {componentes_historial}")
        
        if not hasattr(user, 'cliente'):
             return Response({"error": "Usuario sin perfil de cliente"}, status=status.HTTP_403_FORBIDDEN)

        # 1. Resolver marca/modelo canónicos (prioriza nombres sobre IDs)
        from .catalogo_resolver import (
            normalizar_tipo_motor_vehiculo,
            resolver_marca_modelo_registro,
        )

        marca_obj, modelo_obj, err_key = resolver_marca_modelo_registro(
            marca_id=data.get('marca'),
            marca_nombre=data.get('marca_nombre'),
            modelo_id=data.get('modelo'),
            modelo_nombre=data.get('modelo_nombre'),
        )
        if err_key == 'marca':
            return Response(
                {'marca_nombre': ['Indica la marca del vehículo.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if err_key == 'modelo':
            return Response(
                {'modelo_nombre': ['No se pudo identificar el modelo para esta marca.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data['marca'] = marca_obj.id
        data['modelo'] = modelo_obj.id
        print(f"DEBUG: Resolved Brand ID: {marca_obj.id}, Model ID: {modelo_obj.id}")

        if data.get('tipo_motor'):
            data['tipo_motor'] = normalizar_tipo_motor_vehiculo(data.get('tipo_motor'))
             
        # 2. Verificar existencia por Patente para este Cliente
        patente = data.get('patente', '').upper().strip()
        data['patente'] = patente # Asegurar que esté saneada en los datos

        if not patente:
             return Response({"patente": ["Este campo es obligatorio."]}, status=status.HTTP_400_BAD_REQUEST)

        if patente:
            # Reject if another user already owns this patente
            other_vehicle = Vehiculo.objects.filter(patente=patente).exclude(cliente=user.cliente).first()
            if other_vehicle:
                return Response(
                    {"patente": ["Esta patente ya se encuentra registrada por otro usuario."]},
                    status=status.HTTP_409_CONFLICT,
                )

            existing_vehicle = Vehiculo.objects.filter(cliente=user.cliente, patente=patente).first()
            if existing_vehicle:
                print(f"DEBUG: Updating existing vehicle {existing_vehicle.id}")
                serializer = self.get_serializer(existing_vehicle, data=data, partial=True)
                if not serializer.is_valid():
                    print(f"DEBUG: Update Serializer Errors: {serializer.errors}")
                serializer.is_valid(raise_exception=True)
                self.perform_update(serializer)
                return Response(serializer.data)

        # 3. Create normal
        print("DEBUG: Creating new vehicle")
        self._componentes_historial = componentes_historial
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
            from django.core.files.storage import default_storage
            try:
                logger.warning(f"📸 [VehiculoViewSet.perform_update] Forzando uso de storage: {type(default_storage).__name__}")
                serializer.validated_data['foto'].storage = default_storage
            except AttributeError as e:
                logger.error(f"❌ [VehiculoViewSet.perform_update] Error asignando storage: {e}")
        
        vehiculo = serializer.save()
        
        if vehiculo.foto:
            logger.warning(f"✅ [VehiculoViewSet.perform_update] Vehículo {vehiculo.id} actualizado. Foto: {vehiculo.foto.name}")
            logger.warning(f"📸 [VehiculoViewSet.perform_update] Storage usado: {type(vehiculo.foto.storage).__name__}")
    
    @action(detail=True, methods=['post'], url_path='registrar-viaje')
    def registrar_viaje(self, request, pk=None):
        """
        Registra un viaje GPS: suma km al odómetro y responde de inmediato.
        Recálculo de salud y notificaciones se procesan en background vía Celery.
        POST /api/vehiculos/{id}/registrar-viaje/
        """
        import logging
        logger = logging.getLogger(__name__)

        vehiculo = self.get_object()

        serializer = RegistrarViajeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        km_recorridos = data['km_recorridos']
        km_anterior = vehiculo.kilometraje
        km_nuevo = km_anterior + int(round(km_recorridos))

        vehiculo.kilometraje = km_nuevo
        vehiculo.save(update_fields=['kilometraje', 'fecha_actualizacion'])

        viaje = ViajeRegistrado.objects.create(
            vehiculo=vehiculo,
            km_recorridos=km_recorridos,
            km_odometro_anterior=km_anterior,
            km_odometro_nuevo=km_nuevo,
            duracion_segundos=data.get('duracion_segundos', 0),
            coordenadas_inicio=data.get('coordenadas_inicio'),
            coordenadas_fin=data.get('coordenadas_fin'),
            velocidad_promedio_kmh=data.get('velocidad_promedio_kmh', 0),
            fecha_inicio=data.get('fecha_inicio'),
        )

        # Everything below is fire-and-forget: enqueue to Celery, never block.
        from .tasks import procesar_post_viaje
        try:
            procesar_post_viaje.delay(vehiculo.id, viaje.id, km_recorridos, km_anterior, km_nuevo)
        except Exception as e:
            logger.warning(f"Celery no disponible para post-viaje: {e}")

        logger.info(
            f"Viaje registrado: vehículo={vehiculo.id} "
            f"km_recorridos={km_recorridos} "
            f"odómetro={km_anterior}→{km_nuevo}"
        )

        return Response({
            'viaje_id': viaje.id,
            'km_recorridos': viaje.km_recorridos,
            'km_odometro_anterior': viaje.km_odometro_anterior,
            'km_odometro_nuevo': viaje.km_odometro_nuevo,
            'kilometraje_actual': vehiculo.kilometraje,
            'salud_status': 'recalculando',
        }, status=status.HTTP_201_CREATED)

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
        Se filtra por tipo de motor (Gasolina/Diesel) usando las Reglas Genericas.
        """
        tipo_motor_param = request.query_params.get('tipo_motor', 'Gasolina')
        
        # Mapear el parámetro a los valores del modelo (GASOLINA, DIESEL)
        tipo_motor_map = {
            'gasolina': 'GASOLINA',
            'diesel': 'DIESEL',
            'diésel': 'DIESEL',
            'electrico': 'ELECTRICO',
            'hibrido': 'HIBRIDO'
        }
        
        tipo_motor = tipo_motor_map.get(tipo_motor_param.lower(), 'GASOLINA')
        
        # Obtener componentes que tengan una regla genérica para este tipo de motor
        # Esto asegura que solo mostramos lo relevante (ej: no mostrar DPF a Gasolina)
        componentes = ComponenteSalud.objects.filter(
            reglas_genericas__tipo_motor=tipo_motor
        ).values('id', 'nombre', 'descripcion').distinct()
        
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

    @action(detail=False, methods=['get'], url_path='validar-kilometraje')
    def validar_kilometraje(self, request):
        """
        Valida kilometraje ingresado vs mileage SII (GetAPI).
        GET /api/vehiculos/validar-kilometraje/?kilometraje=150000&mileage_sii=120000&tiene_mileage_sii=true&year=2012
        """
        kilometraje = request.query_params.get('kilometraje')
        if kilometraje is None or str(kilometraje).strip() == '':
            return Response(
                {'error': 'Debe proporcionar el kilometraje a validar'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tiene_param = request.query_params.get('tiene_mileage_sii')
        tiene_mileage_sii = None
        if tiene_param is not None:
            tiene_mileage_sii = str(tiene_param).lower() in ('1', 'true', 'yes', 'si', 'sí')

        year = (
            request.query_params.get('year')
            or request.query_params.get('año')
            or request.query_params.get('anio')
        )

        resultado = validar_kilometraje_usuario(
            kilometraje,
            mileage_sii=request.query_params.get('mileage_sii') or request.query_params.get('kilometraje_api'),
            tiene_mileage_sii=tiene_mileage_sii,
            year=year,
        )
        http_status = status.HTTP_200_OK if resultado['valid'] else status.HTTP_400_BAD_REQUEST
        return Response(resultado, status=http_status)

    @action(detail=False, methods=['get'], url_path='verificar-patente')
    def verificar_patente(self, request):
        """
        Verifica si una patente ya está registrada en el sistema.
        Retorna owner=self si es del mismo usuario, owner=other si pertenece a otro,
        o registered=false si no existe.
        GET /api/vehiculos/verificar-patente/?patente=ABCD12
        """
        patente = request.query_params.get('patente', '').upper().strip()
        if not patente:
            return Response({"error": "Debe proporcionar una patente"}, status=status.HTTP_400_BAD_REQUEST)

        existing = Vehiculo.objects.filter(patente=patente).select_related('cliente__usuario').first()
        if not existing:
            return Response({"registered": False})

        is_own = hasattr(request.user, 'cliente') and existing.cliente_id == request.user.cliente.id
        return Response({
            "registered": True,
            "owner": "self" if is_own else "other",
            "vehicle_id": existing.id if is_own else None,
            "marca": str(existing.marca) if existing.marca else None,
            "modelo": str(existing.modelo) if existing.modelo else None,
        })

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
                    return Response(
                        {
                            "error": "La patente ingresada no existe en el registro nacional de vehículos.",
                            "code": "patente_no_encontrada",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )

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
                
                # Try to map Marca/Modelo to internal IDs (misma lógica que al registrar)
                try:
                    from .catalogo_resolver import resolve_marca, resolve_modelo

                    marca_obj = resolve_marca(normalized_data["marca_nombre"])
                    if marca_obj:
                        normalized_data["marca_id"] = marca_obj.id
                        modelo_obj = resolve_modelo(marca_obj, normalized_data["modelo_nombre"])
                        if modelo_obj:
                            normalized_data["modelo_id"] = modelo_obj.id
                except Exception as e:
                    print(f"Error mapping marca/modelo: {e}")

                appraisal_extra = fetch_appraisal_for_plate(patente)
                normalized_data.update(appraisal_extra)
                if "tiene_tasacion_mercado" not in normalized_data:
                    normalized_data["tiene_tasacion_mercado"] = False
                normalized_data.update(merge_mileage_metadata(data, appraisal_extra))

                return Response(normalized_data)
            else:
                return Response(
                    {
                        "error": "La patente ingresada no existe en el registro nacional de vehículos.",
                        "code": "patente_no_encontrada",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
                
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

    @action(detail=True, methods=['get'], url_path='valor-real')
    def valor_real(self, request, pk=None):
        """
        Valor real estimado, liquidez y proyección del vehículo.
        GET /api/vehiculos/{id}/valor-real/?refresh=1
        """
        from mecanimovilapp.apps.valoracion_mercado.serializers import ValoracionVehiculoSerializer
        from mecanimovilapp.apps.valoracion_mercado.services.valoracion_service import (
            get_or_compute_valoracion,
        )

        vehiculo = self.get_object()
        force = str(request.query_params.get('refresh', '')).lower() in ('1', 'true', 'yes', 'si')
        payload = get_or_compute_valoracion(vehiculo, force=force)
        serializer = ValoracionVehiculoSerializer(payload)
        return Response(serializer.data)

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
            # Bloquear publicación si hay componentes declarados sin verificar por taller.
            # El usuario debe contratar una inspección técnica que certifique lo que declaró.
            intentando_publicar = request.data.get('is_published') is True
            if intentando_publicar and not vehiculo.is_published:
                componentes_sin_verificar = ComponenteSaludVehiculo.objects.filter(
                    vehiculo=vehiculo,
                    historial_fuente='USUARIO_DECLARADO',
                ).select_related('componente')

                if componentes_sin_verificar.exists():
                    nombres = [
                        c.componente.nombre if c.componente else 'Componente desconocido'
                        for c in componentes_sin_verificar
                    ]
                    return Response(
                        {
                            'error_code': 'INSPECCION_REQUERIDA',
                            'error': (
                                'Tu vehículo tiene componentes declarados manualmente que no han sido '
                                'verificados por un taller. Debes contratar una inspección técnica que '
                                'certifique esos componentes antes de publicar.'
                            ),
                            'componentes_sin_verificar': nombres,
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

            serializer = VehiculoMarketplaceSerializer(vehiculo, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
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

    @action(detail=True, methods=['get', 'post'], url_path='marketplace-fotos')
    def marketplace_fotos(self, request, pk=None):
        """
        GET  — lista las fotos de venta del vehículo.
        POST — sube una nueva foto (máx 10). Requiere campo `foto` (multipart).
        """
        vehiculo = self.get_object()

        if vehiculo.cliente.usuario != request.user:
            return Response({'error': 'No eres el dueño de este vehículo.'}, status=status.HTTP_403_FORBIDDEN)

        if request.method == 'GET':
            fotos = vehiculo.fotos_marketplace.all()
            serializer = FotoVehiculoMarketplaceSerializer(fotos, many=True, context={'request': request})
            return Response(serializer.data)

        # POST: upload
        fotos_count = vehiculo.fotos_marketplace.count()
        if fotos_count >= 10:
            return Response({'error': 'Límite de 10 fotos alcanzado.'}, status=status.HTTP_400_BAD_REQUEST)

        foto_file = request.FILES.get('foto')
        if not foto_file:
            return Response({'error': 'No se recibió ninguna foto.'}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.files.storage import default_storage

        foto_obj = FotoVehiculoMarketplace(vehiculo=vehiculo, orden=fotos_count)
        foto_obj.foto.storage = default_storage
        foto_obj.foto = foto_file
        foto_obj.save()

        serializer = FotoVehiculoMarketplaceSerializer(foto_obj, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'marketplace-fotos/(?P<foto_id>[^/.]+)')
    def marketplace_foto_delete(self, request, pk=None, foto_id=None):
        """
        DELETE — elimina una foto específica de venta del vehículo.
        """
        vehiculo = self.get_object()

        if vehiculo.cliente.usuario != request.user:
            return Response({'error': 'No eres el dueño de este vehículo.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            foto = FotoVehiculoMarketplace.objects.get(id=foto_id, vehiculo=vehiculo)
        except FotoVehiculoMarketplace.DoesNotExist:
            return Response({'error': 'Foto no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        foto.foto.delete(save=False)
        foto.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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

    @action(detail=True, methods=['get'], url_path='historial-servicios')
    def historial_servicios(self, request, pk=None):
        """
        Retorna TODAS las solicitudes completadas de un vehículo independientemente
        del dueño que las creó. Preserva trazabilidad tras transferencias.
        Solo accesible por el dueño actual del vehículo.
        """
        try:
            vehiculo = Vehiculo.objects.select_related('cliente__usuario').get(pk=pk)
        except Vehiculo.DoesNotExist:
            return Response({"error": "Vehículo no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        if vehiculo.cliente.usuario != request.user:
            return Response({"error": "No eres el dueño de este vehículo"}, status=status.HTTP_403_FORBIDDEN)

        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        from mecanimovilapp.apps.ordenes.history_km import kilometraje_al_momento_del_servicio
        from mecanimovilapp.storage.utils import get_image_url

        solicitudes = SolicitudServicio.objects.filter(
            vehiculo=vehiculo, estado='completado'
        ).select_related(
            'taller', 'mecanico__usuario', 'cliente__usuario',
            'oferta_proveedor__solicitud',
        ).prefetch_related(
            'lineas__oferta_servicio__servicio',
            'checklist_instance__respuestas__item_template__catalog_item',
        ).order_by('-fecha_servicio')

        history = []
        for sol in solicitudes:
            service_name = "Servicio General"
            first_line = sol.lineas.first()
            if first_line and first_line.oferta_servicio and first_line.oferta_servicio.servicio:
                service_name = first_line.oferta_servicio.servicio.nombre
                if sol.lineas.count() > 1:
                    service_name += " y otros"

            provider_name = "Proveedor"
            provider_avatar = None
            provider_type = 'mecanico'

            if sol.taller:
                provider_name = sol.taller.nombre
                provider_type = 'taller'
                if sol.taller.logo:
                    provider_avatar = get_image_url(sol.taller.logo, request)
            elif sol.mecanico:
                provider_name = f"{sol.mecanico.usuario.first_name} {sol.mecanico.usuario.last_name}".strip()
                provider_type = 'mecanico'
                if sol.mecanico.usuario.foto_perfil:
                    provider_avatar = get_image_url(sol.mecanico.usuario.foto_perfil, request)

            solicitud_publica_id = None
            if sol.oferta_proveedor_id and sol.oferta_proveedor and sol.oferta_proveedor.solicitud_id:
                solicitud_publica_id = str(sol.oferta_proveedor.solicitud_id)

            km_servicio = kilometraje_al_momento_del_servicio(sol)
            history.append({
                'id': sol.id,
                'solicitud_publica_id': solicitud_publica_id,
                'fecha_servicio': sol.fecha_servicio.isoformat() if sol.fecha_servicio else None,
                'servicio_nombre': service_name,
                'nombre_proveedor': provider_name,
                'proveedor_foto': provider_avatar,
                'tipo_proveedor': provider_type,
                'total': str(sol.total) if sol.total else None,
                'kilometraje': km_servicio,
                'verified': True,
                'cliente_original': sol.cliente.usuario.username if sol.cliente and sol.cliente.usuario else None,
            })

        return Response(history)


class OfertaVehiculoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para manejar las ofertas de vehículos (Compras)
    """
    queryset = OfertaVehiculo.objects.all()
    serializer_class = OfertaVehiculoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Retorna ofertas enviadas por mí O recibidas por mis vehículos O donde soy el vendedor en una transferencia
        return OfertaVehiculo.objects.filter(
            Q(comprador=user) | 
            Q(vehiculo__cliente__usuario=user) |
            Q(transferencia__vendedor=user)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(comprador=self.request.user)

    @action(detail=False, methods=['get'], url_path='puede_ofertar')
    def puede_ofertar(self, request):
        """
        Pre-check: ¿el comprador autenticado puede ofertar por este vehículo?
        Query: vehiculo_id (requerido)
        """
        from .marketplace_ofertas import (
            comprador_tiene_oferta_activa_con_vendedor,
            vendedor_id_desde_vehiculo,
            MENSAJE_OFERTA_ACTIVA_MISMO_VENDEDOR,
        )

        raw_id = request.query_params.get('vehiculo_id')
        if not raw_id:
            return Response(
                {'detail': 'Parámetro vehiculo_id requerido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            vehiculo = Vehiculo.objects.select_related('cliente__usuario').get(pk=int(raw_id))
        except (ValueError, Vehiculo.DoesNotExist):
            return Response({'detail': 'Vehículo no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        vendedor_id = vendedor_id_desde_vehiculo(vehiculo)
        if vendedor_id and int(vendedor_id) == int(request.user.id):
            return Response({
                'puede_ofertar': False,
                'code': 'vehiculo_propio',
                'mensaje': 'No puedes ofertar por tu propio vehículo.',
            })

        if comprador_tiene_oferta_activa_con_vendedor(request.user.id, vendedor_id):
            return Response({
                'puede_ofertar': False,
                'code': 'oferta_activa_mismo_vendedor',
                'mensaje': MENSAJE_OFERTA_ACTIVA_MISMO_VENDEDOR,
            })

        return Response({'puede_ofertar': True})

    @action(detail=False, methods=['get'])
    def mis_ofertas_enviadas(self, request):
        ofertas = OfertaVehiculo.objects.filter(comprador=request.user)
        serializer = self.get_serializer(ofertas, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def mis_ofertas_recibidas(self, request):
        # Retorna ofertas recibidas por mis vehículos actuales O donde fui el vendedor
        ofertas = OfertaVehiculo.objects.filter(
            Q(vehiculo__cliente__usuario=request.user) |
            Q(transferencia__vendedor=request.user)
        ).distinct()
        serializer = self.get_serializer(ofertas, many=True)
        return Response(serializer.data)
        
    @action(detail=True, methods=['post'])
    def responder(self, request, pk=None):
        oferta = self.get_object()
        nuevo_estado = request.data.get('estado')
        
        # Validar permisos (solo dueño del vehículo puede aceptar/rechazar)
        if oferta.vehiculo.cliente.usuario != request.user:
            return Response({"error": "Solo el dueño del vehículo puede responder"}, status=403)
            
        if nuevo_estado in ['aceptada', 'rechazada', 'contraoferta']:
            oferta.estado = nuevo_estado
            
            # Si se acepta, crear (o recuperar) la conversación
            if nuevo_estado == 'aceptada':
                from mecanimovilapp.apps.chat.models import Conversation
                from django.contrib.contenttypes.models import ContentType
                
                # Check if conversation already exists for this offer
                if not oferta.conversacion:
                    seller = oferta.vehiculo.cliente.usuario
                    buyer = oferta.comprador
                    
                    # Create with correct Type and Context
                    conversation = Conversation.objects.create(
                        type='MARKETPLACE',
                        content_type=ContentType.objects.get_for_model(oferta),
                        object_id=oferta.id
                    )
                    conversation.participants.add(seller, buyer)
                    
                    oferta.conversacion = conversation
            
            oferta.save()
            return Response(self.get_serializer(oferta).data)
        
        return Response({"error": "Estado inválido"}, status=400)
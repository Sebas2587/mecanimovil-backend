from rest_framework import serializers
from .models import Vehiculo, Marca, MarcaVehiculo, Modelo, OfertaVehiculo
from .models_health import ComponenteSalud, ComponenteSaludVehiculo, EstadoSaludVehiculo
from django.db.models import Q
from mecanimovilapp.apps.usuarios.serializers import ClienteSerializer


class MarcaVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo MarcaVehiculo
    """
    class Meta:
        model = MarcaVehiculo
        fields = ('id', 'nombre')


# Mantenemos el serializador Marca para compatibilidad
class MarcaSerializer(MarcaVehiculoSerializer):
    """
    Serializador para el modelo Marca (Proxy de MarcaVehiculo)
    """
    class Meta(MarcaVehiculoSerializer.Meta):
        model = Marca


class ModeloSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Modelo
    """
    marca_nombre = serializers.StringRelatedField(source='marca', read_only=True)
    
    class Meta:
        model = Modelo
        fields = ('id', 'nombre', 'marca', 'marca_nombre')


class VehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Vehiculo
    """
    cliente_detail = ClienteSerializer(source='cliente', read_only=True)
    marca_nombre = serializers.SerializerMethodField()
    modelo_nombre = serializers.SerializerMethodField()

    def get_marca_nombre(self, obj):
        return obj.marca.nombre if obj.marca else None

    def get_modelo_nombre(self, obj):
        return obj.modelo.nombre if obj.modelo else None
    
    # Mapeo de campos para compatibilidad con frontend
    año = serializers.ReadOnlyField(source='year')  # Mapear year -> año
    placa = serializers.ReadOnlyField(source='patente')  # Mapear patente -> placa
    
    # Campo foto: usar el campo del modelo directamente para escritura
    # Sobrescribir to_representation para devolver URL completa en lectura
    
    # Forzar campos como escritura explicita para evitar que sean ReadOnly implícitamente
    year = serializers.IntegerField(required=True)
    patente = serializers.CharField(max_length=20, required=True)
    
    # Campo adicional para inicialización inteligente (checklist)
    componentes_al_dia = serializers.ListField(
        child=serializers.IntegerField(), 
        write_only=True, 
        required=False
    )
    
    health_score = serializers.SerializerMethodField()
    health_report = serializers.SerializerMethodField()
    active_requests_count = serializers.SerializerMethodField()
    ofertas_activas_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehiculo
        fields = (
            'id', 'marca', 'modelo', 'cilindraje', 'tipo_motor', 
            'year', 'año', 'patente', 'placa', 'kilometraje', 'kilometraje_api', 'foto', 'cliente',
            'cliente_detail', 'marca_nombre', 'modelo_nombre',
            'color', 'numero_motor', 'vin',
            'fecha_creacion', 'fecha_actualizacion',
            'componentes_al_dia',
            'transmision', 'version', 'puertas', 'mes_revision_tecnica',
            # Appraisal Fields
            'tasacion_fiscal', 'permiso_circulacion', 'year_tasacion_fiscal',
            'precio_mercado_min', 'precio_mercado_max', 'precio_mercado_promedio',
            'precio_retoma', 'fecha_ultima_tasacion', 'precio_sugerido_final',
            'health_score',
            'active_requests_count',
            'ofertas_activas_count',
            'health_report'
        )
        extra_kwargs = {
            'cliente': {'write_only': True, 'required': False},
            'foto': {'required': False, 'allow_null': True}
        }
    
    def to_representation(self, instance):
        """
        Sobrescribir para devolver URL completa de foto en lectura
        """
        representation = super().to_representation(instance)
        # Reemplazar el valor de foto con la URL completa usando get_foto
        representation['foto'] = self.get_foto(instance)
        return representation
    
    def get_foto(self, obj):
        """Retorna la URL completa de la foto del vehículo usando cPanel si está configurado"""
        # Usar el helper centralizado para construir URLs
        from mecanimovilapp.storage.utils import get_image_url
        request = self.context.get('request')
        return get_image_url(obj.foto, request)
    
    def get_health_score(self, obj):
        # Usar snapshot de estado de salud si existe
        from .models_health import EstadoSaludVehiculo
        snapshot = EstadoSaludVehiculo.objects.filter(vehiculo=obj).first() # Ordering is -fecha_calculo by default
        if snapshot:
            return int(snapshot.salud_general_porcentaje)
        return 0

    def get_health_report(self, obj):
        # Construir reporte basado en componentes persistidos
        # Esto es más rápido que recalcular todo el motor
        from .models_health import ComponenteSaludVehiculo
        
        comps = ComponenteSaludVehiculo.objects.filter(vehiculo=obj).select_related('componente')
        report = []
        for c in comps:
             report.append({
                'componente': c.componente.nombre,
                'slug': c.componente.slug,
                'salud': c.salud_porcentaje,
                'status': c.nivel_alerta,
                'vida_util_total': c.vida_util_proyectada,
                'es_especifica': c.es_regla_especifica,
                'mensaje_alerta': c.mensaje_alerta
             })
        return report

    def get_active_requests_count(self, obj):
        """Retorna el número de solicitudes activas para este vehículo"""
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        return SolicitudServicio.objects.filter(
            vehiculo=obj,
            estado__in=['pendiente', 'aceptado', 'en_camino', 'en_progreso']
        ).count()

    def get_ofertas_activas_count(self, obj):
        """Retorna el número de ofertas activas para solicitudes de este vehículo"""
        from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, OfertaProveedor
        from django.db.models import Count
        
        # Contar ofertas activas en solicitudes públicas de este vehículo
        # que están en estado 'abierta' (esperando ofertas o comparando)
        # Contar ofertas activas (no rechazadas) en solicitudes públicas activas
        count = OfertaProveedor.objects.filter(
            solicitud__vehiculo=obj,
            solicitud__estado__in=['abierta', 'comparando', 'adjudicada'],
        ).exclude(
            estado='rechazada'
        ).count()
        
        return count

    
    def validate(self, data):
        """
        Validar que el modelo pertenezca a la marca
        """
        if 'marca' in data and 'modelo' in data:
            if data['modelo'].marca != data['marca']:
                raise serializers.ValidationError(
                    {"modelo": "El modelo seleccionado no pertenece a la marca indicada."}
                )
        return data
    
    def create(self, validated_data):
        """
        Crear vehículo asegurando que la foto use el storage correcto (cPanel)
        """
        import logging
        from django.conf import settings
        
        logger = logging.getLogger(__name__)
        
        logger.info(f"🚗 Creating Vehicle with data keys: {validated_data.keys()}")
        logger.info(f"🚗 Detailed specs received: VIN={validated_data.get('vin')}, Motor={validated_data.get('numero_motor')}, Version={validated_data.get('version')}")

        # Extraer la lista de componentes al día
        componentes_al_dia = validated_data.pop('componentes_al_dia', [])
        # Extraer la foto si existe
        foto_file = validated_data.pop('foto', None)
        
        # Crear el vehículo sin la foto primero
        vehiculo = Vehiculo.objects.create(**validated_data)
        
        # Si hay una foto, guardarla usando el storage correcto
        if foto_file:
            storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            if storage_class:
                from django.utils.module_loading import import_string
                try:
                    storage = import_string(storage_class)()
                    filename = storage.save(foto_file.name, foto_file)
                    vehiculo.foto = filename
                    vehiculo.save()
                    logger.info(f"✅ Foto de vehículo {vehiculo.id} guardada en storage: {filename}")
                except Exception as e:
                    logger.error(f"❌ Error guardando foto de vehículo: {e}")
                    vehiculo.foto = foto_file
                    vehiculo.save()
            else:
                vehiculo.foto = foto_file
                vehiculo.save()
        
        # --- INICIALIZACIÓN INTELIGENTE DE SALUD ---
        # 3. Inicialización inteligente delegada a Health Engine (Async)
        # Ya no creamos componentes estáticamente aquí.
        # La tarea asíncrona se encargará de:
        # - Detectar motor y reglas
        # - Crear componentes iniciales
        # - Calcular salud
        
        # 3.5. Invocar tarea asíncrona para calcular salud general y alertas
        # Esto asegura que se genere un EstadoSaludVehiculo y se actualicen métricas globales
        from mecanimovilapp.apps.vehiculos.tasks import calcular_salud_vehiculo_async
        calcular_salud_vehiculo_async.delay(vehiculo.id)
        logger.info(f"🚀 Tarea de cálculo de salud disparada para vehículo {vehiculo.id}")

            # 4. Obtener Tasación y Valoración (GetAPI)
        try:
            import requests
            from django.utils import timezone
            from mecanimovilapp.apps.marketplace.valuation_engine import calculate_suggested_price
            
            API_KEY = "28054a51-09f6-4687-a4a7-ecf3ead55ef4"
            URL_APPRAISAL = f"https://chile.getapi.cl/v1/vehicles/appraisal/{vehiculo.patente}"
            
            logger.info(f"💰 Consultando tasación para {vehiculo.patente}")
            
            headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}
            response = requests.get(URL_APPRAISAL, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # data = { success: true, data: { vehicleId: ..., informacionFiscal: {...}, precioUsado: {...}, ... } }
                
                if data.get("success") is not False:
                    appraisal_data = data.get("data", {})
                    
                    info_fiscal = appraisal_data.get("informacionFiscal", {})
                    precio_usado = appraisal_data.get("precioUsado", {})
                    
                    # Actualizar campos
                    vehiculo.tasacion_fiscal = int(info_fiscal.get("tasacion", 0) or 0)
                    vehiculo.permiso_circulacion = int(info_fiscal.get("permiso", 0) or 0)
                    vehiculo.year_tasacion_fiscal = int(info_fiscal.get("ano_info_fiscal", 0) or 0)
                    
                    vehiculo.precio_mercado_min = int(precio_usado.get("banda_min", 0) or 0)
                    vehiculo.precio_mercado_max = int(precio_usado.get("banda_max", 0) or 0)
                    vehiculo.precio_mercado_promedio = int(precio_usado.get("precio", 0) or 0)
                    
                    vehiculo.precio_retoma = int(appraisal_data.get("precioRetoma", 0) or 0)
                    vehiculo.fecha_ultima_tasacion = timezone.now()
                    
                    # CALCULAR PRECIO SUGERIDO (ALGORITMO MAESTRO)
                    vehiculo.precio_sugerido_final = calculate_suggested_price(
                        vehiculo,
                        precio_mercado=vehiculo.precio_mercado_promedio,
                        precio_fiscal=vehiculo.tasacion_fiscal
                    )
                    
                    vehiculo.save(update_fields=[
                        'tasacion_fiscal', 'permiso_circulacion', 'year_tasacion_fiscal',
                        'precio_mercado_min', 'precio_mercado_max', 'precio_mercado_promedio',
                        'precio_retoma', 'fecha_ultima_tasacion', 'precio_sugerido_final'
                    ])
                    
                    logger.info(f"✅ Tasación guardada. Precio Sugerido: {vehiculo.precio_sugerido_final}")
                else:
                    logger.warning(f"⚠️ Tasación no exitosa en API: {data.get('message')}")
            else:
                logger.warning(f"⚠️ Error HTTP al consultar tasación: {response.status_code}")
                
        except Exception as e:
            logger.error(f"❌ Error obteniendo tasación: {e}")

        # End of create method
        
        return vehiculo
    
    def update(self, instance, validated_data):
        """
        Actualizar vehículo asegurando que la foto use el storage correcto (cPanel)
        """
        import logging
        from django.conf import settings
        
        logger = logging.getLogger(__name__)
        
        # Extraer la foto si existe
        foto_file = validated_data.pop('foto', None)
        
        # Actualizar otros campos
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Si hay una nueva foto, guardarla usando el storage correcto
        if foto_file:
            # Eliminar la foto anterior si existe
            if instance.foto:
                try:
                    instance.foto.delete()
                except:
                    pass
            
            storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            if storage_class:
                from django.utils.module_loading import import_string
                try:
                    storage = import_string(storage_class)()
                    filename = storage.save(foto_file.name, foto_file)
                    instance.foto = filename
                    logger.info(f"✅ Foto de vehículo {instance.id} actualizada: {filename}")
                except Exception as e:
                    logger.error(f"❌ Error actualizando foto de vehículo: {e}")
                    instance.foto = foto_file
            else:
                instance.foto = foto_file
        
        # Recalcular valoración si cambia el precio de mercado
        if 'precio_mercado_promedio' in validated_data:
            from mecanimovilapp.apps.marketplace.valuation_engine import calculate_suggested_price
            
            # Si se actualiza el precio de mercado manual y no hay tasación fiscal,
            # asumimos la misma base para evitar devaluación artificial
            if instance.tasacion_fiscal == 0 or not instance.tasacion_fiscal:
                instance.tasacion_fiscal = instance.precio_mercado_promedio
                
            instance.precio_sugerido_final = calculate_suggested_price(
                instance,
                precio_mercado=instance.precio_mercado_promedio,
                precio_fiscal=instance.tasacion_fiscal
            )
            logger.info(f"🔄 Recalculando valor sugerido: {instance.precio_sugerido_final}")

        instance.save()
        return instance


class VehiculoLiteSerializer(serializers.ModelSerializer):
    """
    Serializador ligero para listas de vehículos.
    Excluye cliente_detail y otros campos pesados para optimizar la respuesta.
    """
    marca_nombre = serializers.CharField(source='marca.nombre', read_only=True)
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    
    # Mapeo de campos para compatibilidad con frontend
    año = serializers.ReadOnlyField(source='year')  # Mapear year -> año
    placa = serializers.ReadOnlyField(source='patente')  # Mapear patente -> placa
    
    # Campos adicionales que pueden no estar en el modelo pero el frontend espera
    color = serializers.SerializerMethodField()
    numero_motor = serializers.SerializerMethodField()
    numero_chasis = serializers.SerializerMethodField()
    active_requests_count = serializers.SerializerMethodField()
    ofertas_activas_count = serializers.SerializerMethodField()
    health_score = serializers.SerializerMethodField()
    pending_alerts_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehiculo
        fields = (
            'id', 'marca', 'modelo', 'cilindraje', 'tipo_motor', 
            'year', 'año', 'patente', 'placa', 'kilometraje', 'foto',
            'marca_nombre', 'modelo_nombre',
            'color', 'numero_motor', 'numero_chasis',
            'fecha_creacion', 'fecha_actualizacion',
            'precio_mercado_promedio', 'precio_sugerido_final',
            'active_requests_count',
            'ofertas_activas_count',
            'health_score', 'pending_alerts_count'
        )
        read_only_fields = fields
    
    def to_representation(self, instance):
        """
        Sobrescribir para devolver URL completa de foto en lectura
        """
        representation = super().to_representation(instance)
        # Reemplazar el valor de foto con la URL completa usando get_foto
        representation['foto'] = self.get_foto(instance)
        return representation
    
    def get_foto(self, obj):
        """Retorna la URL completa de la foto del vehículo usando cPanel si está configurado"""
        from mecanimovilapp.storage.utils import get_image_url
        request = self.context.get('request')
        return get_image_url(obj.foto, request)
    
    def get_color(self, obj):
        """Retorna el color del vehículo si está disponible"""
        return getattr(obj, 'color', None)
    
    def get_numero_motor(self, obj):
        """Retorna el número de motor si está disponible"""
        return getattr(obj, 'numero_motor', None)
    
    def get_numero_chasis(self, obj):
        """Retorna el número de chasis si está disponible"""
        return getattr(obj, 'numero_chasis', None)
    
    def get_active_requests_count(self, obj):
        """Retorna el número de solicitudes activas para este vehículo"""
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        return SolicitudServicio.objects.filter(
            vehiculo=obj,
            estado__in=['pendiente', 'aceptado', 'en_camino', 'en_progreso']
        ).count()

    def get_ofertas_activas_count(self, obj):
        """Retorna el número de ofertas activas para solicitudes de este vehículo"""
        from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, OfertaProveedor
        
        # Contar ofertas activas (no rechazadas) en solicitudes públicas activas
        count = OfertaProveedor.objects.filter(
            solicitud__vehiculo=obj,
            solicitud__estado__in=['abierta', 'comparando', 'adjudicada'],
        ).exclude(
            estado='rechazada'
        ).count()
        
        return count

    def get_health_score(self, obj):
        """Retorna el puntaje promedio de salud del vehículo"""
        from django.db.models import Avg
        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludVehiculo
        
        avg_health = ComponenteSaludVehiculo.objects.filter(vehiculo=obj).aggregate(Avg('salud_porcentaje'))['salud_porcentaje__avg']
        
        if avg_health is not None:
            return int(avg_health)
            
        # Si no hay componentes reportados, NO asumir 100%.
        # Retornar 0 indica que falta inicialización o datos.
        return 0

    def get_pending_alerts_count(self, obj):
        """Retorna el número de componentes en estado crítico o advertencia"""
        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludVehiculo
        
        # Contamos componentes que requieren atención inmediata o próxima
        return ComponenteSaludVehiculo.objects.filter(
            vehiculo=obj, 
            nivel_alerta__in=['ATENCION', 'URGENTE', 'CRITICO']
        ).count()


class VehiculoMarketplaceSerializer(serializers.ModelSerializer):
    """
    Serializador específico para la gestión de venta en Marketplace
    """
    health_bonus_percentage = serializers.SerializerMethodField()
    suggested_price = serializers.IntegerField(source='precio_sugerido_final', read_only=True)
    marca_nombre = serializers.ReadOnlyField()
    modelo_nombre = serializers.ReadOnlyField()
    year = serializers.ReadOnlyField()
    foto_url = serializers.SerializerMethodField()
    health_score = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    is_reserved = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehiculo
        fields = (
            'id', 'is_published', 'precio_venta', 'suggested_price',
            'health_bonus_percentage', 'views_count', 'favorites_count', 'leads_count',
            'marca_nombre', 'modelo_nombre', 'year', 'foto_url', 'health_score',
            'seller', 'cilindraje', 'tipo_motor', 'kilometraje', 'color', 'transmision',
            'vin', 'numero_motor', 'version', 'puertas', 'mes_revision_tecnica',
            'is_reserved'
        )
        read_only_fields = ('suggested_price', 'views_count', 'favorites_count', 'leads_count', 'health_bonus_percentage', 'health_score', 'seller', 'is_reserved')

    def get_is_reserved(self, obj):
        # A vehicle is reserved if it has any accepted offer
        # We use the reversed relationship 'ofertas_recibidas'
        return obj.ofertas_recibidas.filter(estado='aceptada').exists()

    def get_seller(self, obj):
        """Retorna información básica del vendedor"""
        if hasattr(obj, 'cliente') and obj.cliente and hasattr(obj.cliente, 'usuario'):
            user = obj.cliente.usuario
            
            # Obtener URL de foto de perfil
            foto_url = None
            # Check various potential photo fields
            if hasattr(user, 'foto_perfil') and user.foto_perfil:
                from mecanimovilapp.storage.utils import get_image_url
                request = self.context.get('request')
                foto_url = get_image_url(user.foto_perfil, request)
            elif hasattr(user, 'foto_perfil_url') and user.foto_perfil_url:
                foto_url = user.foto_perfil_url
                
            return {
                'id': user.id,
                'nombre': f"{user.first_name} {user.last_name}".strip() or user.username,
                'foto_url': foto_url
            }


    def get_foto_url(self, obj):
        from mecanimovilapp.storage.utils import get_image_url
        request = self.context.get('request')
        return get_image_url(obj.foto, request)
    
    def get_health_score(self, obj):
        # Calcular promedio de salud de componentes
        from .models_health import ComponenteSaludVehiculo
        from django.db.models import Avg
        
        avg_health = ComponenteSaludVehiculo.objects.filter(vehiculo=obj).aggregate(Avg('salud_porcentaje'))['salud_porcentaje__avg']
        
        if avg_health is not None:
            return int(avg_health)
        return 0 # Default para nuevos vehículos sin datos (evita falso 100%)

    def get_health_bonus_percentage(self, obj):
        # We repurpose this field to return the Monetary Value of Potential Gain for now, 
        # or we might want to rename it in the frontend. 
        # Given the legacy name implies percentage, let's keep likely consistent for now 
        # or better: Return the actual value if frontend expects value OR percent.
        # User prompt implies "obtener el potencial de ganancia".
        
        from mecanimovilapp.apps.marketplace.valuation_engine import calculate_potential_gain
        return calculate_potential_gain(obj)


class VehiculoMarketplaceDetailSerializer(VehiculoMarketplaceSerializer):
    """
    Serializador detallado para la vista pública de un vehículo en marketplace.
    Incluye historial de servicios.
    """
    history = serializers.SerializerMethodField()
    
    class Meta(VehiculoMarketplaceSerializer.Meta):
        fields = VehiculoMarketplaceSerializer.Meta.fields + ('history',)
        read_only_fields = VehiculoMarketplaceSerializer.Meta.read_only_fields + ('history',)
        
    def get_history(self, obj):
        # Obtener solicitudes completadas asociados al vehículo
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        solicitudes = SolicitudServicio.objects.filter(vehiculo=obj, estado='completado').order_by('-fecha_servicio')
        
        history_data = []
        for sol in solicitudes:
            # Determinar el nombre del servicio real desde las líneas
            service_name = "Servicio General"
            
            # Intentar obtener servicio desde lineas (lo más común en historial completado)
            first_line = sol.lineas.first()
            if first_line:
                if first_line.oferta_servicio and first_line.oferta_servicio.servicio:
                    service_name = first_line.oferta_servicio.servicio.nombre
                # Si hay más de una línea, podríamos agregar un indicador " + otros"
                if sol.lineas.count() > 1:
                    service_name += " y otros"

            # Obtener proveedor y avatar
            provider_name = "MecaniMóvil Provider"
            provider_avatar = None
            provider_type = 'mecanico'

            from mecanimovilapp.storage.utils import get_image_url
            request = self.context.get('request')

            if sol.taller:
                provider_name = sol.taller.nombre
                provider_type = 'taller'
                if sol.taller.logo:
                    provider_avatar = get_image_url(sol.taller.logo, request)
            elif sol.mecanico:
                provider_name = f"{sol.mecanico.usuario.first_name} {sol.mecanico.usuario.last_name}"
                provider_type = 'mecanico'
                if sol.mecanico.usuario.foto_perfil:
                    provider_avatar = get_image_url(sol.mecanico.usuario.foto_perfil, request)
                elif hasattr(sol.mecanico.usuario, 'foto_perfil_url') and sol.mecanico.usuario.foto_perfil_url:
                     provider_avatar = sol.mecanico.usuario.foto_perfil_url
            
            history_data.append({
                'id': sol.id,
                'date': sol.fecha_servicio.strftime('%d %b %Y'),
                'service_name': service_name,
                'provider_name': provider_name,
                'provider_avatar': provider_avatar,
                'provider_type': provider_type,
                'verified': True,
                'mileage': f"{obj.kilometraje} km", # Fallback: Historical mileage logic needed in future
                'cost': sol.total # Adding total cost of the service
            })
            
        return history_data

    # Add health_details field
    health_details = serializers.SerializerMethodField()
    
    class Meta(VehiculoMarketplaceSerializer.Meta):
        fields = VehiculoMarketplaceSerializer.Meta.fields + ('history', 'health_details')
        read_only_fields = VehiculoMarketplaceSerializer.Meta.read_only_fields + ('history', 'health_details')

    def get_health_details(self, obj):
        from .models_health import ComponenteSaludVehiculo
        # Obtener todos los componentes del vehículo
        componentes = ComponenteSaludVehiculo.objects.filter(vehiculo=obj).select_related('componente')
        
        details = []
        for comp in componentes:
            # Skip if component relation is missing (prevent crash)
            if not comp.componente:
                continue
                
            # Determinar estado basado en porcentaje (fallback logic matches frontend)
            status = 'normal'
            if comp.salud_porcentaje < 40:
                status = 'critical'
            elif comp.salud_porcentaje < 70:
                status = 'warning'
                
            details.append({
                'id': comp.componente.id,
                'name': comp.componente.nombre,
                'nombre': comp.componente.nombre, # Dual support for frontend
                'score': int(comp.salud_porcentaje),
                'salud_porcentaje': int(comp.salud_porcentaje), # Dual support
                'status': status,
                'nivel_alerta': comp.nivel_alerta, 
                'nivel_alerta_display': comp.get_nivel_alerta_display(),
                'km_ultimo_servicio': comp.km_ultimo_servicio,
                'km_estimados_restantes': comp.km_estimados_restantes,
                'mensaje_alerta': comp.mensaje_alerta,
                'category': 'General'
            })
            
        return details


class OfertaVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para las ofertas de vehículos
    """
    comprador_nombre = serializers.ReadOnlyField(source='comprador.first_name')
    comprador_apellido = serializers.ReadOnlyField(source='comprador.last_name')
    comprador_foto = serializers.SerializerMethodField()
    
    # Datos planos del vehículo para fácil visualización
    vehiculo_marca = serializers.ReadOnlyField(source='vehiculo.marca.nombre')
    vehiculo_modelo = serializers.ReadOnlyField(source='vehiculo.modelo.nombre')
    vehiculo_year = serializers.ReadOnlyField(source='vehiculo.year')
    vehiculo_imagen = serializers.SerializerMethodField()
    vehiculo_precio = serializers.ReadOnlyField(source='vehiculo.precio_venta')

    # Datos del vendedor (para ofertas enviadas)
    vendedor_id = serializers.ReadOnlyField(source='vehiculo.cliente.usuario.id')
    vendedor_nombre = serializers.ReadOnlyField(source='vehiculo.cliente.usuario.first_name')
    vendedor_apellido = serializers.ReadOnlyField(source='vehiculo.cliente.usuario.last_name')
    vendedor_foto = serializers.SerializerMethodField()
    vendedor_foto = serializers.SerializerMethodField()
    conversacion_id = serializers.SerializerMethodField()

    class Meta:
        model = OfertaVehiculo
        fields = [
            'id', 'vehiculo', 'comprador', 'monto', 'mensaje', 'estado', 
            'fecha_creacion', 'fecha_actualizacion',
            'comprador_nombre', 'comprador_apellido', 'comprador_foto',
            'vendedor_id', 'vendedor_nombre', 'vendedor_apellido', 'vendedor_foto',
            'vehiculo_marca', 'vehiculo_modelo', 'vehiculo_year', 'vehiculo_imagen', 'vehiculo_precio',
            'conversacion_id'
        ]
        read_only_fields = ['comprador', 'fecha_creacion', 'fecha_actualizacion']

    def get_conversacion_id(self, obj):
        # Self-healing: If accepted but no conversation, create it now
        if obj.estado == 'aceptada' and not obj.conversacion:
            try:
                from mecanimovilapp.apps.chat.models import Conversation
                from django.contrib.contenttypes.models import ContentType
                
                # Double check to prevent race conditions or duplicates
                if not obj.conversacion:
                    seller = obj.vehiculo.cliente.usuario
                    buyer = obj.comprador
                    
                    conversation = Conversation.objects.create(
                        type='MARKETPLACE',
                        content_type=ContentType.objects.get_for_model(obj),
                        object_id=obj.id
                    )
                    conversation.participants.add(seller, buyer)
                    
                    obj.conversacion = conversation
                    obj.save(update_fields=['conversacion'])
            except Exception as e:
                # Log error silently, return None
                print(f"Error auto-healing conversation for offer {obj.id}: {e}")
                return None
                
        return obj.conversacion.id if obj.conversacion else None


    def get_comprador_foto(self, obj):
        from mecanimovilapp.storage.utils import get_image_url
        request = self.context.get('request')
        if obj.comprador and obj.comprador.foto_perfil:
            return get_image_url(obj.comprador.foto_perfil, request)
        return None

    def get_vehiculo_imagen(self, obj):
        from mecanimovilapp.storage.utils import get_image_url
        request = self.context.get('request')
        if obj.vehiculo and obj.vehiculo.foto:
            return get_image_url(obj.vehiculo.foto, request)
        return None

    def get_vendedor_foto(self, obj):
        from mecanimovilapp.storage.utils import get_image_url
        request = self.context.get('request')
        if obj.vehiculo and obj.vehiculo.cliente and obj.vehiculo.cliente.usuario and obj.vehiculo.cliente.usuario.foto_perfil:
             return get_image_url(obj.vehiculo.cliente.usuario.foto_perfil, request)
        return None
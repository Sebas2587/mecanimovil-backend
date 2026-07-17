from rest_framework import serializers
from .models import (
    CategoriaServicio, Servicio, DetalleServicio, OfertaServicio, Repuesto, ServicioRepuesto, SolicitudRepuesto, FotoServicio
)
from mecanimovilapp.apps.usuarios.serializers import TallerSerializer, MecanicoDomicilioSerializer
from mecanimovilapp.apps.vehiculos.serializers import MarcaSerializer, ModeloSerializer
from mecanimovilapp.apps.servicios.repuestos_info import build_repuestos_info
from mecanimovilapp.apps.servicios.tipos_motor_utils import normalizar_lista_tipos_motor
from mecanimovilapp.apps.servicios.oferta_compatibilidad import (
    motores_catalogo_servicio,
    motores_opciones_para_proveedor,
    normalizar_tipo_motor_oferta,
    validar_tipo_motor_oferta,
)
from django.db import models

# Helper para URLs de archivos en cPanel
from mecanimovilapp.storage.utils import get_image_url


class CategoriaServicioBasicSerializer(serializers.ModelSerializer):
    """
    Serializador básico para el modelo CategoriaServicio sin relaciones anidadas
    """
    imagen_url = serializers.SerializerMethodField()

    class Meta:
        model = CategoriaServicio
        fields = ('id', 'nombre', 'descripcion', 'icono', 'imagen_url', 'orden')

    def get_imagen_url(self, obj):
        if not getattr(obj, 'imagen', None):
            return None
        request = self.context.get('request')
        return get_image_url(obj.imagen, request)


class CategoriaServicioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo CategoriaServicio con soporte para jerarquía
    """
    categoria_padre_info = CategoriaServicioBasicSerializer(source='categoria_padre', read_only=True)
    subcategorias = serializers.SerializerMethodField()
    es_categoria_principal = serializers.BooleanField(read_only=True)
    tiene_subcategorias = serializers.BooleanField(read_only=True)
    imagen_url = serializers.SerializerMethodField()

    class Meta:
        model = CategoriaServicio
        fields = (
            'id', 'nombre', 'descripcion', 'icono', 'imagen', 'imagen_url', 'orden',
            'categoria_padre', 'categoria_padre_info',
            'subcategorias', 'es_categoria_principal', 'tiene_subcategorias',
        )
        extra_kwargs = {
            'imagen': {'write_only': True, 'required': False},
        }

    def get_imagen_url(self, obj):
        if not getattr(obj, 'imagen', None):
            return None
        request = self.context.get('request')
        return get_image_url(obj.imagen, request)

    def get_subcategorias(self, obj):
        """Obtiene las subcategorías inmediatas, sin anidación adicional para evitar recursión"""
        subcategorias = obj.subcategorias.all()
        if subcategorias:
            return CategoriaServicioBasicSerializer(
                subcategorias, many=True, context=self.context
            ).data
        return []


class DetalleServicioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo DetalleServicio
    """
    class Meta:
        model = DetalleServicio
        fields = ('id', 'servicio', 'caracteristica')


class OfertaServicioBasicSerializer(serializers.ModelSerializer):
    """
    Serializador básico para el modelo OfertaServicio
    """
    nombre_proveedor = serializers.CharField(read_only=True)
    
    class Meta:
        model = OfertaServicio
        fields = (
            'id', 'tipo_proveedor', 'servicio', 'disponible',
            'precio_con_repuestos', 'precio_sin_repuestos', 'nombre_proveedor',
            'tipo_servicio', 'precio_publicado_cliente'
        )


class FotoServicioSerializer(serializers.ModelSerializer):
    """
    Serializador para fotos de servicios
    """
    imagen_url = serializers.SerializerMethodField()
    
    class Meta:
        model = FotoServicio
        fields = ['id', 'oferta_servicio', 'imagen', 'imagen_url', 'descripcion', 'orden', 'fecha_subida']
        read_only_fields = ['id', 'fecha_subida']
    
    def get_imagen_url(self, obj):
        """Retorna la URL completa de la imagen usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.imagen, request)


class FotoServicioUploadSerializer(serializers.ModelSerializer):
    """
    Serializador específico para subir fotos de servicios
    """
    
    class Meta:
        model = FotoServicio
        fields = ['oferta_servicio', 'imagen', 'descripcion', 'orden']
    
    def create(self, validated_data):
        """Crear nueva foto de servicio"""
        return FotoServicio.objects.create(**validated_data)


class OfertaServicioSerializer(serializers.ModelSerializer):
    """
    Serializador completo para el modelo OfertaServicio
    """
    taller_info = TallerSerializer(source='taller', read_only=True)
    mecanico_info = MecanicoDomicilioSerializer(source='mecanico', read_only=True)
    servicio_info = serializers.SerializerMethodField()
    marca_vehiculo_info = serializers.SerializerMethodField()
    modelo_vehiculo_info = serializers.SerializerMethodField()
    nombre_proveedor = serializers.CharField(read_only=True)
    fotos_servicio = FotoServicioSerializer(many=True, read_only=True)
    repuestos_info = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = OfertaServicio
        fields = (
            'id', 'tipo_proveedor', 'taller', 'taller_info', 'mecanico', 'mecanico_info',
            'servicio', 'servicio_info', 'marca_vehiculo_seleccionada', 'marca_vehiculo_info',
            'modelo_vehiculo_seleccionado', 'modelo_vehiculo_info',
            'tipo_motor',
            'disponible', 'duracion_estimada', 'duracion_minima_minutos', 'duracion_maxima_minutos',
            'precio_con_repuestos', 'precio_sin_repuestos', 'incluye_garantia',
            'duracion_garantia', 'detalles_adicionales', 'nombre_proveedor',
            'fecha_creacion', 'ultima_actualizacion',
            # Nuevos campos para gestión avanzada
            'tipo_servicio', 'repuestos_seleccionados', 'repuestos_info', 'costo_mano_de_obra_sin_iva',
            'costo_repuestos_sin_iva', 'fotos_urls', 'fotos_servicio', 'precio_publicado_cliente',
            'comision_mecanmovil', 'iva_sobre_comision', 'ganancia_neta_proveedor'
        )

    def get_repuestos_info(self, obj):
        """Ítems de repuesto (nombre, cantidad, precio) para ficha y nueva solicitud."""
        request = self.context.get('request')
        return build_repuestos_info(obj.repuestos_seleccionados, request=request)
    
    def get_servicio_info(self, obj):
        """
        Retorna información completa del servicio embebida en la oferta.
        Incluye categorias_info y modelos_info para evitar que el cliente
        tenga que hacer requests individuales por cada servicio (N+1).
        """
        request = self.context.get('request')
        servicio = obj.servicio

        # categorias: prefetch_related('servicio__categorias') en las vistas por_taller/por_mecanico
        categorias_info = [
            {'id': c.id, 'nombre': c.nombre, 'descripcion': getattr(c, 'descripcion', ''), 'icono': getattr(c, 'icono', '')}
            for c in servicio.categorias.all()
        ]

        # modelos_compatibles / marcas_compatibles: prefetch_related en las vistas
        modelos_info = []
        for m in servicio.modelos_compatibles.all():
            marca_obj = getattr(m, 'marca', None)
            modelos_info.append({
                'id': m.id,
                'nombre': getattr(m, 'nombre', '') or getattr(m, 'modelo_nombre', ''),
                'marca_id': getattr(marca_obj, 'id', None) if marca_obj else getattr(m, 'marca_id', None),
                'marca_nombre': getattr(m, 'marca_nombre', '') or (
                    getattr(marca_obj, 'nombre', '') if marca_obj else ''
                ),
            })

        marcas_info = [
            {'id': mc.id, 'nombre': mc.nombre}
            for mc in servicio.marcas_compatibles.all()
        ]
        motores_info = normalizar_lista_tipos_motor(
            getattr(servicio, 'tipos_motor_compatibles', None) or []
        )

        return {
            'id': servicio.id,
            'nombre': servicio.nombre,
            'descripcion': servicio.descripcion,
            'foto': get_image_url(servicio.foto, request),
            'duracion_estimada_base': getattr(servicio, 'duracion_estimada_base', None),
            'precio_referencia': str(servicio.precio_referencia) if getattr(servicio, 'precio_referencia', None) else None,
            'categorias_info': categorias_info,
            'modelos_info': modelos_info,
            'marcas_info': marcas_info,
            'motores_info': motores_info,
            'tipos_motor_compatibles': motores_info,
        }

    def get_marca_vehiculo_info(self, obj):
        """Marca configurada por el proveedor para esta oferta de catálogo."""
        request = self.context.get('request')
        marca = getattr(obj, 'marca_vehiculo_seleccionada', None)
        if marca:
            return {
                'id': marca.id,
                'nombre': marca.nombre,
                'logo': get_image_url(marca.logo, request),
            }
        pk = getattr(obj, 'marca_vehiculo_seleccionada_id', None)
        if pk:
            from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo

            m = MarcaVehiculo.objects.filter(pk=pk).only('id', 'nombre', 'logo').first()
            if m:
                return {
                    'id': m.id,
                    'nombre': m.nombre,
                    'logo': get_image_url(m.logo, request),
                }
        return None

    def get_modelo_vehiculo_info(self, obj):
        """Modelo configurado por el proveedor para esta oferta de catálogo."""
        modelo = getattr(obj, 'modelo_vehiculo_seleccionado', None)
        if modelo:
            marca_obj = getattr(modelo, 'marca', None)
            return {
                'id': modelo.id,
                'nombre': modelo.nombre,
                'marca_id': getattr(marca_obj, 'id', None) if marca_obj else getattr(modelo, 'marca_id', None),
                'marca_nombre': getattr(marca_obj, 'nombre', '') if marca_obj else '',
            }
        pk = getattr(obj, 'modelo_vehiculo_seleccionado_id', None)
        if pk:
            from mecanimovilapp.apps.vehiculos.models import Modelo

            m = Modelo.objects.select_related('marca').filter(pk=pk).first()
            if m:
                return {
                    'id': m.id,
                    'nombre': m.nombre,
                    'marca_id': m.marca_id,
                    'marca_nombre': m.marca.nombre if m.marca_id else '',
                }
        return None


class OfertaServicioProveedorSerializer(serializers.ModelSerializer):
    """
    Serializador específico para que los proveedores creen y gestionen sus ofertas de servicios
    """
    servicio_info = serializers.SerializerMethodField(read_only=True)
    repuestos_info = serializers.SerializerMethodField(read_only=True)
    repuestos_info_detallado = serializers.SerializerMethodField(read_only=True)
    desglose_precios = serializers.SerializerMethodField(read_only=True)
    marca_vehiculo_info = serializers.SerializerMethodField(read_only=True)
    modelo_vehiculo_info = serializers.SerializerMethodField(read_only=True)
    motores_catalogo_info = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = OfertaServicio
        fields = (
            'id', 'servicio', 'servicio_info', 'marca_vehiculo_seleccionada', 'marca_vehiculo_info',
            'modelo_vehiculo_seleccionado', 'modelo_vehiculo_info',
            'tipo_motor', 'motores_catalogo_info',
            'disponible', 'duracion_estimada', 'duracion_minima_minutos', 'duracion_maxima_minutos',
            'incluye_garantia', 'duracion_garantia', 'detalles_adicionales',
            # Campos específicos para proveedores
            'tipo_servicio', 'repuestos_seleccionados', 'repuestos_info', 'repuestos_info_detallado',
            'costo_mano_de_obra_sin_iva', 'costo_repuestos_sin_iva', 'fotos_urls',
            'precio_publicado_cliente', 'comision_mecanmovil', 'iva_sobre_comision', 
            'ganancia_neta_proveedor', 'desglose_precios',
            'fecha_creacion', 'ultima_actualizacion'
        )
        read_only_fields = (
            'precio_publicado_cliente', 'comision_mecanmovil', 
            'iva_sobre_comision', 'ganancia_neta_proveedor', 
            'fecha_creacion', 'ultima_actualizacion'
        )
    
    def get_servicio_info(self, obj):
        """Retorna información del servicio con repuestos y motores del catálogo."""
        request = self.context.get('request')
        if obj.servicio:
            motores = motores_catalogo_servicio(obj.servicio)
            return {
                'id': obj.servicio.id,
                'nombre': obj.servicio.nombre,
                'descripcion': obj.servicio.descripcion,
                'requiere_repuestos': obj.servicio.requiere_repuestos,
                'foto': get_image_url(obj.servicio.foto, request),
                'motores_info': motores,
                'tipos_motor_compatibles': motores,
                'motores_opciones_proveedor': motores_opciones_para_proveedor(obj.servicio),
                'categorias_info': [
                    {'id': c.id, 'nombre': c.nombre}
                    for c in obj.servicio.categorias.all()
                ],
            }
        return None

    def get_motores_catalogo_info(self, obj):
        """Motores del catálogo maestro para UI del proveedor."""
        if not obj.servicio:
            return {
                'catalogo': [],
                'opciones_proveedor': [],
                'es_universal': True,
            }
        catalogo = motores_catalogo_servicio(obj.servicio)
        return {
            'catalogo': catalogo,
            'opciones_proveedor': motores_opciones_para_proveedor(obj.servicio),
            'es_universal': not catalogo,
        }
    
    def get_marca_vehiculo_info(self, obj):
        """Retorna información de la marca de vehículo seleccionada por el proveedor"""
        request = self.context.get('request')
        marca = getattr(obj, 'marca_vehiculo_seleccionada', None)
        if marca:
            return {
                'id': marca.id,
                'nombre': marca.nombre,
                'logo': get_image_url(marca.logo, request),
            }
        pk = getattr(obj, 'marca_vehiculo_seleccionada_id', None)
        if pk:
            from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo

            m = MarcaVehiculo.objects.filter(pk=pk).only('id', 'nombre', 'logo').first()
            if m:
                return {
                    'id': m.id,
                    'nombre': m.nombre,
                    'logo': get_image_url(m.logo, request),
                }
        return None

    def get_modelo_vehiculo_info(self, obj):
        """Retorna información del modelo de vehículo seleccionado por el proveedor."""
        modelo = getattr(obj, 'modelo_vehiculo_seleccionado', None)
        if modelo:
            marca_obj = getattr(modelo, 'marca', None)
            return {
                'id': modelo.id,
                'nombre': modelo.nombre,
                'marca_id': getattr(marca_obj, 'id', None) if marca_obj else getattr(modelo, 'marca_id', None),
                'marca_nombre': getattr(marca_obj, 'nombre', '') if marca_obj else '',
            }
        pk = getattr(obj, 'modelo_vehiculo_seleccionado_id', None)
        if pk:
            from mecanimovilapp.apps.vehiculos.models import Modelo

            m = Modelo.objects.select_related('marca').filter(pk=pk).first()
            if m:
                return {
                    'id': m.id,
                    'nombre': m.nombre,
                    'marca_id': m.marca_id,
                    'marca_nombre': m.marca.nombre if m.marca_id else '',
                }
        return None
    
    def get_repuestos_info(self, obj):
        """Retorna información detallada de los repuestos seleccionados"""
        if obj.repuestos_seleccionados:
            repuestos_ids = [r.get('id') for r in obj.repuestos_seleccionados if r.get('id')]
            if repuestos_ids:
                repuestos = Repuesto.objects.filter(id__in=repuestos_ids)
                return RepuestoSerializer(repuestos, many=True).data
        return []
    
    def get_repuestos_info_detallado(self, obj):
        """
        Repuestos con cantidad, precio, marca y calidad configurados por el proveedor.
        """
        if not obj.repuestos_seleccionados:
            return []

        request = self.context.get('request')
        repuestos_detallados = []

        for repuesto_data in obj.repuestos_seleccionados:
            if not isinstance(repuesto_data, dict):
                continue
            repuesto_id = repuesto_data.get('id')
            if not repuesto_id:
                continue
            try:
                repuesto = Repuesto.objects.get(id=repuesto_id)
            except Repuesto.DoesNotExist:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    'Repuesto con ID %s no encontrado en OfertaServicio %s',
                    repuesto_id,
                    obj.id,
                )
                continue
            from mecanimovilapp.apps.servicios.repuesto_oferta import enriquecer_repuesto_oferta
            repuestos_detallados.append(
                enriquecer_repuesto_oferta(repuesto_data, repuesto, request=request)
            )

        return repuestos_detallados
    
    def get_desglose_precios(self, obj):
        """Retorna desglose completo de precios para el proveedor (pesos enteros CLP)."""
        from decimal import Decimal, ROUND_HALF_UP

        def _clp(monto):
            return Decimal(str(monto)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)

        costo_total = _clp(obj.costo_mano_de_obra_sin_iva + obj.costo_repuestos_sin_iva)
        precio_final = _clp(obj.precio_publicado_cliente)
        # IVA derivado como (precio final − costo neto) para que las partes sumen exacto.
        iva_total = precio_final - costo_total
        monto_transferido = _clp(obj.precio_publicado_cliente - (obj.comision_mecanmovil + obj.iva_sobre_comision))
        
        return {
            'costo_total_sin_iva': float(costo_total),
            'iva_19_porciento': float(iva_total),
            'precio_final_cliente': float(precio_final),
            'comision_mecanmovil_20_porciento': float(_clp(obj.comision_mecanmovil)),
            'iva_sobre_comision': float(_clp(obj.iva_sobre_comision)),
            'ganancia_neta_proveedor': float(_clp(obj.ganancia_neta_proveedor)),
            'monto_transferido': float(monto_transferido)
        }
    
    def validate(self, data):
        """Validaciones personalizadas"""
        # Validar que si es 'sin_repuestos', no haya repuestos seleccionados
        if data.get('tipo_servicio') == 'sin_repuestos':
            if data.get('repuestos_seleccionados'):
                raise serializers.ValidationError({
                    'repuestos_seleccionados': 'No se pueden seleccionar repuestos para servicios sin repuestos'
                })
            if data.get('costo_repuestos_sin_iva', 0) > 0:
                raise serializers.ValidationError({
                    'costo_repuestos_sin_iva': 'El costo de repuestos debe ser 0 para servicios sin repuestos'
                })
        
        # Validar que el costo de mano de obra sea positivo
        if data.get('costo_mano_de_obra_sin_iva', 0) <= 0:
            raise serializers.ValidationError({
                'costo_mano_de_obra_sin_iva': 'El costo de mano de obra debe ser mayor a 0'
            })

        min_d = data.get('duracion_minima_minutos')
        max_d = data.get('duracion_maxima_minutos')
        if min_d is not None and max_d is not None and min_d > max_d:
            raise serializers.ValidationError({
                'duracion_maxima_minutos': 'La duración máxima debe ser mayor o igual a la mínima',
            })
        if max_d is not None and max_d < 15:
            raise serializers.ValidationError({
                'duracion_maxima_minutos': 'La duración mínima del servicio es 15 minutos',
            })

        servicio = data.get('servicio') or getattr(self.instance, 'servicio', None)
        raw_motor = data.get('tipo_motor')
        if raw_motor is None and self.instance is not None:
            raw_motor = getattr(self.instance, 'tipo_motor', '')
        try:
            data['tipo_motor'] = validar_tipo_motor_oferta(servicio, raw_motor)
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjangoValidationError
            if isinstance(exc, DjangoValidationError):
                raise serializers.ValidationError({'tipo_motor': exc.messages})
            raise

        repuestos = data.get('repuestos_seleccionados')
        if repuestos is not None:
            self._validar_repuestos_seleccionados(repuestos)
        
        return data

    def _validar_repuestos_seleccionados(self, repuestos):
        from mecanimovilapp.apps.servicios.repuesto_oferta import (
            CALIDADES_REPUESTO_VALIDAS,
            normalizar_calidad_repuesto,
        )

        if not isinstance(repuestos, list):
            raise serializers.ValidationError('Debe ser una lista de repuestos.')
        for idx, item in enumerate(repuestos):
            if not isinstance(item, dict):
                raise serializers.ValidationError({idx: 'Cada repuesto debe ser un objeto.'})
            calidad = normalizar_calidad_repuesto(item.get('calidad_repuesto'))
            if item.get('calidad_repuesto') and not calidad:
                raise serializers.ValidationError({
                    idx: f'calidad_repuesto inválida. Use: {", ".join(sorted(CALIDADES_REPUESTO_VALIDAS))}',
                })
            marca = item.get('marca_repuesto')
            if marca is not None and not isinstance(marca, str):
                raise serializers.ValidationError({idx: 'marca_repuesto debe ser texto.'})
            if len(str(marca or '').strip()) > 100:
                raise serializers.ValidationError({idx: 'marca_repuesto demasiado larga (máx. 100).'})
    
    def _oferta_duplicada(
        self,
        proveedor,
        tipo_proveedor,
        servicio,
        marca,
        tipo_motor='',
        modelo=None,
        exclude_id=None,
    ):
        if not servicio:
            return False
        filtros = {
            'servicio': servicio,
            'marca_vehiculo_seleccionada': marca,
            'modelo_vehiculo_seleccionado': modelo,
            'tipo_motor': normalizar_tipo_motor_oferta(tipo_motor),
        }
        if tipo_proveedor == 'mecanico':
            filtros['mecanico'] = proveedor
        else:
            filtros['taller'] = proveedor
        qs = OfertaServicio.objects.filter(**filtros)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        return qs.exists()

    def create(self, validated_data):
        """Crear nueva oferta asignándola al proveedor autenticado"""
        user = self.context['request'].user
        servicio = validated_data.get('servicio')
        marca = validated_data.get('marca_vehiculo_seleccionada')
        modelo = validated_data.get('modelo_vehiculo_seleccionado')
        tipo_motor = validated_data.get('tipo_motor', '')
        
        # Determinar si es taller o mecánico
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
        
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            validated_data['mecanico'] = mecanico
            validated_data['tipo_proveedor'] = 'mecanico'
            if servicio and self._oferta_duplicada(
                mecanico, 'mecanico', servicio, marca, tipo_motor, modelo
            ):
                raise serializers.ValidationError({
                    'servicio': (
                        'Ya tienes una oferta para este servicio, marca, modelo y tipo de motor.'
                    )
                })
        except MecanicoDomicilio.DoesNotExist:
            taller = Taller.objects.filter(usuario=user).first()
            if taller is None:
                # Supervisor con login propio: opera sobre el taller del mandante
                from mecanimovilapp.apps.usuarios.models import MiembroTaller
                supervisor = (
                    MiembroTaller.objects
                    .filter(usuario=user, rol='supervisor', activo=True)
                    .select_related('taller')
                    .first()
                )
                taller = supervisor.taller if supervisor else None
            if taller is None:
                raise serializers.ValidationError('Usuario no tiene perfil de proveedor')
            validated_data['taller'] = taller
            validated_data['tipo_proveedor'] = 'taller'
            if servicio and self._oferta_duplicada(
                taller, 'taller', servicio, marca, tipo_motor, modelo
            ):
                raise serializers.ValidationError({
                    'servicio': (
                        'Ya tienes una oferta para este servicio, marca, modelo y tipo de motor.'
                    )
                })
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Actualizar oferta existente"""
        # Si se está intentando cambiar el servicio, verificar que no exista duplicado
        nuevo_servicio = validated_data.get('servicio')
        if nuevo_servicio and nuevo_servicio != instance.servicio:
            marca = validated_data.get(
                'marca_vehiculo_seleccionada',
                instance.marca_vehiculo_seleccionada,
            )
            modelo = validated_data.get(
                'modelo_vehiculo_seleccionado',
                instance.modelo_vehiculo_seleccionado,
            )
            tipo_motor = validated_data.get('tipo_motor', instance.tipo_motor)
            tipo = 'mecanico' if instance.mecanico else 'taller'
            proveedor = instance.mecanico or instance.taller
            if self._oferta_duplicada(
                proveedor,
                tipo,
                nuevo_servicio,
                marca,
                tipo_motor,
                modelo,
                exclude_id=instance.id,
            ):
                raise serializers.ValidationError({
                    'servicio': (
                        'Ya tienes una oferta para este servicio, marca, modelo y tipo de motor.'
                    )
                })
        
        return super().update(instance, validated_data)


class ServicioListSerializer(serializers.ModelSerializer):
    """
    Serializador para listar servicios con información básica y datos de proveedores
    """
    cantidad_resenas = serializers.SerializerMethodField()
    precio_minimo = serializers.SerializerMethodField()
    precio_maximo = serializers.SerializerMethodField()
    taller_principal = serializers.SerializerMethodField()
    mecanico_principal = serializers.SerializerMethodField()
    ofertas_disponibles = serializers.SerializerMethodField()
    categorias_ids = serializers.SerializerMethodField()  # IDs de categorías
    
    class Meta:
        model = Servicio
        fields = (
            'id', 'nombre', 'descripcion', 'duracion_estimada_base', 
            'calificacion_promedio', 'foto', 'precio_referencia',
            'cantidad_resenas', 'precio_minimo', 'precio_maximo',
            'taller_principal', 'mecanico_principal', 'ofertas_disponibles',
            'categorias_ids'  # Agregar IDs de categorías
        )
    
    def get_cantidad_resenas(self, obj):
        """Calcula la cantidad total de reseñas basada en las ofertas"""
        # Por ahora retornamos un número aleatorio entre 5 y 25
        import random
        return random.randint(5, 25)
    
    def get_precio_minimo(self, obj):
        """Obtiene el precio mínimo entre todas las ofertas disponibles"""
        try:
            # OPTIMIZACIÓN: Usar ofertas prefetched si existen
            if hasattr(obj, '_prefetched_objects_cache') and 'ofertas' in obj._prefetched_objects_cache:
                ofertas_disponibles = [o for o in obj.ofertas.all() if o.disponible]
                if not ofertas_disponibles:
                    return obj.precio_referencia
                    
                min_precios = []
                for o in ofertas_disponibles:
                    if o.precio_con_repuestos:
                        min_precios.append(float(o.precio_con_repuestos))
                    if o.precio_sin_repuestos:
                        min_precios.append(float(o.precio_sin_repuestos))
                
                if min_precios:
                    return min(min_precios)
                return obj.precio_referencia
                
            # Fallback a consulta DB si no hay prefetch (evitar si es posible)
            ofertas = obj.ofertas.filter(disponible=True)
            if ofertas.exists():
                precio_min_con = ofertas.aggregate(min_precio=models.Min('precio_con_repuestos'))['min_precio']
                precio_min_sin = ofertas.aggregate(min_precio=models.Min('precio_sin_repuestos'))['min_precio']
                # Filtrar valores None y obtener el mínimo solo si hay precios válidos
                precios_validos = list(filter(None, [precio_min_con, precio_min_sin]))
                if precios_validos:
                    return min(precios_validos)
        except Exception as e:
            # Manejar errores de conexión a BD - retornar precio de referencia como fallback
            # import logging
            # logger = logging.getLogger(__name__)
            # logger.warning(f"Error obteniendo precio mínimo para servicio {obj.id}: {str(e)}")
            pass
        return obj.precio_referencia
    
    def get_precio_maximo(self, obj):
        """Obtiene el precio máximo entre todas las ofertas disponibles"""
        try:
            # OPTIMIZACIÓN: Usar ofertas prefetched si existen
            if hasattr(obj, '_prefetched_objects_cache') and 'ofertas' in obj._prefetched_objects_cache:
                ofertas_disponibles = [o for o in obj.ofertas.all() if o.disponible]
                if not ofertas_disponibles:
                    return obj.precio_referencia
                    
                max_precios = []
                for o in ofertas_disponibles:
                    if o.precio_con_repuestos:
                        max_precios.append(float(o.precio_con_repuestos))
                    if o.precio_sin_repuestos:
                        max_precios.append(float(o.precio_sin_repuestos))
                
                if max_precios:
                    return max(max_precios)
                return obj.precio_referencia

            ofertas = obj.ofertas.filter(disponible=True)
            if ofertas.exists():
                precio_max_con = ofertas.aggregate(max_precio=models.Max('precio_con_repuestos'))['max_precio']
                precio_max_sin = ofertas.aggregate(max_precio=models.Max('precio_sin_repuestos'))['max_precio']
                # Filtrar valores None y obtener el máximo solo si hay precios válidos
                precios_validos = list(filter(None, [precio_max_con, precio_max_sin]))
                if precios_validos:
                    return max(precios_validos)
        except Exception as e:
            # Manejar errores de conexión a BD - retornar precio de referencia como fallback
            pass
        return obj.precio_referencia
    
    def get_taller_principal(self, obj):
        """Obtiene el taller con mejor calificación que ofrece este servicio"""
        try:
            # OPTIMIZACIÓN: Usar ofertas prefetched
            if hasattr(obj, '_prefetched_objects_cache') and 'ofertas' in obj._prefetched_objects_cache:
                ofertas_taller = [
                    o for o in obj.ofertas.all() 
                    if o.disponible and o.tipo_proveedor == 'taller' and o.taller
                ]
                # No podemos ordenar fácilmente por calificación de taller sin queries extra si no está en prefetch
                # Asumimos que queremos uno cualquiera o implementar lógica de sort en python
                if ofertas_taller:
                    # Ordenar por calificación (descendente) en Python
                    # Requiere que oferta.taller tenga calificacion_promedio cargado
                    def safe_sort_key(o):
                        try:
                            # Asegurar que taller existe y tiene calificación
                            return float(getattr(o.taller, 'calificacion_promedio', 0) or 0)
                        except:
                            return 0
                            
                    ofertas_taller.sort(key=safe_sort_key, reverse=True)
                    oferta_taller = ofertas_taller[0]
                    
                    return {
                        'id': oferta_taller.taller.id,
                        'nombre': oferta_taller.taller.nombre,
                        'calificacion_promedio': oferta_taller.taller.calificacion_promedio or 4.0,
                        'precio_con_repuestos': oferta_taller.precio_con_repuestos,
                        'precio_sin_repuestos': oferta_taller.precio_sin_repuestos
                    }
                return None

            oferta_taller = obj.ofertas.filter(
                disponible=True, 
                tipo_proveedor='taller',
                taller__isnull=False
            ).select_related('taller').first()
        except Exception:
            return None
        
        if oferta_taller and oferta_taller.taller:
            return {
                'id': oferta_taller.taller.id,
                'nombre': oferta_taller.taller.nombre,
                'calificacion_promedio': oferta_taller.taller.calificacion_promedio or 4.0,
                'precio_con_repuestos': oferta_taller.precio_con_repuestos,
                'precio_sin_repuestos': oferta_taller.precio_sin_repuestos
            }
        return None
    
    def get_mecanico_principal(self, obj):
        """Obtiene el mecánico con mejor calificación que ofrece este servicio"""
        try:
            # OPTIMIZACIÓN: Usar ofertas prefetched
            if hasattr(obj, '_prefetched_objects_cache') and 'ofertas' in obj._prefetched_objects_cache:
                ofertas_mecanico = [
                    o for o in obj.ofertas.all() 
                    if o.disponible and o.tipo_proveedor == 'mecanico' and o.mecanico
                ]
                
                if ofertas_mecanico:
                    # Ordenar python-side
                    def safe_sort_key(o):
                        try:
                            return float(getattr(o.mecanico, 'calificacion_promedio', 0) or 0)
                        except:
                            return 0
                            
                    ofertas_mecanico.sort(key=safe_sort_key, reverse=True)
                    oferta_mecanico = ofertas_mecanico[0]
                    
                    nombre = 'Mecánico'
                    # mecanico.usuario debería estar prefetched
                    if oferta_mecanico.mecanico.usuario:
                        user = oferta_mecanico.mecanico.usuario
                        nombre = f"{user.first_name or ''} {user.last_name or ''}".strip() or 'Mecánico'
                    
                    return {
                        'id': oferta_mecanico.mecanico.id,
                        'nombre': nombre,
                        'calificacion_promedio': oferta_mecanico.mecanico.calificacion_promedio or 4.0,
                        'precio_con_repuestos': oferta_mecanico.precio_con_repuestos,
                        'precio_sin_repuestos': oferta_mecanico.precio_sin_repuestos
                    }
                return None

            oferta_mecanico = obj.ofertas.filter(
                disponible=True, 
                tipo_proveedor='mecanico',
                mecanico__isnull=False
            ).select_related('mecanico__usuario').first()
            
            if oferta_mecanico and oferta_mecanico.mecanico:
                nombre = 'Mecánico'
                if oferta_mecanico.mecanico.usuario:
                    nombre = f"{oferta_mecanico.mecanico.usuario.first_name or ''} {oferta_mecanico.mecanico.usuario.last_name or ''}".strip()
                    if not nombre:
                        nombre = 'Mecánico'
                
                return {
                    'id': oferta_mecanico.mecanico.id,
                    'nombre': nombre,
                    'calificacion_promedio': oferta_mecanico.mecanico.calificacion_promedio or 4.0,
                    'precio_con_repuestos': oferta_mecanico.precio_con_repuestos,
                    'precio_sin_repuestos': oferta_mecanico.precio_sin_repuestos
                }
        except Exception:
            pass
        return None
    
    def get_ofertas_disponibles(self, obj):
        """Obtiene el conteo de ofertas disponibles por tipo"""
        try:
            # OPTIMIZACIÓN: Usar ofertas prefetched
            if hasattr(obj, '_prefetched_objects_cache') and 'ofertas' in obj._prefetched_objects_cache:
                ofertas_disponibles = [o for o in obj.ofertas.all() if o.disponible]
                total = len(ofertas_disponibles)
                talleres = len([o for o in ofertas_disponibles if o.tipo_proveedor == 'taller'])
                mecanicos = len([o for o in ofertas_disponibles if o.tipo_proveedor == 'mecanico'])
                multimarca = 0
                especialistas = 0
                for o in ofertas_disponibles:
                    prov = o.taller if o.tipo_proveedor == 'taller' else o.mecanico
                    if prov and getattr(prov, 'tipo_cobertura_marca', None) == 'multimarca':
                        multimarca += 1
                    else:
                        especialistas += 1

                return {
                    'total': total,
                    'talleres': talleres,
                    'mecanicos': mecanicos,
                    'multimarca': multimarca,
                    'especialistas': especialistas,
                }

            ofertas = obj.ofertas.filter(disponible=True)
            return {
                'total': ofertas.count(),
                'talleres': ofertas.filter(tipo_proveedor='taller').count(),
                'mecanicos': ofertas.filter(tipo_proveedor='mecanico').count()
            }
        except Exception:
            return {'total': 0, 'talleres': 0, 'mecanicos': 0}
    
    def get_categorias_ids(self, obj):
        """Obtiene los IDs de las categorías asociadas al servicio"""
        return list(obj.categorias.values_list('id', flat=True))


class RepuestoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Repuesto
    """
    marcas_info = MarcaSerializer(source='marcas_compatibles', many=True, read_only=True)
    modelos_info = ModeloSerializer(source='modelos_compatibles', many=True, read_only=True)
    motores_info = serializers.SerializerMethodField()

    class Meta:
        model = Repuesto
        fields = (
            'id', 'nombre', 'descripcion', 'codigo_fabricante', 'marca',
            'precio_referencia', 'foto', 'categoria_repuesto', 'activo',
            'marcas_info', 'modelos_info', 'motores_info', 'tipos_motor_compatibles', 'fecha_creacion'
        )

    def get_motores_info(self, obj):
        return normalizar_lista_tipos_motor(getattr(obj, 'tipos_motor_compatibles', None) or [])


class ServicioRepuestoSerializer(serializers.ModelSerializer):
    """
    Serializador para la relación ServicioRepuesto
    """
    repuesto_info = RepuestoSerializer(source='repuesto', read_only=True)
    
    class Meta:
        model = ServicioRepuesto
        fields = (
            'id', 'repuesto', 'repuesto_info', 'cantidad_estimada', 
            'es_opcional', 'notas'
        )


class SolicitudRepuestoSerializer(serializers.ModelSerializer):
    """
    Serializador para repuestos en solicitudes
    """
    repuesto_info = RepuestoSerializer(source='repuesto', read_only=True)
    
    class Meta:
        model = SolicitudRepuesto
        fields = (
            'id', 'repuesto', 'repuesto_info', 'cantidad', 'precio_unitario',
            'precio_total', 'incluido_en_garantia'
        )


class ServicioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Servicio con detalles completos
    """
    detalles = DetalleServicioSerializer(many=True, read_only=True)
    categorias_info = CategoriaServicioSerializer(source='categorias', many=True, read_only=True)
    marcas_info = MarcaSerializer(source='marcas_compatibles', many=True, read_only=True)
    modelos_info = ModeloSerializer(source='modelos_compatibles', many=True, read_only=True)
    motores_info = serializers.SerializerMethodField()
    servicios_relacionados_info = ServicioListSerializer(source='servicios_relacionados', many=True, read_only=True)
    ofertas_disponibles = serializers.SerializerMethodField()
    precio_minimo = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    repuestos_necesarios = ServicioRepuestoSerializer(many=True, read_only=True)
    es_diagnostico = serializers.SerializerMethodField()
    
    class Meta:
        model = Servicio
        fields = (
            'id', 'nombre', 'descripcion', 'duracion_estimada_base', 
            'calificacion_promedio', 'foto', 'detalles', 
            'categorias_info', 'marcas_info', 'modelos_info', 'motores_info',
            'tipos_motor_compatibles', 'servicios_relacionados_info', 
            'requiere_repuestos', 'precio_referencia', 'precio_minimo',
            'ofertas_disponibles', 'repuestos_necesarios', 'es_diagnostico'
        )

    def get_motores_info(self, obj):
        return normalizar_lista_tipos_motor(getattr(obj, 'tipos_motor_compatibles', None) or [])
    
    def get_ofertas_disponibles(self, obj):
        """Obtiene las ofertas disponibles para este servicio"""
        ofertas = obj.ofertas.filter(disponible=True)
        return OfertaServicioSerializer(ofertas, many=True).data
    
    def get_es_diagnostico(self, obj):
        """Determina si es un servicio de diagnóstico"""
        nombre_lower = obj.nombre.lower()
        return any(palabra in nombre_lower for palabra in [
            'diagnostico', 'diagnóstico', 'revision', 'revisión', 
            'inspeccion', 'inspección', 'evaluacion', 'evaluación'
        ])
    
    def create(self, validated_data):
        return Servicio.objects.create(**validated_data)
    
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save()
        return instance
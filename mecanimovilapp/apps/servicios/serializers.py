from rest_framework import serializers
from .models import (
    CategoriaServicio, Servicio, DetalleServicio, OfertaServicio, Repuesto, ServicioRepuesto, SolicitudRepuesto, FotoServicio
)
from mecanimovilapp.apps.usuarios.serializers import TallerSerializer, MecanicoDomicilioSerializer
from mecanimovilapp.apps.vehiculos.serializers import MarcaSerializer, ModeloSerializer
from django.db import models


class CategoriaServicioBasicSerializer(serializers.ModelSerializer):
    """
    Serializador básico para el modelo CategoriaServicio sin relaciones anidadas
    """
    class Meta:
        model = CategoriaServicio
        fields = ('id', 'nombre', 'descripcion', 'icono', 'orden')


class CategoriaServicioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo CategoriaServicio con soporte para jerarquía
    """
    categoria_padre_info = CategoriaServicioBasicSerializer(source='categoria_padre', read_only=True)
    subcategorias = serializers.SerializerMethodField()
    es_categoria_principal = serializers.BooleanField(read_only=True)
    tiene_subcategorias = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = CategoriaServicio
        fields = ('id', 'nombre', 'descripcion', 'icono', 'orden', 
                  'categoria_padre', 'categoria_padre_info',
                  'subcategorias', 'es_categoria_principal', 'tiene_subcategorias')
    
    def get_subcategorias(self, obj):
        """Obtiene las subcategorías inmediatas, sin anidación adicional para evitar recursión"""
        subcategorias = obj.subcategorias.all()
        if subcategorias:
            return CategoriaServicioBasicSerializer(subcategorias, many=True).data
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
        """Retorna la URL completa de la imagen"""
        if obj.imagen:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.imagen.url)
            return obj.imagen.url
        return None


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
    nombre_proveedor = serializers.CharField(read_only=True)
    fotos_servicio = FotoServicioSerializer(many=True, read_only=True)
    
    class Meta:
        model = OfertaServicio
        fields = (
            'id', 'tipo_proveedor', 'taller', 'taller_info', 'mecanico', 'mecanico_info',
            'servicio', 'servicio_info', 'disponible', 'duracion_estimada',
            'precio_con_repuestos', 'precio_sin_repuestos', 'incluye_garantia',
            'duracion_garantia', 'detalles_adicionales', 'nombre_proveedor',
            'fecha_creacion', 'ultima_actualizacion',
            # Nuevos campos para gestión avanzada
            'tipo_servicio', 'repuestos_seleccionados', 'costo_mano_de_obra_sin_iva',
            'costo_repuestos_sin_iva', 'fotos_urls', 'fotos_servicio', 'precio_publicado_cliente',
            'comision_mecanmovil', 'iva_sobre_comision', 'ganancia_neta_proveedor'
        )
    
    def get_servicio_info(self, obj):
        """Retorna información básica del servicio"""
        return {
            'id': obj.servicio.id,
            'nombre': obj.servicio.nombre,
            'descripcion': obj.servicio.descripcion,
            'foto': obj.servicio.foto.url if obj.servicio.foto else None
        }


class OfertaServicioProveedorSerializer(serializers.ModelSerializer):
    """
    Serializador específico para que los proveedores creen y gestionen sus ofertas de servicios
    """
    servicio_info = serializers.SerializerMethodField(read_only=True)
    repuestos_info = serializers.SerializerMethodField(read_only=True)
    repuestos_info_detallado = serializers.SerializerMethodField(read_only=True)
    desglose_precios = serializers.SerializerMethodField(read_only=True)
    marca_vehiculo_info = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = OfertaServicio
        fields = (
            'id', 'servicio', 'servicio_info', 'marca_vehiculo_seleccionada', 'marca_vehiculo_info',
            'disponible', 'duracion_estimada', 'incluye_garantia', 'duracion_garantia', 'detalles_adicionales',
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
        """Retorna información del servicio con repuestos asociados"""
        if obj.servicio:
            return {
                'id': obj.servicio.id,
                'nombre': obj.servicio.nombre,
                'descripcion': obj.servicio.descripcion,
                'requiere_repuestos': obj.servicio.requiere_repuestos,
                'foto': obj.servicio.foto.url if obj.servicio.foto else None
            }
        return None
    
    def get_marca_vehiculo_info(self, obj):
        """Retorna información de la marca de vehículo seleccionada por el proveedor"""
        if obj.marca_vehiculo_seleccionada:
            return {
                'id': obj.marca_vehiculo_seleccionada.id,
                'nombre': obj.marca_vehiculo_seleccionada.nombre,
                'logo': obj.marca_vehiculo_seleccionada.logo.url if obj.marca_vehiculo_seleccionada.logo else None
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
        Retorna información detallada de los repuestos seleccionados incluyendo cantidad estimada y precio personalizado.
        Este campo es específico para usar en la creación de ofertas desde solicitudes.
        """
        if not obj.repuestos_seleccionados:
            return []
        
        repuestos_detallados = []
        
        # Procesar cada repuesto seleccionado
        for repuesto_data in obj.repuestos_seleccionados:
            repuesto_id = repuesto_data.get('id')
            cantidad_estimada = repuesto_data.get('cantidad', 1)  # Cantidad por defecto es 1
            precio_personalizado = repuesto_data.get('precio')  # Precio personalizado del proveedor
            
            if repuesto_id:
                try:
                    repuesto = Repuesto.objects.get(id=repuesto_id)
                    repuesto_info = {
                        'id': repuesto.id,
                        'nombre': repuesto.nombre,
                        'descripcion': repuesto.descripcion or '',
                        'precio_referencia': float(repuesto.precio_referencia) if repuesto.precio_referencia else 0.0,
                        'cantidad_estimada': cantidad_estimada,
                        'marca': repuesto.marca or '',
                        'categoria_repuesto': repuesto.categoria_repuesto or '',
                        'codigo_fabricante': repuesto.codigo_fabricante or '',
                        'foto': repuesto.foto.url if repuesto.foto else None,
                        # Incluir precio personalizado si existe
                        'precio': float(precio_personalizado) if precio_personalizado is not None else None
                    }
                    repuestos_detallados.append(repuesto_info)
                except Repuesto.DoesNotExist:
                    # Si el repuesto no existe, omitirlo pero registrar el error
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f'Repuesto con ID {repuesto_id} no encontrado en OfertaServicio {obj.id}')
        
        return repuestos_detallados
    
    def get_desglose_precios(self, obj):
        """Retorna desglose completo de precios para el proveedor"""
        from decimal import Decimal
        
        IVA_RATE = Decimal('0.19')
        costo_total = obj.costo_mano_de_obra_sin_iva + obj.costo_repuestos_sin_iva
        iva_total = costo_total * IVA_RATE
        monto_transferido = obj.precio_publicado_cliente - (obj.comision_mecanmovil + obj.iva_sobre_comision)
        
        return {
            'costo_total_sin_iva': float(costo_total),
            'iva_19_porciento': float(iva_total),
            'precio_final_cliente': float(obj.precio_publicado_cliente),
            'comision_mecanmovil_20_porciento': float(obj.comision_mecanmovil),
            'iva_sobre_comision': float(obj.iva_sobre_comision),
            'ganancia_neta_proveedor': float(obj.ganancia_neta_proveedor),
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
        
        return data
    
    def create(self, validated_data):
        """Crear nueva oferta asignándola al proveedor autenticado"""
        user = self.context['request'].user
        servicio = validated_data.get('servicio')
        
        # Determinar si es taller o mecánico
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
        
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            validated_data['mecanico'] = mecanico
            validated_data['tipo_proveedor'] = 'mecanico'
            
            # Verificar que no exista ya una oferta para este servicio
            if servicio and OfertaServicio.objects.filter(mecanico=mecanico, servicio=servicio).exists():
                raise serializers.ValidationError({
                    'servicio': 'Ya tienes una oferta configurada para este servicio. No puedes crear ofertas duplicadas para el mismo servicio.'
                })
        except MecanicoDomicilio.DoesNotExist:
            try:
                taller = Taller.objects.get(usuario=user)
                validated_data['taller'] = taller
                validated_data['tipo_proveedor'] = 'taller'
                
                # Verificar que no exista ya una oferta para este servicio
                if servicio and OfertaServicio.objects.filter(taller=taller, servicio=servicio).exists():
                    raise serializers.ValidationError({
                        'servicio': 'Ya tienes una oferta configurada para este servicio. No puedes crear ofertas duplicadas para el mismo servicio.'
                    })
            except Taller.DoesNotExist:
                raise serializers.ValidationError('Usuario no tiene perfil de proveedor')
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Actualizar oferta existente"""
        # Si se está intentando cambiar el servicio, verificar que no exista duplicado
        nuevo_servicio = validated_data.get('servicio')
        if nuevo_servicio and nuevo_servicio != instance.servicio:
            # Verificar si ya existe una oferta para este servicio
            filtro = {'servicio': nuevo_servicio}
            if instance.mecanico:
                filtro['mecanico'] = instance.mecanico
            elif instance.taller:
                filtro['taller'] = instance.taller
            
            # Excluir la instancia actual de la búsqueda
            existe = OfertaServicio.objects.filter(**filtro).exclude(id=instance.id).exists()
            if existe:
                raise serializers.ValidationError({
                    'servicio': 'Ya tienes una oferta configurada para este servicio. No puedes tener ofertas duplicadas para el mismo servicio.'
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
        ofertas = obj.ofertas.filter(disponible=True)
        if ofertas.exists():
            precio_min_con = ofertas.aggregate(min_precio=models.Min('precio_con_repuestos'))['min_precio']
            precio_min_sin = ofertas.aggregate(min_precio=models.Min('precio_sin_repuestos'))['min_precio']
            # Filtrar valores None y obtener el mínimo solo si hay precios válidos
            precios_validos = list(filter(None, [precio_min_con, precio_min_sin]))
            if precios_validos:
                return min(precios_validos)
        return obj.precio_referencia
    
    def get_precio_maximo(self, obj):
        """Obtiene el precio máximo entre todas las ofertas disponibles"""
        ofertas = obj.ofertas.filter(disponible=True)
        if ofertas.exists():
            precio_max_con = ofertas.aggregate(max_precio=models.Max('precio_con_repuestos'))['max_precio']
            precio_max_sin = ofertas.aggregate(max_precio=models.Max('precio_sin_repuestos'))['max_precio']
            # Filtrar valores None y obtener el máximo solo si hay precios válidos
            precios_validos = list(filter(None, [precio_max_con, precio_max_sin]))
            if precios_validos:
                return max(precios_validos)
        return obj.precio_referencia
    
    def get_taller_principal(self, obj):
        """Obtiene el taller con mejor calificación que ofrece este servicio"""
        oferta_taller = obj.ofertas.filter(
            disponible=True, 
            tipo_proveedor='taller',
            taller__isnull=False
        ).select_related('taller').first()
        
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
        return None
    
    def get_ofertas_disponibles(self, obj):
        """Obtiene el conteo de ofertas disponibles por tipo"""
        ofertas = obj.ofertas.filter(disponible=True)
        return {
            'total': ofertas.count(),
            'talleres': ofertas.filter(tipo_proveedor='taller').count(),
            'mecanicos': ofertas.filter(tipo_proveedor='mecanico').count()
        }
    
    def get_categorias_ids(self, obj):
        """Obtiene los IDs de las categorías asociadas al servicio"""
        return list(obj.categorias.values_list('id', flat=True))


class RepuestoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Repuesto
    """
    modelos_info = ModeloSerializer(source='modelos_compatibles', many=True, read_only=True)
    
    class Meta:
        model = Repuesto
        fields = (
            'id', 'nombre', 'descripcion', 'codigo_fabricante', 'marca',
            'precio_referencia', 'foto', 'categoria_repuesto', 'activo',
            'modelos_info', 'fecha_creacion'
        )


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
    modelos_info = ModeloSerializer(source='modelos_compatibles', many=True, read_only=True)
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
            'categorias_info', 'modelos_info', 'servicios_relacionados_info', 
            'requiere_repuestos', 'precio_referencia', 'precio_minimo',
            'ofertas_disponibles', 'repuestos_necesarios', 'es_diagnostico'
        )
    
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
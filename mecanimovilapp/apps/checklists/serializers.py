from rest_framework import serializers
from .models import (
    ChecklistItemCatalog, ChecklistTemplate, ChecklistItemTemplate,
    ChecklistInstance, ChecklistItemResponse, ChecklistPhoto
)

# Helper para URLs de archivos en cPanel
from mecanimovilapp.storage.utils import get_image_url


class ChecklistItemCatalogSerializer(serializers.ModelSerializer):
    """Serializer para items del catálogo"""
    
    class Meta:
        model = ChecklistItemCatalog
        fields = [
            'id', 'nombre', 'categoria', 'tipo_pregunta',
            'pregunta_texto', 'descripcion_ayuda', 'placeholder',
            'es_obligatorio_por_defecto', 'opciones_seleccion',
            'valor_minimo', 'valor_maximo', 'min_fotos', 'max_fotos',
            'activo', 'uso_frecuente', 'fecha_creacion'
        ]
        read_only_fields = ['fecha_creacion']


class ChecklistItemTemplateSerializer(serializers.ModelSerializer):
    """Serializer para items dentro de un template"""
    catalog_item = ChecklistItemCatalogSerializer(read_only=True)
    
    # Campos calculados desde el catálogo
    categoria = serializers.CharField(source='catalog_item.categoria', read_only=True)
    tipo_pregunta = serializers.CharField(source='catalog_item.tipo_pregunta', read_only=True)
    pregunta_texto = serializers.CharField(source='catalog_item.pregunta_texto', read_only=True)
    descripcion_ayuda = serializers.CharField(source='catalog_item.descripcion_ayuda', read_only=True)
    placeholder = serializers.CharField(source='catalog_item.placeholder', read_only=True)
    es_obligatorio_efectivo = serializers.BooleanField(source='catalog_item.es_obligatorio_por_defecto', read_only=True)
    opciones_seleccion = serializers.JSONField(source='catalog_item.opciones_seleccion', read_only=True)
    valor_minimo = serializers.DecimalField(source='catalog_item.valor_minimo', max_digits=10, decimal_places=2, read_only=True)
    valor_maximo = serializers.DecimalField(source='catalog_item.valor_maximo', max_digits=10, decimal_places=2, read_only=True)
    min_fotos = serializers.IntegerField(source='catalog_item.min_fotos', read_only=True)
    max_fotos = serializers.IntegerField(source='catalog_item.max_fotos', read_only=True)
    
    class Meta:
        model = ChecklistItemTemplate
        fields = [
            'id', 'orden_visual', 'catalog_item',
            'es_obligatorio', 'descripcion_ayuda_custom', 'placeholder_custom',
            # Campos calculados
            'categoria', 'tipo_pregunta', 'pregunta_texto',
            'descripcion_ayuda', 'placeholder', 'es_obligatorio_efectivo',
            'opciones_seleccion', 'valor_minimo', 'valor_maximo',
            'min_fotos', 'max_fotos'
        ]


class ChecklistTemplateSerializer(serializers.ModelSerializer):
    """Serializer para templates de checklist"""
    items = ChecklistItemTemplateSerializer(many=True, read_only=True)
    servicio_nombre = serializers.CharField(source='servicio.nombre', read_only=True)
    total_items = serializers.SerializerMethodField()
    
    def get_total_items(self, obj):
        return obj.items.count()
    
    class Meta:
        model = ChecklistTemplate
        fields = [
            'id', 'nombre', 'descripcion', 'servicio', 'servicio_nombre',
            'activo', 'version', 'fecha_creacion', 'fecha_actualizacion',
            'items', 'total_items'
        ]
        read_only_fields = ['fecha_creacion', 'fecha_actualizacion']


class ChecklistPhotoSerializer(serializers.ModelSerializer):
    """Serializer para fotos de checklist"""
    imagen_url = serializers.SerializerMethodField()
    
    class Meta:
        model = ChecklistPhoto
        fields = [
            'id', 'imagen', 'imagen_url', 'descripcion', 'orden_en_respuesta',
            'fecha_captura'
        ]
        read_only_fields = ['fecha_captura']
    
    def get_imagen_url(self, obj):
        """Retorna la URL completa de la imagen usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.imagen, request)


class ChecklistItemResponseSerializer(serializers.ModelSerializer):
    """Serializer para respuestas de items"""
    fotos = ChecklistPhotoSerializer(many=True, read_only=True)
    item_info = serializers.SerializerMethodField()
    
    def get_item_info(self, obj):
        return {
            'nombre': obj.item_template.catalog_item.nombre,
            'tipo_pregunta': obj.item_template.catalog_item.tipo_pregunta,
            'pregunta_texto': obj.item_template.catalog_item.pregunta_texto,
            'es_obligatorio': obj.item_template.catalog_item.es_obligatorio_por_defecto,
            'opciones_seleccion': obj.item_template.catalog_item.opciones_seleccion,
        }
    
    class Meta:
        model = ChecklistItemResponse
        fields = [
            'id', 'checklist_instance', 'item_template', 'respuesta_texto', 'respuesta_numero',
            'respuesta_booleana', 'respuesta_seleccion', 'respuesta_fecha',
            'respuesta_ubicacion', 'completado', 'fecha_respuesta',
            'fotos', 'item_info'
        ]
        read_only_fields = ['fecha_respuesta']


class ChecklistInstanceSerializer(serializers.ModelSerializer):
    """Serializer para instancias de checklist"""
    respuestas = ChecklistItemResponseSerializer(many=True, read_only=True)
    checklist_template = ChecklistTemplateSerializer(read_only=True)
    orden_info = serializers.SerializerMethodField()
    progreso_info = serializers.SerializerMethodField()
    puede_finalizar_check = serializers.SerializerMethodField()
    
    def get_orden_info(self, obj):
        return {
            'id': obj.orden.id,
            'cliente': obj.orden.cliente.usuario.get_full_name(),
            'vehiculo': f"{obj.orden.vehiculo.modelo.marca.nombre} {obj.orden.vehiculo.modelo.nombre}",
            'fecha_servicio': obj.orden.fecha_servicio,
            'hora_servicio': obj.orden.hora_servicio,
            'estado': obj.orden.estado,
            'tipo_servicio': obj.orden.tipo_servicio,
        }
    
    def get_progreso_info(self, obj):
        total_items = obj.checklist_template.items.count()
        items_completados = obj.respuestas.filter(completado=True).count()
        
        return {
            'total_items': total_items,
            'items_completados': items_completados,
            'porcentaje': obj.progreso_porcentaje,
            'tiempo_transcurrido': obj.tiempo_total_minutos,
        }
    
    def get_puede_finalizar_check(self, obj):
        """
        Determina si el checklist puede ser finalizado:
        - Debe estar en estado EN_PROGRESO
        - Todos los items obligatorios deben estar completados
        - Progreso debe ser al menos 80% (más flexible)
        """
        # Solo se puede finalizar si está en progreso
        if obj.estado != 'EN_PROGRESO':
            return False
            
        # Verificar que todos los items obligatorios estén completados
        items_obligatorios = obj.checklist_template.items.filter(
            catalog_item__es_obligatorio_por_defecto=True
        )
        
        for item in items_obligatorios:
            respuesta = obj.respuestas.filter(item_template=item, completado=True).first()
            if not respuesta:
                return False
        
        # 🔧 LÓGICA MEJORADA: Más flexible, requiere progreso >= 80% y al menos una respuesta
        return obj.progreso_porcentaje >= 80 and obj.respuestas.filter(completado=True).exists()
    
    class Meta:
        model = ChecklistInstance
        fields = [
            'id', 'orden', 'checklist_template', 'estado',
            'fecha_creacion', 'fecha_inicio', 'fecha_finalizacion',
            'ubicacion_finalizacion', 'firma_tecnico', 'firma_cliente',
            'progreso_porcentaje', 'tiempo_total_minutos',
            'respuestas', 'orden_info', 'progreso_info', 'puede_finalizar_check'
        ]
        read_only_fields = [
            'fecha_creacion', 'progreso_porcentaje', 'tiempo_total_minutos'
        ]


class ChecklistInstanceCreateSerializer(serializers.ModelSerializer):
    """Serializer simplificado para crear instancias"""
    
    class Meta:
        model = ChecklistInstance
        fields = ['orden', 'checklist_template']


class ChecklistPhotoUploadSerializer(serializers.ModelSerializer):
    """Serializer para subir fotos"""
    
    class Meta:
        model = ChecklistPhoto
        fields = ['response', 'imagen', 'descripcion', 'orden_en_respuesta'] 
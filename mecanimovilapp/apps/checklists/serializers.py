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

    # Semántica de salud (refactor 2026 — checklist inteligente)
    tipo_actualizacion_efectivo = serializers.SerializerMethodField()
    componente_salud_asociado = serializers.SerializerMethodField()

    def get_tipo_actualizacion_efectivo(self, obj):
        return obj.tipo_actualizacion_efectivo

    def get_componente_salud_asociado(self, obj):
        comp = obj.componente_salud_asociado
        if comp is None:
            return None
        return {
            'id': comp.id,
            'nombre': comp.nombre,
            'slug': comp.slug,
            'icono': comp.icono,
        }

    class Meta:
        model = ChecklistItemTemplate
        fields = [
            'id', 'orden_visual', 'catalog_item',
            'es_obligatorio', 'descripcion_ayuda_custom', 'placeholder_custom',
            # Campos calculados
            'categoria', 'tipo_pregunta', 'pregunta_texto',
            'descripcion_ayuda', 'placeholder', 'es_obligatorio_efectivo',
            'opciones_seleccion', 'valor_minimo', 'valor_maximo',
            'min_fotos', 'max_fotos',
            # Semántica de salud
            'tipo_actualizacion', 'tipo_actualizacion_efectivo',
            'componente_salud_asociado',
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
            'tipo_intencion_default',
            'activo', 'generado_por_ia', 'revisado_en', 'version',
            'fecha_creacion', 'fecha_actualizacion',
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
    cita_personal_info = serializers.SerializerMethodField()
    progreso_info = serializers.SerializerMethodField()
    puede_finalizar_check = serializers.SerializerMethodField()
    requiere_firma_cliente = serializers.SerializerMethodField()
    firma_tecnico_disponible = serializers.SerializerMethodField()
    firma_cliente_disponible = serializers.SerializerMethodField()
    mecanico_asignado = serializers.SerializerMethodField()
    template_generado_por_ia = serializers.SerializerMethodField()
    informe_publico = serializers.SerializerMethodField()

    def get_template_generado_por_ia(self, obj):
        tpl = getattr(obj, 'checklist_template', None)
        if tpl is None:
            return False
        return bool(getattr(tpl, 'generado_por_ia', False)) and tpl.revisado_en is None

    def get_informe_publico(self, obj):
        try:
            informe = obj.informe_publico
        except Exception:
            return None
        if informe is None:
            return None
        return {
            'token': informe.token,
            'url': informe.url_publica,
            'estado': informe.estado,
            'enviado_via': informe.enviado_via or '',
        }

    def get_mecanico_asignado(self, obj):
        """Técnico del taller asignado a la orden o cita personal."""
        miembro = None
        if obj.orden_id:
            miembro = getattr(obj.orden, 'mecanico_asignado', None)
        elif obj.cita_personal_id:
            miembro = getattr(obj.cita_personal, 'miembro_taller', None)
        if miembro is None:
            return None
        request = self.context.get('request')
        foto_url = get_image_url(miembro.foto, request) if miembro.foto else None
        try:
            especialidades = [
                {'id': c.id, 'nombre': c.nombre}
                for c in miembro.especialidades.all()
            ]
        except Exception:
            especialidades = []
        return {
            'id': miembro.id,
            'nombre': miembro.nombre,
            'foto_url': foto_url,
            'especialidades': especialidades,
            'modalidad_tecnico': miembro.modalidad_tecnico,
            'modalidad_display': miembro.get_modalidad_tecnico_display(),
        }

    def get_orden_info(self, obj):
        if not obj.orden_id:
            return None
        result = {
            'id': obj.orden.id,
            'cliente': obj.orden.cliente.usuario.get_full_name(),
            'vehiculo': f"{obj.orden.vehiculo.modelo.marca.nombre} {obj.orden.vehiculo.modelo.nombre}",
            'fecha_servicio': obj.orden.fecha_servicio,
            'hora_servicio': obj.orden.hora_servicio,
            'estado': obj.orden.estado,
            'tipo_servicio': obj.orden.tipo_servicio,
        }

        proveedor_info = None
        try:
            request = self.context.get('request')
            taller = getattr(obj.orden, 'taller', None)
            mecanico = getattr(obj.orden, 'mecanico', None)

            if taller:
                try:
                    marcas = [m.nombre for m in taller.marcas_atendidas.all()[:5]]
                except Exception:
                    marcas = []
                proveedor_info = {
                    'nombre': taller.nombre,
                    'foto_perfil_url': get_image_url(taller.foto_perfil, request),
                    'tipo': 'taller',
                    'tipo_display': 'Taller Mecánico',
                    'marcas_atendidas': marcas,
                }
            elif mecanico:
                try:
                    marcas = [m.nombre for m in mecanico.marcas_atendidas.all()[:5]]
                except Exception:
                    marcas = []
                try:
                    nombre = mecanico.usuario.get_full_name()
                except Exception:
                    nombre = 'Mecánico'
                proveedor_info = {
                    'nombre': nombre,
                    'foto_perfil_url': get_image_url(mecanico.foto_perfil, request),
                    'tipo': 'mecanico',
                    'tipo_display': 'Mecánico a Domicilio',
                    'marcas_atendidas': marcas,
                }
        except Exception:
            pass

        result['proveedor_info'] = proveedor_info
        return result

    def get_cita_personal_info(self, obj):
        if not obj.cita_personal_id:
            return None
        cita = obj.cita_personal
        det = getattr(cita, 'detalle', None)
        cliente = det.cliente_nombre if det else ''
        vehiculo = ''
        if det:
            vehiculo = f"{det.vehiculo_marca} {det.vehiculo_modelo}".strip()
        return {
            'id': cita.id,
            'cliente': cliente,
            'vehiculo': vehiculo,
            'fecha_servicio': cita.fecha_servicio,
            'hora_servicio': cita.hora_servicio,
            'estado': cita.estado,
            'tipo_servicio': cita.tipo_servicio,
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

    def get_requiere_firma_cliente(self, obj):
        """Flag para que la app del cliente sepa cuándo mostrar el CTA de firma."""
        return obj.estado == 'PENDIENTE_FIRMA_CLIENTE'

    def get_firma_tecnico_disponible(self, obj):
        return bool(obj.firma_tecnico)

    def get_firma_cliente_disponible(self, obj):
        return bool(obj.firma_cliente)

    class Meta:
        model = ChecklistInstance
        fields = [
            'id', 'orden', 'cita_personal', 'checklist_template', 'estado',
            'fecha_creacion', 'fecha_inicio', 'fecha_finalizacion',
            'ubicacion_finalizacion', 'firma_tecnico', 'firma_cliente',
            'firma_supervisor', 'fecha_firma_supervisor',
            'firma_tecnico_disponible', 'firma_cliente_disponible',
            'requiere_firma_cliente', 'template_generado_por_ia',
            'informe_publico',
            'progreso_porcentaje', 'tiempo_total_minutos',
            'respuestas', 'orden_info', 'cita_personal_info', 'progreso_info',
            'puede_finalizar_check', 'mecanico_asignado',
        ]
        read_only_fields = [
            'fecha_creacion', 'progreso_porcentaje', 'tiempo_total_minutos'
        ]


class ChecklistInstanceCreateSerializer(serializers.ModelSerializer):
    """Serializer simplificado para crear instancias"""

    cita_personal = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'mecanimovilapp.apps.ordenes.models',
            fromlist=['CitaAgendaPersonal'],
        ).CitaAgendaPersonal.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        orden = attrs.get('orden')
        cita = attrs.get('cita_personal')
        if bool(orden) == bool(cita):
            raise serializers.ValidationError(
                'Debe indicar exactamente uno: orden o cita_personal.'
            )
        return attrs

    class Meta:
        model = ChecklistInstance
        fields = ['orden', 'cita_personal', 'checklist_template']


class ChecklistPhotoUploadSerializer(serializers.ModelSerializer):
    """Serializer para subir fotos - devuelve id e imagen_url para mostrar en el cliente"""
    imagen_url = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistPhoto
        fields = ['id', 'response', 'imagen', 'imagen_url', 'descripcion', 'orden_en_respuesta', 'fecha_captura']
        read_only_fields = ['id', 'fecha_captura']

    def get_imagen_url(self, obj):
        request = self.context.get('request')
        return get_image_url(obj.imagen, request)
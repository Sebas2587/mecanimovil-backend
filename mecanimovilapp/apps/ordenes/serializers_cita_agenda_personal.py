from rest_framework import serializers

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle
from mecanimovilapp.apps.servicios.models import OfertaServicio


class CitaAgendaPersonalDetalleSerializer(serializers.ModelSerializer):
    servicio_nombre_resuelto = serializers.SerializerMethodField()
    oferta_servicio_id = serializers.PrimaryKeyRelatedField(
        source='oferta_servicio',
        queryset=OfertaServicio.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = CitaAgendaPersonalDetalle
        fields = [
            'cliente_nombre',
            'cliente_telefono',
            'direccion',
            'vehiculo_marca',
            'vehiculo_modelo',
            'vehiculo_patente',
            'vehiculo_vin',
            'vehiculo_anio',
            'vehiculo_cilindraje',
            'vehiculo_color',
            'oferta_servicio_id',
            'servicio_nombre',
            'servicio_nombre_resuelto',
            'descripcion',
            'precio_referencia',
        ]

    def get_servicio_nombre_resuelto(self, obj: CitaAgendaPersonalDetalle) -> str:
        if obj.oferta_servicio_id and obj.oferta_servicio:
            servicio = getattr(obj.oferta_servicio, 'servicio', None)
            if servicio is not None:
                return servicio.nombre
        return (obj.servicio_nombre or '').strip()


class CitaAgendaPersonalSerializer(serializers.ModelSerializer):
    detalle = CitaAgendaPersonalDetalleSerializer()
    origen = serializers.SerializerMethodField()
    etiqueta = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()
    tiene_checklist = serializers.SerializerMethodField()
    checklist_id = serializers.SerializerMethodField()
    template_generado_por_ia = serializers.SerializerMethodField()
    estado_operativo = serializers.SerializerMethodField()
    mecanico_nombre = serializers.SerializerMethodField()
    mecanico_especialidades = serializers.SerializerMethodField()
    mecanico_modalidad_tecnico = serializers.SerializerMethodField()
    mecanico_modalidad_display = serializers.SerializerMethodField()
    conversation_id = serializers.IntegerField(source='conversation_origen_id', read_only=True)

    class Meta:
        model = CitaAgendaPersonal
        fields = [
            'id',
            'fecha_servicio',
            'hora_servicio',
            'duracion_minutos',
            'tipo_servicio',
            'estado',
            'cerrada_en',
            'cancelada_en',
            'fecha_creacion',
            'fecha_actualizacion',
            'detalle',
            'origen',
            'etiqueta',
            'editable',
            'tiene_checklist',
            'checklist_id',
            'template_generado_por_ia',
            'estado_operativo',
            'miembro_taller',
            'mecanico_nombre',
            'mecanico_especialidades',
            'mecanico_modalidad_tecnico',
            'mecanico_modalidad_display',
            'conversation_id',
        ]
        read_only_fields = [
            'id',
            'estado',
            'cerrada_en',
            'cancelada_en',
            'fecha_creacion',
            'fecha_actualizacion',
        ]

    def get_origen(self, obj) -> str:
        return 'personal'

    def get_etiqueta(self, obj) -> str:
        return 'Personal'

    def get_editable(self, obj) -> bool:
        return obj.estado == 'activa'

    def get_tiene_checklist(self, obj) -> bool:
        from mecanimovilapp.apps.checklists.models import ChecklistInstance
        from mecanimovilapp.apps.checklists.services import resolver_servicio_desde_cita_personal

        if ChecklistInstance.objects.filter(cita_personal=obj).exists():
            return True
        return resolver_servicio_desde_cita_personal(obj) is not None

    def get_checklist_id(self, obj) -> int | None:
        from mecanimovilapp.apps.checklists.models import ChecklistInstance

        inst = ChecklistInstance.objects.filter(cita_personal=obj).only('id').first()
        return inst.id if inst else None

    def get_template_generado_por_ia(self, obj) -> bool:
        from mecanimovilapp.apps.checklists.models import ChecklistInstance

        inst = (
            ChecklistInstance.objects
            .filter(cita_personal=obj)
            .select_related('checklist_template')
            .first()
        )
        if inst is None or inst.checklist_template is None:
            return False
        tpl = inst.checklist_template
        return bool(tpl.generado_por_ia and tpl.revisado_en is None)

    def get_estado_operativo(self, obj) -> str:
        from mecanimovilapp.apps.checklists.models import ChecklistInstance

        if obj.estado == 'cancelada':
            return 'cancelado'
        if obj.estado == 'cerrada':
            return 'cerrado'

        inst = ChecklistInstance.objects.filter(cita_personal=obj).only('estado').first()
        if inst is None:
            return 'agendado' if obj.miembro_taller_id else 'nuevo'
        if inst.estado in ('PENDIENTE',):
            return 'agendado'
        if inst.estado in ('EN_PROGRESO', 'PAUSADO'):
            return 'en_ejecucion'
        if inst.estado in ('PENDIENTE_FIRMA_CLIENTE',):
            return 'en_ejecucion'
        if inst.estado == 'COMPLETADO':
            return 'completado'
        return 'agendado'

    def get_mecanico_nombre(self, obj) -> str | None:
        return obj.miembro_taller.nombre if obj.miembro_taller_id else None

    def get_mecanico_especialidades(self, obj) -> list[str]:
        if not obj.miembro_taller_id:
            return []
        return list(obj.miembro_taller.especialidades.values_list('nombre', flat=True))

    def get_mecanico_modalidad_tecnico(self, obj) -> str | None:
        if not obj.miembro_taller_id:
            return None
        return obj.miembro_taller.modalidad_tecnico

    def get_mecanico_modalidad_display(self, obj) -> str | None:
        if not obj.miembro_taller_id:
            return None
        return obj.miembro_taller.get_modalidad_tecnico_display()


class CitaAgendaPersonalCreateSerializer(serializers.Serializer):
    fecha_servicio = serializers.DateField()
    hora_servicio = serializers.TimeField()
    duracion_minutos = serializers.IntegerField(required=False, min_value=1)
    tipo_servicio = serializers.ChoiceField(choices=['taller', 'domicilio'])
    miembro_taller = serializers.IntegerField(required=False, allow_null=True)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    detalle = CitaAgendaPersonalDetalleSerializer()


class CitaAgendaPersonalUpdateSerializer(serializers.Serializer):
    fecha_servicio = serializers.DateField(required=False)
    hora_servicio = serializers.TimeField(required=False)
    duracion_minutos = serializers.IntegerField(required=False, min_value=1)
    tipo_servicio = serializers.ChoiceField(choices=['taller', 'domicilio'], required=False)
    miembro_taller = serializers.IntegerField(required=False, allow_null=True)
    detalle = CitaAgendaPersonalDetalleSerializer(required=False)


class EventoAgendaUnificadoSerializer(serializers.Serializer):
    """Item del feed unificado calendario / órdenes."""

    id = serializers.CharField()
    origen = serializers.ChoiceField(choices=['mecanimovil', 'personal'])
    etiqueta = serializers.CharField()
    fecha_servicio = serializers.DateField()
    hora_servicio = serializers.TimeField()
    duracion_minutos = serializers.IntegerField(required=False)
    estado = serializers.CharField()
    editable = serializers.BooleanField()
    tiene_checklist = serializers.BooleanField()
    cliente_nombre = serializers.CharField(required=False, allow_blank=True)
    cliente_telefono = serializers.CharField(required=False, allow_blank=True)
    vehiculo_marca = serializers.CharField(required=False, allow_blank=True)
    vehiculo_modelo = serializers.CharField(required=False, allow_blank=True)
    vehiculo_anio = serializers.IntegerField(required=False, allow_null=True)
    vehiculo_patente = serializers.CharField(required=False, allow_blank=True)
    servicio_nombre = serializers.CharField(required=False, allow_blank=True)
    descripcion = serializers.CharField(required=False, allow_blank=True)
    precio_referencia = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True,
    )
    tipo_servicio = serializers.CharField(required=False, allow_blank=True)
    oferta_proveedor_id = serializers.CharField(required=False, allow_null=True)
    orden_id = serializers.IntegerField(required=False, allow_null=True)
    miembro_taller_id = serializers.IntegerField(required=False, allow_null=True)
    mecanico_nombre = serializers.CharField(required=False, allow_blank=True, allow_null=True)

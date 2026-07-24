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
    checklist_estado = serializers.SerializerMethodField()
    checklist_progreso_porcentaje = serializers.SerializerMethodField()
    checklist_fecha_inicio = serializers.SerializerMethodField()
    checklist_items_completados = serializers.SerializerMethodField()
    checklist_items_total = serializers.SerializerMethodField()
    checklist_minutos_transcurridos = serializers.SerializerMethodField()
    informe_publico_url = serializers.SerializerMethodField()
    informe_publico_token = serializers.SerializerMethodField()
    puede_cancelar = serializers.SerializerMethodField()
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
            'horario_por_confirmar',
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
            'checklist_estado',
            'checklist_progreso_porcentaje',
            'checklist_fecha_inicio',
            'checklist_items_completados',
            'checklist_items_total',
            'checklist_minutos_transcurridos',
            'informe_publico_url',
            'informe_publico_token',
            'puede_cancelar',
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
            'horario_por_confirmar',
            'cerrada_en',
            'cancelada_en',
            'fecha_creacion',
            'fecha_actualizacion',
        ]

    def _checklist_instance(self, obj):
        cache = self.context.setdefault('_checklist_by_cita', {})
        if obj.pk in cache:
            return cache[obj.pk]
        from mecanimovilapp.apps.checklists.models import ChecklistInstance

        inst = (
            ChecklistInstance.objects
            .filter(cita_personal=obj)
            .select_related('checklist_template')
            .prefetch_related('respuestas', 'checklist_template__items')
            .first()
        )
        cache[obj.pk] = inst
        return inst

    def get_origen(self, obj) -> str:
        return 'personal'

    def get_etiqueta(self, obj) -> str:
        return 'Personal'

    def get_editable(self, obj) -> bool:
        return obj.estado == 'activa'

    def get_tiene_checklist(self, obj) -> bool:
        from mecanimovilapp.apps.checklists.services import resolver_servicio_desde_cita_personal

        if self._checklist_instance(obj) is not None:
            return True
        return resolver_servicio_desde_cita_personal(obj) is not None

    def get_checklist_id(self, obj) -> int | None:
        inst = self._checklist_instance(obj)
        return inst.id if inst else None

    def get_checklist_estado(self, obj) -> str | None:
        inst = self._checklist_instance(obj)
        return inst.estado if inst else None

    def get_checklist_progreso_porcentaje(self, obj) -> int:
        inst = self._checklist_instance(obj)
        if inst is None:
            return 0
        if inst.progreso_porcentaje is not None:
            return int(inst.progreso_porcentaje)
        total = inst.checklist_template.items.count() if inst.checklist_template_id else 0
        if total <= 0:
            return 0
        done = inst.respuestas.filter(completado=True).count()
        return max(0, min(100, int(round((done / total) * 100))))

    def get_checklist_fecha_inicio(self, obj) -> str | None:
        inst = self._checklist_instance(obj)
        if inst is None or not inst.fecha_inicio:
            return None
        return inst.fecha_inicio.isoformat()

    def get_checklist_items_completados(self, obj) -> int:
        inst = self._checklist_instance(obj)
        if inst is None:
            return 0
        return inst.respuestas.filter(completado=True).count()

    def get_checklist_items_total(self, obj) -> int:
        inst = self._checklist_instance(obj)
        if inst is None or not inst.checklist_template_id:
            return 0
        return inst.checklist_template.items.count()

    def get_checklist_minutos_transcurridos(self, obj) -> int | None:
        from django.utils import timezone

        inst = self._checklist_instance(obj)
        if inst is None or not inst.fecha_inicio:
            return None
        fin = inst.fecha_finalizacion or timezone.now()
        return max(0, int((fin - inst.fecha_inicio).total_seconds() // 60))

    def _informe_publico(self, obj):
        inst = self._checklist_instance(obj)
        if inst is None:
            return None
        try:
            return inst.informe_publico
        except Exception:
            return None

    def get_informe_publico_url(self, obj) -> str | None:
        informe = self._informe_publico(obj)
        if informe is None:
            return None
        return informe.url_publica or None

    def get_informe_publico_token(self, obj) -> str | None:
        informe = self._informe_publico(obj)
        return informe.token if informe else None

    def get_puede_cancelar(self, obj) -> bool:
        """No cancelable una vez iniciado el checklist operativo."""
        if obj.estado != 'activa':
            return False
        inst = self._checklist_instance(obj)
        if inst is None:
            return True
        return inst.estado in ('PENDIENTE',)

    def get_template_generado_por_ia(self, obj) -> bool:
        inst = self._checklist_instance(obj)
        if inst is None or inst.checklist_template is None:
            return False
        tpl = inst.checklist_template
        return bool(tpl.generado_por_ia and tpl.revisado_en is None)

    def get_estado_operativo(self, obj) -> str:
        if obj.estado == 'cancelada':
            return 'cancelado'
        if obj.estado == 'cerrada':
            # Cita cerrada = servicio completado (mismo semántica UI que marketplace).
            return 'completado'
        if obj.horario_por_confirmar:
            return 'por_agendar'

        inst = self._checklist_instance(obj)
        if inst is None:
            return 'agendado' if obj.miembro_taller_id else 'nuevo'
        if inst.estado in ('PENDIENTE',):
            return 'agendado'
        if inst.estado in ('EN_PROGRESO', 'PAUSADO'):
            return 'en_ejecucion'
        if inst.estado in (
            'PENDIENTE_FIRMA_SUPERVISOR',
            'PENDIENTE_FIRMA_CLIENTE',
        ):
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

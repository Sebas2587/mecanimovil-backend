"""Modelos del agente IA conversacional por taller."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class TallerAgenteConfig(models.Model):
    """Configuración global del agente IA para un taller."""

    CANAL_WHATSAPP = 'WHATSAPP'
    CANAL_MESSENGER = 'MESSENGER'
    CANAL_INSTAGRAM = 'INSTAGRAM'
    CANAL_APP = 'APP'

    taller = models.OneToOneField(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='agente_config',
    )
    habilitado = models.BooleanField(default=False)
    nombre_agente = models.CharField(
        max_length=80,
        blank=True,
        default='',
        help_text='Nombre con el que el agente se presenta a los clientes (ej. Carlos, Sofía).',
    )
    instrucciones_personalizadas = models.TextField(blank=True, default='')
    canales_habilitados = models.JSONField(
        default=list,
        blank=True,
        help_text='Lista de canales donde el agente puede responder (WHATSAPP, MESSENGER, INSTAGRAM, APP).',
    )
    mensaje_bienvenida = models.TextField(blank=True, default='')
    recargo_domicilio_clp = models.PositiveIntegerField(
        default=5000,
        help_text='Recargo fijo (CLP) que se suma a la mano de obra cuando la modalidad es a domicilio.',
    )
    NIVEL_INSISTENCIA_BAJO = 'bajo'
    NIVEL_INSISTENCIA_MEDIO = 'medio'
    NIVEL_INSISTENCIA_ALTO = 'alto'
    NIVEL_INSISTENCIA_CHOICES = [
        (NIVEL_INSISTENCIA_BAJO, 'Bajo'),
        (NIVEL_INSISTENCIA_MEDIO, 'Medio'),
        (NIVEL_INSISTENCIA_ALTO, 'Alto'),
    ]
    nivel_insistencia = models.CharField(
        max_length=10,
        choices=NIVEL_INSISTENCIA_CHOICES,
        default=NIVEL_INSISTENCIA_MEDIO,
        help_text='Qué tan insistente es el agente al empujar cotización/agenda.',
    )
    permite_estimados_historicos = models.BooleanField(
        default=True,
        help_text='Si está activo, el agente puede citar referencias históricas cuando no hay tarifa de catálogo.',
    )
    TONO_CONSERVADOR = 'conservador'
    TONO_BALANCEADO = 'balanceado'
    TONO_PROACTIVO = 'proactivo'
    TONO_VENTAS_CHOICES = [
        (TONO_CONSERVADOR, 'Conservador'),
        (TONO_BALANCEADO, 'Balanceado'),
        (TONO_PROACTIVO, 'Proactivo'),
    ]
    tono_ventas = models.CharField(
        max_length=15,
        choices=TONO_VENTAS_CHOICES,
        default=TONO_BALANCEADO,
        help_text='Estilo comercial del agente (asesoría vs cierre).',
    )
    requiere_direccion_antes_de_cotizar = models.BooleanField(
        default=False,
        help_text='Si está activo, el agente debe pedir dirección del cliente antes de armar borrador.',
    )
    preguntar_calidad_repuestos = models.BooleanField(
        default=True,
        help_text='Si está activo, el agente puede preguntar calidad (original/OEM/alternativo).',
    )
    vitrina_repuestos_habilitada = models.BooleanField(
        default=True,
        help_text='Si el agente está activo, puede enviar la vitrina pública de opciones.',
    )
    vitrina_muestra_bandas = models.BooleanField(
        default=True,
        help_text='Si hay ≥2 fuentes, mostrar banda de referencia en la vitrina.',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración agente IA'
        verbose_name_plural = 'Configuraciones agente IA'

    def __str__(self):
        return f'Agente IA — {self.taller_id} ({self.habilitado})'

    def canal_habilitado(self, channel: str) -> bool:
        if not self.habilitado:
            return False
        canales = self.canales_habilitados or []
        if not canales:
            return True
        return channel in canales


class TallerConocimientoDocumento(models.Model):
    """Documento de contexto cargado por el taller."""

    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PROCESANDO = 'procesando'
    ESTADO_LISTO = 'listo'
    ESTADO_ERROR = 'error'

    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_PROCESANDO, 'Procesando'),
        (ESTADO_LISTO, 'Listo'),
        (ESTADO_ERROR, 'Error'),
    ]

    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='conocimiento_documentos',
    )
    titulo = models.CharField(max_length=255)
    archivo = models.FileField(
        upload_to='agente_ia/conocimiento/%Y/%m/',
        blank=True,
        null=True,
    )
    texto_pegado = models.TextField(blank=True, default='')
    estado_procesamiento = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default=ESTADO_PENDIENTE,
        db_index=True,
    )
    error_detalle = models.TextField(blank=True, default='')
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conocimiento_documentos_creados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Documento de conocimiento'
        verbose_name_plural = 'Documentos de conocimiento'
        ordering = ['-creado_en']

    def __str__(self):
        return f'{self.titulo} ({self.taller_id})'


class TallerConocimientoChunk(models.Model):
    """Fragmento indexado para búsqueda semántica (RAG)."""

    FUENTE_DOCUMENTO = 'DOCUMENTO_TALLER'
    FUENTE_CATALOGO = 'CATALOGO_SERVICIO'
    FUENTE_HISTORICO = 'HISTORICO_SERVICIO'
    FUENTE_INSTRUCCION = 'INSTRUCCION'
    FUENTE_CONVERSACION_EXITOSA = 'CONVERSACION_EXITOSA'
    FUENTE_LECCION_DIARIA = 'LECCION_DIARIA'

    FUENTE_CHOICES = [
        (FUENTE_DOCUMENTO, 'Documento del taller'),
        (FUENTE_CATALOGO, 'Catálogo de servicios'),
        (FUENTE_HISTORICO, 'Histórico de servicios'),
        (FUENTE_INSTRUCCION, 'Instrucciones personalizadas'),
        (FUENTE_CONVERSACION_EXITOSA, 'Conversación exitosa'),
        (FUENTE_LECCION_DIARIA, 'Lección diaria'),
    ]

    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='conocimiento_chunks',
    )
    documento = models.ForeignKey(
        TallerConocimientoDocumento,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='chunks',
    )
    fuente = models.CharField(max_length=30, choices=FUENTE_CHOICES, db_index=True)
    contenido = models.TextField()
    embedding = VectorField(dimensions=768, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    referencia_externa = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text='Clave estable para upsert (ej. oferta_servicio:123).',
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Chunk de conocimiento'
        verbose_name_plural = 'Chunks de conocimiento'
        indexes = [
            models.Index(fields=['taller', 'fuente'], name='agente_ia_chunk_taller_fuente'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['taller', 'referencia_externa'],
                condition=~models.Q(referencia_externa=''),
                name='agente_ia_chunk_ref_unica',
            ),
        ]

    def __str__(self):
        return f'Chunk {self.pk} ({self.fuente}) — taller {self.taller_id}'


class AgenteConversacionSesion(models.Model):
    """Estado del agente IA en una conversación."""

    ESTADO_CAPTURANDO = 'capturando'
    ESTADO_LISTO_COTIZAR = 'listo_para_cotizar'
    ESTADO_ELIGIENDO_REPUESTOS = 'eligiendo_repuestos'
    ESTADO_ESPERANDO_REVISION = 'esperando_revision_taller'
    ESTADO_AGENDANDO = 'agendando'
    ESTADO_COORDINACION_TERRENO = 'coordinacion_terreno'
    ESTADO_PAUSADO = 'pausado_por_taller'
    ESTADO_CERRADO = 'cerrado'

    ESTADO_CHOICES = [
        (ESTADO_CAPTURANDO, 'Capturando información'),
        (ESTADO_LISTO_COTIZAR, 'Listo para cotizar'),
        (ESTADO_ELIGIENDO_REPUESTOS, 'Eligiendo repuestos'),
        (ESTADO_ESPERANDO_REVISION, 'Esperando revisión del taller'),
        (ESTADO_AGENDANDO, 'Agendando cita'),
        (ESTADO_COORDINACION_TERRENO, 'Coordinación en terreno / en sitio'),
        (ESTADO_PAUSADO, 'Pausado por taller'),
        (ESTADO_CERRADO, 'Cerrado'),
    ]

    conversation = models.OneToOneField(
        'chat.Conversation',
        on_delete=models.CASCADE,
        related_name='agente_sesion',
    )
    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='agente_sesiones',
    )
    estado = models.CharField(
        max_length=30,
        choices=ESTADO_CHOICES,
        default=ESTADO_CAPTURANDO,
        db_index=True,
    )
    datos_capturados = models.JSONField(default=dict, blank=True)
    cotizacion_borrador = models.ForeignKey(
        'ordenes.CotizacionCanal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agente_sesiones',
    )
    cita_en_negociacion = models.ForeignKey(
        'ordenes.CitaAgendaPersonal',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='agente_sesiones_negociacion',
    )
    vitrina_activa = models.ForeignKey(
        'ordenes.VitrinaRepuestos',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sesiones_agente',
    )
    # Opt-out por conversación: en chats nuevos el agente arranca activo.
    # El taller lo apaga solo si quiere intervenir a mano en ese chat.
    habilitado_en_chat = models.BooleanField(
        default=True,
        help_text=(
            'Si True, el agente responde en ESTA conversación. '
            'Por defecto activo en chats nuevos; el taller debe desactivarlo para intervenir.'
        ),
    )
    pausado_por_taller = models.BooleanField(default=False)
    pausado_hasta = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Si el taller intervino, la IA se reanuda automáticamente después de esta fecha.',
    )
    ultima_interaccion_ia = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Sesión agente IA'
        verbose_name_plural = 'Sesiones agente IA'

    def __str__(self):
        return f'Sesión agente {self.pk} — conv {self.conversation_id} ({self.estado})'


class AgenteMensajeLog(models.Model):
    """Auditoría de decisiones del agente."""

    ACCION_RESPONDER = 'responder'
    ACCION_ESCALAR = 'escalar'
    ACCION_COTIZAR = 'cotizar'
    ACCION_IGNORAR = 'ignorar'

    ACCION_CHOICES = [
        (ACCION_RESPONDER, 'Responder'),
        (ACCION_ESCALAR, 'Escalar a humano'),
        (ACCION_COTIZAR, 'Generar cotización'),
        (ACCION_IGNORAR, 'Ignorar'),
    ]

    sesion = models.ForeignKey(
        AgenteConversacionSesion,
        on_delete=models.CASCADE,
        related_name='logs',
    )
    mensaje_entrante = models.TextField(blank=True, default='')
    chunks_usados = models.JSONField(default=list, blank=True)
    respuesta_generada = models.TextField(blank=True, default='')
    accion = models.CharField(max_length=20, choices=ACCION_CHOICES)
    metadata = models.JSONField(default=dict, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Log agente IA'
        verbose_name_plural = 'Logs agente IA'
        ordering = ['-fecha']

    def __str__(self):
        return f'Log {self.pk} — {self.accion}'


class LeadCalificacion(models.Model):
    """Score de intención comercial por conversación (embudo + priorización)."""

    CATEGORIA_SIN_CALIFICAR = 'sin_calificar'
    CATEGORIA_CURIOSO = 'curioso'
    CATEGORIA_COMPARANDO = 'comparando'
    CATEGORIA_SIN_PRESUPUESTO = 'sin_presupuesto'
    CATEGORIA_INTERESADO = 'interesado_calificado'
    CATEGORIA_LISTO_AGENDAR = 'listo_agendar'
    CATEGORIA_NO_AUTOMOTRIZ = 'no_automotriz'
    CATEGORIA_CERRADO_PERDIDO = 'cerrado_perdido'

    CATEGORIA_CHOICES = [
        (CATEGORIA_SIN_CALIFICAR, 'Sin calificar'),
        (CATEGORIA_CURIOSO, 'Curioso'),
        (CATEGORIA_COMPARANDO, 'Comparando'),
        (CATEGORIA_SIN_PRESUPUESTO, 'Sin presupuesto'),
        (CATEGORIA_INTERESADO, 'Interesado calificado'),
        (CATEGORIA_LISTO_AGENDAR, 'Listo para agendar'),
        (CATEGORIA_NO_AUTOMOTRIZ, 'No automotriz'),
        (CATEGORIA_CERRADO_PERDIDO, 'Cerrado / Perdido'),
    ]

    SENAL_LLM_MAP = {
        'curioso': CATEGORIA_CURIOSO,
        'comparando_precios': CATEGORIA_COMPARANDO,
        'sin_presupuesto': CATEGORIA_SIN_PRESUPUESTO,
        'interesado': CATEGORIA_INTERESADO,
        'listo_agendar': CATEGORIA_LISTO_AGENDAR,
        'no_automotriz': CATEGORIA_NO_AUTOMOTRIZ,
        'cerrado_perdido': CATEGORIA_CERRADO_PERDIDO,
        'rechazado': CATEGORIA_CERRADO_PERDIDO,
        'cancelado': CATEGORIA_CERRADO_PERDIDO,
    }

    conversation = models.OneToOneField(
        'chat.Conversation',
        on_delete=models.CASCADE,
        related_name='lead_calificacion',
    )
    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='leads_calificados',
    )
    categoria = models.CharField(
        max_length=30,
        choices=CATEGORIA_CHOICES,
        default=CATEGORIA_SIN_CALIFICAR,
        db_index=True,
    )
    score = models.PositiveSmallIntegerField(default=0)
    senal_llm = models.CharField(max_length=30, blank=True, default='')
    senales = models.JSONField(default=dict, blank=True)
    perdido_por_competencia = models.BooleanField(
        default=False,
        help_text='True si el cliente indicó que se fue con otro taller/competencia.',
    )
    motivo_perdida = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Motivo por el cual se perdió el lead (competencia, presupuesto, etc.).',
    )
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Calificación de lead'
        verbose_name_plural = 'Calificaciones de leads'
        indexes = [
            models.Index(fields=['taller', 'categoria'], name='agente_ia_lead_taller_cat'),
            models.Index(fields=['taller', '-score'], name='agente_ia_lead_taller_score'),
        ]

    def __str__(self):
        return f'Lead conv={self.conversation_id} score={self.score} ({self.categoria})'


class AgenteClienteMemoria(models.Model):
    """Memoria persistente del taller sobre un cliente (entre conversaciones distintas)."""

    DISPOSICION_CURIOSO = 'curioso'
    DISPOSICION_NO_LISTO = 'no_listo'
    DISPOSICION_INTERESADO = 'interesado'
    DISPOSICION_LISTO_AGENDAR = 'listo_agendar'

    DISPOSICION_CHOICES = [
        (DISPOSICION_CURIOSO, 'Curioso / asesoría'),
        (DISPOSICION_NO_LISTO, 'No listo para cotizar'),
        (DISPOSICION_INTERESADO, 'Interesado'),
        (DISPOSICION_LISTO_AGENDAR, 'Listo para agendar'),
    ]

    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='memorias_clientes_agente',
    )
    external_contact = models.ForeignKey(
        'omnichannel.ExternalContact',
        on_delete=models.CASCADE,
        related_name='memorias_agente',
    )
    resumen = models.TextField(blank=True, default='')
    disposicion_reciente = models.CharField(
        max_length=30,
        choices=DISPOSICION_CHOICES,
        blank=True,
        default='',
    )
    calidad_preferida = models.CharField(max_length=16, blank=True, default='')
    preferencias_repuestos = models.JSONField(default=dict, blank=True)
    ultima_conversacion = models.ForeignKey(
        'chat.Conversation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Memoria cliente agente IA'
        verbose_name_plural = 'Memorias clientes agente IA'
        constraints = [
            models.UniqueConstraint(
                fields=['taller', 'external_contact'],
                name='agente_ia_memoria_taller_contacto_unique',
            ),
        ]
        indexes = [
            models.Index(fields=['taller', '-actualizado_en'], name='agente_ia_mem_taller_idx'),
        ]

    def __str__(self):
        return f'Memoria taller={self.taller_id} contact={self.external_contact_id}'


class AgenteAprendizajeDiario(models.Model):
    """Hallazgos estructurados del job diario de aprendizaje por taller."""

    TIPO_LEAD_PERDIDO = 'lead_perdido'
    TIPO_RESPUESTA_INSUFICIENTE = 'respuesta_insuficiente'
    TIPO_CORRECCION_SISTEMATICA = 'correccion_sistematica'
    TIPO_PATRON_ALTA_CONFIANZA = 'patron_alta_confianza'
    TIPO_SELECCION_REPUESTO = 'seleccion_repuesto'

    TIPO_HALLAZGO_CHOICES = [
        (TIPO_LEAD_PERDIDO, 'Lead perdido'),
        (TIPO_RESPUESTA_INSUFICIENTE, 'Respuesta insuficiente'),
        (TIPO_CORRECCION_SISTEMATICA, 'Corrección sistemática'),
        (TIPO_PATRON_ALTA_CONFIANZA, 'Patrón alta confianza'),
        (TIPO_SELECCION_REPUESTO, 'Selección de repuesto'),
    ]

    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='aprendizajes_diarios',
    )
    fecha = models.DateField(db_index=True)
    tipo_hallazgo = models.CharField(max_length=40, choices=TIPO_HALLAZGO_CHOICES, db_index=True)
    detalle_json = models.JSONField(default=dict, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Aprendizaje diario agente IA'
        verbose_name_plural = 'Aprendizajes diarios agente IA'
        indexes = [
            models.Index(fields=['taller', '-fecha'], name='agente_ia_aprend_taller_fecha'),
        ]

    def __str__(self):
        return f'Aprendizaje {self.taller_id} {self.fecha} ({self.tipo_hallazgo})'

import secrets

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def _generar_token_informe() -> str:
    return secrets.token_urlsafe(24)


def _default_fecha_expiracion_informe():
    from django.conf import settings
    dias = getattr(settings, 'INFORME_PUBLICO_TTL_DAYS', 30)
    return timezone.now() + timezone.timedelta(days=dias)


class InformeServicioPublico(models.Model):
    """Informe público de servicio (cita personal taller) con firma de cliente y reclamo de vehículo."""

    ESTADO_CHOICES = [
        ('PENDIENTE_FIRMA_CLIENTE', 'Pendiente de firma del cliente'),
        ('FIRMADO', 'Firmado por el cliente'),
        ('VEHICULO_RECLAMADO', 'Vehículo reclamado en la app'),
    ]

    ENVIADO_VIA_CHOICES = [
        ('whatsapp', 'WhatsApp'),
        ('instagram', 'Instagram'),
        ('messenger', 'Messenger'),
        ('manual_link', 'Enlace manual'),
    ]

    checklist_instance = models.OneToOneField(
        'checklists.ChecklistInstance',
        on_delete=models.CASCADE,
        related_name='informe_publico',
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        default=_generar_token_informe,
        db_index=True,
    )
    resumen_ia = models.TextField(blank=True, default='')
    generado_en = models.DateTimeField(auto_now_add=True)
    fecha_expiracion = models.DateTimeField(
        default=_default_fecha_expiracion_informe,
        db_index=True,
        help_text='Vencimiento del enlace público del informe.',
    )

    # Snapshot de vehículo (texto + datos API patente al generar)
    vehiculo_patente = models.CharField(max_length=20, blank=True, default='')
    vehiculo_marca = models.CharField(max_length=100, blank=True, default='')
    vehiculo_modelo = models.CharField(max_length=100, blank=True, default='')
    vehiculo_anio = models.PositiveIntegerField(null=True, blank=True)
    vehiculo_vin = models.CharField(max_length=30, blank=True, default='')
    kilometraje_servicio = models.PositiveIntegerField(null=True, blank=True)
    kilometraje_api = models.IntegerField(null=True, blank=True)
    datos_patente_json = models.JSONField(default=dict, blank=True)

    estado = models.CharField(
        max_length=30,
        choices=ESTADO_CHOICES,
        default='PENDIENTE_FIRMA_CLIENTE',
    )
    firma_cliente = models.TextField(null=True, blank=True)
    firmado_por_nombre = models.CharField(max_length=200, blank=True, default='')
    fecha_firma_cliente = models.DateTimeField(null=True, blank=True)

    reclamado_por_vehiculo = models.ForeignKey(
        'vehiculos.Vehiculo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='informes_reclamados',
    )
    reclamado_por_cliente = models.ForeignKey(
        'usuarios.Cliente',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='informes_reclamados',
    )
    reclamado_en = models.DateTimeField(null=True, blank=True)

    enviado_via = models.CharField(
        max_length=20,
        choices=ENVIADO_VIA_CHOICES,
        blank=True,
        default='',
    )
    url_publica = models.URLField(max_length=500, blank=True, default='')

    class Meta:
        verbose_name = _('Informe público de servicio')
        verbose_name_plural = _('Informes públicos de servicio')
        ordering = ['-generado_en']

    def __str__(self):
        return f'Informe {self.token[:8]}… (checklist #{self.checklist_instance_id})'

    @property
    def is_expired(self) -> bool:
        if self.fecha_expiracion is None:
            return False
        return timezone.now() > self.fecha_expiracion

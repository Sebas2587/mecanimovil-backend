from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import secrets


class TransferenciaVehiculo(models.Model):
    """
    Transferencia digital del registro vehicular (historial, salud, km).
    Flujo P2P: el dueño genera QR; el comprador lo escanea y asume la propiedad
    en Mecanimovil (no es traspaso legal de dominio).
    """
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('COMPLETADO', 'Completado'),
        ('EXPIRADO', 'Expirado'),
        ('CANCELADO', 'Cancelado'),
    ]

    vehiculo = models.ForeignKey(
        'vehiculos.Vehiculo',
        on_delete=models.CASCADE,
        related_name='transferencias'
    )
    vendedor = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE,
        related_name='transferencias_ventas'
    )
    # Nullable: en P2P el comprador se asigna al escanear el QR.
    comprador = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE,
        related_name='transferencias_compras',
        null=True,
        blank=True,
    )
    # Nullable: marketplace de ofertas deprecado; se conserva por transferencias legacy.
    oferta_asociada = models.OneToOneField(
        'vehiculos.OfertaVehiculo',
        on_delete=models.CASCADE,
        related_name='transferencia',
        null=True,
        blank=True,
    )

    token_transferencia = models.CharField(max_length=64, unique=True, editable=False)
    qr_data = models.TextField(help_text="Datos encriptados para generar el QR")
    fecha_expiracion = models.DateTimeField()
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PENDIENTE')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('transferencia de vehículo')
        verbose_name_plural = _('transferencias de vehículos')
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"Transferencia {self.vehiculo} ({self.estado})"

    def save(self, *args, **kwargs):
        if not self.token_transferencia:
            self.token_transferencia = secrets.token_urlsafe(32)
        if not self.fecha_expiracion:
            self.fecha_expiracion = timezone.now() + timezone.timedelta(minutes=15)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.fecha_expiracion

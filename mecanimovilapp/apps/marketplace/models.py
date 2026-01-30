from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import uuid
import secrets

class TransferenciaVehiculo(models.Model):
    """
    Modelo para gestionar la transferencia digital de vehículos mediante QR/Token.
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
    comprador = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE,
        related_name='transferencias_compras'
    )
    oferta_asociada = models.OneToOneField(
        'vehiculos.OfertaVehiculo',
        on_delete=models.CASCADE,
        related_name='transferencia'
    )
    
    # Token seguro para la transferencia (lo que el vendedor muestra/comparte)
    token_transferencia = models.CharField(max_length=64, unique=True, editable=False)
    
    # Datos encriptados/firmados para el QR (para mayor seguridad off-line o validación extra)
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

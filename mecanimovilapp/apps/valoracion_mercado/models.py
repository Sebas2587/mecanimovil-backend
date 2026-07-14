from django.db import models
from django.utils.translation import gettext_lazy as _


class AvisoExternoVehiculo(models.Model):
    """Listado scrapeado de portales externos (sin datos de contacto del vendedor)."""

    FUENTE_CHOICES = [
        ('mercadolibre', 'MercadoLibre'),
        ('chileautos', 'Chileautos'),
    ]

    fuente = models.CharField(max_length=32, choices=FUENTE_CHOICES)
    external_id = models.CharField(max_length=128)
    url = models.URLField(max_length=512, blank=True, default='')
    marca_texto = models.CharField(max_length=80, blank=True, default='')
    modelo_texto = models.CharField(max_length=120, blank=True, default='')
    marca = models.ForeignKey(
        'vehiculos.MarcaVehiculo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='avisos_externos',
    )
    modelo = models.ForeignKey(
        'vehiculos.Modelo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='avisos_externos',
    )
    year = models.PositiveIntegerField(null=True, blank=True)
    kilometraje = models.PositiveIntegerField(null=True, blank=True)
    precio = models.PositiveIntegerField()
    region = models.CharField(max_length=80, blank=True, default='')
    titulo_raw = models.TextField(blank=True, default='')
    fecha_primera_vista = models.DateTimeField(auto_now_add=True)
    fecha_ultima_vista = models.DateTimeField(auto_now=True)
    activo = models.BooleanField(default=True)
    fecha_removido = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('aviso externo de vehículo')
        verbose_name_plural = _('avisos externos de vehículos')
        unique_together = [('fuente', 'external_id')]
        indexes = [
            models.Index(fields=['marca', 'modelo', 'year', 'activo']),
            models.Index(fields=['fecha_ultima_vista']),
        ]

    def __str__(self):
        return f'{self.fuente}:{self.external_id} — {self.precio}'


class SegmentoValorHistorial(models.Model):
    """Agregado semanal por marca+modelo+año (bucket ±1)."""

    marca = models.ForeignKey(
        'vehiculos.MarcaVehiculo',
        on_delete=models.CASCADE,
        related_name='segmentos_valor',
    )
    modelo = models.ForeignKey(
        'vehiculos.Modelo',
        on_delete=models.CASCADE,
        related_name='segmentos_valor',
    )
    year_bucket = models.PositiveIntegerField(help_text='Año representativo del segmento')
    year_min = models.PositiveIntegerField()
    year_max = models.PositiveIntegerField()
    fecha_snapshot = models.DateField()
    n_anuncios_activos = models.PositiveIntegerField(default=0)
    precio_mediana = models.PositiveIntegerField(default=0)
    precio_p25 = models.PositiveIntegerField(default=0)
    precio_p75 = models.PositiveIntegerField(default=0)
    tasa_rotacion_30d_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Porcentaje de avisos removidos en ~30 días',
    )

    class Meta:
        verbose_name = _('histórico de segmento')
        verbose_name_plural = _('históricos de segmentos')
        unique_together = [('marca', 'modelo', 'year_bucket', 'fecha_snapshot')]
        ordering = ['-fecha_snapshot']

    def __str__(self):
        return f'{self.marca} {self.modelo} {self.year_bucket} @ {self.fecha_snapshot}'


class TasacionHistorial(models.Model):
    """Snapshot mensual de tasación GetAPI por vehículo."""

    vehiculo = models.ForeignKey(
        'vehiculos.Vehiculo',
        on_delete=models.CASCADE,
        related_name='tasaciones_historial',
    )
    fecha = models.DateField()
    precio_mercado_promedio = models.PositiveIntegerField(default=0)
    banda_min = models.PositiveIntegerField(default=0)
    banda_max = models.PositiveIntegerField(default=0)
    tasacion_fiscal = models.PositiveIntegerField(default=0)
    mileage = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _('histórico de tasación')
        verbose_name_plural = _('históricos de tasación')
        unique_together = [('vehiculo', 'fecha')]
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.vehiculo_id} @ {self.fecha}'


class CurvaDepreciacionSegmento(models.Model):
    """Tasa anual de depreciación por categoría de vehículo (fallback administrable)."""

    tipo_vehiculo = models.CharField(max_length=40, unique=True)
    tasa_anual_pct = models.DecimalField(max_digits=5, decimal_places=2, default=7.0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('curva de depreciación')
        verbose_name_plural = _('curvas de depreciación')

    def __str__(self):
        return f'{self.tipo_vehiculo}: {self.tasa_anual_pct}%/año'


class ValoracionVehiculo(models.Model):
    """Cache de valoración calculada por vehículo."""

    CONFIANZA_CHOICES = [
        ('alta', 'Alta'),
        ('media', 'Media'),
        ('estimado', 'Estimado'),
    ]
    LIQUIDEZ_LABEL_CHOICES = [
        ('facil', 'Fácil'),
        ('moderado', 'Moderado'),
        ('dificil', 'Difícil'),
        ('calculando', 'Calculando'),
    ]

    vehiculo = models.OneToOneField(
        'vehiculos.Vehiculo',
        on_delete=models.CASCADE,
        related_name='valoracion_mercado',
    )
    valor_real_hoy = models.PositiveIntegerField(default=0)
    valor_real_rango_min = models.PositiveIntegerField(default=0)
    valor_real_rango_max = models.PositiveIntegerField(default=0)
    confianza = models.CharField(max_length=16, choices=CONFIANZA_CHOICES, default='estimado')
    liquidez_score = models.PositiveSmallIntegerField(default=0)
    liquidez_label = models.CharField(
        max_length=16,
        choices=LIQUIDEZ_LABEL_CHOICES,
        default='calculando',
    )
    liquidez_razones = models.JSONField(default=list, blank=True)
    proyeccion = models.JSONField(default=list, blank=True)
    histograma = models.JSONField(default=list, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    fecha_calculo = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('valoración de vehículo')
        verbose_name_plural = _('valoraciones de vehículos')

    def __str__(self):
        return f'Valoración {self.vehiculo_id} — {self.valor_real_hoy}'


class MercadoLibreOAuthToken(models.Model):
    """
    Token OAuth único (singleton) para /sites/MLC/search.
    Persistido en Postgres (no env vars) para sobrevivir deploys sin intervención manual.
    """

    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    access_token = models.TextField(blank=True, default='')
    refresh_token = models.TextField(blank=True, default='')
    token_type = models.CharField(max_length=32, blank=True, default='')
    scope = models.CharField(max_length=255, blank=True, default='')
    ml_user_id = models.BigIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('token OAuth MercadoLibre')
        verbose_name_plural = _('token OAuth MercadoLibre')

    def __str__(self):
        return f'ML OAuth token (actualizado {self.updated_at:%Y-%m-%d %H:%M})'

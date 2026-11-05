"""Libro de caja del taller. No reemplaza Pago ni los flags de la oferta."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class CobroTaller(models.Model):
    """Movimiento append-only. Un reembolso es otra fila, no un borrado."""

    ORIGEN_MP = 'mercadopago'
    ORIGEN_MANUAL = 'manual'
    ORIGEN_CHOICES = [
        (ORIGEN_MP, 'Mercado Pago'),
        (ORIGEN_MANUAL, 'Manual'),
    ]

    TIPO_ENTRADA = 'entrada'
    TIPO_REEMBOLSO = 'reembolso'
    TIPO_CONTRACARGO = 'contracargo'
    TIPO_CHOICES = [
        (TIPO_ENTRADA, 'Entrada'),
        (TIPO_REEMBOLSO, 'Reembolso'),
        (TIPO_CONTRACARGO, 'Contracargo'),
    ]

    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_CONFIRMADO = 'confirmado'
    ESTADO_RECHAZADO = 'rechazado'
    ESTADO_CANCELADO = 'cancelado'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_CONFIRMADO, 'Confirmado'),
        (ESTADO_RECHAZADO, 'Rechazado'),
        (ESTADO_CANCELADO, 'Cancelado'),
    ]

    ANCLA_CITA = 'cita'
    ANCLA_SOLICITUD = 'solicitud'
    ANCLA_OFERTA = 'oferta'
    ANCLA_CHOICES = [
        (ANCLA_CITA, 'Cita'),
        (ANCLA_SOLICITUD, 'Solicitud'),
        (ANCLA_OFERTA, 'Oferta'),
    ]

    COMPONENTE_REPUESTOS = 'repuestos'
    COMPONENTE_SERVICIO = 'servicio'
    COMPONENTE_TOTAL = 'total'
    COMPONENTE_CHOICES = [
        (COMPONENTE_REPUESTOS, 'Repuestos'),
        (COMPONENTE_SERVICIO, 'Servicio'),
        (COMPONENTE_TOTAL, 'Total'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='cobros_caja',
    )
    ancla_tipo = models.CharField(max_length=16, choices=ANCLA_CHOICES)
    ancla_id = models.CharField(max_length=64)
    componente = models.CharField(
        max_length=16,
        choices=COMPONENTE_CHOICES,
        default=COMPONENTE_TOTAL,
    )
    origen = models.CharField(max_length=16, choices=ORIGEN_CHOICES)
    ref_externa = models.CharField(max_length=255)
    tipo = models.CharField(max_length=16, choices=TIPO_CHOICES)
    estado = models.CharField(max_length=16, choices=ESTADO_CHOICES)
    monto_clp = models.PositiveIntegerField(
        help_text='CLP entero. 0 solo si la fila no contabiliza en CLP.',
    )
    moneda = models.CharField(max_length=3, default='CLP')
    contabiliza_clp = models.BooleanField(default=True)
    monto_origen = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Monto tal como llegó de la fuente, antes de dejarlo en CLP entero.',
    )
    fecha_efectiva = models.DateTimeField()
    fecha_local = models.DateField(
        help_text='Día de caja en America/Santiago.',
    )
    movimiento_origen = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='reversos',
    )
    motivo = models.TextField(blank=True, default='')
    cuerpo_hash = models.CharField(max_length=64, blank=True, default='')
    pago = models.ForeignKey(
        'pagos.Pago',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movimientos_caja',
    )
    metadata = models.JSONField(default=dict, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cobros_caja_creados',
    )

    class Meta:
        verbose_name = 'cobro de taller'
        verbose_name_plural = 'cobros de taller'
        ordering = ['fecha_local', 'creado_en']
        constraints = [
            models.UniqueConstraint(
                fields=['taller', 'origen', 'ref_externa'],
                name='cobro_taller_ref_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['taller', 'fecha_local'], name='cobro_taller_fecha_idx'),
            models.Index(
                fields=['taller', 'ancla_tipo', 'ancla_id'],
                name='cobro_taller_ancla_idx',
            ),
        ]

    def __str__(self):
        return f'{self.origen} {self.tipo} {self.monto_clp} {self.fecha_local}'


class CostoTaller(models.Model):
    """Costo del caso. La fila anterior queda vigente=False: no se borra."""

    TIPO_REGISTRADO = 'registrado'
    TIPO_ESTIMADO = 'estimado'
    TIPO_CHOICES = [
        (TIPO_REGISTRADO, 'Registrado'),
        (TIPO_ESTIMADO, 'Estimado'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    taller = models.ForeignKey(
        'usuarios.Taller',
        on_delete=models.CASCADE,
        related_name='costos_caja',
    )
    ancla_tipo = models.CharField(max_length=16, choices=CobroTaller.ANCLA_CHOICES)
    ancla_id = models.CharField(max_length=64)
    componente = models.CharField(max_length=16, choices=CobroTaller.COMPONENTE_CHOICES)
    tipo = models.CharField(max_length=16, choices=TIPO_CHOICES)
    monto_clp = models.PositiveIntegerField()
    moneda = models.CharField(max_length=3, default='CLP')
    nota = models.TextField(blank=True, default='')
    vigente = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='costos_caja_creados',
    )

    class Meta:
        verbose_name = 'costo de taller'
        verbose_name_plural = 'costos de taller'
        ordering = ['-creado_en']
        constraints = [
            models.UniqueConstraint(
                fields=['taller', 'ancla_tipo', 'ancla_id', 'componente', 'tipo'],
                condition=models.Q(vigente=True),
                name='costo_taller_vigente_uniq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['taller', 'ancla_tipo', 'ancla_id'],
                name='costo_taller_ancla_idx',
            ),
        ]

    def __str__(self):
        return f'{self.tipo} {self.componente} {self.monto_clp}'

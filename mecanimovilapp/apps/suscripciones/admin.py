"""
Admin para el sistema Pay-per-Win con créditos.
"""
from django.contrib import admin
from .models import (
    CreditoProveedor,
    PaqueteCreditos,
    CompraCreditos,
    ConsumoCredito,
    ConfiguracionCreditos,
    ConfiguracionCreditosServicio,
    ProveedorCancelaciones
)

# Importar admins de créditos
from . import admin_creditos


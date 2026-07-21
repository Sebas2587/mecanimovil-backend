"""Habilitar / deshabilitar ficha pública compartible (Ley 21.719)."""
from __future__ import annotations

import secrets

from django.conf import settings

from mecanimovilapp.apps.vehiculos.models import Vehiculo


def _base_url_publica() -> str:
    return (
        getattr(settings, 'INFORME_PUBLIC_BASE_URL', '')
        or 'https://mecanimovil-usuarios.vercel.app'
    ).rstrip('/')


def construir_url_ficha_publica(token: str) -> str:
    return f'{_base_url_publica()}/marketplace/vehicle/ficha/{token}'


def habilitar_ficha_publica(vehiculo: Vehiculo) -> Vehiculo:
    if not vehiculo.ficha_publica_token:
        vehiculo.ficha_publica_token = secrets.token_urlsafe(24)
    vehiculo.ficha_publica_habilitada = True
    vehiculo.save(update_fields=['ficha_publica_habilitada', 'ficha_publica_token', 'fecha_actualizacion'])
    return vehiculo


def deshabilitar_ficha_publica(vehiculo: Vehiculo) -> Vehiculo:
    vehiculo.ficha_publica_habilitada = False
    vehiculo.save(update_fields=['ficha_publica_habilitada', 'fecha_actualizacion'])
    return vehiculo


def regenerar_token_ficha_publica(vehiculo: Vehiculo) -> Vehiculo:
    vehiculo.ficha_publica_token = secrets.token_urlsafe(24)
    vehiculo.ficha_publica_habilitada = True
    vehiculo.save(update_fields=['ficha_publica_token', 'ficha_publica_habilitada', 'fecha_actualizacion'])
    return vehiculo

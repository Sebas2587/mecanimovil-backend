"""Horas hábiles del taller: lunes a viernes, 9:00 a 18:30, America/Santiago."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

TZ_TALLER = ZoneInfo('America/Santiago')
APERTURA = time(9, 0)
CIERRE = time(18, 30)
REANUDE = time(9, 30)


def _local(momento: datetime) -> datetime:
    if timezone.is_naive(momento):
        momento = timezone.make_aware(momento, timezone.get_current_timezone())
    return momento.astimezone(TZ_TALLER)


def _siguiente_arranque(momento: datetime) -> datetime:
    """Próximo instante hábil. Si ya es hábil, devuelve el mismo momento."""
    local = _local(momento)
    if local.weekday() < 5 and APERTURA <= local.time() < CIERRE:
        return local
    if local.weekday() < 5 and local.time() < REANUDE:
        return local.replace(hour=9, minute=30, second=0, microsecond=0)
    nxt = (local + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def sumar_horas_habiles(inicio: datetime, horas: float) -> datetime:
    """Suma horas solo dentro del horario hábil. Fuera de horario arranca a las 9:30."""
    cursor = _siguiente_arranque(inicio)
    restante = timedelta(hours=horas)
    while restante > timedelta(0):
        fin_dia = cursor.replace(hour=18, minute=30, second=0, microsecond=0)
        disponible = fin_dia - cursor
        if disponible <= timedelta(0):
            cursor = _siguiente_arranque(fin_dia + timedelta(minutes=1))
            continue
        if restante <= disponible:
            cursor = cursor + restante
            break
        restante -= disponible
        cursor = _siguiente_arranque(fin_dia + timedelta(minutes=1))
    return cursor.astimezone(timezone.get_current_timezone())

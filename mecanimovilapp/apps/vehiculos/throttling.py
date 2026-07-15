"""Throttling acotado para endpoints públicos de invitados."""
from rest_framework.throttling import AnonRateThrottle


class GuestPatenteThrottle(AnonRateThrottle):
    """Limita consultas públicas de patente por IP."""
    scope = 'guest_patente'

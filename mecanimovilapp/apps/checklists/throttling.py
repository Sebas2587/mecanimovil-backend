from rest_framework.throttling import AnonRateThrottle


class InformePublicThrottle(AnonRateThrottle):
    """Limita lectura/firma pública de informes por IP."""
    scope = 'informe_publico'

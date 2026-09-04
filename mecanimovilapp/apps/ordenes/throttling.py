from rest_framework.throttling import AnonRateThrottle


class CotizacionPublicaThrottle(AnonRateThrottle):
    """Limita lectura/respuesta pública de cotizaciones por IP."""
    scope = 'cotizacion_publica'


class VitrinaRepuestosThrottle(AnonRateThrottle):
    """Mismo tope que la cotización pública."""
    scope = 'cotizacion_publica'

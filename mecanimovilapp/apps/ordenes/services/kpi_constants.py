"""Constantes de negocio para KPIs de taller y mecánico."""

# SLA aceptación/rechazo de orden pagada (marketplace)
SLA_ACEPTACION_ORDEN_HORAS = 24
SLA_ACEPTACION_ORDEN_MINUTOS = SLA_ACEPTACION_ORDEN_HORAS * 60

# SLA envío de oferta (ya usado en proveedor_kpis)
SLA_RESPUESTA_OFERTA_MINUTOS = 120

# Decay exponencial: peso = exp(-dias / RECHAZO_DECAY_DIAS)
RECHAZO_DECAY_DIAS = 14

# Multiplicador si hay muchos rechazos recientes
PENALIZACION_RECHAZOS_RECIENTES_UMBRAL = 3
PENALIZACION_RECHAZOS_RECIENTES_VENTANA_DIAS = 7
PENALIZACION_RECHAZOS_MULTIPLICADOR = 0.85

# Severidad por tipo de rechazo (0–1)
SEVERIDAD_RECHAZO_ORDEN = 1.0
SEVERIDAD_RECHAZO_SOLICITUD_PUBLICA = 0.7

# Penalización base por evento de rechazo (× peso temporal × severidad)
PENALIZACION_RECHAZO_K = 20

# Bonus por aceptación dentro del SLA (suma al score confiabilidad)
BONUS_ACEPTACION_A_TIEMPO = 2

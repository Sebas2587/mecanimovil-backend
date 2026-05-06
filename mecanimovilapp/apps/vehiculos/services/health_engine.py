import math
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from ..models_health import (
    ComponenteSalud,
    ReglaMantenimientoEspecifica,
    ReglaMantenimientoGenerica,
    ComponenteSaludVehiculo,
    EstadoSaludVehiculo,
)
from ..models import Vehiculo

logger = logging.getLogger(__name__)


class HealthEngine:
    """
    Motor inteligente de cálculo de salud vehicular.

    Algoritmo Weibull de doble eje (km + tiempo):
      salud_km     = exp(-(km_recorridos / eta)^beta)       × 100
      salud_tiempo = exp(-(meses_desde_servicio / T)^beta)  × 100   [si regla tiene intervalo_meses]
      salud_pct    = min(salud_km, salud_tiempo)

    Modo historial desconocido (historial_conocido=False y km_recorridos > eta):
      Supuesto conservador: el componente se encuentra exactamente a 1 ciclo de vida útil
      desde el último servicio (km_recorridos_efectivos = eta).
      Esto da salud ≈ exp(-1) ≈ 37% (ATENCIÓN) en lugar de 0% (CRÍTICO falso).
      El anchor de tiempo usa vehiculo.fecha_creacion para no escribir fechas irracionales.
      El mensaje informa que los datos son estimados.

    Optimizaciones:
      - 4 queries prefetch al inicio en lugar de N×5 por componente.
      - select_for_update() + UniqueConstraint en EstadoSaludVehiculo.
      - bulk_update al final.
    """

    @staticmethod
    def calcular_salud_vehiculo(vehiculo_id):
        """
        Calcula la salud de todos los componentes para un vehículo dado.
        Actualiza el estado persistente y retorna un reporte detallado.

        Returns:
            list[dict]: Lista de componentes con su estado (orden ascendente por salud).
        """
        try:
            vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(id=vehiculo_id)
        except Vehiculo.DoesNotExist:
            logger.error(f"Vehículo {vehiculo_id} no encontrado para cálculo de salud")
            return []

        marca_nombre  = vehiculo.marca.nombre  if vehiculo.marca  else ""
        modelo_nombre = vehiculo.modelo.nombre if vehiculo.modelo else ""

        tipo_motor_raw = str(vehiculo.tipo_motor).upper().strip()
        if 'DIESEL' in tipo_motor_raw or 'DÍESEL' in tipo_motor_raw:
            tipo_motor_norm = 'DIESEL'
        elif 'ELECTRIC' in tipo_motor_raw:
            tipo_motor_norm = 'ELECTRICO'
        elif 'HYBRID' in tipo_motor_raw:
            tipo_motor_norm = 'HIBRIDO'
        else:
            tipo_motor_norm = 'GASOLINA'

        logger.info(
            "HealthEngine: Calculando para %s (%s %s) — Motor: %s — km: %s",
            vehiculo.patente, marca_nombre, modelo_nombre, tipo_motor_norm, vehiculo.kilometraje,
        )

        # ── Prefetch en 4 queries ────────────────────────────────────────────
        componentes_maestros = list(ComponenteSalud.objects.all())

        reglas_especificas_map = {
            r.componente_id: r
            for r in ReglaMantenimientoEspecifica.objects.filter(
                marca=marca_nombre, modelo=modelo_nombre
            )
        }
        reglas_genericas_map = {
            r.componente_id: r
            for r in ReglaMantenimientoGenerica.objects.filter(
                tipo_motor=tipo_motor_norm
            )
        }
        estados_map = {
            c.componente_id: c
            for c in ComponenteSaludVehiculo.objects.filter(vehiculo=vehiculo)
        }

        reporte_salud     = []
        stats             = {'total': 0, 'optimo': 0, 'atencion': 0, 'urgente': 0, 'critico': 0, 'sum_health': 0}
        nuevos_estados    = []
        estados_a_actualizar = []

        now         = timezone.now()
        fecha_reg   = vehiculo.fecha_creacion  # referencia para historial desconocido

        for comp_maestro in componentes_maestros:
            # ── Cascada de reglas ───────────────────────────────────────────
            regla_especifica = reglas_especificas_map.get(comp_maestro.id)
            regla_generica   = reglas_genericas_map.get(comp_maestro.id)

            if regla_especifica:
                regla_aplicada = regla_especifica
                es_especifica  = True
            elif regla_generica:
                regla_aplicada = regla_generica
                es_especifica  = False
            else:
                continue  # sin regla → skip, no cuenta en promedio global

            # ── Estado del componente ───────────────────────────────────────
            comp_estado = estados_map.get(comp_maestro.id)
            es_nuevo = False
            if comp_estado is None:
                comp_estado = ComponenteSaludVehiculo(
                    vehiculo=vehiculo,
                    componente=comp_maestro,
                    salud_porcentaje=100,
                    nivel_alerta='OPTIMO',
                    km_ultimo_servicio=0,
                    historial_conocido=False,
                )
                es_nuevo = True
                nuevos_estados.append(comp_estado)
                estados_map[comp_maestro.id] = comp_estado

            # ── Parámetros Weibull ──────────────────────────────────────────
            eta  = float(regla_aplicada.vida_util_km)
            beta = float(regla_aplicada.beta)
            km_recorridos_real = max(0, vehiculo.kilometraje - comp_estado.km_ultimo_servicio)

            # ── Modo historial desconocido ──────────────────────────────────
            # Si no hay datos reales de servicio y el vehículo ya superó un ciclo completo,
            # usamos exactamente 1 ciclo como estimación conservadora (~37 % salud).
            # Esto evita fechas proxy absurdas y el falso 0 % CRÍTICO.
            historial_desconocido = (
                not comp_estado.historial_conocido
                and comp_estado.km_ultimo_servicio == 0
                and km_recorridos_real > eta
                and eta > 0
            )

            if historial_desconocido:
                km_recorridos = eta  # 1 ciclo de vida útil → salud ≈ 37 %
                # Usar fecha de registro como referencia temporal (no se persiste como proxy)
                fecha_ref_tiempo = fecha_reg if fecha_reg else now
            else:
                km_recorridos = km_recorridos_real
                fecha_ref_tiempo = None  # se usará fecha_ultimo_servicio normal

            # ── Salud por km (Weibull) ──────────────────────────────────────
            salud_km  = math.exp(-((km_recorridos / eta) ** beta)) * 100.0 if eta > 0 else 0.0
            salud_pct = salud_km
            months_elapsed = None

            # ── Intervalo por tiempo ────────────────────────────────────────
            intervalo_meses = getattr(regla_aplicada, 'intervalo_meses', None)
            if not intervalo_meses and es_especifica and regla_generica:
                intervalo_meses = getattr(regla_generica, 'intervalo_meses', None)

            if intervalo_meses and intervalo_meses > 0:
                # Determinar fecha de referencia para el eje tiempo
                if historial_desconocido:
                    # Usar fecha de registro del vehículo (no escribimos proxy en DB)
                    fecha_eje = fecha_ref_tiempo
                    if timezone.is_naive(fecha_eje):
                        fecha_eje = timezone.make_aware(fecha_eje)
                else:
                    # Anclar fecha_ultimo_servicio si no existe (proxy normal para historial conocido)
                    if not comp_estado.fecha_ultimo_servicio:
                        if km_recorridos_real <= 0:
                            comp_estado.fecha_ultimo_servicio = now
                            logger.info(
                                "HealthEngine: anclaje fecha=now (km=0) componente=%s vehiculo=%s",
                                comp_maestro.nombre, vehiculo_id,
                            )
                        elif eta > 0:
                            frac   = min(2.0, km_recorridos_real / eta)
                            anchor = now - timedelta(days=frac * float(intervalo_meses) * 30.44)
                            if timezone.is_naive(anchor):
                                anchor = timezone.make_aware(anchor)
                            comp_estado.fecha_ultimo_servicio = anchor
                            logger.info(
                                "HealthEngine: anclaje proxy meses=%.2f componente=%s vehiculo=%s",
                                frac * float(intervalo_meses), comp_maestro.nombre, vehiculo_id,
                            )

                    fecha_eje = comp_estado.fecha_ultimo_servicio
                    if fecha_eje and timezone.is_naive(fecha_eje):
                        fecha_eje = timezone.make_aware(fecha_eje)

                if fecha_eje:
                    months_elapsed = max(0.0, (now - fecha_eje).days / 30.44)
                    salud_tiempo   = math.exp(
                        -((months_elapsed / float(intervalo_meses)) ** beta)
                    ) * 100.0
                    salud_pct = min(salud_km, salud_tiempo)

            # ── Cap duro por meses_critico ──────────────────────────────────
            meses_critico = None
            if not es_especifica:
                meses_critico = getattr(regla_aplicada, 'meses_critico', None)
            elif regla_generica:
                meses_critico = getattr(regla_generica, 'meses_critico', None)
            if meses_critico and months_elapsed is not None and months_elapsed >= meses_critico:
                salud_pct = min(salud_pct, 25.0)

            # ── Status ──────────────────────────────────────────────────────
            if salud_pct >= 70:
                status = 'OPTIMO';  stats['optimo']   += 1
            elif salud_pct >= 40:
                status = 'ATENCION'; stats['atencion'] += 1
            elif salud_pct >= 10:
                status = 'URGENTE';  stats['urgente']  += 1
            else:
                status = 'CRITICO';  stats['critico']  += 1

            stats['total']      += 1
            stats['sum_health'] += salud_pct

            km_restantes = max(0, int(eta - km_recorridos))

            # ── Actualizar estado en memoria ────────────────────────────────
            comp_estado.salud_porcentaje          = round(salud_pct, 1)
            comp_estado.nivel_alerta              = status
            comp_estado.vida_util_proyectada      = int(eta)
            comp_estado.es_regla_especifica       = es_especifica
            comp_estado.km_estimados_restantes    = km_restantes
            comp_estado.requiere_servicio_inmediato = (status in ('CRITICO', 'URGENTE'))

            if historial_desconocido:
                comp_estado.mensaje_alerta = (
                    f"Historial no registrado para {comp_maestro.nombre}. "
                    f"Estimación conservadora: ~{round(salud_pct)}% "
                    f"(basada en 1 ciclo de {int(eta):,} km). "
                    f"Actualiza el km de tu último servicio para mayor precisión."
                )
            elif comp_estado.requiere_servicio_inmediato:
                comp_estado.mensaje_alerta = (
                    f"Atención requerida: {comp_maestro.nombre} al {round(salud_pct)}%."
                )
            else:
                comp_estado.mensaje_alerta = ""

            if (
                not historial_desconocido
                and months_elapsed is not None
                and intervalo_meses
                and salud_pct < salud_km - 0.5
            ):
                extra = f" Intervalo por tiempo (~{int(months_elapsed)} meses desde último servicio)."
                comp_estado.mensaje_alerta = (comp_estado.mensaje_alerta or "").strip() + extra

            if not es_nuevo:
                estados_a_actualizar.append(comp_estado)

            reporte_item = {
                'componente':       comp_maestro.nombre,
                'slug':             comp_maestro.slug,
                'salud':            round(salud_pct, 1),
                'status':           status,
                'vida_util_total':  int(eta),
                'km_recorridos':    km_recorridos_real,      # km real (no sobreescrito)
                'km_efectivos':     km_recorridos,           # km usado en el cálculo
                'es_especifica':    es_especifica,
                'historial_conocido': comp_estado.historial_conocido,
            }
            if months_elapsed is not None:
                reporte_item['meses_desde_servicio'] = round(months_elapsed, 1)
            if intervalo_meses:
                reporte_item['intervalo_meses_regla'] = int(intervalo_meses)
            reporte_salud.append(reporte_item)

        # ── Persistir en bulk ───────────────────────────────────────────────
        update_fields = [
            'salud_porcentaje', 'nivel_alerta', 'vida_util_proyectada', 'es_regla_especifica',
            'km_estimados_restantes', 'requiere_servicio_inmediato', 'mensaje_alerta',
            'fecha_ultimo_servicio', 'historial_conocido',
        ]
        if nuevos_estados:
            ComponenteSaludVehiculo.objects.bulk_create(nuevos_estados, ignore_conflicts=True)
        if estados_a_actualizar:
            ComponenteSaludVehiculo.objects.bulk_update(estados_a_actualizar, update_fields)

        # ── Snapshot global (con select_for_update) ─────────────────────────
        promedio_global = (stats['sum_health'] / stats['total']) if stats['total'] > 0 else 0
        tiene_alertas   = (stats['urgente'] > 0 or stats['critico'] > 0)

        with transaction.atomic():
            estado_general, _ = EstadoSaludVehiculo.objects.select_for_update().get_or_create(
                vehiculo=vehiculo,
                defaults={
                    'salud_general_porcentaje':     round(promedio_global, 1),
                    'kilometraje_snapshot':          vehiculo.kilometraje,
                    'total_componentes_evaluados':   stats['total'],
                    'componentes_optimos':           stats['optimo'],
                    'componentes_atencion':          stats['atencion'],
                    'componentes_urgentes':          stats['urgente'],
                    'componentes_criticos':          stats['critico'],
                    'tiene_alertas_activas':         tiene_alertas,
                    'ultima_actualizacion':          now,
                }
            )
            EstadoSaludVehiculo.objects.filter(pk=estado_general.pk).update(
                salud_general_porcentaje    = round(promedio_global, 1),
                kilometraje_snapshot        = vehiculo.kilometraje,
                total_componentes_evaluados = stats['total'],
                componentes_optimos         = stats['optimo'],
                componentes_atencion        = stats['atencion'],
                componentes_urgentes        = stats['urgente'],
                componentes_criticos        = stats['critico'],
                tiene_alertas_activas       = tiene_alertas,
                ultima_actualizacion        = now,
            )

        reporte_salud.sort(key=lambda x: x['salud'])
        logger.info(
            "HealthEngine: Completado vehiculo=%s salud_global=%.1f%% "
            "(óptimos=%d, atención=%d, urgentes=%d, críticos=%d)",
            vehiculo_id, promedio_global,
            stats['optimo'], stats['atencion'], stats['urgente'], stats['critico'],
        )
        return reporte_salud

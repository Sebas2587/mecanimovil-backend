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
    AlertaMantenimiento
)
from ..models import Vehiculo

logger = logging.getLogger(__name__)


class HealthEngine:
    """
    Motor inteligente de cálculo de salud vehicular.
    Implementa arquitectura de Reglas en Cascada (Waterfall) y algoritmo Weibull.

    Optimizaciones aplicadas:
    - Prefetch completo de reglas y estados al inicio (4 queries fijas en lugar de N×5).
    - select_for_update() + unique constraint en EstadoSaludVehiculo evita duplicados bajo concurrencia.
    - bulk_update al final del loop en lugar de save() por componente.
    """

    @staticmethod
    def calcular_salud_vehiculo(vehiculo_id):
        """
        Calcula la salud de todos los componentes para un vehículo dado.
        Actualiza el estado persistente y retorna un reporte detallado.

        Returns:
            list[dict]: Lista de componentes con su estado calculado (orden ascendente por salud).
        """
        try:
            vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(id=vehiculo_id)
        except Vehiculo.DoesNotExist:
            logger.error(f"Vehículo {vehiculo_id} no encontrado para cálculo de salud")
            return []

        marca_nombre = vehiculo.marca.nombre if vehiculo.marca else ""
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
            f"HealthEngine: Calculando para {vehiculo.patente} ({marca_nombre} {modelo_nombre}) - Motor: {tipo_motor_norm}"
        )

        # ----------------------------------------------------------------
        # PREFETCH ÚNICO — 4 queries totales independientemente de cuántos
        # componentes existan en el catálogo.
        # ----------------------------------------------------------------
        componentes_maestros = list(ComponenteSalud.objects.all())

        # Reglas específicas para este vehículo (marca + modelo)
        reglas_especificas_map = {
            r.componente_id: r
            for r in ReglaMantenimientoEspecifica.objects.filter(
                marca=marca_nombre, modelo=modelo_nombre
            )
        }

        # Reglas genéricas para este tipo de motor
        reglas_genericas_map = {
            r.componente_id: r
            for r in ReglaMantenimientoGenerica.objects.filter(
                tipo_motor=tipo_motor_norm
            )
        }

        # Estados actuales de componentes del vehículo
        estados_map = {
            c.componente_id: c
            for c in ComponenteSaludVehiculo.objects.filter(vehiculo=vehiculo)
        }

        reporte_salud = []
        stats = {
            'total': 0, 'optimo': 0, 'atencion': 0,
            'urgente': 0, 'critico': 0, 'sum_health': 0
        }

        nuevos_estados = []
        estados_a_actualizar = []

        for comp_maestro in componentes_maestros:
            # ---- Cascada de reglas ----
            regla_especifica = reglas_especificas_map.get(comp_maestro.id)
            regla_generica = reglas_genericas_map.get(comp_maestro.id)

            if regla_especifica:
                regla_aplicada = regla_especifica
                es_especifica = True
            elif regla_generica:
                regla_aplicada = regla_generica
                es_especifica = False
            else:
                continue  # Sin regla → skip (no cuenta en promedio)

            # ---- Estado del componente ----
            comp_estado = estados_map.get(comp_maestro.id)
            if comp_estado is None:
                comp_estado = ComponenteSaludVehiculo(
                    vehiculo=vehiculo,
                    componente=comp_maestro,
                    salud_porcentaje=100,
                    nivel_alerta='OPTIMO',
                    km_ultimo_servicio=0,
                )
                nuevos_estados.append(comp_estado)
                estados_map[comp_maestro.id] = comp_estado

            # ---- Algoritmo Weibull (eje km) ----
            km_recorridos = max(0, vehiculo.kilometraje - comp_estado.km_ultimo_servicio)
            eta = float(regla_aplicada.vida_util_km)
            beta = float(regla_aplicada.beta)

            salud_km = math.exp(-((km_recorridos / eta) ** beta)) * 100.0 if eta > 0 else 0.0
            salud_pct = salud_km
            months_elapsed = None

            # Intervalo por tiempo: preferir regla específica, fallback a genérica
            intervalo_meses = getattr(regla_aplicada, 'intervalo_meses', None)
            if not intervalo_meses and es_especifica and regla_generica:
                intervalo_meses = getattr(regla_generica, 'intervalo_meses', None)

            # ---- Eje tiempo (Weibull sobre meses) ----
            if intervalo_meses and intervalo_meses > 0:
                now = timezone.now()
                if not comp_estado.fecha_ultimo_servicio:
                    if km_recorridos <= 0:
                        comp_estado.fecha_ultimo_servicio = now
                        logger.info(
                            "HealthEngine: anclaje fecha=now (km=0) componente=%s vehiculo=%s",
                            comp_maestro.nombre, vehiculo_id,
                        )
                    elif eta > 0:
                        frac = min(2.0, km_recorridos / eta)
                        anchor = now - timedelta(days=frac * float(intervalo_meses) * 30.44)
                        if timezone.is_naive(anchor):
                            anchor = timezone.make_aware(anchor)
                        comp_estado.fecha_ultimo_servicio = anchor
                        logger.info(
                            "HealthEngine: anclaje fecha proxy meses=%.2f componente=%s vehiculo=%s",
                            frac * float(intervalo_meses), comp_maestro.nombre, vehiculo_id,
                        )
                    else:
                        logger.warning(
                            "HealthEngine: intervalo_meses=%s pero eta=0; eje tiempo omitido componente=%s",
                            intervalo_meses, comp_maestro.nombre,
                        )

                if comp_estado.fecha_ultimo_servicio:
                    fecha_ref = comp_estado.fecha_ultimo_servicio
                    if timezone.is_naive(fecha_ref):
                        fecha_ref = timezone.make_aware(fecha_ref)
                    months_elapsed = max(0.0, (now - fecha_ref).days / 30.44)
                    salud_tiempo = math.exp(
                        -((months_elapsed / float(intervalo_meses)) ** beta)
                    ) * 100.0
                    salud_pct = min(salud_km, salud_tiempo)
                elif intervalo_meses:
                    logger.warning(
                        "HealthEngine: sin fecha anclable componente=%s vehiculo=%s (revisar checklist/mapeo)",
                        comp_maestro.nombre, vehiculo_id,
                    )

            # ---- Cap duro por meses_critico ----
            meses_critico = None
            if not es_especifica:
                meses_critico = getattr(regla_aplicada, 'meses_critico', None)
            elif regla_generica:
                meses_critico = getattr(regla_generica, 'meses_critico', None)

            if meses_critico and months_elapsed is not None and months_elapsed >= meses_critico:
                salud_pct = min(salud_pct, 25.0)

            # ---- Status ----
            if salud_pct >= 70:
                status = 'OPTIMO'
                stats['optimo'] += 1
            elif salud_pct >= 40:
                status = 'ATENCION'
                stats['atencion'] += 1
            elif salud_pct >= 10:
                status = 'URGENTE'
                stats['urgente'] += 1
            else:
                status = 'CRITICO'
                stats['critico'] += 1

            stats['total'] += 1
            stats['sum_health'] += salud_pct

            km_restantes = max(0, int(eta - km_recorridos))

            # ---- Actualizar objeto en memoria (sin save aún) ----
            comp_estado.salud_porcentaje = round(salud_pct, 1)
            comp_estado.nivel_alerta = status
            comp_estado.vida_util_proyectada = int(eta)
            comp_estado.es_regla_especifica = es_especifica
            comp_estado.km_estimados_restantes = km_restantes
            comp_estado.requiere_servicio_inmediato = (status in ('CRITICO', 'URGENTE'))

            if comp_estado.requiere_servicio_inmediato:
                comp_estado.mensaje_alerta = f"Atención requerida: {comp_maestro.nombre} al {round(salud_pct)}%."
            else:
                comp_estado.mensaje_alerta = ""

            if months_elapsed is not None and intervalo_meses and salud_pct < salud_km - 0.5:
                extra = f" Intervalo por tiempo (~{int(months_elapsed)} meses desde último servicio)."
                comp_estado.mensaje_alerta = (comp_estado.mensaje_alerta or "").strip() + extra

            if comp_estado.pk:
                estados_a_actualizar.append(comp_estado)

            reporte_item = {
                'componente': comp_maestro.nombre,
                'slug': comp_maestro.slug,
                'salud': round(salud_pct, 1),
                'status': status,
                'vida_util_total': int(eta),
                'km_recorridos': km_recorridos,
                'es_especifica': es_especifica,
            }
            if months_elapsed is not None:
                reporte_item['meses_desde_servicio'] = round(months_elapsed, 1)
            if intervalo_meses:
                reporte_item['intervalo_meses_regla'] = int(intervalo_meses)
            reporte_salud.append(reporte_item)

        # ---- Persistir en bulk ----
        update_fields = [
            'salud_porcentaje', 'nivel_alerta', 'vida_util_proyectada', 'es_regla_especifica',
            'km_estimados_restantes', 'requiere_servicio_inmediato', 'mensaje_alerta',
            'fecha_ultimo_servicio',
        ]
        if nuevos_estados:
            ComponenteSaludVehiculo.objects.bulk_create(nuevos_estados, ignore_conflicts=True)
        if estados_a_actualizar:
            ComponenteSaludVehiculo.objects.bulk_update(estados_a_actualizar, update_fields)

        # ---- Snapshot global (con select_for_update para evitar race condition) ----
        promedio_global = (stats['sum_health'] / stats['total']) if stats['total'] > 0 else 0
        tiene_alertas = (stats['urgente'] > 0 or stats['critico'] > 0)
        now = timezone.now()

        with transaction.atomic():
            estado_general, _ = EstadoSaludVehiculo.objects.select_for_update().get_or_create(
                vehiculo=vehiculo,
                defaults={
                    'salud_general_porcentaje': round(promedio_global, 1),
                    'kilometraje_snapshot': vehiculo.kilometraje,
                    'total_componentes_evaluados': stats['total'],
                    'componentes_optimos': stats['optimo'],
                    'componentes_atencion': stats['atencion'],
                    'componentes_urgentes': stats['urgente'],
                    'componentes_criticos': stats['critico'],
                    'tiene_alertas_activas': tiene_alertas,
                    'ultima_actualizacion': now,
                }
            )
            # Actualizar campos si la fila ya existía
            EstadoSaludVehiculo.objects.filter(pk=estado_general.pk).update(
                salud_general_porcentaje=round(promedio_global, 1),
                kilometraje_snapshot=vehiculo.kilometraje,
                total_componentes_evaluados=stats['total'],
                componentes_optimos=stats['optimo'],
                componentes_atencion=stats['atencion'],
                componentes_urgentes=stats['urgente'],
                componentes_criticos=stats['critico'],
                tiene_alertas_activas=tiene_alertas,
                ultima_actualizacion=now,
            )

        reporte_salud.sort(key=lambda x: x['salud'])
        logger.info(f"HealthEngine: Cálculo completado. Salud Global: {round(promedio_global, 1)}%")
        return reporte_salud

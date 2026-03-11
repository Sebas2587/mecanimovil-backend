import math
import logging
from datetime import timedelta
from django.utils import timezone
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
    """
    
    @staticmethod
    def calcular_salud_vehiculo(vehiculo_id):
        """
        Calcula la salud de todos los componentes para un vehículo dado.
        Actualiza el estado persistente y retorna un reporte detallado.
        
        Args:
            vehiculo_id: ID del vehículo
            
        Returns:
            list[dict]: Lista de componentes con su estado calculado.
        """
        try:
            vehiculo = Vehiculo.objects.get(id=vehiculo_id)
        except Vehiculo.DoesNotExist:
            logger.error(f"Vehículo {vehiculo_id} no encontrado para cálculo de salud")
            return []

        # 1. Normalizar datos del vehículo (marca/modelo son FKs; necesitamos el nombre)
        marca_nombre = vehiculo.marca.nombre if vehiculo.marca else ""
        modelo_nombre = vehiculo.modelo.nombre if vehiculo.modelo else ""
        
        # Mapeo de Motor para coincidir con Choices
        tipo_motor_raw = str(vehiculo.tipo_motor).upper().strip()
        if 'DIESEL' in tipo_motor_raw or 'DÍESEL' in tipo_motor_raw:
            tipo_motor_norm = 'DIESEL'
        elif 'ELECTRIC' in tipo_motor_raw:
            tipo_motor_norm = 'ELECTRICO'
        elif 'HYBRID' in tipo_motor_raw:
            tipo_motor_norm = 'HIBRIDO'
        else:
            tipo_motor_norm = 'GASOLINA' # Default safe fallback
            
        logger.info(f"HealthEngine: Calculando para {vehiculo.patente} ({marca_nombre} {modelo_nombre}) - Motor: {tipo_motor_norm}")

        # 2. Obtener todos los componentes activos del catálogo maestro
        # TODO: Filtrar componentes relevantes? Por ahora traemos todos y filtramos por reglas.
        componentes_maestros = ComponenteSalud.objects.all()
        
        reporte_salud = []
        stats = {
            'total': 0, 'optimo': 0, 'atencion': 0, 
            'urgente': 0, 'critico': 0, 'sum_health': 0
        }

        # Cache de Reglas para optimización (aunque con pocos componentes no es critico)
        # Podríamos hacer prefetch, pero iterar es mas claro para la lógica de cascada
        
        for comp_maestro in componentes_maestros:
            regla_aplicada = None
            es_especifica = False
            
            # --------------------------------------------------------
            # NIVEL 1: Regla Específica (Marca + Modelo)
            # --------------------------------------------------------
            try:
                regla_especifica = ReglaMantenimientoEspecifica.objects.get(
                    componente=comp_maestro,
                    marca=marca_nombre,
                    modelo=modelo_nombre
                )
                regla_aplicada = regla_especifica
                es_especifica = True
                # logger.debug(f"  - Regla Específica encontrada para {comp_maestro.nombre}")
            except ReglaMantenimientoEspecifica.DoesNotExist:
                pass
            
            # --------------------------------------------------------
            # NIVEL 2: Regla Genérica (Tipo Motor) - Fallback
            # --------------------------------------------------------
            if not regla_aplicada:
                try:
                    regla_generica = ReglaMantenimientoGenerica.objects.get(
                        componente=comp_maestro,
                        tipo_motor=tipo_motor_norm
                    )
                    regla_aplicada = regla_generica
                    es_especifica = False
                    # logger.debug(f"  - Regla Genérica encontrada para {comp_maestro.nombre}")
                except ReglaMantenimientoGenerica.DoesNotExist:
                    # Nivel 3: Skip
                    # Si no hay regla para este motor (ej: Bujías en Diesel), ignoramos el componente
                    continue

            # --------------------------------------------------------
            # Cálculo de Salud (Weibull Algorithm)
            # --------------------------------------------------------
            # Obtener estado persistente actual para saber el último servicio
            comp_estado, created = ComponenteSaludVehiculo.objects.get_or_create(
                vehiculo=vehiculo,
                componente=comp_maestro,
                defaults={
                    'salud_porcentaje': 100,
                    'nivel_alerta': 'OPTIMO',
                    'km_ultimo_servicio': 0 # Default riesgo: 0 (nunca mantenido)
                }
            )
            
            # Kilometraje recorrido desde último servicio
            km_recorridos = max(0, vehiculo.kilometraje - comp_estado.km_ultimo_servicio)

            # Parámetros Weibull (eje km)
            eta = float(regla_aplicada.vida_util_km)  # Scale Parameter (Vida característica)
            beta = float(regla_aplicada.beta)  # Shape Parameter

            # Salud por km: R(km) = exp(-(km_recorridos/eta)^beta)
            if eta > 0:
                salud_km = math.exp(-((km_recorridos / eta) ** beta)) * 100.0
            else:
                salud_km = 0.0

            salud_pct = salud_km
            months_elapsed = None
            intervalo_meses = getattr(regla_aplicada, 'intervalo_meses', None)

            # Si regla específica no trae intervalo_meses, intentar genérica solo para el eje tiempo
            if not intervalo_meses and es_especifica:
                try:
                    reg_gen = ReglaMantenimientoGenerica.objects.get(
                        componente=comp_maestro, tipo_motor=tipo_motor_norm
                    )
                    intervalo_meses = getattr(reg_gen, 'intervalo_meses', None)
                except ReglaMantenimientoGenerica.DoesNotExist:
                    pass

            # Eje tiempo: misma forma Weibull sobre "meses desde último servicio" vs intervalo_meses.
            # Sin fecha_ultimo_servicio el eje tiempo no aplicaba → métricas no cambiaban solo por tiempo.
            # Anclaje cuando hay intervalo_meses pero fecha null (checklist nunca matcheó o fila antigua):
            # - km_recorridos == 0 → último servicio "en este km" ahora (decae a partir de hoy).
            # - km_recorridos > 0 → proxy: fecha = ahora - fracción del intervalo acorde al desgaste km/eta
            #   para que el primer cálculo sea coherente; los días siguientes el tiempo sigue corriendo.
            if intervalo_meses and intervalo_meses > 0:
                if not comp_estado.fecha_ultimo_servicio:
                    now = timezone.now()
                    if km_recorridos <= 0:
                        comp_estado.fecha_ultimo_servicio = now
                        ComponenteSaludVehiculo.objects.filter(pk=comp_estado.pk).update(
                            fecha_ultimo_servicio=now
                        )
                        comp_estado.fecha_ultimo_servicio = now
                        logger.info(
                            "HealthEngine: anclaje fecha_ultimo_servicio=now (km_recorridos=0) "
                            "componente=%s vehiculo=%s intervalo_meses=%s",
                            comp_maestro.nombre,
                            vehiculo_id,
                            intervalo_meses,
                        )
                    elif eta > 0:
                        # Fracción de vida km consumida → misma fracción del intervalo en meses (tope 2x intervalo)
                        frac = min(2.0, km_recorridos / eta)
                        months_proxy = frac * float(intervalo_meses)
                        anchor = now - timedelta(days=months_proxy * 30.44)
                        if timezone.is_naive(anchor):
                            anchor = timezone.make_aware(anchor)
                        ComponenteSaludVehiculo.objects.filter(pk=comp_estado.pk).update(
                            fecha_ultimo_servicio=anchor
                        )
                        comp_estado.fecha_ultimo_servicio = anchor
                        logger.info(
                            "HealthEngine: anclaje fecha_ultimo_servicio proxy meses=%.2f componente=%s "
                            "vehiculo=%s intervalo_meses=%s km_recorridos=%s",
                            months_proxy,
                            comp_maestro.nombre,
                            vehiculo_id,
                            intervalo_meses,
                            km_recorridos,
                        )
                    else:
                        logger.warning(
                            "HealthEngine: intervalo_meses=%s pero sin fecha y eta=0; eje tiempo omitido "
                            "componente=%s vehiculo=%s",
                            intervalo_meses,
                            comp_maestro.nombre,
                            vehiculo_id,
                        )

                if comp_estado.fecha_ultimo_servicio:
                    fecha_ref = comp_estado.fecha_ultimo_servicio
                    if timezone.is_naive(fecha_ref):
                        fecha_ref = timezone.make_aware(fecha_ref)
                    delta = timezone.now() - fecha_ref
                    months_elapsed = max(0.0, delta.days / 30.44)
                    salud_tiempo = math.exp(
                        -((months_elapsed / float(intervalo_meses)) ** beta)
                    ) * 100.0
                    salud_pct = min(salud_km, salud_tiempo)
                elif intervalo_meses:
                    logger.warning(
                        "HealthEngine: regla con intervalo_meses=%s sin fecha anclable componente=%s "
                        "vehiculo=%s (revisar checklist/mapeo)",
                        intervalo_meses,
                        comp_maestro.nombre,
                        vehiculo_id,
                    )

            # meses_critico solo en genérica: umbral duro opcional
            meses_critico = None
            if not es_especifica:
                meses_critico = getattr(regla_aplicada, 'meses_critico', None)
            else:
                try:
                    reg_gen = ReglaMantenimientoGenerica.objects.get(
                        componente=comp_maestro, tipo_motor=tipo_motor_norm
                    )
                    meses_critico = getattr(reg_gen, 'meses_critico', None)
                except ReglaMantenimientoGenerica.DoesNotExist:
                    pass
            if meses_critico and months_elapsed is not None and months_elapsed >= meses_critico:
                salud_pct = min(salud_pct, 25.0)

            # Determinar Status
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

            # Predicciones
            km_restantes = max(0, int(eta - km_recorridos))
            
            # Actualizar Estado Persistente
            comp_estado.salud_porcentaje = round(salud_pct, 1)
            comp_estado.nivel_alerta = status
            comp_estado.vida_util_proyectada = int(eta)
            comp_estado.es_regla_especifica = es_especifica
            comp_estado.km_estimados_restantes = km_restantes
            comp_estado.requiere_servicio_inmediato = (status == 'CRITICO' or status == 'URGENTE')
            
            if comp_estado.requiere_servicio_inmediato:
                comp_estado.mensaje_alerta = f"Atención requerida: {comp_maestro.nombre} al {round(salud_pct)}%."
            else:
                comp_estado.mensaje_alerta = ""
            if months_elapsed is not None and intervalo_meses and salud_pct < salud_km - 0.5:
                extra = f" Intervalo por tiempo (~{int(months_elapsed)} meses desde último servicio)."
                comp_estado.mensaje_alerta = (comp_estado.mensaje_alerta or "").strip() + extra
                
            comp_estado.save()
            
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

        # --------------------------------------------------------
        # Actualizar Snapshot General (EstadoSaludVehiculo)
        # --------------------------------------------------------
        promedio_global = (stats['sum_health'] / stats['total']) if stats['total'] > 0 else 0
        
        # Verificar alertas activas
        tiene_alertas = (stats['urgente'] > 0 or stats['critico'] > 0)
        
        estado_general, _ = EstadoSaludVehiculo.objects.update_or_create(
            vehiculo=vehiculo,
            defaults={
                'salud_general_porcentaje': round(promedio_global, 1),
                'kilometraje_snapshot': vehiculo.kilometraje,
                'total_componentes_evaluados': stats['total'],
                'componentes_optimos': stats['optimo'],
                'componentes_atencion': stats['atencion'],
                'componentes_urgentes': stats['urgente'],
                'componentes_criticos': stats['critico'],
                'tiene_alertas_activas': tiene_alertas
            }
        )
        # Marcar momento del recálculo (staleness / sync / marketplace coherente)
        EstadoSaludVehiculo.objects.filter(pk=estado_general.pk).update(
            ultima_actualizacion=timezone.now()
        )
        
        # Sort report by criticality (ascending health)
        reporte_salud.sort(key=lambda x: x['salud'])
        
        logger.info(f"HealthEngine: Cálculo completado. Salud Global: {promedio_global}%")
        
        return reporte_salud

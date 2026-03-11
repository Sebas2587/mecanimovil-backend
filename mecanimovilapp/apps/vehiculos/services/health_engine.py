import math
import logging
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
            
            # Parámetros Weibull
            eta = float(regla_aplicada.vida_util_km) # Scale Parameter (Vida característica)
            beta = float(regla_aplicada.beta) # Shape Parameter
            
            # Cálculo de Confiabilidad R(t) = exp(-(t/eta)^beta)
            # R(t) representa la probabilidad de que el componente siga funcionando
            # Lo usamos como proxy de "Salud %"
            if eta > 0:
                reliability = math.exp(-((km_recorridos / eta) ** beta))
                salud_pct = reliability * 100.0
            else:
                salud_pct = 0.0

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
                
            comp_estado.save()
            
            reporte_salud.append({
                'componente': comp_maestro.nombre,
                'slug': comp_maestro.slug,
                'salud': round(salud_pct, 1),
                'status': status,
                'vida_util_total': int(eta),
                'km_recorridos': km_recorridos,
                'es_especifica': es_especifica
            })

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

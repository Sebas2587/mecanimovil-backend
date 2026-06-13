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

# ── Integridad de datos: caps de salud según fuente del historial ────────────
# Un componente cuyo último servicio fue declarado retroactivamente por el usuario
# (sin confirmación de taller) NUNCA puede aparecer como ÓPTIMO en la app.
# Esto impide que un vendedor infle artificialmente las métricas de su vehículo.
#
# Escala de confianza → salud máxima permitida:
#   CHECKLIST / REGISTRO_INICIAL → sin cap (dato confirmado por taller / al registrar)
#   USUARIO_DECLARADO            → máx 65 % (ATENCIÓN, nunca ÓPTIMO)
#   ENGINE                       → sin cap adicional (ya es estimación, no puede "fingir")
#
# Nota: cuando un técnico declara un porcentaje en una inspección, se persiste
# en ComponenteSaludVehiculo.salud_anclada_pct y se usa como origen de la curva
# Weibull (ver bloque "ancla" más abajo). La fuente queda en CHECKLIST.
SALUD_MAX_POR_FUENTE = {
    'USUARIO_DECLARADO': 65.0,
}

# ── Componentes que degradan por EDAD (goma/química), independiente del km ──
# La edad relevante es la del COMPONENTE (tiempo desde su último cambio), NO la
# antigüedad de fabricación del vehículo. Un líquido de frenos recién cambiado en
# un auto de 13 años es "nuevo" y debe partir cerca del 100 %.
# Formato: slug → (max_años_optimo, max_años_critico, salud_max_tras_critico)
_AGE_HARD_CAPS = {
    'tires':        (5,  10, 15.0),   # goma: óptimo ≤5 años, crítico >10 años
    'timing-belt':  (6,  10, 10.0),   # correa distribución (caucho)
    'brake-fluid':  (2,   4, 20.0),   # líquido higroscópico: crítico a los 4 años
    'coolant':      (3,   5, 20.0),   # refrigerante se degrada
    'shocks':       (8,  15, 15.0),   # amortiguadores (goma + aceite)
    # Aliases por slug largo (compatibilidad si el catálogo usara estos slugs)
    'neumaticos':         (5,  10, 15.0),
    'correa-distribucion':(6,  10, 10.0),
    'liquido-frenos':     (2,   4, 20.0),
    'refrigerante':       (3,   5, 20.0),
    'amortiguadores':     (8,  15, 15.0),
}

# ── Slugs de componentes sensibles al perfil de conducción ──────────────────
_WEAR_BY_DRIVING_SLUGS = {'brakes', 'brake-discs', 'tires', 'brake-fluid', 'shocks'}

# Multiplicadores de desgaste por intensidad de uso (km/día como proxy).
# El factor acelera la degradación: 1.0 = normal, >1 = desgaste acelerado.
def _driving_intensity_factor(km_por_dia: float, slug: str) -> float:
    """
    Retorna factor de aceleración de desgaste para componentes de fricción
    según la intensidad de uso diario del usuario.

    La lógica: en ciudad (muchos frenos/día con km cortos) el desgaste de
    pastillas y discos es mucho mayor que en carretera. Un usuario que hace
    10 km/día en ciudad gasta más pastillas que uno que hace 60 km/día en
    autopista — pero como no tenemos aún perfil declarado, usamos km/día
    como indicador de patrón de uso hasta que el usuario lo declare.
    """
    if slug not in _WEAR_BY_DRIVING_SLUGS:
        return 1.0

    if km_por_dia <= 15:
        # Muy pocos km/día → probable uso urbano puro (mucho freno, poco km)
        return 1.35
    elif km_por_dia <= 30:
        # Uso mixto urbano-suburbano
        return 1.15
    elif km_por_dia <= 60:
        # Uso normal / suburbano-autopista
        return 1.0
    else:
        # Alto kilometraje diario → probable largo recorrido (autopista, menos frenadas)
        return 0.90


def _component_age_years(vehiculo, comp_estado, now=None) -> tuple[float | None, bool]:
    """
    Edad EFECTIVA del componente, en años.

    - Si hay historial de servicio confirmado (historial_conocido y
      fecha_ultimo_servicio), la edad se mide desde el último servicio: una
      pieza/líquido recién cambiado es "nuevo" aunque el vehículo sea antiguo.
    - Si NO hay historial, se usa la antigüedad de fabricación del vehículo como
      estimación conservadora (un componente que nunca se cambió en un auto
      viejo probablemente está degradado → seguimos protegiendo al usuario).

    Retorna (años | None, basado_en_servicio: bool).
    """
    now = now or timezone.now()
    fecha_serv = getattr(comp_estado, 'fecha_ultimo_servicio', None) if comp_estado else None
    historial = bool(getattr(comp_estado, 'historial_conocido', False)) if comp_estado else False

    if historial and fecha_serv:
        if timezone.is_naive(fecha_serv):
            fecha_serv = timezone.make_aware(fecha_serv)
        años = max(0.0, (now - fecha_serv).days / 365.25)
        return años, True

    vehicle_year = getattr(vehiculo, 'year', None)
    if not vehicle_year:
        return None, False
    return float(max(0, now.year - int(vehicle_year))), False


def _age_health_cap(vehiculo, slug: str, salud_pct: float, comp_estado=None, now=None) -> tuple[float, str | None]:
    """
    Aplica un cap duro a la salud según la edad del COMPONENTE (tiempo desde su
    último cambio) para piezas cuya vida útil depende del tiempo más que del km.

    Clave: la edad NO es la antigüedad de fabricación del vehículo. Un líquido de
    frenos cambiado hoy en un auto de 13 años parte cerca del 100 % y se degrada a
    lo largo de su intervalo (2–4 años) mediante el eje temporal Weibull.

    Solo cuando no hay historial confirmado caemos a la antigüedad del vehículo
    como estimación conservadora.

    Retorna (salud_ajustada, mensaje_extra | None).
    """
    cap_info = _AGE_HARD_CAPS.get(slug)
    if not cap_info:
        return salud_pct, None

    años_componente, desde_servicio = _component_age_years(vehiculo, comp_estado, now)
    if años_componente is None:
        return salud_pct, None

    max_años_optimo, max_años_critico, salud_min_critico = cap_info
    años_txt = int(round(años_componente))

    if años_componente > max_años_critico:
        # Supera el límite crítico de antigüedad → forzar salud mínima degradada
        salud_ajustada = min(salud_pct, salud_min_critico)
        if desde_servicio:
            msg = (
                f"Último cambio hace ~{años_txt} años: supera su vida útil por "
                f"antigüedad (máx. recomendado {max_años_critico} años) — conviene reemplazarlo."
            )
        else:
            msg = (
                f"Sin registro de cambio en un vehículo de {años_txt} años: este "
                f"componente probablemente supera su vida útil por antigüedad "
                f"({max_años_critico} años). Registra o realiza el servicio para confirmarlo."
            )
        return salud_ajustada, msg
    elif años_componente > max_años_optimo:
        # Entre límite óptimo y crítico → degradar proporcionalmente
        fraccion = (años_componente - max_años_optimo) / max(max_años_critico - max_años_optimo, 1)
        salud_max = 70.0 - (fraccion * (70.0 - salud_min_critico))
        salud_ajustada = min(salud_pct, salud_max)
        if desde_servicio:
            msg = (
                f"Último cambio hace ~{años_txt} años: revisar por antigüedad "
                f"(se recomienda cada {max_años_optimo} años)."
            )
        else:
            msg = (
                f"Vehículo de {años_txt} años sin registro de cambio: revisar este "
                f"componente por antigüedad (recomendado cada {max_años_optimo} años)."
            )
        return salud_ajustada, msg

    return salud_pct, None


class HealthEngine:
    """
    Motor inteligente de cálculo de salud vehicular.

    Algoritmo Weibull de doble eje (km + tiempo):
      salud_km     = exp(-(km_recorridos / eta)^beta)       × 100
      salud_tiempo = exp(-(meses_desde_servicio / T)^beta)  × 100   [si regla tiene intervalo_meses]
      salud_pct    = min(salud_km, salud_tiempo)

    Modo historial desconocido (historial_conocido=False y km_recorridos > eta):
      Estimación inteligente por ciclo de vida útil:
        ciclos_consumidos = km_total // eta
        km_en_ciclo_actual = km_total % eta
        km_efectivos = max(km_en_ciclo_actual, eta * 0.5)  # mínimo medio ciclo
      Esto da valores diferenciados POR COMPONENTE según su eta individual:
        Aceite (eta=10k, km=150k):     150k % 10k = 0    → ~100% (recién en ciclo)
        Distribución (eta=100k, 150k): 150k % 100k = 50k → ~e^-0.5 = 61%
        Neumáticos (eta=40k, km=150k): 150k % 40k = 30k  → ~e^-0.75 = 47%
      El anchor de tiempo usa vehiculo.fecha_creacion para no escribir fechas irracionales.
      El mensaje informa que los datos son estimados y cuántos ciclos se consumieron.

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

            # ── Ancla Weibull desde inspección de checklist ─────────────────
            # Si un técnico declaró un porcentaje de vida útil durante una
            # inspección (tipo_actualizacion='INSPECCIONA'), usamos ese punto
            # como origen de la curva. Inferimos los km efectivamente consumidos:
            #   km_consumido = eta * (1 - salud_declarada / 100)
            # y los sumamos a los km que el vehículo recorre desde la inspección.
            # Esto desplaza el origen de la curva sin perder el ancla en futuros
            # recálculos cuando el vehículo siga acumulando kilometraje.
            ancla_pct = getattr(comp_estado, 'salud_anclada_pct', None)
            historial_fuente_pre = getattr(comp_estado, 'historial_fuente', 'ENGINE')
            usa_ancla = (
                ancla_pct is not None
                and historial_fuente_pre == 'CHECKLIST'
                and eta > 0
            )
            if usa_ancla:
                km_consumido_inferido = eta * max(0.0, min(1.0, 1 - (ancla_pct / 100.0)))
                km_desde_inspeccion = max(
                    0,
                    vehiculo.kilometraje - comp_estado.km_ultimo_servicio,
                )
                km_recorridos_real = int(km_consumido_inferido + km_desde_inspeccion)

            # ── Modo historial desconocido ──────────────────────────────────
            # Estimación inteligente: si el vehículo no tiene historial conocido,
            # usamos km_total % eta para saber en qué fracción del ciclo actual está
            # el componente. Cada pieza tiene un eta distinto, por lo que la salud
            # estimada varía POR COMPONENTE en lugar de fijarse en ~37 % universal.
            historial_desconocido = (
                not comp_estado.historial_conocido
                and comp_estado.km_ultimo_servicio == 0
                and km_recorridos_real > eta
                and eta > 0
                and not usa_ancla
            )
            ciclos_consumidos_est = 0

            if historial_desconocido:
                ciclos_consumidos_est = int(vehiculo.kilometraje // eta)
                km_en_ciclo_actual = vehiculo.kilometraje % eta
                # Piso de medio ciclo: si un componente recién "renovó" en el módulo
                # (km_en_ciclo_actual ~ 0) sería irreal mostrarlo al 100 % sin historial.
                # El piso de eta*0.5 fuerza mostrar al menos un desgaste razonable
                # mientras el usuario no aporte historial real.
                km_recorridos = max(km_en_ciclo_actual, int(eta * 0.5))

                # ── Ancla de tiempo correcta para historial desconocido ──────
                # BUG-FIX: NO usar fecha_creacion del vehículo en la app (que
                # refleja cuándo el usuario registró el auto, no cuándo se hizo
                # el último servicio). En cambio, estimamos los meses transcurridos
                # desde el último servicio usando los ciclos consumidos y el año
                # real del vehículo como tope máximo.
                #
                # Ejemplo: vehículo 2010, 158.000 km, neumáticos eta=45.000 km,
                # intervalo=36 meses → 3 ciclos completos + fracción actual.
                #   meses_estimados = 3×36 + (38k/45k)×36 ≈ 138 meses ≈ 11,5 años
                #   meses_vehiculo  = 2026-2010 = 16 años = 192 meses
                #   fecha_eje = now − min(138, 192) meses → salud temporal ~0%
                fecha_ref_tiempo = None  # se calcula abajo si hay intervalo_meses
            else:
                km_recorridos = km_recorridos_real
                fecha_ref_tiempo = None  # se usará fecha_ultimo_servicio normal

            # ── Salud por km (Weibull) ──────────────────────────────────────
            salud_km  = math.exp(-((km_recorridos / eta) ** beta)) * 100.0 if eta > 0 else 0.0
            salud_pct = salud_km
            months_elapsed = None
            salud_tiempo = None  # se setea solo si la regla tiene intervalo_meses

            # ── Intervalo por tiempo ────────────────────────────────────────
            intervalo_meses = getattr(regla_aplicada, 'intervalo_meses', None)
            if not intervalo_meses and es_especifica and regla_generica:
                intervalo_meses = getattr(regla_generica, 'intervalo_meses', None)

            if intervalo_meses and intervalo_meses > 0:
                fecha_eje = None

                if historial_desconocido:
                    # Estimamos meses transcurridos desde el último servicio usando
                    # ciclos consumidos × intervalo_meses + fracción del ciclo actual.
                    # Se topa por la edad real del vehículo (vehicle.year) para no
                    # proyectar más tiempo del que el auto lleva existiendo.
                    frac_ciclo_actual = (km_en_ciclo_actual / eta) if eta > 0 else 0.0
                    meses_estimados = (
                        ciclos_consumidos_est * float(intervalo_meses)
                        + frac_ciclo_actual * float(intervalo_meses)
                    )
                    vehicle_year = getattr(vehiculo, 'year', None)
                    if vehicle_year:
                        meses_vehiculo = max(0, (timezone.now().year - vehicle_year)) * 12
                        meses_estimados = min(meses_estimados, float(meses_vehiculo))

                    if meses_estimados > 0:
                        fecha_eje = now - timedelta(days=meses_estimados * 30.44)
                        logger.info(
                            "HealthEngine: ancla tiempo estimada=%.1f meses componente=%s vehiculo=%s",
                            meses_estimados, comp_maestro.nombre, vehiculo_id,
                        )
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

            # ── Factor de conducción (componentes de fricción) ───────────────
            # Ajusta la salud según la intensidad de uso del usuario. Dado que
            # el cálculo Weibull ya consumió los km, aquí aplicamos el factor
            # recalculando la salud_km con los km_recorridos amplificados.
            slug_componente = comp_maestro.slug
            if slug_componente in _WEAR_BY_DRIVING_SLUGS:
                try:
                    from .predictor_salud import _get_avg_km_per_day
                    km_dia = _get_avg_km_per_day(vehiculo)
                    intensity = _driving_intensity_factor(km_dia, slug_componente)
                    if intensity != 1.0 and eta > 0:
                        km_recorridos_int = km_recorridos * intensity
                        salud_km_int = math.exp(-((km_recorridos_int / eta) ** beta)) * 100.0
                        salud_pct = min(salud_pct, salud_km_int)
                except Exception:
                    pass  # No degradar si falla la obtención de km/día

            # ── Cap duro por antigüedad (componentes de goma/química) ────────
            # La edad se mide desde el último servicio del componente (no la
            # antigüedad del vehículo): una pieza recién cambiada parte "nueva".
            salud_pct, msg_age = _age_health_cap(
                vehiculo, slug_componente, salud_pct, comp_estado=comp_estado, now=now,
            )

            # ── Cap por fuente del historial (integridad de datos) ───────────
            # Si el dato proviene de una declaración del usuario sin verificación
            # de taller, la salud se limita para que el componente nunca aparezca
            # como ÓPTIMO. Esto previene falsificación de métricas en venta.
            fuente_historial = getattr(comp_estado, 'historial_fuente', 'ENGINE')
            salud_max_fuente = SALUD_MAX_POR_FUENTE.get(fuente_historial)
            if salud_max_fuente is not None and salud_pct > salud_max_fuente:
                salud_pct = salud_max_fuente
                logger.debug(
                    "HealthEngine: cap fuente=%s aplicado componente=%s vehiculo=%s salud=%.1f",
                    fuente_historial, comp_maestro.nombre, vehiculo_id, salud_pct,
                )

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
                ciclo_label = (
                    f"~{ciclos_consumidos_est} ciclos previos estimados"
                    if ciclos_consumidos_est >= 1
                    else "estimación conservadora"
                )
                comp_estado.mensaje_alerta = (
                    f"Historial no registrado para {comp_maestro.nombre}. "
                    f"Estimación inteligente: {round(salud_pct)}% "
                    f"({ciclo_label} de {int(eta):,} km). "
                    f"Registra tu próximo servicio para predicciones precisas."
                )
            elif comp_estado.requiere_servicio_inmediato:
                comp_estado.mensaje_alerta = (
                    f"Atención requerida: {comp_maestro.nombre} al {round(salud_pct)}%."
                )
            else:
                comp_estado.mensaje_alerta = ""

            # Mensaje "intervalo por tiempo": solo cuando el EJE TEMPORAL fue el
            # factor que bajó la salud (no cuando bajó por edad/conducción/fuente)
            # y han pasado al menos ~1 mes desde el servicio (evita "~0 meses"
            # contradictorio justo después de un servicio reciente).
            if (
                not historial_desconocido
                and months_elapsed is not None
                and months_elapsed >= 1
                and intervalo_meses
                and salud_tiempo is not None
                and salud_tiempo < salud_km - 0.5
            ):
                extra = f" Intervalo por tiempo (~{int(months_elapsed)} meses desde último servicio)."
                comp_estado.mensaje_alerta = (comp_estado.mensaje_alerta or "").strip() + extra

            if msg_age:
                comp_estado.mensaje_alerta = (
                    (comp_estado.mensaje_alerta or "").strip() + " " + msg_age
                ).strip()

            if salud_max_fuente is not None and fuente_historial == 'USUARIO_DECLARADO':
                aviso_fuente = (
                    "Datos declarados por el usuario. Para mostrar estado ÓPTIMO "
                    "se requiere confirmación de un taller verificado."
                )
                comp_estado.mensaje_alerta = (
                    (comp_estado.mensaje_alerta or "").strip() + " " + aviso_fuente
                ).strip()

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
            if historial_desconocido:
                reporte_item['ciclos_estimados'] = ciclos_consumidos_est
                reporte_item['km_en_ciclo_actual'] = int(vehiculo.kilometraje % eta) if eta > 0 else 0
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

        # ── Captura de eventos para dataset ML ──────────────────────────────
        # Solo cuando un componente cae a CRÍTICO o se reporta 0 % salud por
        # primera vez, registramos el punto en EventoSaludVehiculo. Esto alimenta
        # el dataset que usa scikit-learn (Random Forest / Linear Regression)
        # para predecir vida útil real por marca/modelo/año/clima.
        try:
            HealthEngine._capturar_eventos_criticos(
                vehiculo, reporte_salud, marca_nombre, modelo_nombre,
                tipo_motor_norm,
            )
        except Exception as evt_err:
            logger.warning(
                "HealthEngine: error capturando eventos ML para vehículo %s: %s",
                vehiculo_id, evt_err,
            )

        return reporte_salud

    @staticmethod
    def _capturar_eventos_criticos(vehiculo, reporte, marca, modelo, tipo_motor):
        """
        Registra eventos NIVEL_CRITICO en EventoSaludVehiculo, con dedupe:
        solo crea un evento por (vehículo, componente, día) para no inundar la tabla.
        Estos eventos alimentan el dataset de entrenamiento de scikit-learn.
        """
        from ..models_health import (
            EventoSaludVehiculo,
            ComponenteSalud,
            ComponenteSaludVehiculo,
        )

        criticos = [r for r in reporte if r.get('status') == 'CRITICO']
        if not criticos:
            return

        hoy = timezone.now().date()
        slugs_criticos = {r['slug'] for r in criticos}
        comp_map = {
            c.slug: c
            for c in ComponenteSalud.objects.filter(slug__in=slugs_criticos)
        }
        # dedupe: ¿ya hay un evento NIVEL_CRITICO hoy para alguno de estos slugs?
        existing = EventoSaludVehiculo.objects.filter(
            vehiculo=vehiculo,
            tipo_evento='NIVEL_CRITICO',
            componente__slug__in=slugs_criticos,
            fecha_evento__date=hoy,
        ).values_list('componente__slug', flat=True)
        ya_registrados = set(existing)

        nuevos = []
        for r in criticos:
            slug = r['slug']
            if slug in ya_registrados or slug not in comp_map:
                continue
            comp_estado = ComponenteSaludVehiculo.objects.filter(
                vehiculo=vehiculo, componente=comp_map[slug],
            ).first()
            km_desde = (
                vehiculo.kilometraje - comp_estado.km_ultimo_servicio
                if comp_estado and comp_estado.km_ultimo_servicio else None
            )
            meses_desde = None
            if comp_estado and comp_estado.fecha_ultimo_servicio:
                delta_dias = (timezone.now() - comp_estado.fecha_ultimo_servicio).days
                meses_desde = round(delta_dias / 30.44, 2) if delta_dias > 0 else 0.0

            nuevos.append(EventoSaludVehiculo(
                vehiculo=vehiculo,
                componente=comp_map[slug],
                tipo_evento='NIVEL_CRITICO',
                marca=marca,
                modelo=modelo,
                year=getattr(vehiculo, 'year', None),
                tipo_motor=tipo_motor,
                transmision=getattr(vehiculo, 'transmision', '') or '',
                kilometraje=vehiculo.kilometraje or 0,
                km_desde_ultimo_servicio=km_desde,
                meses_desde_ultimo_servicio=meses_desde,
                vida_util_referencia_km=r.get('vida_util_total'),
                salud_porcentaje=r.get('salud'),
            ))

        if nuevos:
            EventoSaludVehiculo.objects.bulk_create(nuevos, ignore_conflicts=True)
            logger.info(
                "HealthEngine: %s eventos NIVEL_CRITICO capturados para vehículo %s",
                len(nuevos), vehiculo.id,
            )

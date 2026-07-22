"""
Servicio de cuotas mensuales por plan (IA, patente, mensajería).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

from .creditos_services import obtener_credito_proveedor
from .models import ConsumoFeatureMensual, PlanSuscripcion
from .suscripcion_services import obtener_suscripcion_activa

logger = logging.getLogger(__name__)


class CuotaAgotadaError(Exception):
    """Cuota del plan agotada y sin créditos suficientes para overage."""

    code = 'cuota_agotada'

    def __init__(
        self,
        message: str,
        *,
        feature: str,
        limite: int = 0,
        usados: int = 0,
        creditos_necesarios: int = 1,
        saldo_creditos: int = 0,
    ):
        super().__init__(message)
        self.message = message
        self.feature = feature
        self.limite = limite
        self.usados = usados
        self.creditos_necesarios = creditos_necesarios
        self.saldo_creditos = saldo_creditos

    def to_dict(self) -> dict:
        return {
            'error': self.message,
            'code': self.code,
            'feature': self.feature,
            'limite': self.limite,
            'usados': self.usados,
            'creditos_necesarios': self.creditos_necesarios,
            'saldo_creditos': self.saldo_creditos,
        }


class SinSuscripcionError(CuotaAgotadaError):
    code = 'sin_suscripcion'

    def __init__(self, message: str = 'Necesitas una suscripción activa para usar esta función.'):
        super().__init__(message, feature='', limite=0, usados=0)
        self.message = message


class LimiteCanalesError(CuotaAgotadaError):
    code = 'limite_canales'

    def __init__(self, message: str, *, limite: int, conectados: int):
        super().__init__(message, feature='CANAL_MENSAJERIA', limite=limite, usados=conectados)
        self.conectados = conectados


def cuotas_enforcement_habilitado() -> bool:
    return bool(getattr(settings, 'PLAN_CUOTAS_ENFORCEMENT_ENABLED', False))


def periodo_actual() -> str:
    return timezone.localdate().strftime('%Y-%m')


def resolver_proveedor_suscripcion(user) -> Optional[int]:
    """Usuario dueño de la suscripción (mandante del taller o el propio user)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    taller, _, _ = resolver_contexto_taller(user)
    if taller and taller.usuario_id:
        return taller.usuario_id
    return user.id


def resolver_taller_desde_user(user) -> Optional[Taller]:
    taller, _, _ = resolver_contexto_taller(user)
    return taller


def obtener_plan_activo(user) -> Optional[PlanSuscripcion]:
    proveedor_id = resolver_proveedor_suscripcion(user)
    if not proveedor_id:
        return None
    from django.contrib.auth import get_user_model

    User = get_user_model()
    proveedor = User.objects.filter(pk=proveedor_id).first()
    if not proveedor:
        return None
    suscripcion = obtener_suscripcion_activa(proveedor)
    if not suscripcion:
        return None
    return suscripcion.plan


def _limite_plan(plan: PlanSuscripcion, feature: str) -> int:
    mapping = {
        ConsumoFeatureMensual.FEATURE_COTIZACION_IA: plan.cotizaciones_ia_mensuales,
        ConsumoFeatureMensual.FEATURE_DIAGNOSTICO_IA: plan.diagnosticos_ia_mensuales,
        ConsumoFeatureMensual.FEATURE_CONSULTA_PATENTE: plan.consultas_patente_mensuales,
        ConsumoFeatureMensual.FEATURE_CONVERSACION_SALIENTE: plan.conversaciones_salientes_max,
        ConsumoFeatureMensual.FEATURE_CONVERSACION_AGENTE_IA: plan.conversaciones_agente_ia_max,
    }
    return int(mapping.get(feature, 0))


def agente_ia_incluido_en_plan(user) -> bool:
    """True si el plan activo del proveedor incluye el Agente IA conversacional."""
    if not cuotas_enforcement_habilitado():
        return True
    plan = obtener_plan_activo(user)
    return bool(plan and plan.agente_ia_incluido)


def _overage_rate(plan: PlanSuscripcion, feature: str) -> int:
    mapping = {
        ConsumoFeatureMensual.FEATURE_COTIZACION_IA: plan.overage_cotizaciones_por_credito,
        ConsumoFeatureMensual.FEATURE_DIAGNOSTICO_IA: plan.overage_diagnosticos_por_credito,
        ConsumoFeatureMensual.FEATURE_CONSULTA_PATENTE: plan.overage_patentes_por_credito,
    }
    return max(1, int(mapping.get(feature, 1)))


def _feature_label(feature: str) -> str:
    labels = dict(ConsumoFeatureMensual.FEATURE_CHOICES)
    return labels.get(feature, feature)


@dataclass
class UsoFeatureResumen:
    feature: str
    label: str
    limite: int
    usados: int
    restantes: int
    creditos_overage_gastados: int
    overage_por_credito: int

    def to_dict(self) -> dict:
        return {
            'feature': self.feature,
            'label': self.label,
            'limite': self.limite,
            'usados': self.usados,
            'restantes': self.restantes,
            'creditos_overage_gastados': self.creditos_overage_gastados,
            'overage_por_credito': self.overage_por_credito,
        }


def obtener_uso_features_mes(user, *, periodo: Optional[str] = None) -> dict:
    """Resumen de uso del plan para el mes actual."""
    proveedor_id = resolver_proveedor_suscripcion(user)
    plan = obtener_plan_activo(user)
    periodo = periodo or periodo_actual()

    if not proveedor_id or not plan:
        return {
            'periodo': periodo,
            'plan': None,
            'features': [],
            'canales_mensajeria_max': 0,
            'canales_conectados': 0,
        }

    consumos = {
        c.feature: c
        for c in ConsumoFeatureMensual.objects.filter(proveedor_id=proveedor_id, periodo=periodo)
    }

    features = []
    features_sin_overage = (
        ConsumoFeatureMensual.FEATURE_CONVERSACION_SALIENTE,
        ConsumoFeatureMensual.FEATURE_CONVERSACION_AGENTE_IA,
    )
    for feature in (
        ConsumoFeatureMensual.FEATURE_COTIZACION_IA,
        ConsumoFeatureMensual.FEATURE_DIAGNOSTICO_IA,
        ConsumoFeatureMensual.FEATURE_CONSULTA_PATENTE,
        ConsumoFeatureMensual.FEATURE_CONVERSACION_SALIENTE,
        ConsumoFeatureMensual.FEATURE_CONVERSACION_AGENTE_IA,
    ):
        if feature == ConsumoFeatureMensual.FEATURE_CONVERSACION_AGENTE_IA and not plan.agente_ia_incluido:
            continue
        limite = _limite_plan(plan, feature)
        registro = consumos.get(feature)
        usados = registro.usados if registro else 0
        features.append(
            UsoFeatureResumen(
                feature=feature,
                label=_feature_label(feature),
                limite=limite,
                usados=usados,
                restantes=max(0, limite - usados),
                creditos_overage_gastados=registro.creditos_overage_gastados if registro else 0,
                overage_por_credito=0 if feature in features_sin_overage else _overage_rate(plan, feature),
            ).to_dict()
        )

    canales_conectados = contar_canales_conectados(user)

    return {
        'periodo': periodo,
        'plan': {
            'id': plan.id,
            'nombre': plan.nombre,
            'canales_mensajeria_max': plan.canales_mensajeria_max,
            'acceso_endpoints_patente_pro': plan.acceso_endpoints_patente_pro,
            'agente_ia_incluido': plan.agente_ia_incluido,
        },
        'features': features,
        'canales_mensajeria_max': plan.canales_mensajeria_max,
        'canales_conectados': canales_conectados,
    }


def contar_canales_conectados(user) -> int:
    from django.contrib.contenttypes.models import ContentType

    from mecanimovilapp.apps.omnichannel.models import ProviderChannelConnection
    from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio

    taller, _, _ = resolver_contexto_taller(user)
    if taller:
        content_type = ContentType.objects.get_for_model(Taller)
        return ProviderChannelConnection.objects.filter(
            content_type=content_type,
            object_id=taller.id,
            status='conectada',
        ).count()

    try:
        mecanico = MecanicoDomicilio.objects.get(usuario=user)
        content_type = ContentType.objects.get_for_model(MecanicoDomicilio)
        return ProviderChannelConnection.objects.filter(
            content_type=content_type,
            object_id=mecanico.id,
            status='conectada',
        ).count()
    except MecanicoDomicilio.DoesNotExist:
        return 0


def verificar_limite_canales(user) -> None:
    if not cuotas_enforcement_habilitado():
        return

    plan = obtener_plan_activo(user)
    if not plan:
        raise SinSuscripcionError()

    conectados = contar_canales_conectados(user)
    if conectados >= plan.canales_mensajeria_max:
        raise LimiteCanalesError(
            f'Tu plan {plan.nombre} permite hasta {plan.canales_mensajeria_max} canal(es) conectado(s). '
            f'Actualmente tienes {conectados}. Sube de plan para conectar más canales.',
            limite=plan.canales_mensajeria_max,
            conectados=conectados,
        )


def verificar_puede_conectar_canal(user, *, ya_conectado: bool = False) -> None:
    """Gate al iniciar conexión: no cuenta reconexión del mismo canal."""
    if not cuotas_enforcement_habilitado():
        return
    if ya_conectado:
        return

    plan = obtener_plan_activo(user)
    if not plan:
        raise SinSuscripcionError()

    conectados = contar_canales_conectados(user)
    if conectados >= plan.canales_mensajeria_max:
        raise LimiteCanalesError(
            f'Tu plan {plan.nombre} incluye {plan.canales_mensajeria_max} canal(es) de mensajería. '
            f'Ya tienes {conectados} conectado(s). Sube de plan para agregar otro canal.',
            limite=plan.canales_mensajeria_max,
            conectados=conectados,
        )


@transaction.atomic
def verificar_y_consumir_cuota(user, feature: str) -> None:
    """
    Valida cuota del plan o descuenta créditos por overage.
    Lanza CuotaAgotadaError / SinSuscripcionError si no puede consumir.
    """
    if not cuotas_enforcement_habilitado():
        return

    proveedor_id = resolver_proveedor_suscripcion(user)
    if not proveedor_id:
        raise SinSuscripcionError('No se pudo identificar el proveedor.')

    from django.contrib.auth import get_user_model

    User = get_user_model()
    proveedor = User.objects.select_for_update().get(pk=proveedor_id)

    plan = obtener_plan_activo(user)
    if not plan:
        raise SinSuscripcionError()

    limite = _limite_plan(plan, feature)
    periodo = periodo_actual()
    taller = resolver_taller_desde_user(user)

    registro, _ = ConsumoFeatureMensual.objects.select_for_update().get_or_create(
        proveedor=proveedor,
        feature=feature,
        periodo=periodo,
        defaults={'taller': taller, 'usados': 0},
    )
    if taller and registro.taller_id is None:
        registro.taller = taller
        registro.save(update_fields=['taller'])

    # Conversaciones salientes (manuales o del Agente IA): solo tope duro, sin overage en créditos
    if feature in (
        ConsumoFeatureMensual.FEATURE_CONVERSACION_SALIENTE,
        ConsumoFeatureMensual.FEATURE_CONVERSACION_AGENTE_IA,
    ):
        if feature == ConsumoFeatureMensual.FEATURE_CONVERSACION_AGENTE_IA and not plan.agente_ia_incluido:
            raise SinSuscripcionError(
                'El Agente IA no está incluido en tu plan actual. Sube de plan para activarlo.'
            )
        etiqueta = (
            'conversaciones del Agente IA'
            if feature == ConsumoFeatureMensual.FEATURE_CONVERSACION_AGENTE_IA
            else 'conversaciones salientes'
        )
        if registro.usados >= limite:
            raise CuotaAgotadaError(
                f'Agotaste las {limite} {etiqueta} incluidas en tu plan este mes.',
                feature=feature,
                limite=limite,
                usados=registro.usados,
            )
        registro.usados += 1
        registro.save(update_fields=['usados', 'fecha_actualizacion'])
        return

    if registro.usados < limite:
        registro.usados += 1
        registro.save(update_fields=['usados', 'fecha_actualizacion'])
        return

    # Overage con créditos
    rate = _overage_rate(plan, feature)
    credito = obtener_credito_proveedor(proveedor)
    saldo = credito.saldo_creditos

    # ¿Este uso completa un bucket y requiere 1 crédito?
    nuevas_pendientes = registro.unidades_overage_pendientes + 1
    requiere_credito = nuevas_pendientes >= rate

    if requiere_credito and saldo < 1:
        raise CuotaAgotadaError(
            f'Agotaste las {_feature_label(feature).lower()} incluidas en tu plan '
            f'({limite}/mes) y no tienes créditos para continuar. '
            f'Cada crédito permite {rate} usos extra.',
            feature=feature,
            limite=limite,
            usados=registro.usados,
            creditos_necesarios=1,
            saldo_creditos=saldo,
        )

    if requiere_credito:
        credito.saldo_creditos -= 1
        credito.fecha_ultimo_consumo = timezone.now()
        credito.save(update_fields=['saldo_creditos', 'fecha_ultimo_consumo'])
        registro.creditos_overage_gastados += 1
        registro.unidades_overage_pendientes = nuevas_pendientes - rate
    else:
        registro.unidades_overage_pendientes = nuevas_pendientes

    registro.usados += 1
    registro.save(
        update_fields=[
            'usados',
            'unidades_overage_pendientes',
            'creditos_overage_gastados',
            'fecha_actualizacion',
        ]
    )
    logger.info(
        'Cuota overage consumida: proveedor=%s feature=%s usados=%s creditos_overage=%s',
        proveedor_id,
        feature,
        registro.usados,
        registro.creditos_overage_gastados,
    )


def verificar_acceso_patente_pro(user) -> None:
    if not cuotas_enforcement_habilitado():
        return
    plan = obtener_plan_activo(user)
    if not plan or not plan.acceso_endpoints_patente_pro:
        raise CuotaAgotadaError(
            'Los endpoints avanzados de patente (VIN, alerta de robo, PRT) están disponibles solo en Plan Premium.',
            feature=ConsumoFeatureMensual.FEATURE_CONSULTA_PATENTE,
            limite=0,
            usados=0,
        )

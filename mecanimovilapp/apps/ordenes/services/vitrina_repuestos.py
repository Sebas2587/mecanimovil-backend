"""Vitrina pública de opciones de repuesto (token propio, TTL 72 h)."""
from __future__ import annotations

import logging
import secrets
from typing import Any

from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from mecanimovilapp.apps.ordenes.models import VitrinaRepuestos
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.opciones_repuesto import (
    MAX_OPCIONES_LINEA,
    construir_opciones_linea,
    proyectar_opciones_publicas,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import _base_url_publica

logger = logging.getLogger(__name__)

TTL_HORAS = 72
MAX_LINEAS = 6
_PROHIBIDOS = (
    'tienda', 'dominio', 'url', 'proveedor_id', 'es_proveedor_taller',
    'certeza', 'precio_clp', 'fuente', 'proveedor', 'proveedor_nombre',
)


def construir_url_vitrina(token: str) -> str:
    return f'{_base_url_publica()}/repuestos/{token}'


def vitrina_habilitada(config) -> bool:
    if not getattr(settings, 'VITRINA_REPUESTOS_ENABLED', False):
        return False
    return bool(getattr(config, 'vitrina_repuestos_habilitada', False))


def _posicion_relativa(idx: int, n: int) -> str:
    if n <= 1:
        return 'unica'
    if idx == 0:
        return 'mas_economica'
    if idx == n - 1:
        return 'mayor_precio'
    return 'intermedia'


def _linea_publica(rep: dict[str, Any], *, muestra_bandas: bool) -> dict[str, Any] | None:
    if not isinstance(rep, dict):
        return None
    ops_full = list(rep.get('opciones') or [])
    if not ops_full:
        ops_full = construir_opciones_linea(rep, max_opciones=MAX_OPCIONES_LINEA)
    # Ordenar por precio para posición relativa
    priced = sorted(
        [o for o in ops_full if isinstance(o, dict)],
        key=lambda o: int(o.get('precio_clp') or o.get('precio_min_clp') or 0) or 10**12,
    )
    n = len(priced)
    for i, op in enumerate(priced):
        op['posicion_relativa'] = _posicion_relativa(i, n)
    pubs = proyectar_opciones_publicas(priced)
    certeza = str(rep.get('certeza') or '')
    fuentes_n = int(rep.get('fuentes_n') or 0)
    mostrar_banda = (
        muestra_bandas
        and certeza not in ('', 'sin_precio')
        and fuentes_n >= 2
    )
    if not mostrar_banda:
        for p in pubs:
            p.pop('precio_min_clp', None)
            p.pop('precio_max_clp', None)
    out = {
        'linea_id': str(rep.get('id') or ''),
        'nombre': str(rep.get('nombre') or '')[:120],
        'cantidad': int(rep.get('cantidad') or 1),
        'calidad': str(rep.get('calidad') or ''),
        'especificacion': str(rep.get('especificacion') or '')[:80],
        'opciones': pubs,
        'muestra_banda': mostrar_banda,
    }
    if mostrar_banda:
        mins = [int(p.get('precio_min_clp') or 0) for p in pubs if int(p.get('precio_min_clp') or 0) > 0]
        maxs = [int(p.get('precio_max_clp') or p.get('precio_min_clp') or 0) for p in pubs]
        if mins:
            out['precio_min_clp'] = min(mins)
            out['precio_max_clp'] = max(maxs) if maxs else min(mins)
    return out if out['linea_id'] and pubs else None


def vitrina_tiene_contenido(lineas_pub: list[dict[str, Any]]) -> bool:
    """Regla 31: no mandar si no hay ≥2 opciones con imagen o precio."""
    n_utiles = 0
    for lin in lineas_pub:
        for op in lin.get('opciones') or []:
            if op.get('imagen_url') or int(op.get('precio_min_clp') or 0) > 0:
                n_utiles += 1
            elif op.get('posicion_relativa'):
                n_utiles += 1
        if len(lin.get('opciones') or []) >= 2:
            return True
    return n_utiles >= 2


def crear_vitrina(
    *,
    taller,
    cotizacion=None,
    conversation=None,
    muestra_bandas: bool = True,
    repuesto_ids: list[str] | None = None,
) -> VitrinaRepuestos | None:
    reps = list(getattr(cotizacion, 'repuestos', None) or [])
    if repuesto_ids:
        wanted = {str(x) for x in repuesto_ids}
        reps = [r for r in reps if isinstance(r, dict) and str(r.get('id') or '') in wanted]
    lineas = []
    for r in reps[:MAX_LINEAS]:
        pub = _linea_publica(r, muestra_bandas=muestra_bandas)
        if pub:
            lineas.append(pub)
    if not vitrina_tiene_contenido(lineas):
        logger.info('vitrina_repuestos omitida: sin opciones suficientes')
        return None
    token = secrets.token_urlsafe(48)[:64]
    now = timezone.now()
    vit = VitrinaRepuestos.objects.create(
        taller=taller,
        cotizacion=cotizacion,
        conversation=conversation or getattr(cotizacion, 'conversation', None),
        token=token,
        lineas=lineas,
        estado=VitrinaRepuestos.ESTADO_ENVIADA,
        expira_en=now + timedelta(hours=TTL_HORAS),
        enviada_en=now,
    )
    logger.info(
        'vitrina_repuestos token=%s taller=%s lineas_n=%s opciones_n=%s',
        token[:8],
        getattr(taller, 'id', None),
        len(lineas),
        sum(len(l.get('opciones') or []) for l in lineas),
    )
    try:
        from mecanimovilapp.apps.ordenes.tasks import hidratar_imagenes_vitrina
        hidratar_imagenes_vitrina.delay(vit.id)
    except Exception:
        pass
    return vit


def _sanitizar(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitizar(v) for k, v in obj.items() if k not in _PROHIBIDOS}
    if isinstance(obj, list):
        return [_sanitizar(x) for x in obj]
    return obj


def serializar_vitrina_publica(vitrina: VitrinaRepuestos) -> dict[str, Any]:
    taller = vitrina.taller
    cot = vitrina.cotizacion
    payload = {
        'token': vitrina.token,
        'estado': vitrina.estado,
        'expira_en': vitrina.expira_en.isoformat() if vitrina.expira_en else None,
        'taller': {
            'nombre': getattr(taller, 'nombre', '') or 'Taller',
        },
        'vehiculo': {
            'marca': getattr(cot, 'vehiculo_marca', '') or '',
            'modelo': getattr(cot, 'vehiculo_modelo', '') or '',
            'anio': getattr(cot, 'vehiculo_anio', '') or '',
            'patente': getattr(cot, 'vehiculo_patente', '') or '',
        },
        'lineas': _sanitizar(list(vitrina.lineas or [])),
        'mensaje': (
            'Estas son las opciones que encontramos para tu auto. '
            'El taller confirma el valor final.'
        ),
    }
    return payload


def marcar_abierta(vitrina: VitrinaRepuestos) -> None:
    if vitrina.abierta_en:
        return
    if vitrina.estado == VitrinaRepuestos.ESTADO_ENVIADA:
        vitrina.estado = VitrinaRepuestos.ESTADO_ABIERTA
    vitrina.abierta_en = timezone.now()
    vitrina.save(update_fields=['estado', 'abierta_en', 'actualizado_en'])


def registrar_seleccion(vitrina: VitrinaRepuestos, payload: dict[str, Any]) -> dict[str, Any]:
    """Idempotente: si ya respondió, devuelve ok."""
    if vitrina.estado == VitrinaRepuestos.ESTADO_RESPONDIDA:
        return {'ok': True, 'mensaje': 'Ya registramos tu elección.', 'idempotente': True}
    if vitrina.estado == VitrinaRepuestos.ESTADO_EXPIRADA:
        return {'ok': False, 'error': 'expirada'}
    selecciones = payload.get('selecciones') if isinstance(payload, dict) else None
    if not isinstance(selecciones, list) or not selecciones:
        return {'ok': False, 'error': 'selecciones'}
    ids_ok = {str(l.get('linea_id') or '') for l in (vitrina.lineas or [])}
    limpios = []
    for sel in selecciones:
        if not isinstance(sel, dict):
            continue
        lid = str(sel.get('linea_id') or '')
        if lid not in ids_ok:
            continue
        limpios.append({
            'linea_id': lid,
            'opcion_id': str(sel.get('opcion_id') or ''),
            'delegado_al_taller': bool(sel.get('delegado_al_taller')),
        })
    vitrina.seleccion = limpios
    vitrina.estado = VitrinaRepuestos.ESTADO_RESPONDIDA
    vitrina.respondida_en = timezone.now()
    vitrina.save(update_fields=['seleccion', 'estado', 'respondida_en', 'actualizado_en'])
    if vitrina.cotizacion_id:
        aplicar_seleccion_a_cotizacion(vitrina, vitrina.cotizacion)
    try:
        from mecanimovilapp.apps.agente_ia.tasks import retomar_tras_vitrina_task
        retomar_tras_vitrina_task.delay(vitrina.id)
    except Exception:
        pass
    return {'ok': True, 'mensaje': 'Listo. Se lo pasamos al taller para que te confirme el valor.'}


def aplicar_seleccion_a_cotizacion(vitrina: VitrinaRepuestos, cotizacion) -> None:
    from django.utils import timezone as tz

    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.opciones_repuesto import (
        aplicar_usar_opcion,
    )

    reps = list(cotizacion.repuestos or [])
    changed = False
    for sel in vitrina.seleccion or []:
        lid = str(sel.get('linea_id') or '')
        if sel.get('delegado_al_taller') or not sel.get('opcion_id'):
            continue
        try:
            aplicar_usar_opcion(
                cotizacion,
                repuesto_id=lid,
                opcion_id=str(sel.get('opcion_id')),
                guardar_en_mis_precios=False,
            )
            changed = True
        except Exception:
            logger.info('vitrina aplicar opcion falló linea=%s', lid)
            for i, r in enumerate(reps):
                if not isinstance(r, dict) or str(r.get('id') or '') != lid:
                    continue
                linea = dict(r)
                linea['seleccion_cliente'] = True
                linea['seleccion_cliente_en'] = tz.now().isoformat()
                reps[i] = linea
                cotizacion.repuestos = reps
                changed = True
    if changed:
        cotizacion.save(update_fields=['repuestos', 'actualizado_en'])


def expirar_vitrinas_vencidas() -> int:
    return VitrinaRepuestos.objects.filter(
        estado__in=[VitrinaRepuestos.ESTADO_ENVIADA, VitrinaRepuestos.ESTADO_ABIERTA],
        expira_en__lt=timezone.now(),
    ).update(estado=VitrinaRepuestos.ESTADO_EXPIRADA)


def texto_mensaje_vitrina(vitrina: VitrinaRepuestos) -> str:
    cot = vitrina.cotizacion
    modelo = ''
    if cot is not None:
        modelo = ' '.join(
            x for x in [(cot.vehiculo_marca or '').strip(), (cot.vehiculo_modelo or '').strip()] if x
        )
    auto = modelo or 'tu auto'
    url = construir_url_vitrina(vitrina.token)
    return (
        f'Estas son las opciones que encontré para tu {auto}. '
        f'Elige la que te acomode y el taller te confirma el valor: {url}'
    )

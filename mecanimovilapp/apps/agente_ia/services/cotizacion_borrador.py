"""Generación / actualización de borrador de cotización desde el agente IA.

Reglas de producto:
- Una sola cotización editable por conversación (borrador o enviada; se edita, no se duplica).
- Si el cliente pide cambios tras un envío, la cotización enviada se reabre a borrador.
- Precarga mano de obra y repuestos en los campos editables (catálogo → histórico →
  estimación IA) para que el taller revise/edite antes de enviar.
- El agente NUNCA envía la cotización al cliente; solo deja borrador.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion, TallerAgenteConfig
from mecanimovilapp.apps.agente_ia.services.notificaciones import notificar_cotizacion_borrador_agente
from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.vehiculos.cilindraje_texto import cilindraje_efectivo
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import generar_cotizacion_ia
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import recalcular_totales
from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
    buscar_oferta_exacta,
    normalizar_nombre_servicio,
    precio_publico_oferta,
)
from mecanimovilapp.apps.suscripciones.cuotas_services import CuotaAgotadaError, SinSuscripcionError, verificar_y_consumir_cuota
from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual
from mecanimovilapp.apps.usuarios.models import Taller

logger = logging.getLogger(__name__)
User = get_user_model()

RECARGO_DOMICILIO_DEFAULT_CLP = 5000
IVA_RATE = 1.19  # Precios al cliente siempre con IVA 19% incluido.


def _clp_con_iva(monto_sin_iva: int | float) -> int:
    """Convierte un costo neto a precio público (IVA 19% incluido)."""
    try:
        base = max(0, int(round(float(monto_sin_iva or 0))))
    except (TypeError, ValueError):
        base = 0
    if base <= 0:
        return 0
    return int(round(base * IVA_RATE))


ADVERTENCIA_SIN_CATALOGO = (
    'Valores estimativos precargados (sin tarifa completa en catálogo) — '
    'revisa y edita mano de obra/repuestos antes de enviar'
)
ADVERTENCIA_DESDE_CATALOGO = 'Precio tomado del catálogo publicado del taller'
ADVERTENCIA_ESTIMATIVO = (
    'Mano de obra y/o repuestos incluyen estimaciones (histórico o mercado IA); '
    'el taller puede ajustar los montos antes de enviar'
)
ADVERTENCIA_MULTI_SERVICIO = 'Cotización unificada: varios servicios del mismo vehículo en un solo borrador'
ADVERTENCIA_REABIERTA = (
    'Cliente pidió cambios después del envío — revisa y vuelve a enviar.'
)

# Estados editables por el agente (no terminales).
_ESTADOS_COTIZACION_EDITABLE = ('borrador', 'enviada')


def _construir_notas_cotizacion_ordenadas(
    *,
    descripcion: str,
    lineas: list[dict[str, Any]],
    modalidad: str,
    direccion_servicio: str,
    faltan_precios_catalogo: bool,
    hay_algun_catalogo: bool,
    preferencias_agenda: dict[str, Any] | None,
    marca: str = '',
    modelo: str = '',
    reabierta: bool = False,
) -> str:
    """Notas de cotización numeradas que el agente deja para el taller (editables).

    Orden fijo y legible: síntoma → vehículo → servicios → modalidad → precio →
    repuestos → agenda → reapertura. No son alertas de sistema (esas van en
    ``advertencias``); son consideraciones del servicio según la conversación.
    """
    notas: list[str] = []

    problema = (descripcion or '').strip()
    if problema:
        notas.append(f'Síntoma / motivo de la cotización: {problema[:320]}')

    veh = ' '.join(p for p in [(marca or '').strip(), (modelo or '').strip()] if p)
    if veh:
        notas.append(f'Vehículo identificado: {veh}.')

    nombres = [
        (lin.get('nombre') or '').strip()
        for lin in lineas
        if (lin.get('nombre') or '').strip()
    ]
    if nombres:
        if len(nombres) == 1:
            notas.append(f'Servicio propuesto: {nombres[0]}.')
        else:
            lista = '; '.join(nombres)
            notas.append(f'Servicios incluidos en este borrador: {lista}.')

    if modalidad == 'domicilio':
        dir_txt = (direccion_servicio or '').strip()
        if dir_txt:
            notas.append(f'Modalidad a domicilio. Dirección del cliente: {dir_txt}.')
        else:
            notas.append(
                'Modalidad a domicilio. Falta confirmar comuna/dirección del cliente '
                'antes de coordinar la visita.'
            )
    elif modalidad == 'taller':
        notas.append('Modalidad en taller: el cliente lleva el vehículo al local.')

    if faltan_precios_catalogo or not hay_algun_catalogo:
        notas.append(
            'Precio: sin tarifa publicada completa en catálogo para este caso — '
            'completar valores reales antes de enviar al cliente.'
        )
    elif hay_algun_catalogo:
        notas.append('Precio: tomado del catálogo publicado del taller (revisar que aplique al vehículo).')

    for lin in lineas:
        if lin.get('incluye_repuestos_solicitado'):
            nombre_lin = (lin.get('nombre') or 'servicio').strip()
            notas.append(
                f"Cliente pidió incluir repuestos en '{nombre_lin}' — "
                'confirma modelo, marca y costo del repuesto.'
            )

    pref = preferencias_agenda if isinstance(preferencias_agenda, dict) else {}
    if pref:
        fecha = (pref.get('fecha') or '').strip()
        hora = (pref.get('hora') or '').strip()
        nota_pref = (pref.get('nota') or '').strip()
        partes = [p for p in (fecha, hora, nota_pref) if p]
        if partes or pref.get('confirmado_verbal'):
            detalle = ' '.join(partes) if partes else 'preferencia verbal'
            verbal = ' (confirmada verbalmente con el cliente)' if pref.get('confirmado_verbal') else ''
            notas.append(f'Preferencia de agenda{verbal}: {detalle}.')

    if reabierta:
        notas.append(
            'Esta cotización fue reabierta porque el cliente pidió cambios después del envío.'
        )

    if not notas:
        return ''
    return '\n'.join(f'{i}. {texto}' for i, texto in enumerate(notas, 1))


def _resolver_notas_cotizacion(
    *,
    notas_generadas: str,
    cotizacion_existente: CotizacionCanal | None,
    meta_prev: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Actualiza notas del agente sin pisar ediciones manuales del taller."""
    prev_texto = ''
    if cotizacion_existente is not None:
        prev_texto = (cotizacion_existente.notas_internas or '').strip()
    generadas = (notas_generadas or '').strip()
    ultima_agente = str(meta_prev.get('notas_agente_texto') or '').strip()
    editadas_por_taller = bool(meta_prev.get('notas_editadas_por_taller'))

    # Si el taller ya editó, o el texto actual difiere de lo que dejó el agente, conservar.
    if editadas_por_taller or (prev_texto and ultima_agente and prev_texto != ultima_agente):
        return prev_texto, {
            'notas_editadas_por_taller': True,
            'notas_agente_texto': ultima_agente or generadas,
        }

    return generadas, {
        'notas_editadas_por_taller': False,
        'notas_agente_texto': generadas,
    }

# Sufijos entre paréntesis que no deben crear un servicio distinto.
_PAREN_MODIFIERS_RE = re.compile(
    r'\s*\([^)]*(?:repuesto|sin repuesto|con repuesto|incluye|no incluye)[^)]*\)\s*',
    re.IGNORECASE,
)


def evaluar_listo_para_enviar(
    *,
    lineas: list[dict[str, Any]],
    modalidad: str,
    direccion_servicio: str,
    cliente_telefono: str,
    vehiculo_patente: str,
    patente_verificada: bool = False,
) -> tuple[bool, list[str]]:
    """Checklist determinístico antes de que el taller envíe la cotización al cliente."""
    pendientes: list[str] = []

    patente_ok = bool((vehiculo_patente or '').strip()) or patente_verificada
    if not patente_ok:
        pendientes.append('Falta patente del vehículo verificada')

    if not (cliente_telefono or '').strip():
        pendientes.append('Falta teléfono del cliente')

    if modalidad == 'domicilio' and not (direccion_servicio or '').strip():
        pendientes.append('Falta dirección para servicio a domicilio')

    for linea in lineas or []:
        nombre = (linea.get('nombre') or 'Servicio').strip()
        if not linea.get('precio_desde_catalogo'):
            pendientes.append(f'Falta precio de catálogo para {nombre}')

    return (len(pendientes) == 0, pendientes)


def _recargo_domicilio_taller(taller: Taller) -> int:
    config = TallerAgenteConfig.objects.filter(taller=taller).first()
    if config and config.recargo_domicilio_clp is not None:
        return max(0, int(config.recargo_domicilio_clp))
    return RECARGO_DOMICILIO_DEFAULT_CLP


# Parte "… filtro de aire y filtro de polen" sin romper "aceite y filtro".
_SPLIT_SERVICIOS_Y_RE = re.compile(
    r'^(.+?)\s+(?:y|e)\s+((?:cambio\s+de\s+|filtro\s+de\s+).+)$',
    re.IGNORECASE,
)


def _expandir_nombre_servicio(texto: str) -> list[str]:
    """Parte nombres compuestos ('A, B', 'A + B', 'aire y filtro de polen') en individuales."""
    t = (texto or '').strip()
    if not t:
        return []
    if ' + ' in t:
        partes = [p.strip() for p in t.split(' + ') if p.strip()]
    elif ',' in t:
        partes = [p.strip() for p in t.split(',') if p.strip()]
    else:
        partes = [t]

    out: list[str] = []
    for p in partes:
        if not p or re.match(r'^\(\+\d+', p):
            continue
        # No partir el pack clásico "cambio de aceite y filtro".
        if re.search(r'aceite\s+y\s+filtro\b', p, re.IGNORECASE) and not re.search(
            r'filtro\s+de\s+(?:aire|polen|habit[aá]culo|cabina)',
            p,
            re.IGNORECASE,
        ):
            out.append(p)
            continue
        m = _SPLIT_SERVICIOS_Y_RE.match(p)
        if m:
            left, right = m.group(1).strip(), m.group(2).strip()
            if left and right:
                if re.match(r'^filtro\s+de\s+', right, re.IGNORECASE) and re.match(
                    r'^cambio\s+de\s+', left, re.IGNORECASE
                ):
                    right = f'Cambio de {right[0].lower() + right[1:]}'
                out.extend(_expandir_nombre_servicio(left))
                out.extend(_expandir_nombre_servicio(right))
                continue
        out.append(p)
    return out


_QUAL_SERVICIO = frozenset(
    {
        'aceite',
        'aire',
        'combustible',
        'habitaculo',
        'polen',
        'cabina',
        'gasolina',
        'diesel',
        'bencina',
        'freno',
        'frenos',
        'pastillas',
        'discos',
    }
)
_ENGINE_QUAL = frozenset({'gasolina', 'diesel', 'bencina', 'motor'})


def _tokens_servicio_util(nombre: str) -> set[str]:
    stop = {'de', 'del', 'la', 'el', 'los', 'las', 'y', 'para', 'con', 'sin', 'a', 'e'}
    clave = _clave_servicio(nombre)
    return {t for t in clave.split() if t and t not in stop}


def _qualificadores_servicio(tokens: set[str]) -> set[str]:
    """Calificadores que distinguen servicios; en packs de aceite, gasolina≠filtro combustible."""
    q = tokens & _QUAL_SERVICIO
    if 'aceite' in tokens:
        q -= _ENGINE_QUAL
    return q


def _servicios_equivalentes(nombre_a: str, nombre_b: str) -> bool:
    """True si son el mismo servicio aunque el catálogo haya renombrado el SKU."""
    if _clave_servicio(nombre_a) == _clave_servicio(nombre_b):
        return True
    ta, tb = _tokens_servicio_util(nombre_a), _tokens_servicio_util(nombre_b)
    if not ta or not tb:
        return False
    qa, qb = _qualificadores_servicio(ta), _qualificadores_servicio(tb)
    if qa and qb and qa != qb:
        return False
    # Familia cambio de aceite (+ filtro): variantes con/sin "motor"/"Gasolina".
    if 'aceite' in ta and 'aceite' in tb:
        return True
    if 'filtro' in ta and 'filtro' in tb and qa == qb:
        return True
    inter = ta & tb
    return bool(inter) and len(inter) >= min(len(ta), len(tb)) and (
        len(inter) / max(len(ta), len(tb))
    ) >= 0.7


def _parse_servicios_solicitados(datos: dict) -> list[str]:
    """Lista de servicios pedidos en este turno + previos."""
    nombres: list[str] = []
    raw_lista = datos.get('servicios') or datos.get('servicios_solicitados') or []
    if isinstance(raw_lista, list):
        for item in raw_lista:
            if isinstance(item, str) and item.strip():
                nombres.extend(_expandir_nombre_servicio(item))
            elif isinstance(item, dict):
                n = (item.get('nombre') or item.get('servicio_nombre') or '').strip()
                if n:
                    nombres.extend(_expandir_nombre_servicio(n))
    uno = (datos.get('servicio_nombre') or '').strip()
    if uno:
        nombres.extend(_expandir_nombre_servicio(uno))
    # Dedup case-insensitive preservando orden
    vistos: set[str] = set()
    out: list[str] = []
    for n in nombres:
        key = normalizar_nombre_servicio(n)
        if key and key not in vistos:
            vistos.add(key)
            out.append(n)
    return out


def _clave_servicio(nombre: str) -> str:
    """Clave estable para deduplicar servicios (ignora paréntesis de repuestos, etc.)."""
    base = _PAREN_MODIFIERS_RE.sub('', (nombre or '').strip())
    base = re.sub(r'\s*\([^)]*\)\s*', ' ', base).strip()
    return normalizar_nombre_servicio(base)


def _servicio_es_fusion_redundante(nombre: str, claves_existentes: set[str]) -> bool:
    """True si el nombre combina servicios que ya existen por separado."""
    clave = _clave_servicio(nombre)
    if not clave or clave in claves_existentes:
        return clave in claves_existentes
    texto = (nombre or '').strip().lower()
    for sep in (' y ', ' + ', ' e '):
        if sep in texto:
            partes = [_clave_servicio(p.strip()) for p in texto.split(sep) if p.strip()]
            partes = [p for p in partes if p]
            if len(partes) >= 2 and all(p in claves_existentes for p in partes):
                return True
    return False


def _compactar_lineas_servicio(lineas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una línea por clave de servicio; conserva la más reciente/completa."""
    por_clave: dict[str, dict[str, Any]] = {}
    orden: list[str] = []
    nombre_canon: dict[str, str] = {}

    def _resolver_clave(nombre: str) -> str:
        clave = _clave_servicio(nombre)
        if not clave:
            return ''
        for k, prev_nombre in nombre_canon.items():
            if _servicios_equivalentes(nombre, prev_nombre):
                return k
        return clave

    for lin in lineas or []:
        nombre_raw = (lin.get('nombre') or '').strip()
        # Expande "A, B" / "A + B" / "aire y filtro de polen" del LLM.
        partes = _expandir_nombre_servicio(nombre_raw)
        if len(partes) > 1:
            for parte in partes:
                sub = {**lin, 'nombre': parte}
                clave = _resolver_clave(parte)
                if not clave:
                    continue
                if clave not in por_clave:
                    orden.append(clave)
                    nombre_canon[clave] = parte
                prev = por_clave.get(clave) or {}
                # Al partir un compuesto, no arrastres precios del bloque fusionado.
                limpio = {
                    k: v
                    for k, v in sub.items()
                    if k
                    not in (
                        'precio_catalogo_clp',
                        'precio_desde_catalogo',
                        'precio_estimado_historico_clp',
                        'precio_estimado_muestras',
                        'oferta_servicio_id',
                        'nombre_catalogo',
                    )
                }
                merged = {**prev, **limpio, 'nombre': parte}
                # Prefiere nombre corto sin sufijo de motor del SKU.
                if prev.get('nombre') and 'gasolina' in parte.lower() and 'gasolina' not in (
                    prev.get('nombre') or ''
                ).lower():
                    merged['nombre'] = prev['nombre']
                por_clave[clave] = merged
            continue
        clave = _resolver_clave(nombre_raw)
        if not clave:
            continue
        if clave not in por_clave:
            orden.append(clave)
            nombre_canon[clave] = nombre_raw
        prev = por_clave.get(clave) or {}
        merged = {**prev, **lin}
        if prev.get('nombre') and _servicios_equivalentes(prev.get('nombre') or '', nombre_raw):
            # Conserva el label más legible (no el SKU "… Gasolina").
            if 'gasolina' in nombre_raw.lower() and 'gasolina' not in (prev.get('nombre') or '').lower():
                merged['nombre'] = prev['nombre']
            elif len((prev.get('nombre') or '')) <= len(nombre_raw):
                merged['nombre'] = prev['nombre']
        por_clave[clave] = merged
    return [por_clave[k] for k in orden if k in por_clave]


def _desglose_oferta_catalogo(oferta, *, con_repuestos: bool) -> tuple[int, list[dict[str, Any]]]:
    """Separa mano de obra y repuestos en CLP públicos (IVA 19% incluido)."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import normalizar_repuesto

    # precio_sin_repuestos / precio_con_repuestos ya son al cliente (con IVA).
    mano = int(oferta.precio_sin_repuestos or 0)
    if not mano:
        mano = _clp_con_iva(oferta.costo_mano_de_obra_sin_iva or 0)

    reps: list[dict[str, Any]] = []
    if con_repuestos:
        items = list(oferta.repuestos_seleccionados or [])
        precio_con = int(oferta.precio_con_repuestos or 0)
        costo_rep_sin = int(oferta.costo_repuestos_sin_iva or 0)
        costo_rep_pub = (
            _clp_con_iva(costo_rep_sin) if costo_rep_sin else max(0, precio_con - mano)
        )

        if items:
            precios_raw: list[int] = []
            for item in items:
                if not isinstance(item, dict):
                    precios_raw.append(0)
                    continue
                precios_raw.append(
                    int(item.get('precio_unitario_clp') or item.get('precio') or 0)
                )
            suma_raw = sum(max(0, p) for p in precios_raw)
            # Si la suma de precios unitarios del JSON calza con el costo neto,
            # esos unitarios vienen sin IVA → convertir.
            parecen_sin_iva = bool(
                costo_rep_sin
                and suma_raw > 0
                and abs(suma_raw - costo_rep_sin) <= abs(suma_raw - costo_rep_pub)
            )
            n = len(items)
            base_unit = int(costo_rep_pub / n) if n and costo_rep_pub else 0
            resto = max(0, costo_rep_pub - base_unit * n) if n else 0
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                precio_item = precios_raw[i] if i < len(precios_raw) else 0
                if precio_item > 0 and parecen_sin_iva:
                    precio_item = _clp_con_iva(precio_item)
                if not precio_item:
                    precio_item = base_unit + (resto if i == 0 else 0)
                nombre = (item.get('nombre') or item.get('repuesto') or f'Repuesto {i + 1}').strip()
                serv = getattr(getattr(oferta, 'servicio', None), 'nombre', '') or ''
                if serv and nombre and serv.lower() not in nombre.lower():
                    nombre = f'{nombre} ({serv})'
                marca_rep = (
                    str(item.get('marca_repuesto') or item.get('marca') or '').strip()
                )
                rep = normalizar_repuesto(
                    {
                        'id': item.get('id') or f'cat-rep-{oferta.id}-{i}',
                        'nombre': nombre,
                        'cantidad': item.get('cantidad') or 1,
                        'precio_unitario_clp': precio_item,
                        'marca_repuesto': marca_rep,
                        'fuente_marketplace': 'catalogo',
                        'proveedor_nombre': 'Catálogo del taller',
                        'precio_estimado': False,
                        'comentario': 'Desde catálogo del taller (IVA incl.)',
                    },
                    i,
                )
                rep['precio_iva_incluido'] = True
                rep['precio_estimado'] = False
                rep['proveedor_nombre'] = 'Catálogo del taller'
                reps.append(rep)
        elif precio_con > mano > 0 and (precio_con - mano) > 0:
            serv = getattr(getattr(oferta, 'servicio', None), 'nombre', '') or 'servicio'
            rep = normalizar_repuesto(
                {
                    'id': f'cat-rep-bloque-{oferta.id}',
                    'nombre': f'Repuestos ({serv})',
                    'cantidad': 1,
                    'precio_unitario_clp': precio_con - mano,
                    'comentario': 'Diferencia catálogo con/sin repuestos (IVA incl.)',
                },
                0,
            )
            rep['precio_iva_incluido'] = True
            reps.append(rep)
        elif not mano and precio_con:
            # Sin desglose usable: el total publicado queda en mano de obra.
            mano = precio_con
    else:
        if not mano:
            precio, _ = precio_publico_oferta(oferta, con_repuestos=False)
            mano = precio

    return max(0, mano), reps


def _clave_repuesto_fuzzy(nombre: str) -> str:
    """Clave laxa: ignora paréntesis/sufijos de servicio y ruido genérico."""
    t = normalizar_nombre_servicio(nombre or '')
    t = re.sub(r'\([^)]*\)', ' ', t)
    for ruido in (
        'repuesto',
        'repuestos',
        'original',
        'oem',
        'alternativo',
        'alt',
        'marca',
        'incluye',
    ):
        t = re.sub(rf'\b{ruido}\b', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _repuestos_equivalentes(nombre_a: str, nombre_b: str) -> bool:
    """True si son el mismo ítem aunque el taller haya renombrado el texto."""
    a = _clave_repuesto_fuzzy(nombre_a)
    b = _clave_repuesto_fuzzy(nombre_b)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    ta, tb = set(a.split()), set(b.split())
    stop = {'de', 'del', 'la', 'el', 'los', 'las', 'y', 'para', 'con', 'sin'}
    ta -= stop
    tb -= stop
    if not ta or not tb:
        return False

    # Calificadores que distinguen piezas homónimas (filtro aceite ≠ filtro aire).
    qualificadores = {
        'aceite',
        'aire',
        'combustible',
        'habitaculo',
        'polen',
        'cabina',
        'gasolina',
        'diesel',
        'bencina',
    }
    qa, qb = ta & qualificadores, tb & qualificadores
    if qa and qb and qa != qb:
        return False

    inter = ta & tb
    if not inter:
        return False

    # Misma familia de producto aunque cambien marca/viscosidad/nombre comercial.
    if 'aceite' in ta and 'aceite' in tb and 'filtro' not in ta and 'filtro' not in tb:
        return True
    if 'filtro' in ta and 'filtro' in tb and qa == qb:
        return True
    if {'pastilla', 'pastillas'} & ta and {'pastilla', 'pastillas'} & tb:
        return True
    if {'disco', 'discos'} & ta and {'disco', 'discos'} & tb:
        return True

    # Overlap general alto (renombres parciales).
    return len(inter) >= min(len(ta), len(tb)) and (
        len(inter) / max(len(ta), len(tb))
    ) >= 0.5


def _ids_repuesto(rep: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ('id', 'repuesto_id', 'oferta_repuesto_id'):
        val = rep.get(key)
        if val not in (None, ''):
            ids.add(str(val))
    return ids


def _merge_repuestos_borrador(
    existentes: list[dict[str, Any]],
    nuevos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Une repuestos sin duplicar: respeta renombres manuales e ids previos."""
    out = list(existentes or [])
    ids_vistos: set[str] = set()
    for r in out:
        ids_vistos |= _ids_repuesto(r)

    for rep in nuevos or []:
        if not isinstance(rep, dict):
            continue
        nombre = str(rep.get('nombre') or '').strip()
        if not nombre:
            continue
        ids_nuevos = _ids_repuesto(rep)
        if ids_nuevos and ids_nuevos & ids_vistos:
            continue
        if any(_repuestos_equivalentes(nombre, str(r.get('nombre') or '')) for r in out):
            continue
        out.append(rep)
        ids_vistos |= ids_nuevos
    return out


def _es_servicio_nuevo_vs_previos(
    nombre: str,
    *,
    claves_previas: set[str],
    nombres_previos: list[str],
) -> bool:
    clave = _clave_servicio(nombre)
    if not clave:
        return False
    if clave in claves_previas:
        return False
    for prev in nombres_previos:
        if _servicios_equivalentes(nombre, prev):
            return False
    return True


# Fallback cuando no hay catálogo ni IA para filtros pedidos al actualizar.
_REPUESTOS_FALLBACK_SERVICIO: list[tuple[re.Pattern[str], str, int]] = [
    (
        re.compile(r'filtro\s+de\s+aire\b', re.IGNORECASE),
        'Filtro de aire',
        15_000,
    ),
    (
        re.compile(r'filtro\s+de\s+(?:polen|habit[aá]culo|cabina)\b', re.IGNORECASE),
        'Filtro de polen / habitáculo',
        18_000,
    ),
    (
        re.compile(r'filtro\s+de\s+(?:combustible|gasolina|bencina)\b', re.IGNORECASE),
        'Filtro de combustible',
        16_000,
    ),
]


def _repuesto_cubre_servicio(nombre_rep: str, nombre_serv: str) -> bool:
    """True si el repuesto parece corresponder al servicio (aire≠aceite)."""
    ra = _clave_repuesto_fuzzy(nombre_rep)
    sb = _clave_servicio(nombre_serv)
    if not ra or not sb:
        return False
    quals_a = _qualificadores_servicio(set(ra.split()))
    quals_b = _qualificadores_servicio(set(sb.split()))
    # Pack aceite: aceite en servicio y (aceite o filtro aceite) en repuesto.
    if 'aceite' in sb and 'aire' not in sb and 'polen' not in sb:
        if 'aceite' in ra and 'filtro' not in ra:
            return True
        if 'filtro' in ra and quals_a <= {'aceite'} and 'aire' not in ra:
            return True
        return False
    if quals_b and quals_a and quals_a == quals_b:
        return True
    if 'aire' in sb and 'aire' in ra:
        return True
    if ('polen' in sb or 'habitaculo' in sb or 'cabina' in sb) and (
        'polen' in ra or 'habitaculo' in ra or 'cabina' in ra
    ):
        return True
    if ('combustible' in sb or 'gasolina' in sb) and (
        'combustible' in ra or 'gasolina' in ra
    ):
        return True
    return False


def _repuestos_fallback_servicios(
    servicios: list[str],
    ya_tienen: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Líneas de repuesto mínimas para servicios nuevos sin cobertura catálogo/IA."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        normalizar_repuesto,
    )

    out: list[dict[str, Any]] = []
    for serv in servicios or []:
        if any(_repuesto_cubre_servicio(str(r.get('nombre') or ''), serv) for r in (ya_tienen or [])):
            continue
        if any(_repuesto_cubre_servicio(str(r.get('nombre') or ''), serv) for r in out):
            continue
        for rx, nombre, precio in _REPUESTOS_FALLBACK_SERVICIO:
            if not rx.search(serv):
                continue
            rep = normalizar_repuesto(
                {
                    'id': f'fallback-{_clave_servicio(serv)[:24]}',
                    'nombre': nombre,
                    'cantidad': 1,
                    'precio_unitario_clp': precio,
                    'comentario': 'Sugerido por el servicio pedido (IVA incl.; revisa precio)',
                },
                len(ya_tienen) + len(out),
            )
            rep['precio_iva_incluido'] = True
            out.append(rep)
            break
    return out


def _podar_lineas_servicio_redundantes(lineas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Elimina servicios genéricos ya cubiertos por otro más específico.

    Ej: "Cambio de filtro" sobra si ya está "Cambio de filtro de aceite".
    Nunca poda filtro de aire/polen contra un pack de aceite.
    """
    enriched: list[tuple[str, set[str], set[str], dict[str, Any]]] = []
    for lin in lineas or []:
        clave = _clave_servicio(lin.get('nombre') or '')
        if not clave:
            continue
        tokens = _tokens_servicio_util(lin.get('nombre') or '')
        quals = _qualificadores_servicio(tokens)
        enriched.append((clave, tokens, quals, lin))

    drop: set[int] = set()
    for i, (ci, ti, qi, _) in enumerate(enriched):
        if not ti:
            continue
        for j, (cj, tj, qj, _) in enumerate(enriched):
            if i == j or not tj:
                continue
            # Calificadores distintos (aire vs aceite vs polen) → servicios distintos.
            if qi and qj and qi != qj:
                continue
            if qi - qj:
                continue
            # i es más genérico / corto y sus tokens están contenidos en j
            if ti < tj or (ti <= tj and len(ci) < len(cj) and ti.issubset(tj)):
                drop.add(i)
                break
    return [lin for idx, (_, _, _, lin) in enumerate(enriched) if idx not in drop]


def _titulo_servicios(lineas: list[dict[str, Any]]) -> str:
    nombres = [str(l.get('nombre') or '').strip() for l in lineas if l.get('nombre')]
    nombres = [n for n in nombres if n]
    if not nombres:
        return 'Servicio'
    if len(nombres) == 1:
        return nombres[0]
    if len(nombres) == 2:
        return f'{nombres[0]} + {nombres[1]}'
    return f'{nombres[0]} + {nombres[1]} (+{len(nombres) - 2} más)'


def _merge_linea_servicio(
    existentes: list[dict[str, Any]],
    nueva: dict[str, Any],
) -> list[dict[str, Any]]:
    key = _clave_servicio(nueva.get('nombre') or '')
    if not key:
        return existentes
    out = list(existentes or [])
    for i, lin in enumerate(out):
        nombre_lin = lin.get('nombre') or ''
        if _clave_servicio(nombre_lin) != key and not _servicios_equivalentes(
            nombre_lin, nueva.get('nombre') or ''
        ):
            continue
        merged = {**lin, **nueva}
        # Si el rematch no encontró catálogo, no borres el match previo bueno.
        if not nueva.get('oferta_servicio_id') and lin.get('oferta_servicio_id'):
            merged['oferta_servicio_id'] = lin['oferta_servicio_id']
            merged['precio_catalogo_clp'] = lin.get('precio_catalogo_clp')
            merged['precio_desde_catalogo'] = lin.get('precio_desde_catalogo')
            if lin.get('nombre_catalogo'):
                merged['nombre_catalogo'] = lin.get('nombre_catalogo')
        if not nueva.get('precio_estimado_historico_clp') and lin.get(
            'precio_estimado_historico_clp'
        ):
            merged['precio_estimado_historico_clp'] = lin['precio_estimado_historico_clp']
            merged['precio_estimado_muestras'] = lin.get('precio_estimado_muestras')
        # Conserva el nombre más claro para el taller (evita SKU "… filtro Gasolina").
        nom_nuevo = (nueva.get('nombre') or '').strip()
        nom_prev = (lin.get('nombre') or '').strip()
        if nom_prev and nom_nuevo:
            if 'gasolina' in nom_nuevo.lower() and 'gasolina' not in nom_prev.lower():
                merged['nombre'] = nom_prev
            elif len(nom_prev) < len(nom_nuevo) and _servicios_equivalentes(nom_prev, nom_nuevo):
                merged['nombre'] = nom_prev
        out[i] = merged
        return out
    out.append(nueva)
    return out


def _obtener_borrador_abierto(
    *,
    sesion: AgenteConversacionSesion,
    conversation: Conversation,
    taller: Taller,
) -> CotizacionCanal | None:
    """Reutiliza la cotización editable (borrador o enviada) de la misma conversación."""
    cot = getattr(sesion, 'cotizacion_borrador', None)
    if cot and cot.estado in _ESTADOS_COTIZACION_EDITABLE and cot.taller_id == taller.id:
        return cot
    return (
        CotizacionCanal.objects.filter(
            conversation=conversation,
            taller=taller,
            estado__in=_ESTADOS_COTIZACION_EDITABLE,
            metadata__origen='agente_ia',
        )
        .order_by('-actualizado_en', '-id')
        .first()
    )


def crear_cotizacion_borrador_desde_agente(
    *,
    sesion: AgenteConversacionSesion,
    conversation: Conversation,
    taller: Taller,
    proveedor_user_id: int,
    datos: dict,
) -> CotizacionCanal | None:
    """Crea o actualiza UN CotizacionCanal borrador (no duplica por servicio extra)."""
    proveedor = User.objects.filter(pk=proveedor_user_id).first()
    if not proveedor:
        logger.warning('Proveedor %s no encontrado para cotización agente', proveedor_user_id)
        return None

    cotizacion_existente = _obtener_borrador_abierto(
        sesion=sesion,
        conversation=conversation,
        taller=taller,
    )
    es_update = cotizacion_existente is not None
    estado_previo = cotizacion_existente.estado if cotizacion_existente else None
    reabierta = es_update and estado_previo == 'enviada'

    if not es_update:
        try:
            verificar_y_consumir_cuota(proveedor, ConsumoFeatureMensual.FEATURE_COTIZACION_IA)
        except (CuotaAgotadaError, SinSuscripcionError) as exc:
            logger.info('Cuota cotización IA agotada para agente: %s', exc.message)
            return None

    vehiculo = datos.get('vehiculo') or {}
    servicios_turno = _parse_servicios_solicitados(datos)
    if not servicios_turno:
        servicios_turno = ['Servicio por definir']
    descripcion = (datos.get('descripcion_problema') or datos.get('sintoma') or '').strip()
    modalidad_raw = (datos.get('modalidad') or '').strip().lower()
    if modalidad_raw in ('domicilio', 'a_domicilio'):
        modalidad = 'domicilio'
    elif modalidad_raw in ('taller', 'en_taller'):
        modalidad = 'taller'
    else:
        modalidad = (
            cotizacion_existente.modalidad if cotizacion_existente and cotizacion_existente.modalidad
            else 'taller'
        )
    marca = (vehiculo.get('marca') or '').strip()
    modelo = (vehiculo.get('modelo') or '').strip()
    tipo_motor = (vehiculo.get('tipo_motor') or '').strip()

    meta_prev = dict((cotizacion_existente.metadata if cotizacion_existente else {}) or {})
    lineas: list[dict[str, Any]] = _compactar_lineas_servicio(
        list(meta_prev.get('servicios_lineas') or [])
    )
    precios_ref_ia: list[dict[str, Any]] = list(meta_prev.get('precios_referenciales_ia') or [])
    claves_lineas_previas = {_clave_servicio(l.get('nombre') or '') for l in lineas if l.get('nombre')}

    # Filtra nombres compuestos redundantes ("diagnóstico y pastillas" si ya existen por separado).
    servicios_filtrados: list[str] = []
    claves_acum = set(claves_lineas_previas)
    for nombre_serv in servicios_turno:
        if _servicio_es_fusion_redundante(nombre_serv, claves_acum):
            continue
        clave = _clave_servicio(nombre_serv)
        if clave and clave not in claves_acum:
            claves_acum.add(clave)
        servicios_filtrados.append(nombre_serv)
    servicios_turno = servicios_filtrados or servicios_turno

    repuestos_flag = datos.get('repuestos_incluidos_ultimo_servicio')
    # Cambios de filtro / aceite implican repuestos salvo que el cliente diga lo contrario.
    if repuestos_flag is None and any(
        re.search(r'\b(?:filtro|aceite|pastillas|discos|buj[ií]as)\b', s, re.I)
        for s in servicios_turno
    ):
        repuestos_flag = True
    ultimo_servicio_turno = servicios_turno[-1] if servicios_turno else ''

    nombres_previos = [
        str(l.get('nombre') or '') for l in lineas if (l.get('nombre') or '').strip()
    ]
    servicios_nuevos = [
        s
        for s in servicios_turno
        if _es_servicio_nuevo_vs_previos(
            s,
            claves_previas=claves_lineas_previas,
            nombres_previos=nombres_previos,
        )
    ]

    # En update: la IA estima SOLO los servicios nuevos (si regenera el pack de aceite,
    # el merge fuzzy descarta piezas viejas y aire/polen nunca aparecen).
    if es_update and servicios_nuevos:
        servicio_prompt = ' + '.join(servicios_nuevos)
        descripcion_ia = (
            'Actualización de cotización existente. Estima ÚNICAMENTE mano de obra y '
            'repuestos de estos servicios NUEVOS (no incluyas aceite ni filtro de aceite '
            'si no están en la lista): '
            + (descripcion or servicio_prompt)
        )
    else:
        servicio_prompt = ' + '.join(servicios_turno)
        descripcion_ia = descripcion

    # Reutilizar plantilla aprendizaje (mismo modelo + servicio) → sin Gemini ni Tavily.
    resultado = None
    plantilla_reuso_id = None
    if not es_update:
        try:
            from mecanimovilapp.apps.ordenes.models import CotizacionCanalPlantilla
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aprendizaje_cotizacion import (
                buscar_plantilla_reutilizable,
                plantilla_tiene_cobertura_precios,
            )
            from django.db.models import F

            plantilla = buscar_plantilla_reutilizable(
                taller=taller,
                marca=marca,
                modelo=modelo,
                servicio_nombre=servicio_prompt,
                cilindraje=str(vehiculo.get('cilindraje') or ''),
            )
            if plantilla is not None and plantilla_tiene_cobertura_precios(plantilla):
                snap = plantilla.snapshot if isinstance(plantilla.snapshot, dict) else {}
                CotizacionCanalPlantilla.objects.filter(pk=plantilla.pk).update(
                    uso_count=F('uso_count') + 1,
                )
                plantilla_reuso_id = plantilla.id
                resultado = {
                    'disponible': True,
                    'contenido': {
                        'servicio_nombre': snap.get('servicio_nombre') or servicio_prompt,
                        'descripcion_problema': snap.get('descripcion_problema') or descripcion_ia,
                        'repuestos': list(snap.get('repuestos') or []),
                        'mano_obra_clp': int(snap.get('mano_obra_clp') or 0),
                        'costo_repuestos_clp': int(snap.get('costo_repuestos_clp') or 0),
                        'total_clp': int(snap.get('total_clp') or 0),
                        'duracion_minutos_estimada': snap.get('duracion_minutos_estimada'),
                        'advertencias': list(snap.get('advertencias') or []),
                        'tipo_motor': snap.get('tipo_motor') or tipo_motor,
                        'tipo_motor_label': snap.get('tipo_motor_label') or '',
                        'valores_estimativos': False,
                        'precio_desde_catalogo': False,
                    },
                    'contenido_ia': {'origen': 'plantilla_auto', 'plantilla_id': plantilla.id},
                    'contexto': {
                        'vehiculo_marca': marca,
                        'vehiculo_modelo': modelo,
                        'vehiculo_anio': vehiculo.get('anio'),
                        'vehiculo_cilindraje': vehiculo.get('cilindraje'),
                        'tipo_motor': tipo_motor,
                    },
                    'tokens_entrada': 0,
                    'tokens_salida': 0,
                    'modelo': 'plantilla_auto',
                    'desde_plantilla': True,
                }
                logger.info(
                    'Agente reutiliza plantilla %s (taller=%s %s %s / %s) — sin Gemini/Tavily',
                    plantilla.id,
                    taller.id,
                    marca,
                    modelo,
                    servicio_prompt[:80],
                )
        except Exception as exc:
            logger.warning('Reuso plantilla agente falló: %s', exc)
            resultado = None

    # Generar contexto IA (desglose/orientación). Si Gemini falla, igual mergeamos.
    if resultado is None:
        resultado = generar_cotizacion_ia(
            conversation=conversation,
            servicio_nombre=servicio_prompt,
            descripcion_problema=descripcion_ia,
            modalidad=modalidad if modalidad in ('taller', 'domicilio') else 'taller',
            vehiculo=vehiculo,
            contexto_rag_extra=datos.get('contexto_rag') or '',
            taller=taller,
        )
    if not resultado.get('disponible'):
        logger.warning(
            'generar_cotizacion_ia no disponible (%s); se actualiza borrador sin contenido IA '
            '(sesion=%s servicios=%s)',
            resultado.get('error'),
            sesion.id,
            servicios_turno,
        )
        resultado = {
            'disponible': False,
            'contenido': {},
            'contenido_ia': {},
            'contexto': {},
            'tokens_entrada': 0,
            'tokens_salida': 0,
            'modelo': '',
        }

    contenido = resultado.get('contenido') or {}
    ctx = resultado.get('contexto') or {}
    anio_raw = vehiculo.get('anio') or ctx.get('vehiculo_anio')
    try:
        anio_int = int(anio_raw) if anio_raw else None
    except (TypeError, ValueError):
        anio_int = None

    marca = ctx.get('vehiculo_marca') or vehiculo.get('marca', '') or marca
    modelo = ctx.get('vehiculo_modelo') or vehiculo.get('modelo', '') or modelo

    # Preferencias de repuestos por clave de servicio (líneas previas + turno actual).
    preferencias_repuestos: dict[str, bool] = {}
    for lin in lineas:
        clave_lin = _clave_servicio(lin.get('nombre') or '')
        if clave_lin and lin.get('incluye_repuestos_solicitado') is not None:
            preferencias_repuestos[clave_lin] = bool(lin.get('incluye_repuestos_solicitado'))
    if repuestos_flag is not None and ultimo_servicio_turno:
        clave_ult = _clave_servicio(ultimo_servicio_turno)
        if clave_ult:
            preferencias_repuestos[clave_ult] = bool(repuestos_flag)

    mano_obra_catalogo = 0
    hay_algun_catalogo = False
    faltan_precios_catalogo = False

    from mecanimovilapp.apps.agente_ia.services.historial_pricing import buscar_estimado_historico

    config_taller = TallerAgenteConfig.objects.filter(taller=taller).first()
    permite_hist = bool(getattr(config_taller, 'permite_estimados_historicos', True))

    for nombre_serv in servicios_turno:
        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre_serv,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        precio_cat = 0
        oferta_id = None
        # Mantener el nombre pedido por el cliente; el SKU de catálogo va aparte.
        nombre_final = nombre_serv
        nombre_catalogo = None
        clave_serv = _clave_servicio(nombre_serv)
        con_repuestos = preferencias_repuestos.get(clave_serv, True)
        if oferta:
            precio_cat, _ = precio_publico_oferta(oferta, con_repuestos=con_repuestos)
            oferta_id = oferta.id
            nombre_catalogo = oferta.servicio.nombre
            # Solo copiar el nombre del catálogo si es match exacto (sin sufijos tipo motor).
            if normalizar_nombre_servicio(nombre_catalogo) == normalizar_nombre_servicio(
                nombre_serv
            ):
                nombre_final = nombre_catalogo

        linea_nueva: dict[str, Any] = {
            'nombre': nombre_final,
            'nombre_catalogo': nombre_catalogo,
            'oferta_servicio_id': oferta_id,
            'precio_catalogo_clp': precio_cat or None,
            'precio_desde_catalogo': bool(precio_cat),
        }
        # Sin catálogo: referencia histórica (mercado del taller) para revisión humana.
        if not precio_cat and permite_hist:
            est = buscar_estimado_historico(
                taller=taller,
                servicio_nombre=nombre_final,
                marca=marca,
                modelo=modelo,
                tipo_motor=tipo_motor,
            )
            if est:
                linea_nueva['precio_estimado_historico_clp'] = est.mediana_clp
                linea_nueva['precio_estimado_muestras'] = est.muestras

        lineas = _merge_linea_servicio(lineas, linea_nueva)

    lineas = _podar_lineas_servicio_redundantes(_compactar_lineas_servicio(lineas))

    # Servicios que YA estaban en el borrador (no reinyectar sus repuestos).
    claves_lineas_previas = {
        _clave_servicio(str(l.get('nombre') or ''))
        for l in (meta_prev.get('servicios_lineas') or [])
        if isinstance(l, dict) and l.get('nombre')
    }
    claves_lineas_previas.discard('')

    # Re-matchea catálogo/histórico tras compactar (por si partimos un nombre fusionado).
    for i, lin in enumerate(lineas):
        if lin.get('precio_desde_catalogo') and lin.get('oferta_servicio_id'):
            continue
        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=lin.get('nombre') or '',
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        if not oferta:
            if permite_hist and not lin.get('precio_estimado_historico_clp'):
                est = buscar_estimado_historico(
                    taller=taller,
                    servicio_nombre=lin.get('nombre') or '',
                    marca=marca,
                    modelo=modelo,
                    tipo_motor=tipo_motor,
                )
                if est:
                    lineas[i] = {
                        **lin,
                        'precio_estimado_historico_clp': est.mediana_clp,
                        'precio_estimado_muestras': est.muestras,
                    }
            continue
        clave_serv = _clave_servicio(lin.get('nombre') or '')
        con_repuestos = preferencias_repuestos.get(clave_serv, True)
        precio_cat, _ = precio_publico_oferta(oferta, con_repuestos=con_repuestos)
        nombre_cat = oferta.servicio.nombre or ''
        nombre_lin = (lin.get('nombre') or '').strip()
        nombre_mostrar = nombre_lin
        if nombre_cat and normalizar_nombre_servicio(nombre_cat) == normalizar_nombre_servicio(
            nombre_lin
        ):
            nombre_mostrar = nombre_cat
        lineas[i] = {
            **lin,
            'nombre': nombre_mostrar or nombre_cat,
            'nombre_catalogo': nombre_cat or lin.get('nombre_catalogo'),
            'oferta_servicio_id': oferta.id,
            'precio_catalogo_clp': precio_cat or None,
            'precio_desde_catalogo': bool(precio_cat),
        }

    lineas = _podar_lineas_servicio_redundantes(lineas)

    # Preferencia estructurada de repuestos (no duplicar línea con "(con repuestos)" en el nombre).
    if repuestos_flag is not None and ultimo_servicio_turno:
        clave_ultimo = _clave_servicio(ultimo_servicio_turno)
        for i, lin in enumerate(lineas):
            if _clave_servicio(lin.get('nombre') or '') == clave_ultimo:
                lineas[i] = {
                    **lin,
                    'incluye_repuestos_solicitado': bool(repuestos_flag),
                }
                break

    # Precarga editable: catálogo (mano + repuestos) → histórico → estimación IA.
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        normalizar_repuesto,
    )
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    mano_obra_catalogo = 0
    mano_obra_historico = 0
    mano_obra_nueva = 0  # solo servicios agregados en este update
    hay_algun_catalogo = False
    faltan_precios_catalogo = False
    usa_estimativo = False
    reps_para_agregar: list[dict[str, Any]] = []
    ofertas_cache: dict[int, Any] = {}

    oferta_ids = [
        int(lin['oferta_servicio_id'])
        for lin in lineas
        if lin.get('oferta_servicio_id')
    ]
    if oferta_ids:
        for of in OfertaServicio.objects.filter(pk__in=oferta_ids).select_related('servicio'):
            ofertas_cache[of.id] = of

    for lin in lineas:
        oferta_id = lin.get('oferta_servicio_id')
        oferta = ofertas_cache.get(int(oferta_id)) if oferta_id else None
        clave_lin = _clave_servicio(lin.get('nombre') or '')
        quiere_reps = preferencias_repuestos.get(clave_lin, True)
        es_servicio_nuevo = (not es_update) or (clave_lin not in claves_lineas_previas)

        if oferta and lin.get('precio_desde_catalogo'):
            hay_algun_catalogo = True
            mano_lin, reps_lin = _desglose_oferta_catalogo(oferta, con_repuestos=quiere_reps)
            if mano_lin <= 0:
                precio_pub, _ = precio_publico_oferta(oferta, con_repuestos=quiere_reps)
                mano_lin = precio_pub
            lin['precio_catalogo_clp'] = mano_lin or lin.get('precio_catalogo_clp')
            lin['precio_mano_obra_clp'] = mano_lin
            mano_obra_catalogo += max(0, mano_lin)
            if es_servicio_nuevo:
                mano_obra_nueva += max(0, mano_lin)
                # Solo inyecta repuestos de servicios NUEVOS (no reabrir el original).
                if quiere_reps:
                    reps_para_agregar.extend(reps_lin)
        else:
            faltan_precios_catalogo = True
            est_hist = int(lin.get('precio_estimado_historico_clp') or 0)
            if est_hist > 0:
                lin['precio_mano_obra_clp'] = est_hist
                mano_obra_historico += est_hist
                usa_estimativo = True
                if es_servicio_nuevo:
                    mano_obra_nueva += est_hist

    ref_mano = int(contenido.get('mano_obra_clp') or 0)
    ref_reps_raw = contenido.get('repuestos') or []
    ref_reps = [
        normalizar_repuesto(r, i) if isinstance(r, dict) else normalizar_repuesto({'nombre': r}, i)
        for i, r in enumerate(ref_reps_raw[:12])
    ]
    for r in ref_reps:
        r['comentario'] = (r.get('comentario') or '') or 'Estimación de mercado (IA, IVA incl.)'
        r['precio_referencia_ia'] = int(r.get('precio_unitario_clp') or 0)
        r['precio_iva_incluido'] = True

    if ref_mano or ref_reps:
        precios_ref_ia.append(
            {
                'servicios': servicios_turno,
                'mano_obra_clp': ref_mano,
                'repuestos': ref_reps,
                'nota': 'Estimación precargada en el borrador para revisión del taller',
                'generado_en': timezone.now().isoformat(),
            }
        )

    repuestos: list = (
        list(cotizacion_existente.repuestos or [])
        if es_update and cotizacion_existente
        else []
    )

    if es_update and cotizacion_existente:
        # Conserva mano de obra ya editada y solo SUMA lo nuevo.
        mano_prev = int(cotizacion_existente.mano_obra_clp or 0)
        recargo_prev = int(meta_prev.get('recargo_domicilio_aplicado_clp') or 0)
        base_prev = max(0, mano_prev - recargo_prev)
        if mano_obra_nueva > 0:
            mano_obra = base_prev + mano_obra_nueva
        elif faltan_precios_catalogo and ref_mano > 0 and claves_lineas_previas:
            # IA devolvió total global: suma solo el delta positivo estimado.
            delta = max(0, ref_mano - base_prev)
            mano_obra = base_prev + delta if delta else base_prev
            if delta:
                usa_estimativo = True
        else:
            mano_obra = base_prev if base_prev > 0 else (mano_obra_catalogo + mano_obra_historico)
        # Repuestos: nunca reinyectar los del servicio original; solo candidatos nuevos.
        reps_ia_nuevos = ref_reps if (repuestos_flag is not False) else []
        if servicios_nuevos and reps_ia_nuevos:
            filtrados = [
                r
                for r in reps_ia_nuevos
                if any(
                    _repuesto_cubre_servicio(str(r.get('nombre') or ''), s)
                    for s in servicios_nuevos
                )
            ]
            # Si la IA devolvió solo piezas del servicio viejo, no las metas de nuevo.
            reps_ia_nuevos = filtrados
        repuestos = _merge_repuestos_borrador(repuestos, reps_para_agregar)
        repuestos = _merge_repuestos_borrador(repuestos, reps_ia_nuevos)
        # Sin catálogo/IA para aire/polen: igual deja la línea de repuesto editable.
        if servicios_nuevos and repuestos_flag is not False:
            fallback = _repuestos_fallback_servicios(servicios_nuevos, repuestos)
            if fallback:
                repuestos = _merge_repuestos_borrador(repuestos, fallback)
                usa_estimativo = True
        if reps_para_agregar or reps_ia_nuevos:
            if reps_ia_nuevos:
                usa_estimativo = True
    else:
        mano_obra = mano_obra_catalogo + mano_obra_historico
        if mano_obra <= 0 and ref_mano > 0:
            mano_obra = ref_mano
            usa_estimativo = True
        elif faltan_precios_catalogo and ref_mano > mano_obra:
            mano_obra = ref_mano
            usa_estimativo = True
        repuestos = _merge_repuestos_borrador(repuestos, reps_para_agregar)
        cliente_quiere_reps = any(
            preferencias_repuestos.get(_clave_servicio(l.get('nombre') or ''), True) for l in lineas
        ) or (repuestos_flag is True)
        if cliente_quiere_reps or not repuestos:
            repuestos = _merge_repuestos_borrador(repuestos, ref_reps)
            if ref_reps:
                usa_estimativo = True

    mano_obra_manual_prev = max(0, mano_obra - mano_obra_catalogo)

    advertencias: list[str] = []
    if hay_algun_catalogo and not faltan_precios_catalogo and not usa_estimativo:
        advertencias.append(ADVERTENCIA_DESDE_CATALOGO)
    else:
        advertencias.append(ADVERTENCIA_SIN_CATALOGO)
    if usa_estimativo:
        advertencias.append(ADVERTENCIA_ESTIMATIVO)
    for lin in lineas:
        est_hist = int(lin.get('precio_estimado_historico_clp') or 0)
        if est_hist > 0 and not lin.get('precio_desde_catalogo'):
            n = (lin.get('nombre') or 'servicio').strip()
            muestras = int(lin.get('precio_estimado_muestras') or 0)
            advertencias.append(
                f"Histórico '{n}': ~${est_hist:,} CLP precargado en mano de obra (n={muestras})".replace(
                    ',', '.'
                )
            )

    if len(lineas) > 1:
        advertencias.append(ADVERTENCIA_MULTI_SERVICIO)

    if reabierta:
        advertencias.append(ADVERTENCIA_REABIERTA)

    for lin in lineas:
        if lin.get('incluye_repuestos_solicitado'):
            nombre_lin = (lin.get('nombre') or 'servicio').strip()
            advertencias.append(
                f"Cliente pidió incluir repuestos en '{nombre_lin}' — confirma modelo/costo del repuesto."
            )

    recargo_aplicado = int(meta_prev.get('recargo_domicilio_aplicado_clp') or 0)
    if modalidad == 'domicilio' and mano_obra > 0:
        recargo = _recargo_domicilio_taller(taller)
        if recargo > 0 and recargo_aplicado == 0:
            mano_obra += recargo
            recargo_aplicado = recargo
            advertencias.append(
                f'Incluye recargo a domicilio de ${recargo:,} CLP en mano de obra.'.replace(',', '.')
            )
        elif recargo_aplicado > 0:
            mano_obra += recargo_aplicado

    costo_rep, mano_obra, total = recalcular_totales(repuestos, mano_obra)

    contact = conversation.external_contact
    cliente_nombre = (datos.get('cliente_nombre') or '').strip()
    cliente_telefono = (datos.get('cliente_telefono') or '').strip()
    if contact:
        cliente_nombre = cliente_nombre or (contact.display_name or '')
        # WhatsApp: phone puede venir vacío; external_id suele ser el número real.
        if hasattr(contact, 'telefono_efectivo'):
            cliente_telefono = cliente_telefono or contact.telefono_efectivo()
        else:
            cliente_telefono = cliente_telefono or (contact.phone or '')

    preferencias_agenda = datos.get('preferencias_agenda') or meta_prev.get('preferencias_agenda') or {}
    if isinstance(preferencias_agenda, dict):
        # Fusiona preferencias nuevas del turno
        prev_pref = dict(meta_prev.get('preferencias_agenda') or {})
        for k, v in preferencias_agenda.items():
            if v not in (None, '', []):
                prev_pref[k] = v
        preferencias_agenda = prev_pref

    direccion_servicio_final = str(datos.get('direccion_servicio') or (
        cotizacion_existente.direccion_servicio if cotizacion_existente else ''
    )).strip()
    # Evita persistir frases del chat como si fueran dirección ("Cuánto cuesta").
    try:
        from mecanimovilapp.apps.agente_ia.services.orquestador import _direccion_parece_basura

        if _direccion_parece_basura(direccion_servicio_final):
            direccion_servicio_final = ''
    except Exception:
        pass

    patente_verificada = bool(
        (datos.get('patente_enriquecida') or '').strip()
        or datos.get('vehiculo_verificado')
        or datos.get('vehiculo_fuente') in ('registro_mecanimovil', 'getapi')
    )
    listo_para_enviar, pendientes_revision = evaluar_listo_para_enviar(
        lineas=lineas,
        modalidad=modalidad,
        direccion_servicio=direccion_servicio_final,
        cliente_telefono=cliente_telefono,
        vehiculo_patente=ctx.get('vehiculo_patente') or vehiculo.get('patente', '') or (
            cotizacion_existente.vehiculo_patente if cotizacion_existente else ''
        ),
        patente_verificada=patente_verificada,
    )

    km_actual = (
        vehiculo.get('kilometraje_actual')
        or vehiculo.get('kilometraje')
        or (datos.get('vehiculo') or {}).get('kilometraje_actual')
        or ''
    )
    try:
        km_actual_int = int(str(km_actual).replace('.', '').replace(',', '').strip()) if km_actual not in ('', None) else None
    except (TypeError, ValueError):
        km_actual_int = None

    desc_prev = (cotizacion_existente.descripcion_problema if cotizacion_existente else '') or ''
    descripcion_final = descripcion or desc_prev
    if descripcion and desc_prev and descripcion not in desc_prev:
        descripcion_final = f'{desc_prev}\n{descripcion}'.strip()

    notas_generadas = _construir_notas_cotizacion_ordenadas(
        descripcion=descripcion_final,
        lineas=lineas,
        modalidad=modalidad,
        direccion_servicio=direccion_servicio_final,
        faltan_precios_catalogo=faltan_precios_catalogo,
        hay_algun_catalogo=hay_algun_catalogo,
        preferencias_agenda=preferencias_agenda if isinstance(preferencias_agenda, dict) else {},
        marca=marca,
        modelo=modelo,
        reabierta=reabierta,
    )
    notas_finales, meta_notas = _resolver_notas_cotizacion(
        notas_generadas=notas_generadas,
        cotizacion_existente=cotizacion_existente,
        meta_prev=meta_prev,
    )

    metadata_cot = {
        **meta_prev,
        'origen': 'plantilla_auto' if plantilla_reuso_id else 'agente_ia',
        'plantilla_id': plantilla_reuso_id or meta_prev.get('plantilla_id'),
        'sesion_id': sesion.id,
        'mano_obra_manual_clp': mano_obra_manual_prev,
        'recargo_domicilio_aplicado_clp': recargo_aplicado,
        'precio_desde_catalogo': hay_algun_catalogo and not faltan_precios_catalogo,
        'precio_parcial_catalogo': hay_algun_catalogo and faltan_precios_catalogo,
        'valores_estimativos': usa_estimativo,
        'precios_iva_incluido': True,
        'servicios_lineas': lineas,
        'precios_referenciales_ia': precios_ref_ia[-5:],  # últimas 5 estimaciones
        'preferencias_agenda': preferencias_agenda,
        'requiere_revision_humana': True,
        'enviada_por_agente': False,
        'listo_para_enviar': listo_para_enviar,
        'pendientes_revision': pendientes_revision,
        'vehiculo_kilometraje_actual': km_actual_int,
        'vehiculo_fuente': datos.get('vehiculo_fuente') or meta_prev.get('vehiculo_fuente') or '',
        'patente_enriquecida': (
            (datos.get('patente_enriquecida') or '').strip()
            or meta_prev.get('patente_enriquecida')
            or ''
        ),
        **meta_notas,
    }

    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
        disparar_y_refrescar_cotizacion,
        marcar_busqueda_web_pendiente,
    )

    metadata_cot = marcar_busqueda_web_pendiente(metadata_cot)

    if not es_update and not meta_prev.get('propuesta_agente_original'):
        metadata_cot['propuesta_agente_original'] = {
            'servicios_lineas': [
                {
                    'nombre': (l.get('nombre') or '').strip(),
                    'precio_clp': int(l.get('precio_clp') or 0),
                    'precio_desde_catalogo': bool(l.get('precio_desde_catalogo')),
                    'oferta_servicio_id': l.get('oferta_servicio_id'),
                }
                for l in lineas
            ],
            'servicio_nombre': _titulo_servicios(lineas),
            'descripcion_problema': descripcion_final,
            'modalidad': modalidad,
            'direccion_servicio': direccion_servicio_final[:500],
            'mano_obra_clp': mano_obra,
            'total_clp': total,
            'notas_internas': notas_finales,
            'repuestos': repuestos,
            'congelado_en': timezone.now().isoformat(),
        }
    elif meta_prev.get('propuesta_agente_original'):
        metadata_cot['propuesta_agente_original'] = meta_prev['propuesta_agente_original']

    if reabierta:
        historial = list(meta_prev.get('historial_reapertura') or [])
        historial.append(
            {
                'en': timezone.now().isoformat(),
                'motivo': descripcion[:300] if descripcion else 'Cliente pidió cambios',
                'servicios_turno': servicios_turno,
                'estado_anterior': estado_previo,
            }
        )
        metadata_cot['reabierta_por_cliente'] = True
        metadata_cot['reabierta_en'] = timezone.now().isoformat()
        metadata_cot['historial_reapertura'] = historial[-10:]

    campos = {
        'cliente_nombre': (cliente_nombre or (cotizacion_existente.cliente_nombre if cotizacion_existente else ''))[:200],
        'cliente_telefono': (cliente_telefono or (cotizacion_existente.cliente_telefono if cotizacion_existente else ''))[:20],
        'modalidad': modalidad,
        'direccion_servicio': direccion_servicio_final[:500],
        'vehiculo_marca': marca,
        'vehiculo_modelo': modelo,
        'vehiculo_anio': anio_int,
        'vehiculo_patente': ctx.get('vehiculo_patente') or vehiculo.get('patente', '') or (
            cotizacion_existente.vehiculo_patente if cotizacion_existente else ''
        ),
        'vehiculo_vin': (
            (vehiculo.get('vin') or ctx.get('vehiculo_vin') or '').strip().upper()
            or (cotizacion_existente.vehiculo_vin if cotizacion_existente else '')
        )[:50],
        'vehiculo_cilindraje': cilindraje_efectivo(
            ctx.get('vehiculo_cilindraje') or vehiculo.get('cilindraje', ''),
            marca,
            modelo,
        ),
        'tipo_motor': (
            tipo_motor
            or contenido.get('tipo_motor')
            or ctx.get('tipo_motor', '')
            or (vehiculo.get('tipo_motor') or '')
        ),
        'tipo_motor_label': (
            contenido.get('tipo_motor_label')
            or ctx.get('tipo_motor_label', '')
            or (tipo_motor or vehiculo.get('tipo_motor') or '')
        ),
        'aviso_motor': contenido.get('aviso_motor') or ctx.get('aviso_motor', ''),
        'servicio_nombre': _titulo_servicios(lineas),
        'descripcion_problema': descripcion_final,
        'repuestos': repuestos,
        'mano_obra_clp': mano_obra,
        'costo_repuestos_clp': costo_rep,
        'total_clp': total,
        'duracion_minutos_estimada': contenido.get('duracion_minutos_estimada') or (
            cotizacion_existente.duracion_minutos_estimada if cotizacion_existente else None
        ),
        'advertencias': advertencias,
        'notas_internas': notas_finales,
        'contenido_ia': resultado.get('contenido_ia') or {},
        'metadata': metadata_cot,
        'tokens_entrada': (cotizacion_existente.tokens_entrada if cotizacion_existente else 0)
        + (resultado.get('tokens_entrada') or 0),
        'tokens_salida': (cotizacion_existente.tokens_salida if cotizacion_existente else 0)
        + (resultado.get('tokens_salida') or 0),
        'modelo_ia': resultado.get('modelo') or '',
    }

    if es_update and cotizacion_existente:
        for k, v in campos.items():
            setattr(cotizacion_existente, k, v)
        if reabierta:
            cotizacion_existente.estado = 'borrador'
        cotizacion_existente.save()
        cotizacion = cotizacion_existente
        logger.info(
            'Cotización borrador %s actualizada (servicios=%s, reabierta=%s) sesion=%s',
            cotizacion.id,
            [l.get('nombre') for l in lineas],
            reabierta,
            sesion.id,
        )
    else:
        cotizacion = CotizacionCanal.objects.create(
            conversation=conversation,
            es_libre=False,
            taller=taller,
            creado_por=proveedor,
            estado='borrador',
            **campos,
        )
        logger.info(
            'Cotización borrador %s creada (servicios=%s) sesion=%s',
            cotizacion.id,
            [l.get('nombre') for l in lineas],
            sesion.id,
        )

    sesion.cotizacion_borrador = cotizacion
    sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_REVISION
    # Persistimos preferencias también en la sesión para el agendamiento post-aceptación.
    datos_sesion = dict(sesion.datos_capturados or {})
    datos_sesion['servicios'] = [l.get('nombre') for l in lineas if l.get('nombre')]
    datos_sesion['servicio_nombre'] = cotizacion.servicio_nombre
    if preferencias_agenda:
        datos_sesion['preferencias_agenda'] = preferencias_agenda
    sesion.datos_capturados = datos_sesion
    sesion.save(update_fields=['cotizacion_borrador', 'estado', 'datos_capturados', 'actualizado_en'])

    if (cotizacion.metadata or {}).get('busqueda_web_estado') == 'pendiente':
        cotizacion = disparar_y_refrescar_cotizacion(cotizacion)

    notificar_cotizacion_borrador_agente(
        proveedor_user_id=proveedor_user_id,
        cotizacion=cotizacion,
        conversation_id=conversation.id,
        precio_desde_catalogo=bool(hay_algun_catalogo and not faltan_precios_catalogo),
        listo_para_enviar=listo_para_enviar,
        pendientes_revision=pendientes_revision,
        reabierta=reabierta,
    )
    return cotizacion


def crear_cotizacion_adicional_orden(
    *,
    cotizacion_original_id: int,
    taller_id: int,
    servicio_nombre: str,
    descripcion_problema: str = '',
    mano_obra_clp: int = 0,
    repuestos: list[dict] | None = None,
    creado_por_id: int | None = None,
) -> CotizacionCanal:
    """Crea una cotización secundaria/adicional para un trabajo en ejecución."""
    cot_orig = CotizacionCanal.objects.select_related('taller', 'conversation').get(pk=cotizacion_original_id)
    rep_list = repuestos or []
    costo_rep = sum(
        int(r.get('cantidad', 1) or 1) * int(r.get('precio_unitario_clp', 0) or 0)
        for r in rep_list
    )
    total_clp = int(mano_obra_clp or 0) + costo_rep

    meta = {
        'origen': 'cotizacion_adicional',
        'cotizacion_original_id': cot_orig.id,
        'es_cotizacion_adicional': True,
    }

    adicional = CotizacionCanal.objects.create(
        conversation=cot_orig.conversation,
        es_libre=cot_orig.es_libre,
        taller=cot_orig.taller,
        creado_por_id=creado_por_id,
        estado='borrador',
        modalidad=cot_orig.modalidad,
        direccion_servicio=cot_orig.direccion_servicio,
        vehiculo_marca=cot_orig.vehiculo_marca,
        vehiculo_modelo=cot_orig.vehiculo_modelo,
        vehiculo_anio=cot_orig.vehiculo_anio,
        vehiculo_patente=cot_orig.vehiculo_patente,
        vehiculo_cilindraje=cot_orig.vehiculo_cilindraje,
        vehiculo_vin=cot_orig.vehiculo_vin,
        tipo_motor=cot_orig.tipo_motor,
        tipo_motor_label=cot_orig.tipo_motor_label,
        servicio_nombre=servicio_nombre,
        descripcion_problema=descripcion_problema,
        repuestos=rep_list,
        mano_obra_clp=int(mano_obra_clp or 0),
        costo_repuestos_clp=costo_rep,
        total_clp=total_clp,
        metadata=meta,
    )
    logger.info('Cotización adicional %s creada para cotización original %s', adicional.id, cot_orig.id)
    return adicional


def procesar_ficha_sdr_spec(
    sesion: AgenteConversacionSesion,
    ficha: Any,
) -> CotizacionCanal | None:
    """Procesa una FichaLeadCapturada (Pydantic V2 Spec) y actualiza la sesión e historial."""
    from mecanimovilapp.apps.agente_ia.specs.agente_1_sdr_spec import FichaLeadCapturada

    if not isinstance(ficha, FichaLeadCapturada):
        return None

    datos = dict(sesion.datos_capturados or {})
    if ficha.vehiculo.marca:
        datos['vehiculo_marca'] = ficha.vehiculo.marca
    if ficha.vehiculo.modelo:
        datos['vehiculo_modelo'] = ficha.vehiculo.modelo
    if ficha.vehiculo.anio:
        datos['vehiculo_anio'] = ficha.vehiculo.anio
    if ficha.vehiculo.patente:
        datos['vehiculo_patente'] = ficha.vehiculo.patente
    if ficha.vehiculo.motor:
        datos['vehiculo_motor'] = ficha.vehiculo.motor
    if ficha.vehiculo.vin:
        datos['vehiculo_vin'] = ficha.vehiculo.vin

    if ficha.cliente.nombre:
        datos['cliente_nombre'] = ficha.cliente.nombre
    if ficha.cliente.telefono:
        datos['cliente_telefono'] = ficha.cliente.telefono
    if ficha.cliente.comuna:
        datos['cliente_comuna'] = ficha.cliente.comuna

    if ficha.sintomas_cliente:
        datos['sintomas_cliente'] = ficha.sintomas_cliente
    if ficha.servicios_solicitados:
        datos['servicios_solicitados'] = ficha.servicios_solicitados

    sesion.datos_capturados = datos
    sesion.save(update_fields=['datos_capturados', 'actualizado_en'])

    if ficha.listo_para_cotizar:
        return crear_cotizacion_borrador_desde_agente(
            sesion=sesion,
            datos_actualizados=datos,
            listo_para_cotizar=True,
        )

    return getattr(sesion, 'cotizacion_borrador', None)


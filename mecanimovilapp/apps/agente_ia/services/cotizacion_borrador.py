"""Generación / actualización de borrador de cotización desde el agente IA.

Reglas de producto:
- Una sola cotización editable por conversación (borrador o enviada; se edita, no se duplica).
- Si el cliente pide cambios tras un envío, la cotización enviada se reabre a borrador.
- Precios al cliente/taller: solo del catálogo publicado. Sin match → $0 +
  referencia IA solo en metadata/advertencias para que el humano revise y complete.
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
ADVERTENCIA_SIN_CATALOGO = (
    'Sin precio publicado en catálogo para este servicio/vehículo — '
    'completa el valor real antes de enviar (la referencia IA es solo orientación)'
)
ADVERTENCIA_DESDE_CATALOGO = 'Precio tomado del catálogo publicado del taller'
ADVERTENCIA_MULTI_SERVICIO = 'Cotización unificada: varios servicios del mismo vehículo en un solo borrador'
ADVERTENCIA_REABIERTA = (
    'Cliente pidió cambios después del envío — revisa y vuelve a enviar.'
)

# Estados editables por el agente (no terminales).
_ESTADOS_COTIZACION_EDITABLE = ('borrador', 'enviada')

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


def _parse_servicios_solicitados(datos: dict) -> list[str]:
    """Lista de servicios pedidos en este turno + previos."""
    nombres: list[str] = []
    raw_lista = datos.get('servicios') or datos.get('servicios_solicitados') or []
    if isinstance(raw_lista, list):
        for item in raw_lista:
            if isinstance(item, str) and item.strip():
                nombres.append(item.strip())
            elif isinstance(item, dict):
                n = (item.get('nombre') or item.get('servicio_nombre') or '').strip()
                if n:
                    nombres.append(n)
    uno = (datos.get('servicio_nombre') or '').strip()
    if uno:
        # Puede venir "A + B" o "A y B"
        if ' + ' in uno:
            nombres.extend(p.strip() for p in uno.split(' + ') if p.strip())
        else:
            nombres.append(uno)
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
    for lin in lineas or []:
        clave = _clave_servicio(lin.get('nombre') or '')
        if not clave:
            continue
        if clave not in por_clave:
            orden.append(clave)
        prev = por_clave.get(clave) or {}
        por_clave[clave] = {**prev, **lin}
    return [por_clave[k] for k in orden if k in por_clave]


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
        if _clave_servicio(lin.get('nombre') or '') == key:
            out[i] = {**lin, **nueva}
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
    ultimo_servicio_turno = servicios_turno[-1] if servicios_turno else ''

    # Generar contexto IA una vez con el resumen de servicios del turno (desglose/orientación).
    servicio_prompt = ' + '.join(servicios_turno)
    resultado = generar_cotizacion_ia(
        conversation=conversation,
        servicio_nombre=servicio_prompt,
        descripcion_problema=descripcion,
        modalidad=modalidad if modalidad in ('taller', 'domicilio') else 'taller',
        vehiculo=vehiculo,
        contexto_rag_extra=datos.get('contexto_rag') or '',
    )
    if not resultado.get('disponible'):
        logger.info('generar_cotizacion_ia no disponible: %s', resultado.get('error'))
        return None

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
        nombre_final = nombre_serv
        clave_serv = _clave_servicio(nombre_serv)
        con_repuestos = preferencias_repuestos.get(clave_serv, True)
        if oferta:
            precio_cat, _ = precio_publico_oferta(oferta, con_repuestos=con_repuestos)
            oferta_id = oferta.id
            nombre_final = oferta.servicio.nombre
            if precio_cat > 0:
                hay_algun_catalogo = True
                mano_obra_catalogo += precio_cat
            else:
                faltan_precios_catalogo = True
        else:
            faltan_precios_catalogo = True

        lineas = _merge_linea_servicio(
            lineas,
            {
                'nombre': nombre_final,
                'oferta_servicio_id': oferta_id,
                'precio_catalogo_clp': precio_cat or None,
                'precio_desde_catalogo': bool(precio_cat),
            },
        )

    lineas = _compactar_lineas_servicio(lineas)

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

    # Referencia IA: NUNCA como precio final del borrador; solo orientación al taller.
    ref_mano = int(contenido.get('mano_obra_clp') or 0)
    ref_reps = contenido.get('repuestos') or []
    if ref_mano or ref_reps:
        precios_ref_ia.append(
            {
                'servicios': servicios_turno,
                'mano_obra_clp': ref_mano,
                'repuestos': ref_reps,
                'nota': 'Estimación orientativa IA (NO publicada; el taller debe confirmar)',
                'generado_en': timezone.now().isoformat(),
            }
        )

    # Mano de obra manual: montos del taller para servicios sin catálogo (persistida en metadata).
    mano_obra_manual_prev = int(meta_prev.get('mano_obra_manual_clp', 0) or 0)
    if 'mano_obra_manual_clp' not in meta_prev and es_update and cotizacion_existente:
        catalogo_previo = sum(
            int(l.get('precio_catalogo_clp') or 0)
            for l in (meta_prev.get('servicios_lineas') or [])
            if l.get('precio_desde_catalogo')
        )
        recargo_previo = int(meta_prev.get('recargo_domicilio_aplicado_clp') or 0)
        mano_obra_manual_prev = max(
            0,
            int(cotizacion_existente.mano_obra_clp or 0) - catalogo_previo - recargo_previo,
        )

    mano_obra = mano_obra_catalogo + mano_obra_manual_prev
    repuestos: list = (
        list(cotizacion_existente.repuestos or [])
        if es_update and cotizacion_existente
        else []
    )

    advertencias: list[str] = []
    if hay_algun_catalogo and not faltan_precios_catalogo:
        advertencias.append(ADVERTENCIA_DESDE_CATALOGO)
    else:
        advertencias.append(ADVERTENCIA_SIN_CATALOGO)
        if ref_mano:
            advertencias.append(
                f'Referencia IA (solo orientación, no enviar así): mano de obra ~${ref_mano:,} CLP'.replace(
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

    patente_verificada = bool(
        (datos.get('patente_enriquecida') or '').strip()
        or datos.get('vehiculo_verificado')
        or datos.get('vehiculo_fuente') in ('registro_mecanimovil', 'getapi')
    )
    listo_para_enviar, pendientes_revision = evaluar_listo_para_enviar(
        lineas=lineas,
        modalidad=modalidad,
        direccion_servicio=str(datos.get('direccion_servicio') or (
            cotizacion_existente.direccion_servicio if cotizacion_existente else ''
        )),
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

    metadata_cot = {
        **meta_prev,
        'origen': 'agente_ia',
        'sesion_id': sesion.id,
        'mano_obra_manual_clp': mano_obra_manual_prev,
        'recargo_domicilio_aplicado_clp': recargo_aplicado,
        'precio_desde_catalogo': hay_algun_catalogo and not faltan_precios_catalogo,
        'precio_parcial_catalogo': hay_algun_catalogo and faltan_precios_catalogo,
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
    }

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

    desc_prev = (cotizacion_existente.descripcion_problema if cotizacion_existente else '') or ''
    descripcion_final = descripcion or desc_prev
    if descripcion and desc_prev and descripcion not in desc_prev:
        descripcion_final = f'{desc_prev}\n{descripcion}'.strip()

    campos = {
        'cliente_nombre': (cliente_nombre or (cotizacion_existente.cliente_nombre if cotizacion_existente else ''))[:200],
        'cliente_telefono': (cliente_telefono or (cotizacion_existente.cliente_telefono if cotizacion_existente else ''))[:20],
        'modalidad': modalidad,
        'direccion_servicio': str(datos.get('direccion_servicio') or (
            cotizacion_existente.direccion_servicio if cotizacion_existente else ''
        ))[:500],
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

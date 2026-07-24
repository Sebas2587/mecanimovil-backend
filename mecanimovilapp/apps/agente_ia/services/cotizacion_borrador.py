"""Generación / actualización de borrador de cotización desde el agente IA.

Reglas de producto:
- Una sola cotización en estado 'borrador' por conversación (se edita, no se duplica).
- Precios al cliente/taller: solo del catálogo publicado. Sin match → $0 +
  referencia IA solo en metadata/advertencias para que el humano revise y complete.
- El agente NUNCA envía la cotización al cliente; solo deja borrador.
"""
from __future__ import annotations

import logging
import unicodedata
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
from mecanimovilapp.apps.servicios.models import OfertaServicio
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


def _normalizar_nombre_servicio(texto: str) -> str:
    t = unicodedata.normalize('NFKD', (texto or '').strip().lower())
    return ''.join(c for c in t if not unicodedata.combining(c))


def _recargo_domicilio_taller(taller: Taller) -> int:
    config = TallerAgenteConfig.objects.filter(taller=taller).first()
    if config and config.recargo_domicilio_clp is not None:
        return max(0, int(config.recargo_domicilio_clp))
    return RECARGO_DOMICILIO_DEFAULT_CLP


def _buscar_oferta_exacta(
    *,
    taller: Taller,
    servicio_nombre: str,
    marca: str,
    modelo: str,
    tipo_motor: str = '',
) -> OfertaServicio | None:
    """Match determinístico taller + servicio + marca/modelo + motor."""
    nombre_norm = _normalizar_nombre_servicio(servicio_nombre)
    if not nombre_norm:
        return None

    qs = (
        OfertaServicio.objects.filter(taller=taller, disponible=True)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
    )

    candidatas: list[OfertaServicio] = []
    for oferta in qs:
        serv_norm = _normalizar_nombre_servicio(getattr(oferta.servicio, 'nombre', '') or '')
        if not serv_norm:
            continue
        if nombre_norm not in serv_norm and serv_norm not in nombre_norm:
            continue
        candidatas.append(oferta)

    if not candidatas:
        return None

    def _score(oferta: OfertaServicio) -> int:
        s = 0
        om = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or ''
        omod = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or ''
        if marca and om and om.lower() == marca.lower():
            s += 4
        elif not om:
            s += 1
        if modelo and omod and omod.lower() == modelo.lower():
            s += 4
        elif not omod:
            s += 1
        tm = (oferta.tipo_motor or '').strip().lower()
        tm_req = (tipo_motor or '').strip().lower()
        if tm_req and tm and tm == tm_req:
            s += 2
        elif not tm:
            s += 1
        serv_norm = _normalizar_nombre_servicio(oferta.servicio.nombre)
        if serv_norm == nombre_norm:
            s += 3
        if int(oferta.precio_con_repuestos or 0) or int(oferta.precio_sin_repuestos or 0):
            s += 2
        return s

    candidatas.sort(key=_score, reverse=True)
    mejor = candidatas[0]
    if _score(mejor) < 3:
        return None
    return mejor


def _precio_publico_oferta(oferta: OfertaServicio, *, con_repuestos: bool = True) -> tuple[int, bool]:
    """Devuelve (precio al público con IVA, usó_con_repuestos)."""
    if con_repuestos and int(oferta.precio_con_repuestos or 0):
        return int(oferta.precio_con_repuestos), True
    if int(oferta.precio_sin_repuestos or 0):
        return int(oferta.precio_sin_repuestos), False
    if int(oferta.precio_con_repuestos or 0):
        return int(oferta.precio_con_repuestos), True
    mano = int(oferta.costo_mano_de_obra_sin_iva or 0)
    rep = int(oferta.costo_repuestos_sin_iva or 0)
    if mano or rep:
        base = mano + (rep if con_repuestos else 0)
        return int(round(base * 1.19)), con_repuestos and rep > 0
    return 0, con_repuestos


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
        key = _normalizar_nombre_servicio(n)
        if key and key not in vistos:
            vistos.add(key)
            out.append(n)
    return out


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
    key = _normalizar_nombre_servicio(nueva.get('nombre') or '')
    if not key:
        return existentes
    out = list(existentes or [])
    for i, lin in enumerate(out):
        if _normalizar_nombre_servicio(lin.get('nombre') or '') == key:
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
    """Reutiliza el borrador abierto de la misma conversación/vehículo."""
    cot = getattr(sesion, 'cotizacion_borrador', None)
    if cot and cot.estado == 'borrador' and cot.taller_id == taller.id:
        return cot
    return (
        CotizacionCanal.objects.filter(
            conversation=conversation,
            taller=taller,
            estado='borrador',
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
    lineas: list[dict[str, Any]] = list(meta_prev.get('servicios_lineas') or [])
    precios_ref_ia: list[dict[str, Any]] = list(meta_prev.get('precios_referenciales_ia') or [])

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

    mano_obra_catalogo = 0
    hay_algun_catalogo = False
    faltan_precios_catalogo = False

    for nombre_serv in servicios_turno:
        oferta = _buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre_serv,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        precio_cat = 0
        oferta_id = None
        nombre_final = nombre_serv
        if oferta:
            precio_cat, _ = _precio_publico_oferta(oferta, con_repuestos=True)
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

    if hay_algun_catalogo and not faltan_precios_catalogo:
        mano_obra = mano_obra_catalogo
        repuestos: list = []
    elif hay_algun_catalogo and faltan_precios_catalogo:
        # Solo suma lo publicado; el resto queda en $0 hasta que el humano complete.
        mano_obra = mano_obra_catalogo
        repuestos = []
    else:
        # Sin catálogo: precio 0 — el humano completa en Cotizar con IA antes de enviar.
        mano_obra = 0
        repuestos = []

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

    if modalidad == 'domicilio' and mano_obra > 0:
        recargo = _recargo_domicilio_taller(taller)
        if recargo > 0:
            mano_obra += recargo
            advertencias.append(
                f'Incluye recargo a domicilio de ${recargo:,} CLP en mano de obra.'.replace(',', '.')
            )

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

    metadata_cot = {
        **meta_prev,
        'origen': 'agente_ia',
        'sesion_id': sesion.id,
        'precio_desde_catalogo': hay_algun_catalogo and not faltan_precios_catalogo,
        'precio_parcial_catalogo': hay_algun_catalogo and faltan_precios_catalogo,
        'servicios_lineas': lineas,
        'precios_referenciales_ia': precios_ref_ia[-5:],  # últimas 5 estimaciones
        'preferencias_agenda': preferencias_agenda,
        'requiere_revision_humana': True,
        'enviada_por_agente': False,
    }

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
        'tipo_motor': contenido.get('tipo_motor') or ctx.get('tipo_motor', '') or tipo_motor,
        'tipo_motor_label': contenido.get('tipo_motor_label') or ctx.get('tipo_motor_label', ''),
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
        cotizacion_existente.save()
        cotizacion = cotizacion_existente
        logger.info(
            'Cotización borrador %s actualizada (servicios=%s) sesion=%s',
            cotizacion.id,
            [l.get('nombre') for l in lineas],
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
    )
    return cotizacion

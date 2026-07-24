"""Generación de borrador de cotización desde el agente IA."""
from __future__ import annotations

import logging
import unicodedata

from django.contrib.auth import get_user_model

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
    'Precio referencial sin catálogo del taller — verifica antes de enviar'
)
ADVERTENCIA_DESDE_CATALOGO = 'Precio tomado del catálogo publicado del taller'


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


def _descripcion_muy_generica(descripcion: str, servicio_nombre: str) -> bool:
    texto = f'{servicio_nombre} {descripcion}'.strip().lower()
    if len(texto) < 18:
        return True
    genericos = (
        'revisar',
        'revisión',
        'revision',
        'problema',
        'falla',
        'ruido',
        'servicio',
        'mantención',
        'mantencion',
        'arreglar',
        'cotizar',
        'presupuesto',
        'diagnostico',
        'diagnóstico',
    )
    palabras = [p for p in texto.replace(',', ' ').split() if len(p) > 2]
    if not palabras:
        return True
    return all(any(g in p for g in genericos) for p in palabras[:4])


def crear_cotizacion_borrador_desde_agente(
    *,
    sesion: AgenteConversacionSesion,
    conversation: Conversation,
    taller: Taller,
    proveedor_user_id: int,
    datos: dict,
) -> CotizacionCanal | None:
    """Genera CotizacionCanal borrador usando el generador IA existente."""
    proveedor = User.objects.filter(pk=proveedor_user_id).first()
    if not proveedor:
        logger.warning('Proveedor %s no encontrado para cotización agente', proveedor_user_id)
        return None

    try:
        verificar_y_consumir_cuota(proveedor, ConsumoFeatureMensual.FEATURE_COTIZACION_IA)
    except (CuotaAgotadaError, SinSuscripcionError) as exc:
        logger.info('Cuota cotización IA agotada para agente: %s', exc.message)
        return None

    vehiculo = datos.get('vehiculo') or {}
    servicio_nombre = (datos.get('servicio_nombre') or '').strip()
    descripcion = (datos.get('descripcion_problema') or datos.get('sintoma') or '').strip()
    modalidad = datos.get('modalidad') or 'taller'
    marca = (vehiculo.get('marca') or '').strip()
    modelo = (vehiculo.get('modelo') or '').strip()
    tipo_motor = (vehiculo.get('tipo_motor') or '').strip()

    oferta_exacta = _buscar_oferta_exacta(
        taller=taller,
        servicio_nombre=servicio_nombre,
        marca=marca,
        modelo=modelo,
        tipo_motor=tipo_motor,
    )
    precio_catalogo: int | None = None
    servicio_catalogo_nombre = servicio_nombre
    if oferta_exacta:
        precio_catalogo, _ = _precio_publico_oferta(oferta_exacta, con_repuestos=True)
        servicio_catalogo_nombre = oferta_exacta.servicio.nombre

    # El LLM aporta desglose/duración; el precio lo fija el catálogo si hay match.
    resultado = generar_cotizacion_ia(
        conversation=conversation,
        servicio_nombre=servicio_catalogo_nombre or servicio_nombre,
        descripcion_problema=descripcion,
        modalidad='taller',
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

    marca = ctx.get('vehiculo_marca') or vehiculo.get('marca', '')
    modelo = ctx.get('vehiculo_modelo') or vehiculo.get('modelo', '')

    contact = conversation.external_contact
    cliente_nombre = (datos.get('cliente_nombre') or '').strip()
    cliente_telefono = (datos.get('cliente_telefono') or '').strip()
    if contact:
        cliente_nombre = cliente_nombre or (contact.display_name or '')
        cliente_telefono = cliente_telefono or (contact.phone or '')

    if precio_catalogo and precio_catalogo > 0:
        mano_obra = precio_catalogo
        repuestos = []
    else:
        mano_obra = int(contenido.get('mano_obra_clp') or 0)
        repuestos = contenido.get('repuestos') or []

    advertencias = list(contenido.get('advertencias') or [])

    if modalidad == 'domicilio':
        recargo = _recargo_domicilio_taller(taller)
        if recargo > 0:
            mano_obra += recargo
            advertencias.append(
                f'Incluye recargo a domicilio de ${recargo:,} CLP en mano de obra.'.replace(',', '.')
            )

    if oferta_exacta and precio_catalogo:
        if ADVERTENCIA_DESDE_CATALOGO not in advertencias:
            advertencias.append(ADVERTENCIA_DESDE_CATALOGO)
    else:
        if ADVERTENCIA_SIN_CATALOGO not in advertencias:
            advertencias.append(ADVERTENCIA_SIN_CATALOGO)

    costo_rep, mano_obra, total = recalcular_totales(repuestos, mano_obra)

    metadata_cot = {
        'origen': 'agente_ia',
        'sesion_id': sesion.id,
        'precio_desde_catalogo': bool(oferta_exacta and precio_catalogo),
        'oferta_servicio_id': oferta_exacta.id if oferta_exacta else None,
    }

    cotizacion = CotizacionCanal.objects.create(
        conversation=conversation,
        es_libre=False,
        cliente_nombre=cliente_nombre[:200],
        cliente_telefono=cliente_telefono[:20],
        taller=taller,
        creado_por=proveedor,
        estado='borrador',
        modalidad=modalidad,
        direccion_servicio=str(datos.get('direccion_servicio') or '')[:500],
        vehiculo_marca=marca,
        vehiculo_modelo=modelo,
        vehiculo_anio=anio_int,
        vehiculo_patente=ctx.get('vehiculo_patente') or vehiculo.get('patente', ''),
        vehiculo_cilindraje=cilindraje_efectivo(
            ctx.get('vehiculo_cilindraje') or vehiculo.get('cilindraje', ''),
            marca,
            modelo,
        ),
        tipo_motor=contenido.get('tipo_motor') or ctx.get('tipo_motor', '') or tipo_motor,
        tipo_motor_label=contenido.get('tipo_motor_label') or ctx.get('tipo_motor_label', ''),
        aviso_motor=contenido.get('aviso_motor') or ctx.get('aviso_motor', ''),
        servicio_nombre=contenido.get('servicio_nombre') or servicio_catalogo_nombre or servicio_nombre,
        descripcion_problema=contenido.get('descripcion_problema') or descripcion,
        repuestos=repuestos,
        mano_obra_clp=mano_obra,
        costo_repuestos_clp=costo_rep,
        total_clp=total,
        duracion_minutos_estimada=contenido.get('duracion_minutos_estimada'),
        advertencias=advertencias,
        contenido_ia=resultado.get('contenido_ia') or {},
        metadata=metadata_cot,
        tokens_entrada=resultado.get('tokens_entrada') or 0,
        tokens_salida=resultado.get('tokens_salida') or 0,
        modelo_ia=resultado.get('modelo') or '',
    )

    sesion.cotizacion_borrador = cotizacion
    sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_REVISION
    sesion.save(update_fields=['cotizacion_borrador', 'estado', 'actualizado_en'])

    notificar_cotizacion_borrador_agente(
        proveedor_user_id=proveedor_user_id,
        cotizacion=cotizacion,
        conversation_id=conversation.id,
        precio_desde_catalogo=bool(oferta_exacta and precio_catalogo),
    )
    return cotizacion

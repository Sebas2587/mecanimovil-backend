"""Ficha operativa determinística del taller para el Agente IA.

A diferencia del RAG (búsqueda semántica sobre catálogo/historial/documentos,
que puede o no traer el dato correcto según la query), esta ficha se calcula
en vivo desde la base de datos en CADA turno con un puñado de queries baratas
y siempre indexadas (taller_id / activo). Por eso no hace falta cachearla ni
mantener un proceso aparte "escuchando" cambios de configuración: cualquier
edición del taller (servicios, equipo, horarios, cobertura) se refleja de
inmediato en el próximo mensaje, sin desfases de sincronización.

Esto cubre lo que el RAG no garantiza: modalidad de atención real, cobertura
de marcas (especialista/multimarca), catálogo completo de servicios vigentes,
equipo de mecánicos y su modalidad, y horario general del taller.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from mecanimovilapp.apps.usuarios.models import HorarioProveedor, MiembroTaller, Taller

_DIAS_ES = {
    0: 'lun',
    1: 'mar',
    2: 'mié',
    3: 'jue',
    4: 'vie',
    5: 'sáb',
    6: 'dom',
}

_DIAS_ES_LARGO = {
    0: 'Lunes',
    1: 'Martes',
    2: 'Miércoles',
    3: 'Jueves',
    4: 'Viernes',
    5: 'Sábado',
    6: 'Domingo',
}


def _formatear_clp(valor) -> str:
    return f'${int(valor or 0):,}'.replace(',', '.')


def _formatear_fecha_corta(f: date) -> str:
    return f'{_DIAS_ES.get(f.weekday(), "")} {f.day}/{f.month:02d}'


def _proxima_fecha_para_dia_semana(dia_semana: int, *, desde: date | None = None) -> date:
    """Próxima ocurrencia calendario del día de semana (0=lunes … 6=domingo)."""
    hoy = desde or timezone.localdate()
    delta = (dia_semana - hoy.weekday()) % 7
    if delta == 0:
        return hoy
    return hoy + timedelta(days=delta)


def _taller_abierto_ahora(taller: Taller) -> bool:
    ahora = timezone.localtime()
    dia = ahora.weekday()
    hora = ahora.time()
    horarios = HorarioProveedor.objects.filter(
        taller=taller,
        miembro_taller__isnull=True,
        activo=True,
        dia_semana=dia,
    )
    return any(h.hora_inicio <= hora <= h.hora_fin for h in horarios)


def _bloque_fecha_actual(taller: Taller) -> str:
    ahora = timezone.localtime()
    hoy = ahora.date()
    dia_nombre = _DIAS_ES_LARGO.get(hoy.weekday(), '')
    estado = 'ABIERTO ahora' if _taller_abierto_ahora(taller) else 'CERRADO ahora (fuera de horario)'
    return (
        f'Fecha y hora actual en Chile: {dia_nombre} {hoy.strftime("%d/%m/%Y")} '
        f'{ahora.strftime("%H:%M")}. El taller está {estado}. '
        f'Usa esta fecha para razonar "hoy", "mañana" y próximos días de agenda.'
    )


def _bloque_modalidad(taller: Taller) -> str:
    modalidad = taller.modalidad_atencion
    partes = [f'Modalidad de atención del taller: {taller.get_modalidad_atencion_display()}.']

    if modalidad == 'a_domicilio':
        partes.append(
            'IMPORTANTE: este taller SOLO atiende a domicilio. NO tiene local/sucursal física a la que '
            'el cliente pueda llevar el vehículo. PROHIBIDO ofrecer, sugerir o inventar una dirección de '
            'taller/sucursal, o decir que "para casos complejos hay que llevarlo al taller". Si el cliente '
            'pregunta por una dirección física, responde breve y de forma natural que trabajan a domicilio '
            '(sin sonar a texto legal ni repetir esta frase palabra por palabra). NO pidas la dirección del '
            'cliente en esa misma respuesta si todavía no sabes qué le pasa al auto: sigue con UNA sola '
            'pregunta sobre el síntoma/servicio primero. La dirección del cliente se pide más adelante, '
            'cuando ya haya síntoma/patente y toque coordinar la visita.'
        )
        return '\n'.join(partes)

    direccion = getattr(taller, 'direccion_fisica', None)
    if direccion is not None:
        calle = (direccion.calle or '').strip()
        numero = (direccion.numero or '').strip()
        comuna = (direccion.comuna or '').strip()
        ciudad = (direccion.ciudad or '').strip()
        detalle = (direccion.detalles_adicionales or '').strip()
        linea_direccion = ', '.join(
            filter(None, [f'{calle} {numero}'.strip(), comuna, ciudad])
        )
        if linea_direccion:
            partes.append(
                f'Dirección física EXACTA y verificada del taller (única fuente válida, cópiala tal cual): '
                f'{linea_direccion}.' + (f' Referencia adicional: {detalle}.' if detalle else '')
            )
    else:
        partes.append(
            'No hay una dirección física registrada en el sistema para este taller. '
            'PROHIBIDO inventar calle, número o comuna. Si el cliente pide la dirección exacta y no la '
            'tienes aquí, dile que te confirman la ubicación exacta al coordinar la visita (o deriva a '
            'humano si insiste), pero nunca inventes datos.'
        )

    if modalidad == 'ambas':
        partes.append(
            'Este taller también atiende a domicilio cuando corresponde: si el cliente lo prefiere, '
            'puedes ofrecer esa opción y pedir su dirección (del cliente), sin inventar nada.'
        )

    return '\n'.join(partes)


def _bloque_cobertura_marcas(taller: Taller) -> str:
    """Estrategia de captura de leads: NUNCA espantar por marca fuera de especialidad."""
    if taller.tipo_cobertura_marca == 'multimarca':
        return (
            'Cobertura de marcas: MULTIMARCA — atienden cualquier marca. '
            'Trata todas las marcas con la misma confianza comercial.'
        )
    marcas = list(taller.marcas_atendidas.values_list('nombre', flat=True))
    if marcas:
        return (
            f'Cobertura de marcas: ESPECIALISTA destacado en {", ".join(marcas)}. '
            'Si el vehículo ES de esas marcas, resalta con naturalidad la especialidad '
            '(experiencia, catálogo, confianza). '
            'Si el vehículo NO es de esas marcas: NO digas que no lo atienden ni cierres el lead. '
            'Acepta el requerimiento con normalidad ("igual podemos revisar tu caso"), '
            'sigue el flujo de patente → diagnóstico → cotización. '
            'El humano del taller decide al revisar/enviar la cotización.'
        )
    return (
        'Cobertura de marcas: el taller aún no configuró marcas específicas. '
        'Atiende el lead con normalidad sin rechazar por marca.'
    )


def _especialidades_desde_catalogo(taller: Taller) -> list[str]:
    """Categorías de servicio presentes en ofertas publicadas (fallback/refuerzo)."""
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    nombres = (
        OfertaServicio.objects.filter(taller=taller, disponible=True)
        .values_list('servicio__categorias__nombre', flat=True)
        .distinct()
    )
    return sorted({n for n in nombres if n})


def _bloque_especialidades(taller: Taller) -> str | None:
    especialidades = list(taller.especialidades.values_list('nombre', flat=True))
    desde_catalogo = _especialidades_desde_catalogo(taller)
    # Unión preservando orden: primero las configuradas en el perfil del taller.
    vistos: set[str] = set()
    unidas: list[str] = []
    for n in especialidades + desde_catalogo:
        key = n.strip().lower()
        if key and key not in vistos:
            vistos.add(key)
            unidas.append(n.strip())
    if not unidas:
        return None
    return (
        f'Especialidades / categorías de servicio del taller: {", ".join(unidas)}. '
        'Estas categorías definen QUÉ TIPO de trabajo puede ofrecer el taller '
        '(ej. si solo hay Diagnóstico mecánico, NO ofrezcas Diagnóstico electrónico). '
        'Antes de concluir que algo está fuera de especialidad: (1) pregunta y junta '
        'síntomas concretos del auto (sin especular), (2) orienta con lo que sí cubren, '
        '(3) si el caso queda fuera, explícalo con sutileza y no armes cotización de ese servicio. '
        'Esto es independiente de la cobertura de MARCAS: una marca fuera de lista se cotiza; '
        'una categoría de servicio fuera de especialidad no se ofrece.'
    )


def _bloque_equipo(taller: Taller) -> str:
    miembros = list(
        MiembroTaller.objects.filter(taller=taller, rol='mecanico', activo=True)
        .prefetch_related('especialidades')
    )
    if not miembros:
        return (
            'Equipo: el taller no tiene mecánicos de equipo cargados en el sistema; '
            'la atención depende directamente del taller. '
            'Para agenda usa el horario general del taller.'
        )
    lineas = [
        'Equipo de mecánicos activos '
        '(especialidades por técnico + modalidad; útil para asignar y para domicilio real):'
    ]
    hay_domicilio = False
    for m in miembros:
        especialidades_m = ', '.join(m.especialidades.values_list('nombre', flat=True)) or 'general'
        modalidad_m = m.get_modalidad_tecnico_display()
        if m.modalidad_tecnico in ('a_domicilio', 'ambas'):
            hay_domicilio = True
        lineas.append(
            f'- {m.nombre}: especialidades [{especialidades_m}]; modalidad {modalidad_m}.'
        )
    if hay_domicilio:
        lineas.append(
            'SÍ hay al menos un mecánico que atiende a domicilio: '
            'si el cliente pide domicilio y la FICHA lo permite, captura la dirección '
            'y deja modalidad=domicilio.'
        )
    else:
        lineas.append(
            'Ningún mecánico del equipo tiene modalidad a domicilio; '
            'si el cliente pide domicilio y la modalidad del taller no lo cubre, '
            'explica con amabilidad que la atención es en taller.'
        )
    return '\n'.join(lineas)


def _formatear_horario_con_proxima_fecha(horario: HorarioProveedor) -> str:
    prox = _proxima_fecha_para_dia_semana(horario.dia_semana)
    dia = horario.get_dia_semana_display()
    rango = f'{horario.hora_inicio.strftime("%H:%M")}-{horario.hora_fin.strftime("%H:%M")}'
    return f'{dia} {rango} (próxima fecha: {_formatear_fecha_corta(prox)})'


def _bloque_horarios(taller: Taller) -> str:
    horarios = list(
        HorarioProveedor.objects.filter(taller=taller, miembro_taller__isnull=True, activo=True)
        .order_by('dia_semana')
    )
    if not horarios:
        return 'Horario general del taller: no configurado todavía.'
    dias = ', '.join(_formatear_horario_con_proxima_fecha(h) for h in horarios)
    return (
        f'Horario general del taller: {dias}. '
        'Si el cliente escribe fuera de este horario, igual puedes asesorar y cotizar; '
        'solo al agendar una cita la fecha/hora debe caer dentro de estos rangos.'
    )


def _bloque_horarios_mecanicos(taller: Taller) -> str | None:
    miembros = list(
        MiembroTaller.objects.filter(taller=taller, rol='mecanico', activo=True)
    )
    if not miembros:
        return None

    lineas = [
        'Horarios por mecánico (usa esto si un técnico atiende solo ciertos días; '
        'NO confundas "miércoles" con mañana si hoy no es martes):'
    ]
    hay_propios = False
    for m in miembros:
        horarios = list(
            HorarioProveedor.objects.filter(miembro_taller=m, activo=True).order_by('dia_semana')
        )
        if not horarios:
            continue
        hay_propios = True
        partes = ', '.join(_formatear_horario_con_proxima_fecha(h) for h in horarios)
        lineas.append(f'- {m.nombre}: {partes}')

    if not hay_propios:
        return None
    return '\n'.join(lineas)


def _etiqueta_tipo_motor(tipo_motor: str) -> str:
    tm = (tipo_motor or '').strip().lower()
    if not tm:
        return 'todos los motores'
    mapping = {
        'bencina': 'bencina/gasolina',
        'gasolina': 'bencina/gasolina',
        'diesel': 'diésel',
        'electrico': 'eléctrico',
        'hibrido': 'híbrido',
    }
    return mapping.get(tm, tm)


def _bloque_catalogo(
    taller: Taller,
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
) -> str:
    from mecanimovilapp.apps.ordenes.services.catalogo_pricing import oferta_compatible_con_vehiculo
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    ofertas = list(
        OfertaServicio.objects.filter(taller=taller, disponible=True)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
        .prefetch_related('servicio__categorias')
        .order_by('servicio__nombre')[:80]
    )
    if not ofertas:
        return 'Catálogo: el taller no tiene servicios publicados todavía en el sistema.'

    marca_v = (marca_vehiculo or '').strip()
    modelo_v = (modelo_vehiculo or '').strip()
    vehiculo_conocido = bool(marca_v or modelo_v)

    lineas = [
        'Catálogo de servicios publicados por el taller '
        '(si el cliente pregunta qué ofrecen, puedes citar estos nombres; '
        'para el JSON "servicios" usa nombres cortos del pedido del cliente '
        '(ej. "Cambio de aceite y filtro"), NO copies sufijos de motor del SKU '
        'como "Gasolina"/"Diesel" — eso no es filtro de combustible; '
        'NO inventes servicios ni precios que no estén en esta lista; '
        'precios al público incluyen IVA 19%). '
        'CRÍTICO sobre cobertura: un precio SOLO aplica al vehículo del cliente si la '
        'cobertura es "todas las marcas/modelos" O coincide con la marca/modelo del auto. '
        'PROHIBIDO citar el precio de otra marca/modelo (ej. precio Toyota para un Honda).'
    ]
    if vehiculo_conocido:
        veh_txt = ' '.join(p for p in (marca_v, modelo_v) if p)
        lineas.append(
            f'Vehículo del cliente en este turno: {veh_txt}. '
            'Los ítems marcados [APLICA A ESTE AUTO] son los únicos cuyos precios puedes citar. '
            'Los marcados [OTRA COBERTURA — NO CITAR PRECIO] solo indican que el taller '
            'ofrece ese servicio para OTRA marca/modelo; di que el valor para ESTE auto '
            'lo confirma el taller en la cotización.'
        )

    aplican = 0
    for oferta in ofertas:
        marca = oferta.marca_vehiculo_seleccionada.nombre if oferta.marca_vehiculo_seleccionada_id else None
        modelo = oferta.modelo_vehiculo_seleccionado.nombre if oferta.modelo_vehiculo_seleccionado_id else None
        if marca and modelo:
            cobertura_txt = f'{marca} · {modelo}'
        elif marca:
            cobertura_txt = f'{marca} (todos los modelos)'
        else:
            cobertura_txt = 'todas las marcas/modelos'

        cats = list(oferta.servicio.categorias.values_list('nombre', flat=True))
        cats_txt = f'categoría {", ".join(cats)}' if cats else 'sin categoría'

        motor_txt = _etiqueta_tipo_motor(oferta.tipo_motor)
        precio_con = int(oferta.precio_con_repuestos or 0)
        precio_sin = int(oferta.precio_sin_repuestos or 0)
        mano_obra = int(oferta.costo_mano_de_obra_sin_iva or 0)
        repuestos = int(oferta.costo_repuestos_sin_iva or 0)

        compatible = (
            oferta_compatible_con_vehiculo(
                oferta,
                marca=marca_v,
                modelo=modelo_v,
            )
            if vehiculo_conocido
            else True
        )

        if vehiculo_conocido and not compatible:
            # Muestra el servicio sin precio para no sesgar al modelo.
            lineas.append(
                f'- {oferta.servicio.nombre} · {cats_txt} · {cobertura_txt} · '
                f'motor {motor_txt} · [OTRA COBERTURA — NO CITAR PRECIO]'
            )
            continue

        precios_partes: list[str] = []
        if precio_con:
            precios_partes.append(f'con repuestos {_formatear_clp(precio_con)} (IVA incl.)')
        if precio_sin:
            precios_partes.append(f'sin repuestos {_formatear_clp(precio_sin)} (IVA incl.)')
        if mano_obra:
            precios_partes.append(f'mano de obra sin IVA {_formatear_clp(mano_obra)}')
        if repuestos:
            precios_partes.append(f'repuestos sin IVA {_formatear_clp(repuestos)}')
        precios_txt = ' · '.join(precios_partes) if precios_partes else 'precio no configurado'
        from mecanimovilapp.apps.agente_ia.services.catalogo_oferta_texto import (
            resumen_repuestos_garantia_oferta,
        )

        extra_rep_gar = resumen_repuestos_garantia_oferta(oferta)
        if extra_rep_gar:
            precios_txt = f'{precios_txt} · {extra_rep_gar}'
        tag = ' · [APLICA A ESTE AUTO]' if vehiculo_conocido else ''
        lineas.append(
            f'- {oferta.servicio.nombre} · {cats_txt} · {cobertura_txt} · '
            f'motor {motor_txt} · {precios_txt}{tag}'
        )
        aplican += 1

    if vehiculo_conocido and aplican == 0:
        lineas.append(
            'Ninguna tarifa publicada aplica a este vehículo concreto. '
            'Trata cualquier precio de otra cobertura como inexistente para este auto.'
        )

    return '\n'.join(lineas)


def _bloque_historial_precios(
    taller: Taller,
    *,
    servicios: list[str],
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    tipo_motor: str = '',
    permite_estimados: bool = True,
) -> str:
    """Referencia histórica solo cuando el catálogo no tiene tarifa para ese servicio."""
    from mecanimovilapp.apps.agente_ia.services.historial_pricing import (
        estimados_historicos_para_datos,
        formatear_bloque_historial_precios,
    )

    if not servicios or not permite_estimados:
        return ''
    estimados = estimados_historicos_para_datos(
        taller=taller,
        servicios=servicios,
        marca=marca_vehiculo,
        modelo=modelo_vehiculo,
        tipo_motor=tipo_motor,
        permite_estimados=permite_estimados,
    )
    return formatear_bloque_historial_precios(estimados)


def construir_ficha_operativa_taller(
    taller: Taller,
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    servicios_consulta: list[str] | None = None,
    tipo_motor: str = '',
    permite_estimados_historicos: bool = True,
) -> str:
    """Bloque determinístico con la verdad operativa del taller para el prompt del agente.

    Se recalcula en cada turno (no se cachea): las queries son baratas e
    indexadas por taller_id/activo, así que cualquier cambio de configuración
    del taller se refleja de inmediato sin depender de un proceso de
    sincronización aparte.

    Si se conoce marca/modelo del vehículo del cliente, el catálogo marca qué
    precios aplican a ese auto y oculta montos de otras coberturas.
    """
    nombre = (taller.nombre or '').strip() or f'Taller #{taller.id}'
    bloques = [
        f'Nombre comercial del taller: {nombre}',
        _bloque_fecha_actual(taller),
        _bloque_modalidad(taller),
        _bloque_cobertura_marcas(taller),
        _bloque_especialidades(taller),
        _bloque_equipo(taller),
        _bloque_horarios(taller),
        _bloque_horarios_mecanicos(taller),
        _bloque_catalogo(
            taller,
            marca_vehiculo=marca_vehiculo,
            modelo_vehiculo=modelo_vehiculo,
        ),
    ]
    bloque_hist = _bloque_historial_precios(
        taller,
        servicios=list(servicios_consulta or []),
        marca_vehiculo=marca_vehiculo,
        modelo_vehiculo=modelo_vehiculo,
        tipo_motor=tipo_motor,
        permite_estimados=permite_estimados_historicos,
    )
    if bloque_hist:
        bloques.append(bloque_hist)
    return '\n\n'.join(b for b in bloques if b)

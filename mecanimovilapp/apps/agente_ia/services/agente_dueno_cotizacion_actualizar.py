"""Suma piezas o trabajos a la cotización que ya está en el hilo, con la misma regla que Cotizar."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_AGREGAR = re.compile(
    r'\b(agrega|agregar|agregale|agreguele|suma|sumale|sumar|anade|anadir|'
    r'incluye|incluir|tambien|ponle|mete|meter)\b',
)
_QUITAR = re.compile(r'\b(quita|quitar|saca|sacar|elimina|eliminar|borra|borrar)\b')
_PIEZA = re.compile(
    r'\b(aceite|filtro|kit|pastilla|pastillas|bomba|bombin|reten|ruleman|rodamiento|'
    r'bujia|correa|liquido|refrigerante|repuesto|pieza|disco|amortiguador|bateria|'
    r'soporte|embrague|clutch|balata)\b',
)


def pide_sumar(texto: str) -> bool:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    return bool(_AGREGAR.search(plano(texto)))


def pide_quitar(texto: str) -> bool:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    return bool(_QUITAR.search(plano(texto)))


def documento_del_hilo(taller, hilo):
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    pendiente = hilo.accion_pendiente if isinstance(hilo.accion_pendiente, dict) else {}
    cid = pendiente.get('cotizacion_id')
    if not cid and isinstance(getattr(hilo, 'caso_anclado', None), dict):
        cid = hilo.caso_anclado.get('cotizacion_id') or hilo.caso_anclado.get('documento_id')
    if not cid:
        return None
    return CotizacionCanal.objects.filter(taller=taller, id=cid).exclude(
        estado__in=('cancelada', 'rechazada', 'expirada'),
    ).first()


def aplicar_cambio(taller, user, cotizacion, texto: str, slots: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    if pide_quitar(texto):
        return _quitar(cotizacion, texto, slots)
    items = _items(texto)
    if not items:
        return _respuesta(
            cotizacion,
            slots,
            'Dime qué agrego: una pieza o un trabajo.',
            haciendo='Espero el ítem',
            pasos=[{'texto': 'Estoy en el borrador abierto', 'estado': 'ahora'}],
            siguiente='Nombra la pieza o el trabajo que hay que sumar.',
        )
    trabajos = [item for item in items if item['tipo'] == 'mano_obra']
    piezas = [item for item in items if item['tipo'] == 'repuesto']
    try:
        destino, nota_destino = _destino(taller, user, cotizacion, texto, trabajos, piezas)
    except ValueError as exc:
        return _respuesta(
            cotizacion,
            slots,
            str(exc),
            haciendo='Reviso si se puede editar',
            pasos=[{'texto': 'Esta cotización ya no se edita directo', 'estado': 'ahora'}],
            siguiente='Abre la visita y crea el trabajo adicional desde ahí, o dime el hallazgo de nuevo.',
        )
    buscando = False
    if piezas and destino.estado == 'borrador':
        buscando = _sumar_piezas(destino, [item['nombre'] for item in piezas])
    if trabajos and destino.estado == 'borrador':
        _sumar_trabajos(taller, destino, trabajos)
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import (
        _filas_desglose,
        _guardar_listo,
        _pendientes_precio,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        aplicar_totales_cotizacion,
    )

    aplicar_totales_cotizacion(destino)
    _guardar_listo(destino, _pendientes_precio(destino))
    destino.save()
    pasos = _pasos_suma(cotizacion, destino, piezas, trabajos, nota_destino, buscando)
    siguiente = _siguiente(destino, buscando, nota_destino)
    return _respuesta(
        destino,
        slots,
        _resumen_suma(destino, piezas, trabajos, nota_destino, buscando),
        haciendo='Actualizo la cotización',
        filas=_filas_desglose(destino, buscando),
        pasos=pasos,
        siguiente=siguiente,
        buscando=buscando,
    )


def _destino(taller, user, cotizacion, texto: str, trabajos: list[dict], piezas: list[dict]):
    from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
        asegurar_cotizacion_editable_para_items,
        cita_activa_de_cotizacion,
    )

    if cotizacion.estado == 'borrador':
        return cotizacion, ''
    if cotizacion.estado == 'enviada':
        abierta = asegurar_cotizacion_editable_para_items(cotizacion)
        return abierta, 'La reabrí: el cliente deja de ver la versión enviada hasta que la mandes de nuevo.'
    if cotizacion.estado == 'aceptada':
        return _adicional(taller, user, cotizacion, texto, trabajos, piezas)
    raise ValueError('Esa cotización ya no se puede modificar.')


def _adicional(taller, user, cotizacion, texto: str, trabajos: list[dict], piezas: list[dict]):
    from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
        adicional_pendiente_de_cita,
        crear_cotizacion_adicional_con_ia,
    )
    from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
        asegurar_cotizacion_editable_para_items,
        cita_activa_de_cotizacion,
    )

    cita = cita_activa_de_cotizacion(cotizacion) or cotizacion.cita_origen
    if cita is None:
        raise ValueError(
            'Esa cotización ya fue aceptada. El trabajo nuevo va en un adicional, '
            'y esta visita todavía no está en la agenda.'
        )
    pendiente = adicional_pendiente_de_cita(cita)
    if pendiente is not None:
        if pendiente.estado == 'enviada':
            pendiente = asegurar_cotizacion_editable_para_items(pendiente)
        return pendiente, 'Ya había un trabajo adicional abierto. Lo sumé ahí.'
    servicio = trabajos[0]['nombre'] if trabajos else (piezas[0]['nombre'] if piezas else 'Trabajo adicional')
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    ejecucion = 'nueva_fecha' if re.search(r'otra fecha|otro dia|manana|proxima visita', plano(texto)) else 'misma_visita'
    creado = crear_cotizacion_adicional_con_ia(
        cotizacion_original=cotizacion,
        cita=cita,
        taller=taller,
        creado_por=user,
        motivo_servicio_adicional=texto.strip()[:500],
        servicio_nombre=servicio,
        descripcion_problema=texto.strip()[:500],
        ejecucion_adicional=ejecucion,
    )
    meta = dict(creado.metadata or {})
    meta['origen_chat_dueno'] = True
    creado.metadata = meta
    creado.save(update_fields=['metadata', 'actualizado_en'])
    cuando = 'en otra fecha' if ejecucion == 'nueva_fecha' else 'en la misma visita'
    return creado, f'El servicio principal ya está aceptado. Abrí un trabajo adicional {cuando}.'


def _sumar_piezas(cotizacion, nombres: list[str]) -> bool:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes import (
        cotizar_items_faltantes,
    )

    try:
        resultado = cotizar_items_faltantes(cotizacion, nombres=nombres)
    except ValueError:
        return False
    return bool(resultado.get('busqueda_web'))


def _sumar_trabajos(taller, cotizacion, trabajos: list[dict]) -> None:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import generar_cotizacion_ia
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        persistir_mano_obra_lineas,
        resolver_mano_obra_lineas,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes import (
        _ya_existe,
    )

    lineas = resolver_mano_obra_lineas(cotizacion)
    nombres_piezas = []
    for trabajo in trabajos:
        contenido = _cotizar_trabajo(generar_cotizacion_ia, taller, cotizacion, trabajo['nombre'])
        monto = trabajo['precio'] if trabajo.get('precio') else int((contenido or {}).get('mano_obra_clp') or 0)
        if not any(_mismo(linea.get('nombre'), trabajo['nombre']) for linea in lineas):
            lineas.append({
                'id': f"mo-{len(lineas) + 1}",
                'nombre': trabajo['nombre'][:200],
                'monto_clp': monto,
            })
        for rep in (contenido or {}).get('repuestos') or []:
            if isinstance(rep, dict) and rep.get('nombre') and not _ya_existe(rep['nombre'], cotizacion.repuestos or []):
                nombres_piezas.append(str(rep['nombre']))
    persistir_mano_obra_lineas(cotizacion, lineas)
    if nombres_piezas:
        _sumar_piezas(cotizacion, nombres_piezas)


def _cotizar_trabajo(generar, taller, cotizacion, servicio: str) -> dict:
    try:
        resultado = generar(
            conversation=None,
            servicio_nombre=servicio,
            descripcion_problema='',
            modalidad=cotizacion.modalidad or 'taller',
            vehiculo={
                'marca': cotizacion.vehiculo_marca,
                'modelo': cotizacion.vehiculo_modelo,
                'anio': cotizacion.vehiculo_anio,
                'patente': cotizacion.vehiculo_patente,
                'cilindraje': cotizacion.vehiculo_cilindraje,
                'vin': cotizacion.vehiculo_vin,
            },
            taller=taller,
            enriquecer_ml=False,
        )
    except Exception:
        logger.exception('No pude cotizar el trabajo extra %s', servicio)
        return {}
    if not resultado.get('disponible'):
        return {}
    return resultado.get('contenido') or {}


def _quitar(cotizacion, texto: str, slots: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import (
        _filas_desglose,
        _guardar_listo,
        _pendientes_precio,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        persistir_mano_obra_lineas,
        resolver_mano_obra_lineas,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        aplicar_totales_cotizacion,
    )
    from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
        asegurar_cotizacion_editable_para_items,
    )

    if cotizacion.estado == 'aceptada':
        return _respuesta(
            cotizacion,
            slots,
            'Esa cotización ya fue aceptada. No le quito líneas; el cambio va en un trabajo adicional.',
            haciendo='Reviso si se puede editar',
            pasos=[{'texto': 'La cotización aceptada queda como está', 'estado': 'ahora'}],
            siguiente='Dime el hallazgo nuevo si hay que cotizarlo aparte.',
        )
    if cotizacion.estado == 'enviada':
        cotizacion = asegurar_cotizacion_editable_para_items(cotizacion)
    nombres = [item['nombre'] for item in _items(texto)] or [_resto(texto)]
    nombres = [nombre for nombre in nombres if nombre]
    reps = [
        rep for rep in (cotizacion.repuestos or [])
        if isinstance(rep, dict) and not any(_mismo(rep.get('nombre'), nombre) for nombre in nombres)
    ]
    labores = [
        linea for linea in resolver_mano_obra_lineas(cotizacion)
        if not any(_mismo(linea.get('nombre'), nombre) for nombre in nombres)
    ]
    cotizacion.repuestos = reps
    if labores:
        persistir_mano_obra_lineas(cotizacion, labores)
    aplicar_totales_cotizacion(cotizacion)
    _guardar_listo(cotizacion, _pendientes_precio(cotizacion))
    cotizacion.save()
    return _respuesta(
        cotizacion,
        slots,
        f"Quité {', '.join(nombres)} del borrador.",
        haciendo='Actualizo la cotización',
        filas=_filas_desglose(cotizacion, False),
        pasos=[
            {'texto': f"Quité {', '.join(nombres)}", 'estado': 'hecho'},
            {'texto': 'El borrador quedó actualizado', 'estado': 'ahora'},
        ],
        siguiente='Ábrelo para revisar el total y enviarlo.',
    )


def _items(texto: str) -> list[dict]:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import (
        _SERVICIO_RE,
        _precio_en,
        _titulo,
    )

    p = plano(texto)
    resto = _resto(texto)
    if not resto:
        return []
    partes = re.split(r'\s*(?:,| y | e )\s*', resto)
    precio = _precio_en(texto, None)
    items = []
    for parte in partes:
        nombre = parte.strip(' .')
        if len(nombre) < 3:
            continue
        plano_nombre = plano(nombre)
        es_trabajo = bool(_SERVICIO_RE.search(plano_nombre) or re.search(r'\bmano de obra\b', plano_nombre))
        es_pieza = bool(_PIEZA.search(plano_nombre) or re.search(r'\brepuesto\b', plano_nombre))
        if es_trabajo and es_pieza:
            tipo = 'repuesto' if re.search(r'\b(repuesto|pieza|kit|filtro|aceite)\b', plano_nombre) else 'mano_obra'
        elif es_trabajo:
            tipo = 'mano_obra'
        else:
            tipo = 'repuesto'
        items.append({
            'nombre': _titulo(nombre),
            'tipo': tipo,
            'precio': precio if len(partes) == 1 else None,
        })
    return items[:8]


def _resto(texto: str) -> str:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    corte = _AGREGAR.sub(' ', p, count=1)
    corte = _QUITAR.sub(' ', corte, count=1)
    corte = re.sub(
        r'\b(al borrador|a la cotizacion|en la cotizacion|por favor)\b',
        ' ',
        corte,
    )
    corte = re.sub(r'^(?:el|la|los|las|un|una)\s+', '', ' '.join(corte.split()))
    return corte.strip(' .')


def _mismo(actual, pedido) -> bool:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        _clave_fuzzy,
    )

    a = _clave_fuzzy(str(actual or ''))
    b = _clave_fuzzy(str(pedido or ''))
    return bool(a and b and (a == b or a in b or b in a))


def _pasos_suma(origen, destino, piezas, trabajos, nota, buscando) -> list[dict]:
    pasos = []
    if nota:
        pasos.append({'texto': nota, 'estado': 'hecho'})
    for item in piezas:
        pasos.append({'texto': f"{item['nombre']} quedó como repuesto", 'estado': 'hecho'})
    for item in trabajos:
        pasos.append({'texto': f"{item['nombre']} quedó como mano de obra", 'estado': 'hecho'})
    if buscando:
        pasos.append({'texto': 'Buscando esos precios en tiendas', 'estado': 'ahora'})
    elif destino.id != origen.id:
        pasos.append({'texto': 'El adicional quedó en borrador', 'estado': 'ahora'})
    else:
        pasos.append({'texto': 'El borrador ya tiene las líneas nuevas', 'estado': 'ahora'})
    return pasos


def _siguiente(cotizacion, buscando: bool, nota: str) -> str:
    if buscando:
        return 'Cuando el precio aparezca, abre el borrador y envíalo.'
    if cotizacion.es_cotizacion_adicional:
        return 'Abre el trabajo adicional, confirma si es en esta visita y envíaselo al cliente.'
    if 'reabrí' in (nota or '').lower():
        return 'Revisa el borrador reabierto y vuelve a enviarlo. Hasta entonces el cliente ve la versión anterior.'
    return 'Abre el borrador, revisa el total y envíalo.'


def _resumen_suma(cotizacion, piezas, trabajos, nota, buscando: bool) -> str:
    lineas = [item['nombre'] for item in piezas + trabajos]
    donde = 'trabajo adicional' if cotizacion.es_cotizacion_adicional else 'borrador'
    frase = f"Sumé {', '.join(lineas)} al {donde}."
    if nota:
        frase = f'{nota} {frase}'
    if buscando:
        frase = f'{frase} Estoy consultando el precio en tiendas.'
    return frase


def _respuesta(
    cotizacion,
    slots,
    resumen: str,
    *,
    haciendo: str,
    filas=None,
    pasos=None,
    siguiente: str = '',
    buscando: bool = False,
) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import (
        _enlace,
        _filas_desglose,
        _slots_publicos,
        _turno,
        _caso_anclado,
    )

    return _turno(
        haciendo=haciendo,
        titulo=cotizacion.numero_publico or 'Borrador',
        resumen=resumen,
        filas=filas if filas is not None else _filas_desglose(cotizacion, buscando),
        enlace=_enlace(cotizacion, buscando),
        pasos=pasos or [],
        siguiente=siguiente,
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_lista',
            'cotizacion_id': cotizacion.id,
            'slots': _slots_publicos(slots),
        },
    )

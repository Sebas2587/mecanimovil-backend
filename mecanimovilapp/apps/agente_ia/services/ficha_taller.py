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

from mecanimovilapp.apps.usuarios.models import HorarioProveedor, MiembroTaller, Taller


def _formatear_clp(valor) -> str:
    return f'${int(valor or 0):,}'.replace(',', '.')


def _bloque_modalidad(taller: Taller) -> str:
    return f'Modalidad de atención del taller: {taller.get_modalidad_atencion_display()}.'


def _bloque_cobertura_marcas(taller: Taller) -> str:
    if taller.tipo_cobertura_marca == 'multimarca':
        return 'Cobertura de marcas: MULTIMARCA — atiende vehículos de cualquier marca.'
    marcas = list(taller.marcas_atendidas.values_list('nombre', flat=True))
    if marcas:
        return (
            f'Cobertura de marcas: ESPECIALISTA en {", ".join(marcas)}. '
            'No ofrezcas el servicio para otras marcas sin confirmar antes con el taller.'
        )
    return (
        'Cobertura de marcas: especialista, pero el taller aún no configuró marcas específicas. '
        'No asumas que atienden cualquier marca.'
    )


def _bloque_especialidades(taller: Taller) -> str | None:
    especialidades = list(taller.especialidades.values_list('nombre', flat=True))
    if not especialidades:
        return None
    return f'Especialidades del taller: {", ".join(especialidades)}.'


def _bloque_equipo(taller: Taller) -> str:
    miembros = list(
        MiembroTaller.objects.filter(taller=taller, rol='mecanico', activo=True)
        .prefetch_related('especialidades')
    )
    if not miembros:
        return (
            'Equipo: el taller no tiene mecánicos de equipo cargados en el sistema; '
            'la atención depende directamente del taller.'
        )
    lineas = ['Equipo de mecánicos activos (usa esto para saber si hay atención a domicilio real):']
    hay_domicilio = False
    for m in miembros:
        especialidades_m = ', '.join(m.especialidades.values_list('nombre', flat=True)) or 'general'
        modalidad_m = m.get_modalidad_tecnico_display()
        if m.modalidad_tecnico in ('a_domicilio', 'ambas'):
            hay_domicilio = True
        lineas.append(f'- {m.nombre}: especialidad {especialidades_m}; atiende {modalidad_m}.')
    if hay_domicilio:
        lineas.append('SÍ hay al menos un mecánico que atiende a domicilio: no derives a domicilio como "no disponible".')
    return '\n'.join(lineas)


def _bloque_horarios(taller: Taller) -> str:
    horarios = list(
        HorarioProveedor.objects.filter(taller=taller, miembro_taller__isnull=True, activo=True)
        .order_by('dia_semana')
    )
    if not horarios:
        return 'Horario general del taller: no configurado todavía.'
    dias = ', '.join(
        f'{h.get_dia_semana_display()} {h.hora_inicio.strftime("%H:%M")}-{h.hora_fin.strftime("%H:%M")}'
        for h in horarios
    )
    return f'Horario general del taller: {dias}.'


def _bloque_catalogo(taller: Taller) -> str:
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    ofertas = list(
        OfertaServicio.objects.filter(taller=taller, disponible=True)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
        .order_by('servicio__nombre')[:40]
    )
    if not ofertas:
        return 'Catálogo: el taller no tiene servicios publicados todavía en el sistema.'

    lineas = [
        'Catálogo de servicios publicados por el taller '
        '(usa EXACTAMENTE estos nombres si el cliente pregunta qué servicios ofrecen; '
        'no inventes servicios que no estén en esta lista):'
    ]
    for oferta in ofertas:
        marca = oferta.marca_vehiculo_seleccionada.nombre if oferta.marca_vehiculo_seleccionada_id else None
        modelo = oferta.modelo_vehiculo_seleccionado.nombre if oferta.modelo_vehiculo_seleccionado_id else None
        if marca and modelo:
            cobertura_txt = f'{marca} {modelo}'
        elif marca:
            cobertura_txt = f'{marca} (todos los modelos)'
        else:
            cobertura_txt = 'todas las marcas/modelos'
        precio = oferta.precio_con_repuestos or oferta.precio_sin_repuestos or 0
        lineas.append(
            f'- {oferta.servicio.nombre} · {cobertura_txt} · desde {_formatear_clp(precio)} CLP'
        )
    return '\n'.join(lineas)


def construir_ficha_operativa_taller(taller: Taller) -> str:
    """Bloque determinístico con la verdad operativa del taller para el prompt del agente.

    Se recalcula en cada turno (no se cachea): las queries son baratas e
    indexadas por taller_id/activo, así que cualquier cambio de configuración
    del taller se refleja de inmediato sin depender de un proceso de
    sincronización aparte.
    """
    nombre = (taller.nombre or '').strip() or f'Taller #{taller.id}'
    bloques = [
        f'Nombre comercial del taller: {nombre}',
        _bloque_modalidad(taller),
        _bloque_cobertura_marcas(taller),
        _bloque_especialidades(taller),
        _bloque_equipo(taller),
        _bloque_horarios(taller),
        _bloque_catalogo(taller),
    ]
    return '\n\n'.join(b for b in bloques if b)

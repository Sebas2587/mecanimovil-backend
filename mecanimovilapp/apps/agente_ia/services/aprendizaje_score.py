"""Score de aprendizaje/contexto del agente IA por taller (completitud + actividad)."""
from __future__ import annotations

from typing import Any

from django.db.models import Q

from mecanimovilapp.apps.agente_ia.models import (
    AgenteMensajeLog,
    TallerAgenteConfig,
    TallerConocimientoChunk,
    TallerConocimientoDocumento,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import HorarioProveedor, MiembroTaller, Taller


def _pct(ok: bool) -> float:
    return 100.0 if ok else 0.0


def _pct_parcial(actual: int, meta: int) -> float:
    if meta <= 0:
        return 100.0 if actual > 0 else 0.0
    return min(100.0, round(100.0 * actual / meta, 1))


def calcular_aprendizaje_taller(taller: Taller) -> dict[str, Any]:
    """Recalcula en vivo completitud de config + actividad histórica."""
    config = TallerAgenteConfig.objects.filter(taller=taller).first()

    ofertas_qs = OfertaServicio.objects.filter(taller=taller, disponible=True)
    ofertas_total = ofertas_qs.count()
    ofertas_con_precio = ofertas_qs.filter(
        Q(precio_con_repuestos__gt=0) | Q(precio_sin_repuestos__gt=0)
    ).count()

    mecanicos = MiembroTaller.objects.filter(taller=taller, rol='mecanico', activo=True).count()
    horarios_taller = HorarioProveedor.objects.filter(
        taller=taller,
        miembro_taller__isnull=True,
        activo=True,
    ).count()
    horarios_mecanicos = HorarioProveedor.objects.filter(
        taller=taller,
        miembro_taller__isnull=False,
        activo=True,
    ).count()
    docs_listos = TallerConocimientoDocumento.objects.filter(
        taller=taller,
        estado_procesamiento=TallerConocimientoDocumento.ESTADO_LISTO,
    ).count()
    chunks_total = TallerConocimientoChunk.objects.filter(taller_id=taller.id).count()
    logs_agente = AgenteMensajeLog.objects.filter(sesion__taller=taller).count()

    marcas_ok = (
        taller.tipo_cobertura_marca == 'multimarca'
        or taller.marcas_atendidas.exists()
    )

    factores = [
        {
            'clave': 'instrucciones',
            'label': 'Instrucciones personalizadas',
            'peso': 12,
            'pct': _pct(bool((config.instrucciones_personalizadas if config else '') or '').strip()),
            'ok': bool((config.instrucciones_personalizadas if config else '') or '').strip(),
        },
        {
            'clave': 'catalogo',
            'label': 'Catálogo con precios',
            'peso': 20,
            'pct': _pct_parcial(ofertas_con_precio, max(ofertas_total, 1)),
            'ok': ofertas_con_precio > 0,
            'detalle': f'{ofertas_con_precio}/{ofertas_total} ofertas con precio',
        },
        {
            'clave': 'marcas',
            'label': 'Cobertura de marcas',
            'peso': 10,
            'pct': _pct(marcas_ok),
            'ok': marcas_ok,
        },
        {
            'clave': 'equipo',
            'label': 'Equipo de mecánicos',
            'peso': 10,
            'pct': _pct(mecanicos > 0),
            'ok': mecanicos > 0,
            'detalle': f'{mecanicos} mecánico(s)',
        },
        {
            'clave': 'horarios',
            'label': 'Horarios configurados',
            'peso': 15,
            'pct': _pct(horarios_taller > 0 or horarios_mecanicos > 0),
            'ok': horarios_taller > 0 or horarios_mecanicos > 0,
        },
        {
            'clave': 'modalidad',
            'label': 'Modalidad de atención',
            'peso': 8,
            'pct': _pct(bool(taller.modalidad_atencion)),
            'ok': bool(taller.modalidad_atencion),
        },
        {
            'clave': 'bienvenida',
            'label': 'Mensaje de bienvenida',
            'peso': 5,
            'pct': _pct(bool((config.mensaje_bienvenida if config else '') or '').strip()),
            'ok': bool((config.mensaje_bienvenida if config else '') or '').strip(),
        },
        {
            'clave': 'documentos',
            'label': 'Documentos indexados',
            'peso': 10,
            'pct': _pct(docs_listos > 0),
            'ok': docs_listos > 0,
            'detalle': f'{docs_listos} documento(s) listo(s)',
        },
        {
            'clave': 'especialidades',
            'label': 'Especialidades del taller',
            'peso': 10,
            'pct': _pct(taller.especialidades.exists()),
            'ok': taller.especialidades.exists(),
        },
    ]

    peso_total = sum(f['peso'] for f in factores)
    completitud = round(
        sum(f['pct'] * f['peso'] for f in factores) / peso_total,
        1,
    ) if peso_total else 0.0

    # Actividad: mensajes procesados + chunks indexados (cap suave a 100%).
    actividad_msgs = min(100.0, round(logs_agente / 50.0 * 100, 1))
    actividad_chunks = min(100.0, round(chunks_total / 30.0 * 100, 1))
    actividad = round(0.6 * actividad_msgs + 0.4 * actividad_chunks, 1)

    score = round(0.7 * completitud + 0.3 * actividad)

    pendientes = [f['label'] for f in factores if not f.get('ok')]

    return {
        'score': score,
        'completitud': completitud,
        'actividad': actividad,
        'detalle': factores,
        'pendientes': pendientes,
        'metricas': {
            'ofertas_total': ofertas_total,
            'ofertas_con_precio': ofertas_con_precio,
            'mecanicos': mecanicos,
            'chunks_indexados': chunks_total,
            'mensajes_procesados': logs_agente,
            'documentos_listos': docs_listos,
        },
    }

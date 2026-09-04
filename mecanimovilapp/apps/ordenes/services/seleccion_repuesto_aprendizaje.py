"""Aprendizaje de selección de repuestos. Nunca escribe precio."""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import (
    AgenteAprendizajeDiario,
    AgenteClienteMemoria,
    TallerConocimientoChunk,
)
from mecanimovilapp.apps.ordenes.models import (
    CotizacionCanal,
    SeleccionRepuestoEvento,
    VehiculoPreferenciaRepuesto,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.familias_sensibles import (
    detectar_familia_sensible,
)

logger = logging.getLogger(__name__)

UMBRAL_MUESTRAS = 6


def registrar_eventos_seleccion(cotizacion: CotizacionCanal) -> dict[str, Any]:
    n = 0
    for rep in cotizacion.repuestos or []:
        if not isinstance(rep, dict):
            continue
        propuesta = ''
        prop_id = ''
        ops = list(rep.get('opciones') or [])
        if ops and isinstance(ops[0], dict):
            propuesta = str(ops[0].get('calidad') or '')
            prop_id = str(ops[0].get('id') or '')
        cliente_cal = str(rep.get('calidad') or '') if rep.get('seleccion_cliente') else ''
        cliente_op = ''
        if rep.get('seleccion_cliente'):
            for op in ops:
                if isinstance(op, dict) and (
                    str(op.get('id') or '') == str(rep.get('opcion_elegida_id') or '')
                    or str(op.get('marca_repuesto') or '') == str(rep.get('marca_repuesto') or '')
                ):
                    cliente_op = str(op.get('id') or '')
                    break
        taller_cal = str(rep.get('calidad') or '') if not rep.get('seleccion_cliente') else ''
        if not (cliente_cal or taller_cal or rep.get('seleccion_cliente')):
            continue
        precio_prop = int((ops[0] or {}).get('precio_clp') or 0) if ops else 0
        precio_fin = int(rep.get('precio_unitario_clp') or 0)
        delta = None
        if precio_prop > 0 and precio_fin > 0:
            delta = round(100.0 * (precio_fin - precio_prop) / precio_prop, 1)
        SeleccionRepuestoEvento.objects.create(
            taller_id=cotizacion.taller_id,
            cotizacion=cotizacion,
            linea_id=str(rep.get('id') or ''),
            familia=detectar_familia_sensible(str(rep.get('nombre') or '')) or '',
            propuesta_ia_calidad=propuesta,
            cliente_calidad=cliente_cal,
            taller_calidad=taller_cal,
            propuesta_ia_opcion_id=prop_id,
            cliente_opcion_id=cliente_op,
            cambio_calidad=bool(cliente_cal and propuesta and cliente_cal != propuesta),
            delta_precio_pct=delta,
        )
        n += 1
        _upsert_preferencias(cotizacion, cliente_cal or taller_cal)
    return {'ok': True, 'eventos': n}


def _upsert_preferencias(cotizacion: CotizacionCanal, calidad: str) -> None:
    if not calidad:
        return
    conv = cotizacion.conversation
    ext_id = getattr(conv, 'external_contact_id', None) if conv else None
    if ext_id:
        mem, _ = AgenteClienteMemoria.objects.get_or_create(
            taller_id=cotizacion.taller_id,
            external_contact_id=ext_id,
        )
        prefs = dict(mem.preferencias_repuestos or {})
        muestras = int(prefs.get('muestras') or 0) + 1
        prefs['muestras'] = muestras
        prefs['calidad_preferida'] = calidad
        ult = list(prefs.get('ultimas') or [])
        ult.insert(0, calidad)
        prefs['ultimas'] = ult[:8]
        mem.preferencias_repuestos = prefs
        mem.calidad_preferida = calidad
        mem.save(update_fields=['preferencias_repuestos', 'calidad_preferida', 'actualizado_en'])

    patente = (cotizacion.vehiculo_patente or '').strip().upper().replace('-', '').replace(' ', '')
    if patente:
        row, _ = VehiculoPreferenciaRepuesto.objects.get_or_create(
            taller_id=cotizacion.taller_id,
            patente=patente[:12],
        )
        row.calidad_preferida = calidad
        row.muestras = int(row.muestras or 0) + 1
        row.save(update_fields=['calidad_preferida', 'muestras', 'actualizado_en'])


def consolidar_aprendizaje_taller(taller_id: int, fecha=None) -> dict[str, Any]:
    """Umbral 6 muestras por familia. Nunca escribe precio. Sin PII en RAG."""
    dia = fecha or timezone.localdate()
    qs = SeleccionRepuestoEvento.objects.filter(taller_id=taller_id)
    if not qs.exists():
        return {'ok': True, 'hallazgos': 0}
    por_fam: dict[str, Counter] = {}
    cambios = 0
    for ev in qs.iterator():
        fam = ev.familia or 'otros'
        por_fam.setdefault(fam, Counter())
        cal = ev.cliente_calidad or ev.taller_calidad
        if cal:
            por_fam[fam][cal] += 1
        if ev.cambio_calidad:
            cambios += 1
    hallazgos = 0
    por_familia_ok: dict[str, Any] = {}
    calidad_global = Counter()
    for fam, cnt in por_fam.items():
        total = sum(cnt.values())
        if total < UMBRAL_MUESTRAS:
            continue
        top, n = cnt.most_common(1)[0]
        por_familia_ok[fam] = {'calidad': top, 'muestras': total}
        calidad_global[top] += n
        hallazgos += 1
    if not por_familia_ok:
        return {'ok': True, 'hallazgos': 0}
    top_global = calidad_global.most_common(1)[0][0]
    muestras = sum(v['muestras'] for v in por_familia_ok.values())
    detalle = {
        'calidad_preferida': top_global,
        'muestras': muestras,
        'por_familia': por_familia_ok,
        'cambios_calidad': cambios,
        'patron': f'calidad más elegida: {top_global}',
    }
    AgenteAprendizajeDiario.objects.create(
        taller_id=taller_id,
        fecha=dia,
        tipo_hallazgo=AgenteAprendizajeDiario.TIPO_SELECCION_REPUESTO,
        detalle_json=detalle,
    )
    contenido = (
        f'Lección operativa ({dia.isoformat()}): con {muestras} selecciones de repuesto, '
        f'el taller suele confirmar calidad "{top_global}". '
        f'Sesgar la propuesta inicial hacia esa calidad. No citar clientes ni patentes.'
    )
    TallerConocimientoChunk.objects.update_or_create(
        taller_id=taller_id,
        referencia_externa=f'leccion_diaria:{taller_id}:{dia.isoformat()}:seleccion_repuesto',
        defaults={
            'fuente': TallerConocimientoChunk.FUENTE_LECCION_DIARIA,
            'contenido': contenido,
            'metadata': {'tipo': 'seleccion_repuesto', 'muestras': muestras},
        },
    )
    return {'ok': True, 'hallazgos': 1, 'muestras': muestras}

"""Enriquecimiento automático del agente IA cuando el cliente envía una patente."""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Formatos Chile: ABCD12 / AB12CD / AB1234 (con o sin guión/espacios)
_PATENTE_RE = re.compile(
    r'\b([A-Za-z]{2}[\s\-]?[A-Za-z0-9]{2}[\s\-]?[0-9]{2}|[A-Za-z]{2}[\s\-]?[0-9]{4})\b'
)


def normalizar_patente(raw: str) -> str:
    return re.sub(r'[\s\-]', '', (raw or '')).upper().strip()


def detectar_patente_en_texto(texto: str) -> str | None:
    if not (texto or '').strip():
        return None
    match = _PATENTE_RE.search(texto)
    if not match:
        return None
    return normalizar_patente(match.group(1))


def _resumen_historial(vehiculo_id: int, *, limite: int = 5) -> list[str]:
    from mecanimovilapp.apps.ordenes.models import LineaServicio, SolicitudServicio

    solicitudes = (
        SolicitudServicio.objects.filter(vehiculo_id=vehiculo_id, estado='completado')
        .order_by('-fecha_servicio', '-fecha_hora_solicitud')[:limite]
    )
    lineas: list[str] = []
    for s in solicitudes:
        nombres = list(
            LineaServicio.objects.filter(solicitud=s)
            .select_related('oferta_servicio__servicio')
            .values_list('oferta_servicio__servicio__nombre', flat=True)
        )
        servicios = ', '.join(n for n in nombres if n) or 'Servicio'
        fecha = s.fecha_servicio or (s.fecha_hora_solicitud.date() if s.fecha_hora_solicitud else '')
        lineas.append(f'- {fecha}: {servicios}')
    return lineas


def _resumen_salud(vehiculo_id: int) -> str:
    try:
        from mecanimovilapp.apps.vehiculos.services.health_engine import HealthEngine

        reporte = HealthEngine.calcular_salud_vehiculo(vehiculo_id) or []
    except Exception as exc:
        logger.warning('No se pudo calcular salud para vehículo %s: %s', vehiculo_id, exc)
        return ''

    if not reporte:
        return ''

    criticos = [c for c in reporte if str(c.get('estado') or '').lower() in ('critico', 'urgente', 'atencion')]
    if not criticos:
        promedio = None
        try:
            vals = [float(c.get('salud') or c.get('porcentaje_salud') or 0) for c in reporte]
            promedio = round(sum(vals) / len(vals), 0) if vals else None
        except (TypeError, ValueError, ZeroDivisionError):
            promedio = None
        if promedio is not None:
            return f'Salud general aproximada: {int(promedio)}%. Sin alertas urgentes.'
        return 'Salud del vehículo disponible; sin alertas urgentes.'

    partes = []
    for c in criticos[:5]:
        nombre = c.get('nombre') or c.get('componente') or 'Componente'
        estado = c.get('estado') or ''
        partes.append(f'{nombre} ({estado})')
    return 'Alertas de salud: ' + ', '.join(partes)


def _ofertas_catalogo_taller(
    *,
    taller_id: int,
    marca_nombre: str,
    modelo_nombre: str,
    limite: int = 8,
) -> list[str]:
    from django.db.models import Q

    from mecanimovilapp.apps.servicios.models import OfertaServicio

    qs = (
        OfertaServicio.objects.filter(taller_id=taller_id, disponible=True)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
        .order_by('servicio__nombre')
    )
    if marca_nombre:
        qs = qs.filter(
            Q(marca_vehiculo_seleccionada__nombre__iexact=marca_nombre)
            | Q(marca_vehiculo_seleccionada__isnull=True)
        )
    if modelo_nombre:
        qs = qs.filter(
            Q(modelo_vehiculo_seleccionado__nombre__iexact=modelo_nombre)
            | Q(modelo_vehiculo_seleccionado__isnull=True)
        )

    lineas: list[str] = []
    for oferta in qs[:limite]:
        servicio = oferta.servicio.nombre if oferta.servicio_id else 'Servicio'
        con_rep = int(oferta.precio_con_repuestos or 0)
        sin_rep = int(oferta.precio_sin_repuestos or 0)
        marca = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or 'general'
        modelo = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or 'general'
        lineas.append(
            f'- {servicio} ({marca} {modelo}): '
            f'con repuestos ${con_rep:,} / sin repuestos ${sin_rep:,}'.replace(',', '.')
        )
    return lineas


def enriquecer_contexto_patente(
    *,
    patente: str,
    taller_id: int,
    proveedor_user=None,
) -> dict[str, Any]:
    """
    Consulta GetAPI + vehículo registrado + historial + salud + catálogo del taller.
    No falla el flujo si alguna fuente no está disponible.
    """
    patente_norm = normalizar_patente(patente)
    resultado: dict[str, Any] = {
        'patente': patente_norm,
        'vehiculo': {},
        'registrado_en_sistema': False,
        'vehiculo_id': None,
        'texto_contexto': '',
        'ofertas': [],
        'historial': [],
        'salud': '',
        'error': None,
    }
    if not patente_norm:
        resultado['error'] = 'patente_vacia'
        return resultado

    # Cuota de consulta patente (si hay usuario y enforcement activo)
    if proveedor_user is not None:
        try:
            from mecanimovilapp.apps.suscripciones.cuotas_services import (
                CuotaAgotadaError,
                SinSuscripcionError,
                verificar_y_consumir_cuota,
            )
            from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual

            verificar_y_consumir_cuota(proveedor_user, ConsumoFeatureMensual.FEATURE_CONSULTA_PATENTE)
        except (CuotaAgotadaError, SinSuscripcionError) as exc:
            logger.info('Cuota patente agotada en agente IA: %s', getattr(exc, 'message', exc))
            # Seguimos con lookup interno (sin GetAPI) si hay vehículo en BD
        except Exception as exc:
            logger.warning('Error consumiendo cuota patente agente: %s', exc)

    # 1) GetAPI
    try:
        from mecanimovilapp.apps.vehiculos.services.guest_patente_lookup import fetch_patente_normalized

        payload, status_code, error_code = fetch_patente_normalized(
            patente_norm,
            include_private_fields=False,
        )
        if payload:
            resultado['vehiculo'] = {
                'patente': payload.get('patente') or patente_norm,
                'marca': payload.get('marca_nombre') or '',
                'modelo': payload.get('modelo_nombre') or '',
                'anio': str(payload.get('year') or ''),
                'cilindraje': payload.get('cilindraje') or '',
                'tipo_motor': payload.get('tipo_motor') or '',
                'color': payload.get('color') or '',
                'marca_id': payload.get('marca_id'),
                'modelo_id': payload.get('modelo_id'),
            }
        else:
            resultado['error'] = error_code or f'http_{status_code}'
    except Exception as exc:
        logger.warning('Error GetAPI patente en agente: %s', exc)
        resultado['error'] = 'servicio_externo'

    # 2) Vehículo registrado en Mecanimovil
    try:
        from mecanimovilapp.apps.vehiculos.models import Vehiculo

        veh = (
            Vehiculo.objects.select_related('marca', 'modelo', 'cliente')
            .filter(patente__iexact=patente_norm)
            .first()
        )
        if veh:
            resultado['registrado_en_sistema'] = True
            resultado['vehiculo_id'] = veh.id
            marca = getattr(veh.marca, 'nombre', '') or resultado['vehiculo'].get('marca', '')
            modelo = getattr(veh.modelo, 'nombre', '') or resultado['vehiculo'].get('modelo', '')
            resultado['vehiculo'] = {
                **(resultado['vehiculo'] or {}),
                'patente': veh.patente or patente_norm,
                'marca': marca,
                'modelo': modelo,
                'anio': str(veh.anio or resultado['vehiculo'].get('anio') or ''),
                'cilindraje': veh.cilindraje or resultado['vehiculo'].get('cilindraje') or '',
                'tipo_motor': veh.tipo_motor or resultado['vehiculo'].get('tipo_motor') or '',
                'kilometraje': veh.kilometraje,
            }
            resultado['historial'] = _resumen_historial(veh.id)
            resultado['salud'] = _resumen_salud(veh.id)
    except Exception as exc:
        logger.warning('Error buscando vehículo registrado por patente: %s', exc)

    marca = (resultado['vehiculo'] or {}).get('marca') or ''
    modelo = (resultado['vehiculo'] or {}).get('modelo') or ''
    resultado['ofertas'] = _ofertas_catalogo_taller(
        taller_id=taller_id,
        marca_nombre=marca,
        modelo_nombre=modelo,
    )

    # Texto para el prompt
    v = resultado['vehiculo'] or {}
    bloques = [f'Patente consultada: {patente_norm}']
    if v.get('marca') or v.get('modelo'):
        bloques.append(
            f"Vehículo identificado: {v.get('marca', '')} {v.get('modelo', '')} "
            f"{v.get('anio', '')} — cilindraje {v.get('cilindraje') or 'n/d'} "
            f"— motor {v.get('tipo_motor') or 'n/d'}".strip()
        )
    else:
        bloques.append('No se pudo identificar marca/modelo vía API de patente.')

    if resultado['registrado_en_sistema']:
        bloques.append('Esta patente ESTÁ registrada en Mecanimovil.')
        if resultado['historial']:
            bloques.append('Historial de servicios completados:\n' + '\n'.join(resultado['historial']))
        else:
            bloques.append('Sin historial de servicios completados en el sistema.')
        if resultado['salud']:
            bloques.append(resultado['salud'])
    else:
        bloques.append('Esta patente NO está registrada como vehículo de un cliente en Mecanimovil.')

    if resultado['ofertas']:
        bloques.append(
            'Servicios del taller compatibles (con/sin repuestos):\n' + '\n'.join(resultado['ofertas'])
        )
    else:
        bloques.append('No hay ofertas de catálogo exactas para esta marca/modelo; usa el catálogo general del RAG.')

    resultado['texto_contexto'] = '\n'.join(bloques)
    return resultado

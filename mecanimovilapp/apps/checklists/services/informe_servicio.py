"""
Generación y envío de informes públicos de servicio (citas personales de taller).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

from mecanimovilapp.apps.checklists.km_extraction import extraer_kilometraje_desde_checklist_instance
from mecanimovilapp.apps.checklists.models import ChecklistInstance
from mecanimovilapp.apps.checklists.models_informe import InformeServicioPublico
from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.generador import (
    _contexto_desde_cita_personal,
    _llamar_gemini,
)

logger = logging.getLogger(__name__)


def _base_url_publica() -> str:
    return (
        getattr(settings, 'INFORME_PUBLIC_BASE_URL', '')
        or 'https://mecanimovil-usuarios.vercel.app'
    ).rstrip('/')


def construir_url_publica(token: str) -> str:
    return f'{_base_url_publica()}/reporte/{token}'


def _snapshot_vehiculo_desde_cita(cita) -> dict[str, Any]:
    det = getattr(cita, 'detalle', None)
    patente = (getattr(det, 'vehiculo_patente', '') or '').strip().upper()
    marca = (getattr(det, 'vehiculo_marca', '') or '').strip()
    modelo = (getattr(det, 'vehiculo_modelo', '') or '').strip()
    anio = getattr(det, 'vehiculo_anio', None)
    vin = (getattr(det, 'vehiculo_vin', '') or '').strip()

    datos_patente: dict[str, Any] = {}
    kilometraje_api = None
    if patente:
        try:
            from mecanimovilapp.apps.vehiculos.getapi_client import fetch_plate_basic_info

            info = fetch_plate_basic_info(patente) or {}
            datos_patente = dict(info)
            raw_km = info.get('mileage') or info.get('kilometraje_api')
            if raw_km is not None:
                try:
                    kilometraje_api = int(float(raw_km))
                except (TypeError, ValueError):
                    kilometraje_api = None
        except Exception as exc:
            logger.warning('No se pudo consultar patente %s para informe: %s', patente, exc)

    return {
        'vehiculo_patente': patente,
        'vehiculo_marca': marca,
        'vehiculo_modelo': modelo,
        'vehiculo_anio': anio,
        'vehiculo_vin': vin,
        'kilometraje_api': kilometraje_api,
        'datos_patente_json': datos_patente,
    }


def _resumen_checklist_texto(instance: ChecklistInstance) -> str:
    lineas: list[str] = []
    tpl = instance.checklist_template
    nombre_tpl = getattr(tpl, 'nombre', 'Checklist')
    lineas.append(f'Checklist: {nombre_tpl}')

    respuestas = list(
        instance.respuestas.select_related('item_template__catalog_item').prefetch_related('fotos').all()
    )
    for resp in respuestas:
        if not resp.completado:
            continue
        cat = resp.item_template.catalog_item
        pregunta = (cat.pregunta_texto or cat.nombre or '').strip()
        tipo = (cat.tipo_pregunta or '').strip()
        valor = ''
        if resp.respuesta_texto:
            valor = str(resp.respuesta_texto).strip()
        elif resp.respuesta_numero is not None:
            valor = str(int(resp.respuesta_numero)) if tipo == 'KILOMETER_INPUT' else str(resp.respuesta_numero)
        elif resp.respuesta_booleana is not None:
            valor = 'Sí' if resp.respuesta_booleana else 'No'
        elif resp.respuesta_seleccion:
            valor = str(resp.respuesta_seleccion)
        fotos = resp.fotos.count() if hasattr(resp, 'fotos') else 0
        if fotos:
            valor = (valor + f' ({fotos} foto(s))').strip()
        if pregunta:
            lineas.append(f'- {pregunta}: {valor or "completado"}')

    return '\n'.join(lineas)


def _fallback_resumen_ia(ctx: dict[str, Any], checklist_texto: str, km: int | None) -> str:
    vehiculo = ctx.get('vehiculo_label') or 'Vehículo'
    patente = ctx.get('patente') or 'sin patente'
    problema = ctx.get('problema_reportado') or 'Servicio mecánico'
    km_txt = f' Kilometraje registrado: {km:,} km.' if km else ''
    return (
        f'Se realizó un servicio en {vehiculo} (patente {patente}). '
        f'Motivo / alcance: {problema}.{km_txt}\n\n'
        f'Resumen del checklist:\n{checklist_texto}\n\n'
        'Este informe resume el trabajo ejecutado por el taller. '
        'Si deseas llevar el historial de mantenciones de tu vehículo en Mecanimovil, '
        'puedes crear una cuenta y vincular este servicio escaneando el código QR del informe.'
    )


def generar_informe(checklist_instance: ChecklistInstance) -> InformeServicioPublico:
    """
    Crea o actualiza el informe público asociado al checklist.
    Genera resumen narrativo con Gemini (fallback determinista).
    """
    if not checklist_instance.cita_personal_id:
        raise ValueError('Solo checklists de cita personal pueden generar informe público')

    cita = checklist_instance.cita_personal
    vehiculo_snap = _snapshot_vehiculo_desde_cita(cita)
    km_servicio = extraer_kilometraje_desde_checklist_instance(checklist_instance)
    ctx = _contexto_desde_cita_personal(cita)
    checklist_texto = _resumen_checklist_texto(checklist_instance)

    prompt = (
        'Eres un asistente técnico automotriz. Redacta un informe claro para el dueño del vehículo '
        'sobre el servicio realizado en el taller. Usa tono profesional, español de Chile, '
        'segunda persona (usted). Incluye: vehículo, trabajo realizado, hallazgos relevantes del '
        'checklist y recomendaciones breves. No inventes repuestos no mencionados.\n\n'
        f'Contexto vehículo: {json.dumps(ctx, ensure_ascii=False)}\n'
        f'Kilometraje servicio: {km_servicio or "no registrado"}\n\n'
        f'Detalle checklist:\n{checklist_texto}\n\n'
        'Responde SOLO con el texto del informe (máx. 800 palabras).'
    )

    resumen_ia = _fallback_resumen_ia(ctx, checklist_texto, km_servicio)
    parsed, _usage, err = _llamar_gemini(prompt)
    if parsed and isinstance(parsed, dict):
        texto = (parsed.get('informe') or parsed.get('resumen') or parsed.get('texto') or '').strip()
        if texto:
            resumen_ia = texto
    elif isinstance(parsed, str) and parsed.strip():
        resumen_ia = parsed.strip()
    elif err:
        logger.info('Informe IA fallback (Gemini): %s', err)

    informe, _created = InformeServicioPublico.objects.get_or_create(
        checklist_instance=checklist_instance,
        defaults={
            'resumen_ia': resumen_ia,
            'vehiculo_patente': vehiculo_snap['vehiculo_patente'],
            'vehiculo_marca': vehiculo_snap['vehiculo_marca'],
            'vehiculo_modelo': vehiculo_snap['vehiculo_modelo'],
            'vehiculo_anio': vehiculo_snap['vehiculo_anio'],
            'vehiculo_vin': vehiculo_snap['vehiculo_vin'],
            'kilometraje_servicio': km_servicio,
            'kilometraje_api': vehiculo_snap['kilometraje_api'],
            'datos_patente_json': vehiculo_snap['datos_patente_json'],
            'estado': 'PENDIENTE_FIRMA_CLIENTE',
        },
    )
    informe.resumen_ia = resumen_ia
    informe.vehiculo_patente = vehiculo_snap['vehiculo_patente']
    informe.vehiculo_marca = vehiculo_snap['vehiculo_marca']
    informe.vehiculo_modelo = vehiculo_snap['vehiculo_modelo']
    informe.vehiculo_anio = vehiculo_snap['vehiculo_anio']
    informe.vehiculo_vin = vehiculo_snap['vehiculo_vin']
    informe.kilometraje_servicio = km_servicio
    informe.kilometraje_api = vehiculo_snap['kilometraje_api']
    informe.datos_patente_json = vehiculo_snap['datos_patente_json']
    if informe.estado not in ('FIRMADO', 'VEHICULO_RECLAMADO'):
        informe.estado = 'PENDIENTE_FIRMA_CLIENTE'
    informe.url_publica = construir_url_publica(informe.token)
    informe.save()

    return informe


def enviar_informe(cita, informe: InformeServicioPublico) -> dict[str, Any]:
    """
    Intenta enviar el enlace del informe por canal omnicanal conectado.
    Retorna { enviado: bool, via: str, url: str, message?: str }.
    """
    url = informe.url_publica or construir_url_publica(informe.token)
    mensaje = (
        f'Hola, tu taller ha finalizado el servicio de tu vehículo. '
        f'Revisa el informe y confirma con tu firma aquí: {url}'
    )

    conversation = getattr(cita, 'conversation_origen', None)
    if conversation is None:
        informe.enviado_via = 'manual_link'
        informe.url_publica = url
        informe.save(update_fields=['enviado_via', 'url_publica'])
        return {
            'enviado': False,
            'via': 'manual_link',
            'url': url,
            'message': 'No hay canal conectado; comparte el enlace manualmente.',
        }

    try:
        from mecanimovilapp.apps.chat.models import Message

        msg = Message.objects.create(
            conversation=conversation,
            sender=None,
            content=mensaje,
            direction='outbound',
            channel_metadata={'tipo': 'informe_servicio', 'informe_token': informe.token},
        )
        from mecanimovilapp.apps.omnichannel.tasks import send_meta_message

        send_meta_message.delay(msg.id)

        channel = getattr(conversation, 'source_channel', '') or 'WHATSAPP'
        via_map = {
            'WHATSAPP': 'whatsapp',
            'INSTAGRAM': 'instagram',
            'MESSENGER': 'messenger',
        }
        informe.enviado_via = via_map.get(channel.upper(), 'manual_link')
        informe.url_publica = url
        informe.save(update_fields=['enviado_via', 'url_publica'])
        return {'enviado': True, 'via': informe.enviado_via, 'url': url}
    except Exception as exc:
        logger.warning('No se pudo enviar informe por canal: %s', exc, exc_info=True)
        informe.enviado_via = 'manual_link'
        informe.url_publica = url
        informe.save(update_fields=['enviado_via', 'url_publica'])
        return {
            'enviado': False,
            'via': 'manual_link',
            'url': url,
            'message': str(exc),
        }

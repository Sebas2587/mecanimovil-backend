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


_VALORES_OK = frozenset({
    'bien', 'bueno', 'buena', 'a nivel', 'ok', 'normal', 'valor normal',
    'valor  normal', 'n/a', 'na', 'no', 'sin novedad', 'correcto', 'correcta',
    'dentro de rango', 'completo', 'completado',
})


def _parse_numero_respuesta(resp) -> float | None:
    if resp is None or resp.respuesta_numero is None:
        return None
    try:
        return float(resp.respuesta_numero)
    except (TypeError, ValueError):
        return None


def _es_porcentaje_vida_util(tipo: str, pregunta: str) -> bool:
    """COMPONENT_HEALTH y textos de vida útil son % (0–100), no montos."""
    if (tipo or '').strip() == 'COMPONENT_HEALTH':
        return True
    p = (pregunta or '').lower()
    return 'vida útil' in p or 'vida util' in p


def _severidad_porcentaje(pct: float) -> str:
    """Gravedad de vida útil restante (misma lógica que preview de impacto en prov)."""
    if pct >= 80:
        return 'ok'
    if pct >= 60:
        return 'atencion'
    if pct >= 35:
        return 'alerta'
    return 'critico'


def _meta_valor_respuesta(resp, cat) -> dict[str, Any]:
    """
    Valor legible + metadatos de formato para la UI pública.
    formato: texto | km | porcentaje
    """
    tipo = (getattr(cat, 'tipo_pregunta', '') or '').strip()
    pregunta = (getattr(cat, 'pregunta_texto', None) or getattr(cat, 'nombre', '') or '')
    num = _parse_numero_respuesta(resp)
    meta: dict[str, Any] = {
        'valor': '',
        'formato': 'texto',
        'porcentaje': None,
        'severidad': None,
    }
    if resp is None:
        return meta

    if tipo == 'KILOMETER_INPUT' and num is not None:
        meta['formato'] = 'km'
        meta['valor'] = f'{int(round(num)):,}'.replace(',', '.')
        return meta

    if _es_porcentaje_vida_util(tipo, pregunta) and num is not None:
        pct = max(0.0, min(100.0, num))
        meta['formato'] = 'porcentaje'
        meta['porcentaje'] = round(pct, 1)
        meta['severidad'] = _severidad_porcentaje(pct)
        meta['valor'] = f'{int(round(pct))}%'
        return meta

    if resp.respuesta_seleccion:
        meta['valor'] = str(resp.respuesta_seleccion).strip()
        return meta
    if resp.respuesta_booleana is not None:
        meta['valor'] = 'Sí' if resp.respuesta_booleana else 'No'
        return meta
    if resp.respuesta_texto:
        meta['valor'] = str(resp.respuesta_texto).strip()
        return meta
    if num is not None:
        if abs(num - round(num)) < 1e-9:
            meta['valor'] = str(int(round(num)))
        else:
            meta['valor'] = f'{num:.2f}'.rstrip('0').rstrip('.')
    return meta


def _valor_respuesta(resp, cat) -> str:
    return str(_meta_valor_respuesta(resp, cat).get('valor') or '')


def _es_hallazgo_relevante(pregunta: str, valor: str, tipo: str) -> bool:
    """True si el ítem merece mención al cliente (no es un OK rutinario)."""
    if not valor:
        return False
    v = ' '.join(valor.lower().split())
    p = (pregunta or '').lower()

    if tipo == 'KILOMETER_INPUT' or 'kilometraje' in p:
        return False
    if v in _VALORES_OK:
        return False

    keywords_alerta = (
        'bajo', 'alta', 'alto', 'malo', 'mala', 'regular', 'fuga', 'desgaste',
        'ruido', 'golpe', 'fisura', 'grieta', 'oxid', 'reemplaz', 'cambiar',
        'urgente', 'crític', 'critic', 'falla', 'dañ', 'danad',
    )
    if any(k in v for k in keywords_alerta):
        return True
    if v in ('sí', 'si') and any(k in p for k in ('fuga', 'ruido', 'golpe', 'falla', 'pérdida', 'perdida')):
        return True

    try:
        num = float(v.replace('%', '').replace(',', '.'))
        if _es_porcentaje_vida_util(tipo, pregunta) or 'vida' in p or 'filtro' in p or 'pastilla' in p or 'disco' in p or 'neum' in p:
            if num <= 40:
                return True
    except (TypeError, ValueError):
        pass

    return False


def _extraer_hallazgos(instance: ChecklistInstance, limite: int = 8) -> list[dict[str, str]]:
    hallazgos: list[dict[str, str]] = []
    respuestas = list(
        instance.respuestas.select_related('item_template__catalog_item').prefetch_related('fotos').all()
    )
    for resp in respuestas:
        if not resp.completado:
            continue
        cat = resp.item_template.catalog_item
        pregunta = (cat.pregunta_texto or cat.nombre or '').strip()
        tipo = (cat.tipo_pregunta or '').strip()
        valor = _valor_respuesta(resp, cat)
        if not _es_hallazgo_relevante(pregunta, valor, tipo):
            continue
        hallazgos.append({'pregunta': pregunta, 'valor': valor})
        if len(hallazgos) >= limite:
            break
    return hallazgos


def _resumen_checklist_para_ia(instance: ChecklistInstance) -> str:
    """Contexto compacto para Gemini: solo hallazgos + conteo de ítems OK."""
    hallazgos = _extraer_hallazgos(instance, limite=12)
    total = instance.respuestas.filter(completado=True).count()
    lineas = [f'Ítems completados: {total}', f'Hallazgos relevantes: {len(hallazgos)}']
    for h in hallazgos:
        lineas.append(f"- {h['pregunta']}: {h['valor']}")
    if not hallazgos:
        lineas.append('- Sin observaciones críticas en la inspección.')
    return '\n'.join(lineas)


def resumen_parece_dump_checklist(texto: str | None) -> bool:
    if not texto:
        return False
    if 'Resumen del checklist:' in texto:
        return True
    return texto.count('\n- ') >= 6


def normalizar_resumen_publico(texto: str | None) -> str:
    """Quita dumps antiguos del fallback para no repetir el detalle del checklist."""
    if not texto:
        return ''
    cleaned = texto
    for marker in ('\n\nResumen del checklist:', '\nResumen del checklist:'):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].strip()
            break
    return cleaned.strip()


def _fallback_resumen_ia(
    ctx: dict[str, Any],
    hallazgos: list[dict[str, str]],
    km: int | None,
    taller_nombre: str = '',
) -> str:
    vehiculo = ctx.get('vehiculo_label') or 'su vehículo'
    patente = ctx.get('patente') or ''
    problema = ctx.get('problema_reportado') or 'servicio mecánico'
    km_txt = f', con {km:,} km registrados'.replace(',', '.') if km else ''
    patente_txt = f' (patente {patente})' if patente else ''
    taller_txt = f' en {taller_nombre}' if taller_nombre else ' en el taller'

    intro = (
        f'Se realizó un {problema.lower() if not problema.lower().startswith("servicio") else problema}'
        f'{taller_txt} para su {vehiculo}{patente_txt}{km_txt}.'
    )
    # Normalizar "Servicio: X" → más legible
    if problema.lower().startswith('servicio:'):
        intro = (
            f'Se realizó {problema[len("Servicio:"):].strip()}'
            f'{taller_txt} para su {vehiculo}{patente_txt}{km_txt}.'
        )

    if hallazgos:
        bullets = '\n'.join(f'• {h["pregunta"]}: {h["valor"]}' for h in hallazgos[:6])
        cuerpo = (
            'Hallazgos que conviene tener presente:\n'
            f'{bullets}\n\n'
            'El resto de la inspección no presentó observaciones críticas.'
        )
    else:
        cuerpo = (
            'La inspección no presentó observaciones críticas: '
            'los sistemas revisados quedaron dentro de parámetros normales.'
        )

    cierre = (
        'Este documento certifica el trabajo ejecutado. '
        'Si desea llevar el historial de mantenciones en Mecanimovil, '
        'puede crear una cuenta y vincular este servicio con el código del informe.'
    )
    return f'{intro}\n\n{cuerpo}\n\n{cierre}'


def regenerar_resumen_si_es_dump(informe: InformeServicioPublico) -> InformeServicioPublico:
    """ Reescribe resúmenes antiguos que pegaban todo el checklist (sin llamar a Gemini). """
    if not resumen_parece_dump_checklist(informe.resumen_ia):
        return informe
    instance = informe.checklist_instance
    if not instance or not instance.cita_personal_id:
        informe.resumen_ia = normalizar_resumen_publico(informe.resumen_ia)
        informe.save(update_fields=['resumen_ia'])
        return informe

    cita = instance.cita_personal
    ctx = _contexto_desde_cita_personal(cita)
    km = informe.kilometraje_servicio or extraer_kilometraje_desde_checklist_instance(instance)
    hallazgos = _extraer_hallazgos(instance)
    taller_nombre = ''
    if cita and cita.taller_id:
        taller_nombre = getattr(cita.taller, 'nombre', '') or ''
    informe.resumen_ia = _fallback_resumen_ia(ctx, hallazgos, km, taller_nombre=taller_nombre)
    informe.save(update_fields=['resumen_ia'])
    return informe


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
    hallazgos = _extraer_hallazgos(checklist_instance)
    hallazgos_texto = _resumen_checklist_para_ia(checklist_instance)
    taller_nombre = ''
    if cita and cita.taller_id:
        taller_nombre = getattr(cita.taller, 'nombre', '') or ''

    prompt = (
        'Eres un asesor automotriz que escribe para el dueño del vehículo (no para mecánicos). '
        'Redacta un informe breve, claro y humano en español de Chile, segunda persona (usted).\n'
        'Estructura: 1) qué servicio se realizó y en qué vehículo; 2) solo hallazgos relevantes '
        'que el dueño deba conocer; 3) una recomendación corta si aplica.\n'
        'PROHIBIDO: listar ítem por ítem del checklist; repetir valores "Bien/Bueno/A nivel/No/N/A"; '
        'usar jerga técnica innecesaria; inventar repuestos o fallas no mencionadas.\n'
        'Máximo 180 palabras, 2 a 4 párrafos cortos.\n\n'
        f'Contexto: {json.dumps(ctx, ensure_ascii=False)}\n'
        f'Taller: {taller_nombre or "taller"}\n'
        f'Kilometraje: {km_servicio or "no registrado"}\n'
        f'Hallazgos ya filtrados:\n{hallazgos_texto}\n\n'
        'Responde SOLO un JSON válido con esta forma exacta:\n'
        '{"informe": "<texto del informe>"}\n'
        'Sin markdown ni texto fuera del JSON.'
    )

    resumen_ia = _fallback_resumen_ia(ctx, hallazgos, km_servicio, taller_nombre=taller_nombre)
    parsed, _usage, err = _llamar_gemini(prompt)
    if parsed and isinstance(parsed, dict):
        texto = (parsed.get('informe') or parsed.get('resumen') or parsed.get('texto') or '').strip()
        if texto and not resumen_parece_dump_checklist(texto):
            resumen_ia = texto
    elif isinstance(parsed, str) and parsed.strip() and not resumen_parece_dump_checklist(parsed):
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
    if not informe.fecha_expiracion:
        from mecanimovilapp.apps.checklists.models_informe import _default_fecha_expiracion_informe
        informe.fecha_expiracion = _default_fecha_expiracion_informe()
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

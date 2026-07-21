"""Vistas públicas del informe de servicio (AllowAny + throttle)."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status, views
from rest_framework.response import Response

from mecanimovilapp.apps.checklists.firma_utils import firma_a_payload_base64
from mecanimovilapp.apps.checklists.models_informe import InformeServicioPublico
from mecanimovilapp.apps.checklists.throttling import InformePublicThrottle
from mecanimovilapp.apps.checklists.services.informe_servicio import (
    construir_url_publica,
    _es_hallazgo_relevante,
    _extraer_hallazgos,
    _meta_valor_respuesta,
    regenerar_resumen_si_es_dump,
)
from mecanimovilapp.storage.utils import get_image_url

logger = logging.getLogger(__name__)


def _enmascarar_vin(vin: str) -> str:
    valor = (vin or '').strip()
    if not valor:
        return ''
    if len(valor) <= 4:
        return '****'
    return f"{'*' * (len(valor) - 4)}{valor[-4:]}"


def _serializar_informe_publico(informe: InformeServicioPublico, request) -> dict:
    checklist = informe.checklist_instance
    cita = checklist.cita_personal
    det = getattr(cita, 'detalle', None) if cita else None

    fotos_evidencia = []
    hallazgos_ui = []
    items = []
    tpl = checklist.checklist_template
    resp_map = {r.item_template_id: r for r in checklist.respuestas.all()}
    for item_tpl in tpl.items.select_related('catalog_item').order_by('orden_visual'):
        cat = item_tpl.catalog_item
        resp = resp_map.get(item_tpl.id)
        pregunta = (cat.pregunta_texto or cat.nombre or '').strip()
        tipo = cat.tipo_pregunta or ''
        valor_meta = (
            _meta_valor_respuesta(resp, cat)
            if resp and resp.completado
            else {'valor': '', 'formato': 'texto', 'porcentaje': None, 'severidad': None}
        )
        valor = valor_meta.get('valor') or ''
        fotos = []
        if resp:
            for foto in resp.fotos.all().order_by('orden_en_respuesta', 'id'):
                url = get_image_url(foto.imagen, request)
                if not url:
                    continue
                # Nombre que puso el técnico al subir la foto (no el título del ítem).
                desc = (foto.descripcion or '').strip()
                if not desc:
                    orden = foto.orden_en_respuesta or (len(fotos) + 1)
                    desc = f'Foto {orden}'
                foto_payload = {
                    'id': foto.id,
                    'descripcion': desc,
                    'imagen_url': url,
                    'item_id': item_tpl.id,
                }
                fotos.append(foto_payload)
                fotos_evidencia.append(foto_payload)

        es_hallazgo = bool(
            resp and resp.completado and _es_hallazgo_relevante(pregunta, valor, tipo)
        )
        item_payload = {
            'id': item_tpl.id,
            'pregunta_texto': pregunta,
            'tipo_pregunta': tipo,
            'completado': bool(resp and resp.completado),
            'valor': valor or ('—' if not (resp and resp.completado) else ''),
            'formato': valor_meta.get('formato') or 'texto',
            'porcentaje': valor_meta.get('porcentaje'),
            'severidad': valor_meta.get('severidad'),
            'es_hallazgo': es_hallazgo,
            'fotos': fotos,
        }
        if es_hallazgo:
            hallazgos_ui.append({
                'id': item_tpl.id,
                'pregunta': pregunta,
                'valor': item_payload['valor'],
                'formato': item_payload['formato'],
                'porcentaje': item_payload['porcentaje'],
                'severidad': item_payload['severidad'],
            })

        items.append(item_payload)

    if not hallazgos_ui:
        for h in _extraer_hallazgos(checklist, limite=8):
            hallazgos_ui.append({
                'id': f"{h['pregunta']}:{h['valor']}",
                'pregunta': h['pregunta'],
                'valor': h['valor'],
                'formato': 'texto',
                'porcentaje': None,
                'severidad': None,
            })

    taller_nombre = ''
    if cita and cita.taller_id:
        taller_nombre = getattr(cita.taller, 'nombre', '') or ''

    componentes_oficiales = []
    try:
        from mecanimovilapp.apps.vehiculos.services.reclamar_informe import _componentes_desde_checklist

        componentes_oficiales = _componentes_desde_checklist(checklist)
    except Exception:
        logger.warning('No se pudo calcular componentes_oficiales del informe %s', informe.token, exc_info=True)

    return {
        'token': informe.token,
        'estado': informe.estado,
        'url_publica': informe.url_publica or construir_url_publica(informe.token),
        'resumen_ia': informe.resumen_ia,
        'generado_en': informe.generado_en.isoformat() if informe.generado_en else None,
        'fecha_expiracion': informe.fecha_expiracion.isoformat() if informe.fecha_expiracion else None,
        'expirado': informe.is_expired,
        'vehiculo': {
            'patente': informe.vehiculo_patente,
            'marca': informe.vehiculo_marca,
            'modelo': informe.vehiculo_modelo,
            'anio': informe.vehiculo_anio,
            'vin': _enmascarar_vin(informe.vehiculo_vin),
            'kilometraje_servicio': informe.kilometraje_servicio,
            'kilometraje_api': informe.kilometraje_api,
        },
        'cliente_nombre': getattr(det, 'cliente_nombre', '') if det else '',
        'servicio_descripcion': getattr(det, 'descripcion', '') if det else '',
        'taller_nombre': taller_nombre,
        'hallazgos': hallazgos_ui,
        'fotos_evidencia': fotos_evidencia,
        'checklist': {
            'id': checklist.id,
            'estado': checklist.estado,
            'template_nombre': getattr(tpl, 'nombre', ''),
            'items': items,
            'items_completados': sum(1 for it in items if it['completado']),
            'items_total': len(items),
            'firma_tecnico_presente': bool(checklist.firma_tecnico),
            'firma_supervisor_presente': bool(checklist.firma_supervisor),
            'firma_cliente_presente': bool(checklist.firma_cliente),
        },
        'firmado_por_nombre': informe.firmado_por_nombre,
        'fecha_firma_cliente': (
            informe.fecha_firma_cliente.isoformat() if informe.fecha_firma_cliente else None
        ),
        'reclamado': informe.estado == 'VEHICULO_RECLAMADO',
        'qr_payload': informe.url_publica or construir_url_publica(informe.token),
        # Componentes de salud que este checklist cubrirá al vincularlo (preview pre-reclamo).
        'componentes_oficiales': componentes_oficiales,
    }


class InformePublicoDetailView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [InformePublicThrottle]

    def get(self, request, token=None):
        try:
            informe = InformeServicioPublico.objects.select_related(
                'checklist_instance__checklist_template',
                'checklist_instance__cita_personal__detalle',
                'checklist_instance__cita_personal__taller',
            ).prefetch_related(
                'checklist_instance__respuestas__fotos',
                'checklist_instance__checklist_template__items__catalog_item',
            ).get(token=token)
        except InformeServicioPublico.DoesNotExist:
            return Response({'error': 'Informe no encontrado'}, status=status.HTTP_404_NOT_FOUND)

        # Informes antiguos pegaban todo el checklist en el resumen: reescribir una vez.
        informe = regenerar_resumen_si_es_dump(informe)

        if informe.is_expired:
            return Response(
                {
                    'error': 'Este enlace de informe ha expirado',
                    'codigo': 'enlace_expirado',
                    'expirado': True,
                },
                status=status.HTTP_410_GONE,
            )

        return Response(_serializar_informe_publico(informe, request))


class InformePublicoFirmarClienteView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [InformePublicThrottle]

    def post(self, request, token=None):
        try:
            informe = InformeServicioPublico.objects.select_related(
                'checklist_instance__cita_personal',
            ).get(token=token)
        except InformeServicioPublico.DoesNotExist:
            return Response({'error': 'Informe no encontrado'}, status=status.HTTP_404_NOT_FOUND)

        if informe.is_expired:
            return Response(
                {'error': 'Este enlace de informe ha expirado', 'codigo': 'enlace_expirado'},
                status=status.HTTP_410_GONE,
            )

        if informe.estado in ('FIRMADO', 'VEHICULO_RECLAMADO'):
            return Response(
                {
                    'message': 'El informe ya fue firmado',
                    'estado': informe.estado,
                },
                status=status.HTTP_200_OK,
            )

        firma_cliente = request.data.get('firma_cliente')
        if not firma_cliente:
            return Response(
                {'error': 'Se requiere la firma del cliente'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nombre = (request.data.get('firmado_por_nombre') or '').strip()
        if not nombre:
            return Response(
                {'error': 'Indique su nombre para certificar el servicio'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        checklist = informe.checklist_instance
        if checklist.estado not in ('PENDIENTE_FIRMA_CLIENTE', 'PENDIENTE_FIRMA_SUPERVISOR'):
            if checklist.estado == 'COMPLETADO' and informe.firma_cliente:
                # Idempotencia: también repara cita que quedó activa por desfase.
                from mecanimovilapp.apps.ordenes.services.cita_cierre_sync import (
                    asegurar_cierre_cita_si_checklist_completo,
                )
                asegurar_cierre_cita_si_checklist_completo(checklist.cita_personal)
                return Response({'message': 'Ya firmado', 'estado': informe.estado})
            return Response(
                {'error': f'El checklist no acepta firma (estado: {checklist.estado})'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not checklist.firma_supervisor and checklist.cita_personal_id and checklist.cita_personal.taller_id:
            return Response(
                {'error': 'El taller aún no ha rectificado el servicio'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ahora = timezone.now()
        with transaction.atomic():
            checklist.firma_cliente = firma_a_payload_base64(firma_cliente)
            checklist.estado = 'COMPLETADO'
            checklist.fecha_finalizacion = ahora
            checklist.progreso_porcentaje = 100
            checklist.save()

            informe.firma_cliente = checklist.firma_cliente
            informe.firmado_por_nombre = nombre
            informe.fecha_firma_cliente = ahora
            informe.estado = 'FIRMADO'
            informe.save()

            from mecanimovilapp.apps.ordenes.services.cita_cierre_sync import (
                asegurar_cierre_cita_si_checklist_completo,
            )
            asegurar_cierre_cita_si_checklist_completo(checklist.cita_personal)

        logger.info('Cliente firmó informe público token=%s checklist=%s', token, checklist.id)
        return Response({
            'message': 'Servicio certificado correctamente. ¡Gracias por tu firma!',
            'estado': informe.estado,
            'checklist_estado': checklist.estado,
        })

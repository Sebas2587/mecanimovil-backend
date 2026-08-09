"""
Tareas asíncronas de Celery para el sistema de órdenes y solicitudes
Incluye envío de push notifications para recordatorios de pago
"""
try:
    from celery import shared_task
    CELERY_AVAILABLE = True
except ImportError:
    # Celery no está disponible, crear decorador dummy
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    CELERY_AVAILABLE = False

import requests
import logging
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.core.management import call_command
from mecanimovilapp.apps.usuarios.models import PushToken

logger = logging.getLogger(__name__)


@shared_task
def enviar_push_notificacion_pago_pendiente(solicitud_id, user_id, mensaje, titulo=None):
    """
    Enviar push notification de recordatorio de pago a un usuario
    
    Args:
        solicitud_id: ID de la solicitud
        user_id: ID del usuario (cliente)
        mensaje: Mensaje de la notificación
        titulo: Título de la notificación (opcional)
    """
    try:
        # Obtener tokens activos del usuario
        tokens = PushToken.objects.filter(
            usuario_id=user_id,
            activo=True
        ).values_list('token', flat=True)
        
        if not tokens:
            logger.warning(f"⚠️ No hay tokens push activos para usuario {user_id}")
            return {'enviados': 0, 'error': 'No hay tokens activos'}
        
        # Preparar mensajes para Expo
        mensajes = [
            {
                'to': token,
                'sound': 'default',
                'title': titulo or '💳 Recordatorio de Pago',
                'body': mensaje,
                'data': {
                    'type': 'recordatorio_pago',
                    'solicitud_id': str(solicitud_id)
                },
                'priority': 'high',
                'badge': 1
            }
            for token in tokens
        ]
        
        # Enviar a Expo Push Notification Service
        response = requests.post(
            'https://exp.host/--/api/v2/push/send',
            json=mensajes,
            headers={
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate',
                'Content-Type': 'application/json',
            },
            timeout=10
        )
        
        if response.status_code == 200:
            resultado = response.json()
            # Verificar si hay errores en la respuesta
            errores = [r for r in resultado.get('data', []) if r.get('status') == 'error']
            exitosos = [r for r in resultado.get('data', []) if r.get('status') == 'ok']
            
            # Desactivar tokens que dieron error
            if errores:
                for error in errores:
                    token_error = error.get('details', {}).get('expoPushToken')
                    if token_error:
                        PushToken.objects.filter(token=token_error).update(activo=False)
                        logger.warning(f"⚠️ Token inválido desactivado: {token_error[:20]}...")
            
            # Actualizar fecha de última notificación para tokens exitosos
            if exitosos:
                tokens_exitosos = [e.get('details', {}).get('expoPushToken') for e in exitosos if e.get('details', {}).get('expoPushToken')]
                PushToken.objects.filter(token__in=tokens_exitosos).update(
                    ultima_notificacion_enviada=timezone.now()
                )
            
            logger.info(f"✅ Push notifications enviadas para solicitud {solicitud_id}: {len(exitosos)} exitosas, {len(errores)} errores")
            return {
                'enviados': len(exitosos),
                'errores': len(errores),
                'total_tokens': len(tokens)
            }
        else:
            logger.error(f"❌ Error enviando push notifications: {response.status_code} - {response.text}")
            return {
                'enviados': 0,
                'error': f'HTTP {response.status_code}: {response.text[:200]}'
            }
            
    except requests.exceptions.Timeout:
        logger.error(f"❌ Timeout enviando push notifications para solicitud {solicitud_id}")
        return {'enviados': 0, 'error': 'Timeout'}
    except Exception as e:
        logger.error(f"❌ Error en tarea push notification: {e}", exc_info=True)
        return {'enviados': 0, 'error': str(e)}


@shared_task
def verificar_pagos_pendientes():
    """
    Tarea periódica que verifica solicitudes con pagos pendientes
    y envía recordatorios push
    """
    try:
        from .models import SolicitudServicioPublica
        
        ahora = timezone.now()
        ventana_6_horas = ahora + timedelta(hours=6)
        
        # Buscar solicitudes adjudicadas sin pago que venzan en las próximas 6 horas
        # NOTA: SolicitudServicioPublica NO tiene campo 'pago_realizado'
        # El estado del pago se refleja en el campo 'estado':
        # - 'adjudicada' = sin pago
        # - 'pendiente_pago' = procesando pago
        # - 'pagada' = pago completado
        solicitudes_pendientes = SolicitudServicioPublica.objects.filter(
            estado__in=['adjudicada', 'pendiente_pago'],  # Estados sin pago completado
            fecha_limite_pago__gte=ahora,  # Usar fecha_limite_pago en lugar de fecha_preferida
            fecha_limite_pago__lte=ventana_6_horas
        ).select_related('cliente__usuario')
        
        logger.info(f"🔍 Verificando pagos pendientes: {solicitudes_pendientes.count()} solicitudes encontradas")
        
        notificaciones_enviadas = 0
        
        for solicitud in solicitudes_pendientes:
            if solicitud.cliente and solicitud.cliente.usuario:
                # Usar fecha_limite_pago si existe, sino usar fecha_preferida como fallback
                fecha_limite = solicitud.fecha_limite_pago or solicitud.fecha_preferida
                if not fecha_limite:
                    continue  # Saltar si no hay fecha límite
                
                # Calcular tiempo restante
                tiempo_restante = fecha_limite - ahora
                if tiempo_restante.total_seconds() < 0:
                    continue  # Ya expiró
                    
                horas_restantes = int(tiempo_restante.total_seconds() / 3600)
                minutos_restantes = int((tiempo_restante.total_seconds() % 3600) / 60)
                
                # Solo enviar si faltan entre 5.5 y 6 horas (evitar duplicados)
                if 5.5 <= tiempo_restante.total_seconds() / 3600 <= 6:
                    mensaje = (
                        f"Tu solicitud #{solicitud.id} requiere pago antes de "
                        f"{fecha_limite.strftime('%d/%m/%Y a las %H:%M')}. "
                        f"Quedan {horas_restantes}h {minutos_restantes}m"
                    )
                    
                    enviar_push_notificacion_pago_pendiente.delay(
                        solicitud.id,
                        solicitud.cliente.usuario.id,
                        mensaje,
                        titulo='💳 Recordatorio de Pago'
                    )
                    notificaciones_enviadas += 1
        
        logger.info(f"✅ Verificación de pagos completada: {notificaciones_enviadas} notificaciones programadas")
        return {
            'solicitudes_revisadas': solicitudes_pendientes.count(),
            'notificaciones_enviadas': notificaciones_enviadas
        }
        
    except Exception as e:
        logger.error(f"❌ Error en verificar_pagos_pendientes: {e}", exc_info=True)
        return {'error': str(e)}


@shared_task
def enviar_alertas_pago_proximo_task():
    """
    Tarea Celery que ejecuta el comando de management para enviar alertas de pago próximo
    Incluye notificaciones push y WebSocket
    """
    try:
        logger.info("🔄 Ejecutando comando enviar_alertas_pago_proximo...")
        call_command('enviar_alertas_pago_proximo' )
        logger.info("✅ Comando enviar_alertas_pago_proximo ejecutado exitosamente")
        return {'status': 'success'}
    except Exception as e:
        logger.error(f"❌ Error ejecutando enviar_alertas_pago_proximo: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}


@shared_task
def enviar_notificacion_cambio_estado(solicitud_id, user_id, estado_anterior, estado_nuevo):
    """
    Push + notificación in-app cuando cambia el estado de una SolicitudServicioPublica.

    Usa send_expo_push_notification (cola 'default', throttle, receipt checking).
    Los mensajes incluyen contexto del proveedor, vehículo y tipo de servicio.
    """
    try:
        from mecanimovilapp.apps.usuarios.models import Notificacion, Usuario
        from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

        ESTADOS_CON_PUSH = {
            'adjudicada', 'pendiente_pago', 'pagada',
            'en_ejecucion', 'completada', 'cancelada', 'expirada',
        }
        if estado_nuevo not in ESTADOS_CON_PUSH:
            logger.debug(f"[cambio_estado] Estado {estado_nuevo} no requiere push")
            return {'enviados': 0, 'razon': 'estado_no_notificable'}

        # Obtener contexto rico de la solicitud
        try:
            from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica
            solicitud = SolicitudServicioPublica.objects.select_related(
                'vehiculo__marca', 'vehiculo__modelo',
                'oferta_seleccionada__proveedor',
            ).get(pk=solicitud_id)

            nombre_vehiculo = ""
            if solicitud.vehiculo:
                v = solicitud.vehiculo
                marca = getattr(v.marca, 'nombre', '') if v.marca else ''
                modelo = getattr(v.modelo, 'nombre', '') if v.modelo else ''
                nombre_vehiculo = f"{marca} {modelo}".strip() or f"Vehículo {v.patente or ''}"

            nombre_proveedor = ""
            try:
                oferta = solicitud.oferta_seleccionada
                if oferta and oferta.proveedor:
                    prov_user = oferta.proveedor
                    # Intentar nombre del taller si existe
                    taller = getattr(prov_user, 'taller', None)
                    if taller and getattr(taller, 'nombre_taller', ''):
                        nombre_proveedor = taller.nombre_taller
                    else:
                        nombre_proveedor = f"{prov_user.first_name} {prov_user.last_name}".strip()
            except Exception:
                pass

        except Exception:
            nombre_vehiculo = ""
            nombre_proveedor = ""

        # Plantillas enriquecidas con contexto
        def _t(titulo, cuerpo):
            return titulo, cuerpo

        ctx_vehiculo = f" para tu {nombre_vehiculo}" if nombre_vehiculo else ""
        ctx_proveedor = f" por {nombre_proveedor}" if nombre_proveedor else ""

        MENSAJES = {
            'adjudicada': _t(
                "✅ ¡Tu solicitud fue aceptada!",
                f"El proveedor{ctx_proveedor} aceptó tu solicitud{ctx_vehiculo}. "
                "Completa el pago para confirmar el servicio.",
            ),
            'pendiente_pago': _t(
                "💳 Pago pendiente",
                f"Tienes un pago pendiente{ctx_vehiculo}. "
                "Completa el pago para agendar el servicio.",
            ),
            'pagada': _t(
                "💳 Pago confirmado",
                f"Tu pago{ctx_vehiculo} fue confirmado. "
                f"El proveedor{ctx_proveedor} recibirá la notificación y coordinará el servicio.",
            ),
            'en_ejecucion': _t(
                "🔧 Servicio en progreso",
                f"El proveedor{ctx_proveedor} comenzó el servicio{ctx_vehiculo}. "
                "Puedes seguir el progreso en la app.",
            ),
            'completada': _t(
                "🎉 ¡Servicio completado!",
                f"El servicio{ctx_vehiculo} fue completado{ctx_proveedor}. "
                "¿Cómo fue tu experiencia? Deja tu reseña en la app.",
            ),
            'cancelada': _t(
                "❌ Solicitud cancelada",
                f"Tu solicitud{ctx_vehiculo} fue cancelada. "
                "Puedes crear una nueva solicitud cuando lo necesites.",
            ),
            'expirada': _t(
                "⏰ Solicitud expirada",
                f"Tu solicitud{ctx_vehiculo} expiró sin recibir ofertas. "
                "Intenta publicarla nuevamente con más detalles.",
            ),
        }

        titulo, cuerpo = MENSAJES[estado_nuevo]

        # In-app notification
        try:
            usuario_obj = Usuario.objects.get(pk=user_id)
            Notificacion.crear_unica(
                usuario=usuario_obj,
                tipo='order_update',
                titulo=titulo,
                mensaje=cuerpo,
                data={
                    'solicitud_id': str(solicitud_id),
                    'estado_anterior': estado_anterior,
                    'estado_nuevo': estado_nuevo,
                },
                ventana_horas=12,
                dedup_key={'solicitud_id': str(solicitud_id), 'estado': estado_nuevo},
            )
        except Exception as e:
            logger.error(f"[cambio_estado] Error in-app notif: {e}")

        # Push Expo via cola 'default' (con throttle y receipt checking)
        send_expo_push_notification.delay(
            user_id, titulo, cuerpo,
            {
                'type': 'cambio_estado',
                'solicitud_id': str(solicitud_id),
                'estado_anterior': estado_anterior,
                'estado_nuevo': estado_nuevo,
            },
        )

        logger.info(
            f"✅ [cambio_estado] Push encolada para solicitud {solicitud_id} "
            f"(usuario {user_id}): {estado_anterior} → {estado_nuevo}"
        )
        return {'enviados': 1}

    except Exception as e:
        logger.error(f"❌ Error en enviar_notificacion_cambio_estado: {e}", exc_info=True)
        return {'enviados': 0, 'error': str(e)}


@shared_task
def recordar_solicitudes_por_vencer_proveedor_task():
    """Tarea periódica: alertas de solicitudes por vencer para proveedores."""
    try:
        from mecanimovilapp.apps.ordenes.services.notificaciones_proveedor import (
            recordar_solicitudes_por_vencer_proveedor,
        )

        result = recordar_solicitudes_por_vencer_proveedor()
        logger.info('✅ recordar_solicitudes_por_vencer_proveedor: %s', result)
        return result
    except Exception as e:
        logger.error('❌ recordar_solicitudes_por_vencer_proveedor: %s', e, exc_info=True)
        return {'error': str(e)}


@shared_task
def revisar_seguimiento_pipeline_comercial_task():
    """Barrido periódico: recordatorios al taller por cotizaciones/agenda estancadas."""
    try:
        from django.db.models import F

        from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
            recalcular_leads_pipeline_periodico,
            umbrales_seguimiento_por_lead,
        )
        from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal
        from mecanimovilapp.apps.ordenes.services.notificaciones_pipeline import (
            HORAS_BORRADOR_LISTO_RECORDATORIO,
            notificar_agenda_pendiente_confirmacion,
            notificar_borrador_listo_sin_enviar,
            notificar_cotizacion_demorada_48h,
            notificar_cotizacion_sin_respuesta_24h,
        )

        now = timezone.now()
        umbral_borrador = now - timedelta(hours=HORAS_BORRADOR_LISTO_RECORDATORIO)
        umbral_agenda = now - timedelta(hours=24)

        stats = {
            'leads_recalculados': recalcular_leads_pipeline_periodico(),
            'borradores': 0,
            'sin_respuesta_24h': 0,
            'demoradas_48h': 0,
            'agenda_pendiente': 0,
        }

        for cot in CotizacionCanal.objects.filter(
            estado='borrador',
            actualizado_en__lte=umbral_borrador,
        ).iterator(chunk_size=100):
            meta = cot.metadata if isinstance(cot.metadata, dict) else {}
            if meta.get('listo_para_enviar'):
                notificar_borrador_listo_sin_enviar(cotizacion=cot)
                stats['borradores'] += 1

        enviadas_qs = (
            CotizacionCanal.objects.filter(estado='enviada')
            .select_related('conversation__lead_calificacion')
            .order_by(F('conversation__lead_calificacion__score').desc(nulls_last=True))
        )
        for cot in enviadas_qs.iterator(chunk_size=100):
            fecha_ref = cot.enviada_en or cot.actualizado_en or cot.creado_en
            if not fecha_ref:
                continue
            horas = max(0, (now - fecha_ref).total_seconds() / 3600)
            lead = None
            if cot.conversation_id:
                lead = getattr(cot.conversation, 'lead_calificacion', None)
            categoria = lead.categoria if lead else None
            horas_sin, horas_dem = umbrales_seguimiento_por_lead(categoria)
            if horas >= horas_dem and horas_dem < 900:
                notificar_cotizacion_demorada_48h(cotizacion=cot)
                stats['demoradas_48h'] += 1
            elif horas >= horas_sin:
                notificar_cotizacion_sin_respuesta_24h(cotizacion=cot)
                stats['sin_respuesta_24h'] += 1

        for cita in (
            CitaAgendaPersonal.objects.filter(
                estado='activa',
                horario_por_confirmar=True,
                fecha_actualizacion__lte=umbral_agenda,
            )
            .select_related('conversation_origen__lead_calificacion')
            .order_by(F('conversation_origen__lead_calificacion__score').desc(nulls_last=True))
            .iterator(chunk_size=100)
        ):
            notificar_agenda_pendiente_confirmacion(cita=cita)
            stats['agenda_pendiente'] += 1

        logger.info('✅ revisar_seguimiento_pipeline_comercial: %s', stats)
        return stats
    except Exception as e:
        logger.error('❌ revisar_seguimiento_pipeline_comercial: %s', e, exc_info=True)
        return {'error': str(e)}


@shared_task(bind=True, max_retries=1, default_retry_delay=30)
def buscar_precios_web_cotizacion_task(self, cotizacion_id: int):
    """Enriquece borrador con precios/marcas/tiendas vía Gemini URL Context.

    Solo modifica cotizaciones en estado=borrador. Upsert en PrecioRepuestoWeb,
    re-enriquece líneas y actualiza metadata.busqueda_web_estado.
    """
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from mecanimovilapp.apps.ordenes.models import CotizacionCanal, PrecioRepuestoWeb
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        buscar_repuestos_web,
        busqueda_web_habilitada,
        clave_cache_repuesto,
        cuota_diaria_disponible,
        nombres_sin_cache_vigente,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        enriquecer_repuestos_cotizacion,
        _clave_fuzzy,
        _mejor_hit,
        _nombre_con_marca,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        recalcular_totales,
    )

    def _set_estado(cot: CotizacionCanal, estado: str) -> None:
        meta = dict(cot.metadata or {})
        meta['busqueda_web_estado'] = estado
        meta['busqueda_web_en'] = timezone.now().isoformat()
        cot.metadata = meta
        cot.save(update_fields=['metadata', 'actualizado_en'])

    try:
        if not busqueda_web_habilitada():
            return {'ok': False, 'reason': 'disabled'}

        cot = CotizacionCanal.objects.filter(pk=cotizacion_id).first()
        if cot is None:
            return {'ok': False, 'reason': 'not_found'}
        if cot.estado != 'borrador':
            return {'ok': False, 'reason': 'not_borrador', 'estado': cot.estado}

        reps = list(cot.repuestos or [])
        if not isinstance(reps, list) or not reps:
            _set_estado(cot, 'sin_resultados')
            return {'ok': True, 'reason': 'sin_repuestos'}

        max_lineas = max(1, int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_MAX_LINEAS', 6) or 6))
        candidatos: list[dict] = []
        for rep in reps:
            if not isinstance(rep, dict):
                continue
            necesita = (
                bool(rep.get('precio_estimado', True))
                or not str(rep.get('marca_repuesto') or '').strip()
                or not str(rep.get('proveedor_nombre') or '').strip()
            )
            fuente = str(rep.get('fuente_marketplace') or '').strip()
            if fuente in ('catalogo', 'historial'):
                continue
            if necesita:
                candidatos.append(rep)
            if len(candidatos) >= max_lineas:
                break

        if not candidatos:
            _set_estado(cot, 'sin_resultados')
            return {'ok': True, 'reason': 'nada_que_buscar'}

        nombres = [str(r.get('nombre') or '').strip() for r in candidatos if str(r.get('nombre') or '').strip()]
        faltantes, cache_hits = nombres_sin_cache_vigente(
            nombres,
            marca_vehiculo=cot.vehiculo_marca or '',
            modelo_vehiculo=cot.vehiculo_modelo or '',
            anio=cot.vehiculo_anio or '',
        )
        resultados: dict = dict(cache_hits or {})

        # Solo gasta Gemini (y cuota diaria) en líneas sin hit vigente.
        if faltantes:
            if not cuota_diaria_disponible():
                if resultados:
                    # Hay cache parcial: aplica lo que hay y no marca error duro.
                    logger.info(
                        'buscar_precios_web_cotizacion_task(%s): RPD agotado; usa cache parcial',
                        cotizacion_id,
                    )
                else:
                    _set_estado(cot, 'error')
                    return {'ok': False, 'reason': 'rpd'}
            else:
                nuevos = buscar_repuestos_web(
                    faltantes,
                    vehiculo={
                        'marca': cot.vehiculo_marca or '',
                        'modelo': cot.vehiculo_modelo or '',
                        'anio': cot.vehiculo_anio or '',
                        'cilindraje': cot.vehiculo_cilindraje or '',
                        'tipo_motor': cot.tipo_motor or '',
                    },
                    servicio_nombre=cot.servicio_nombre or '',
                )
                if nuevos:
                    resultados.update(nuevos)
        else:
            logger.info(
                'buscar_precios_web_cotizacion_task(%s): cache hit completo (%s líneas), sin Gemini',
                cotizacion_id,
                len(nombres),
            )

        ttl_dias = max(1, int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_TTL_DIAS', 14) or 14))
        expira = timezone.now() + timedelta(days=ttl_dias)
        upserts = 0
        for clave_fuzzy, hit in (resultados or {}).items():
            if not isinstance(hit, dict):
                continue
            dominio = str(hit.get('dominio') or '').strip()[:200]
            if not dominio:
                continue
            clave = clave_cache_repuesto(
                hit.get('nombre_buscado') or hit.get('nombre_producto') or clave_fuzzy,
                marca_vehiculo=cot.vehiculo_marca or '',
                modelo_vehiculo=cot.vehiculo_modelo or '',
                anio=cot.vehiculo_anio or '',
            )
            PrecioRepuestoWeb.objects.update_or_create(
                clave=clave,
                dominio=dominio,
                defaults={
                    'nombre_producto': str(hit.get('nombre_producto') or '')[:200],
                    'marca_repuesto': str(hit.get('marca_repuesto') or '')[:100],
                    'precio_clp': int(hit.get('precio_clp') or 0),
                    'tienda': str(hit.get('tienda') or '')[:200],
                    'url': str(hit.get('url') or '')[:500],
                    'compatibilidad': str(hit.get('compatibilidad') or '')[:20],
                    'confianza': float(hit.get('confianza') or 0.8),
                    'expira_en': expira,
                },
            )
            upserts += 1

        # También indexar por clave fuzzy corta para match en enrich.
        for clave_fuzzy, hit in (resultados or {}).items():
            if not isinstance(hit, dict):
                continue
            dominio = str(hit.get('dominio') or '').strip()[:200]
            if not dominio or not clave_fuzzy:
                continue
            # Shortcut: fila adicional solo con clave de nombre (match más fácil).
            PrecioRepuestoWeb.objects.update_or_create(
                clave=clave_fuzzy[:240],
                dominio=dominio,
                defaults={
                    'nombre_producto': str(hit.get('nombre_producto') or '')[:200],
                    'marca_repuesto': str(hit.get('marca_repuesto') or '')[:100],
                    'precio_clp': int(hit.get('precio_clp') or 0),
                    'tienda': str(hit.get('tienda') or '')[:200],
                    'url': str(hit.get('url') or '')[:500],
                    'compatibilidad': str(hit.get('compatibilidad') or '')[:20],
                    'confianza': float(hit.get('confianza') or 0.8),
                    'expira_en': expira,
                },
            )

        reps_enriquecidos = enriquecer_repuestos_cotizacion(
            reps,
            marca_vehiculo=cot.vehiculo_marca or '',
            modelo_vehiculo=cot.vehiculo_modelo or '',
            anio_vehiculo=cot.vehiculo_anio or '',
            cilindraje=cot.vehiculo_cilindraje or '',
            tipo_motor=cot.tipo_motor or '',
            taller=cot.taller,
            usar_ml=False,
            usar_web=True,
        )

        # Si el enrich por cache no matcheó, aplicar hits directos por clave fuzzy.
        if resultados:
            for i, rep in enumerate(reps_enriquecidos):
                if str(rep.get('fuente_marketplace') or '') in ('catalogo', 'historial', 'web'):
                    continue
                q = _clave_fuzzy(str(rep.get('nombre') or ''))
                hit = resultados.get(q)
                if not hit:
                    # fuzzy best among resultados keys
                    cands = [
                        {
                            'clave': k,
                            'marca_repuesto': v.get('marca_repuesto'),
                            'precio_unitario_clp': v.get('precio_clp'),
                            'fuente_marketplace': 'web',
                            'proveedor_nombre': v.get('tienda'),
                            'url_producto': v.get('url'),
                            'confianza': v.get('confianza') or 0.8,
                        }
                        for k, v in resultados.items()
                        if isinstance(v, dict)
                    ]
                    best = _mejor_hit(str(rep.get('nombre') or ''), cands, min_score=55)
                    if not best:
                        continue
                    hit = {
                        'marca_repuesto': best.get('marca_repuesto'),
                        'precio_clp': best.get('precio_unitario_clp'),
                        'tienda': best.get('proveedor_nombre'),
                        'url': best.get('url_producto'),
                    }
                next_rep = dict(rep)
                if hit.get('marca_repuesto'):
                    next_rep['marca_repuesto'] = str(hit['marca_repuesto'])[:100]
                    next_rep['nombre'] = _nombre_con_marca(
                        str(next_rep.get('nombre') or ''),
                        hit['marca_repuesto'],
                    )
                if hit.get('tienda'):
                    next_rep['proveedor_nombre'] = str(hit['tienda'])[:200]
                if hit.get('url'):
                    next_rep['url_producto'] = str(hit['url'])[:500]
                precio = int(hit.get('precio_clp') or 0)
                if precio > 0 and (
                    bool(next_rep.get('precio_estimado', True))
                    or int(next_rep.get('precio_unitario_clp') or 0) <= 0
                ):
                    next_rep['precio_unitario_clp'] = precio
                    next_rep['precio_referencia_mercado'] = True
                    next_rep['precio_estimado'] = True
                next_rep['fuente_marketplace'] = 'web'
                reps_enriquecidos[i] = next_rep

        costo_rep, mo, total = recalcular_totales(
            reps_enriquecidos,
            int(cot.mano_obra_clp or 0),
        )
        meta = dict(cot.metadata or {})
        meta['busqueda_web_estado'] = 'ok' if (resultados or upserts) else 'sin_resultados'
        meta['busqueda_web_en'] = timezone.now().isoformat()
        meta['valores_estimativos'] = any(
            bool(r.get('precio_estimado', True)) for r in reps_enriquecidos
        ) if reps_enriquecidos else True

        cot.repuestos = reps_enriquecidos
        cot.costo_repuestos_clp = costo_rep
        cot.mano_obra_clp = mo
        cot.total_clp = total
        cot.metadata = meta
        cot.save(update_fields=[
            'repuestos',
            'costo_repuestos_clp',
            'mano_obra_clp',
            'total_clp',
            'metadata',
            'actualizado_en',
        ])
        return {
            'ok': True,
            'estado': meta['busqueda_web_estado'],
            'upserts': upserts,
            'hits': len(resultados or {}),
        }
    except Exception as exc:
        logger.warning(
            'buscar_precios_web_cotizacion_task(%s) falló: %s',
            cotizacion_id,
            exc,
            exc_info=True,
        )
        try:
            cot = CotizacionCanal.objects.filter(pk=cotizacion_id).first()
            if cot and cot.estado == 'borrador':
                _set_estado(cot, 'error')
        except Exception:
            pass
        return {'ok': False, 'error': str(exc)}

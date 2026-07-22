"""
Servicios de lógica de negocio para el sistema de Suscripciones Mensuales.
Gestiona la creación, acreditación y cancelación via MercadoPago Preapproval API.

IMPORTANTE:
- Este módulo es completamente independiente del sistema de compras únicas.
- La acreditación de créditos usa el mismo CreditoProveedor.saldo_creditos.
- La lógica del motor de cotizaciones (validación saldo >= costo) NO se altera.
"""
from django.utils import timezone
from django.db import transaction
from decouple import config
import logging
import requests as http_requests
import mercadopago

from .models import PlanSuscripcion, SuscripcionProveedor, CobroSuscripcion
from .creditos_services import obtener_credito_proveedor

logger = logging.getLogger(__name__)


def _get_mp_sdk():
    """Retorna el SDK de MercadoPago inicializado, igual que pagos/services.py."""
    token = config('MERCADOPAGO_ACCESS_TOKEN', default='')
    if not token:
        raise ValueError("MERCADOPAGO_ACCESS_TOKEN no está configurado")
    return mercadopago.SDK(token)


def obtener_detalle_pago_autorizado(authorized_payment_id):
    """
    Consulta GET /authorized_payments/{id} en MercadoPago y retorna
    los datos completos del cobro recurrente.

    Retorna dict con claves: preapproval_id, status, transaction_amount,
    currency_id, date_created, payment_id, etc.  O None si falla.

    IMPORTANTE: El caller DEBE verificar que response['status'] == 'approved'
    antes de acreditar créditos; el webhook se dispara tanto para pagos
    aprobados como para rechazados/pendientes.
    """
    token = config('MERCADOPAGO_ACCESS_TOKEN', default='')
    if not token:
        logger.error("[obtener_detalle_pago_autorizado] MERCADOPAGO_ACCESS_TOKEN no configurado")
        return None

    url = f"https://api.mercadopago.com/authorized_payments/{authorized_payment_id}"
    try:
        resp = http_requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            logger.info(
                f"[obtener_detalle_pago_autorizado] authorized_payment {authorized_payment_id}: "
                f"status={data.get('status')}, preapproval_id={data.get('preapproval_id')}, "
                f"amount={data.get('transaction_amount')}, payment={data.get('payment', {}).get('id')}"
            )
            return data
        else:
            logger.warning(
                f"[obtener_detalle_pago_autorizado] MP devolvió {resp.status_code} "
                f"para authorized_payment {authorized_payment_id}: {resp.text[:300]}"
            )
            return None
    except Exception as e:
        logger.error(f"[obtener_detalle_pago_autorizado] Error HTTP: {e}")
        return None


# Alias retrocompatible
def obtener_preapproval_id_desde_pago(authorized_payment_id):
    """Wrapper que retorna solo el preapproval_id (retrocompatibilidad)."""
    detalle = obtener_detalle_pago_autorizado(authorized_payment_id)
    if detalle:
        return detalle.get('preapproval_id')
    return None



def crear_suscripcion_mp(proveedor, plan_id):
    """
    Crea una suscripción (preapproval) en MercadoPago y registra en la BD.

    Flujo:
    1. Obtiene el plan activo.
    2. Si ya existe suscripción activa/pendiente, la retorna con su init_point.
    3. Llama a POST /preapproval de MP con back_url y auto_recurring.
    4. Guarda SuscripcionProveedor en estado 'pendiente'.
    5. Retorna el init_point para que el frontend abra el WebView.

    Args:
        proveedor: Usuario proveedor autenticado.
        plan_id: ID del PlanSuscripcion.

    Returns:
        dict: {
            'suscripcion_id': int,
            'init_point': str,
            'estado': str,
            'plan': dict
        }

    Raises:
        ValueError: Si el plan no existe o la API de MP falla.
    """
    # Obtener plan
    try:
        plan = PlanSuscripcion.objects.get(id=plan_id, activo=True)
    except PlanSuscripcion.DoesNotExist:
        raise ValueError("El plan no existe o no está disponible")

    # Si ya tiene suscripción ACTIVA o PAUSADA, retornar la existente (no crear nueva)
    suscripcion_activa = SuscripcionProveedor.objects.filter(
        proveedor=proveedor,
        estado__in=['activa', 'pausada']
    ).first()

    if suscripcion_activa:
        logger.info(
            f"Proveedor {proveedor.id} ya tiene suscripción activa/pausada "
            f"(ID: {suscripcion_activa.id})"
        )
        return {
            'suscripcion_id': suscripcion_activa.id,
            'init_point': suscripcion_activa.mp_init_point,
            'estado': suscripcion_activa.estado,
            'plan': _plan_to_dict(suscripcion_activa.plan),
            'ya_existia': True,
        }

    # Si hay una suscripción PENDIENTE (WebView abierto pero no se pagó),
    # cancelarla en MP y en BD para permitir un nuevo intento limpio.
    suscripcion_pendiente = SuscripcionProveedor.objects.filter(
        proveedor=proveedor,
        estado='pendiente'
    ).first()

    if suscripcion_pendiente:
        logger.info(
            f"Proveedor {proveedor.id}: cancelando suscripción pendiente abandonada "
            f"(ID: {suscripcion_pendiente.id}) para crear una nueva"
        )
        # Intentar cancelar en MP (sin bloquear si falla)
        if suscripcion_pendiente.mp_preapproval_id:
            try:
                sdk = _get_mp_sdk()
                sdk.preapproval().update(
                    suscripcion_pendiente.mp_preapproval_id,
                    {"status": "cancelled"}
                )
            except Exception as e:
                logger.warning(f"⚠️ No se pudo cancelar preapproval pendiente en MP: {e}")
        suscripcion_pendiente.estado = 'cancelada'
        suscripcion_pendiente.fecha_cancelacion = timezone.now()
        suscripcion_pendiente.save(update_fields=['estado', 'fecha_cancelacion', 'fecha_actualizacion'])

    # URLs para el flujo de suscripción
    webhook_base_url = config('WEBHOOK_BASE_URL', default='https://mecanimovil-api.onrender.com')
    back_url = f"{webhook_base_url}/suscripciones-resultado/"
    notification_url = f"{webhook_base_url}/api/suscripciones/webhook-preapproval/?source_news=webhooks"

    precio_entero = int(round(float(plan.precio)))
    currency_id = config('MERCADOPAGO_CURRENCY', default='CLP')
    # site_id MLC = MercadoPago Chile
    site_id = config('MERCADOPAGO_SITE_ID', default='MLC')

    # Obtener el email verificado de la cuenta MP del proveedor.
    # Si el proveedor ya conectó su cuenta MP vía OAuth, usamos ese email verificado.
    # Si no tiene cuenta MP conectada, usamos el email de registro como fallback.
    # MercadoPago Chile (MLC) requiere payer_email siempre en el preapproval.
    payer_email = None
    try:
        cuenta_mp = proveedor.cuenta_mercadopago
        if cuenta_mp and cuenta_mp.email_mp and cuenta_mp.estado == 'conectada':
            payer_email = cuenta_mp.email_mp
            logger.info(f"📧 Usando email MP verificado del proveedor: {payer_email}")
    except Exception:
        pass

    if not payer_email:
        payer_email = proveedor.email
        logger.info(f"📧 Usando email de registro del proveedor como fallback: {payer_email}")

    preapproval_data = {
        "reason": f"Suscripción MecaniMovil — {plan.nombre}",
        "payer_email": payer_email,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": precio_entero,
            "currency_id": currency_id,
        },
        "back_url": back_url,
        "notification_url": notification_url,
        "status": "pending",
    }

    if plan.mp_preapproval_plan_id:
        preapproval_data["preapproval_plan_id"] = plan.mp_preapproval_plan_id

    logger.info(
        f"📤 Creando preapproval MP para proveedor {proveedor.id}, plan '{plan.nombre}' "
        f"| precio={precio_entero} {currency_id} | site={site_id} | payer_email={payer_email}"
    )

    # Usar el SDK oficial de MP (igual que pagos/services.py) para que el
    # site_id sea inferido automáticamente desde el token del merchant.
    try:
        sdk = _get_mp_sdk()
        result = sdk.preapproval().create(preapproval_data)
        logger.info(f"📥 MP Preapproval SDK respuesta status={result.get('status')}: {str(result.get('response', {}))[:400]}")

        if result.get('status') not in [200, 201]:
            error_body = result.get('response', {})
            logger.error(f"❌ MP Preapproval rechazado [{result.get('status')}]: {error_body}")
            raise ValueError(f"MercadoPago rechazó la solicitud: {error_body}")

        mp_response = result.get('response', {})

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"❌ Error llamando a MP Preapproval SDK: {e}")
        raise ValueError(f"Error al comunicarse con MercadoPago: {str(e)}")

    preapproval_id = mp_response.get("id")
    init_point = mp_response.get("init_point")

    if not preapproval_id or not init_point:
        logger.error(f"❌ Respuesta inesperada de MP Preapproval: {mp_response}")
        raise ValueError("MercadoPago no retornó un ID de preapproval válido")

    logger.info(f"✅ Preapproval creado: {preapproval_id}")

    # Usar update_or_create porque SuscripcionProveedor tiene OneToOneField
    # en proveedor → solo puede existir UNA fila por proveedor en la BD.
    # Si ya existe (cancelada o cualquier estado), la actualizamos en lugar de crear.
    suscripcion, _ = SuscripcionProveedor.objects.update_or_create(
        proveedor=proveedor,
        defaults={
            'plan': plan,
            'estado': 'pendiente',
            'mp_preapproval_id': preapproval_id,
            'mp_init_point': init_point,
            'fecha_cancelacion': None,
        }
    )

    return {
        'suscripcion_id': suscripcion.id,
        'init_point': init_point,
        'estado': suscripcion.estado,
        'plan': _plan_to_dict(plan),
        'ya_existia': False,
    }


@transaction.atomic
def acreditar_creditos_suscripcion(preapproval_id, charge_id=None, pago_verificado=None):
    """
    Acredita créditos mensuales al proveedor SOLO cuando existe un cobro
    real verificado en MercadoPago (authorized_payment con status approved).

    REGLA ESTRICTA: charge_id es OBLIGATORIO y debe ser un ID numérico
    real de MercadoPago. No se acreditan créditos sin un cobro verificado.

    Idempotente: verifica contra processed_charge_ids (lista completa)
    para nunca acreditar el mismo cobro dos veces.

    Args:
        preapproval_id: ID del preapproval en MP.
        charge_id: ID del authorized_payment en MP (OBLIGATORIO).
        pago_verificado: dict con datos de verificar_pago_mp() para auditoría.
    """
    if not charge_id:
        logger.warning(f"[acreditar] Intento sin charge_id para {preapproval_id}. Rechazado.")
        return {'acreditado': False, 'motivo': 'charge_id obligatorio — no se acredita sin cobro real'}

    charge_id_str = str(charge_id)

    if not charge_id_str.isdigit():
        logger.warning(f"[acreditar] charge_id no numérico '{charge_id_str}' para {preapproval_id}. Rechazado.")
        return {'acreditado': False, 'motivo': f'charge_id inválido: {charge_id_str}'}

    try:
        suscripcion = SuscripcionProveedor.objects.select_for_update().get(
            mp_preapproval_id=preapproval_id
        )
    except SuscripcionProveedor.DoesNotExist:
        logger.warning(f"[acreditar] Suscripción {preapproval_id} no encontrada en BD")
        return {'acreditado': False, 'motivo': 'Suscripción no encontrada'}

    processed_ids = set(suscripcion.processed_charge_ids or [])

    if charge_id_str in processed_ids:
        logger.info(f"[acreditar] Charge {charge_id_str} ya procesado para {preapproval_id}")
        return {'acreditado': False, 'motivo': 'Cobro ya procesado'}

    if suscripcion.estado == 'pendiente':
        suscripcion.estado = 'activa'
        logger.info(f"[acreditar] Suscripción {preapproval_id} activada tras cobro {charge_id_str}")

    if suscripcion.estado not in ('activa', 'pendiente'):
        logger.warning(
            f"[acreditar] Suscripción {preapproval_id} en estado '{suscripcion.estado}', "
            f"no se acreditan créditos"
        )
        return {'acreditado': False, 'motivo': f"Estado inválido: {suscripcion.estado}"}

    creditos = suscripcion.plan.creditos_mensuales

    credito_proveedor = obtener_credito_proveedor(suscripcion.proveedor)
    credito_proveedor.saldo_creditos += creditos
    credito_proveedor.fecha_ultima_compra = timezone.now()
    credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_ultima_compra', 'fecha_actualizacion'])

    suscripcion.ultimo_charge_id = charge_id_str
    processed_ids.add(charge_id_str)
    suscripcion.processed_charge_ids = sorted(processed_ids)
    suscripcion.estado = 'activa'
    suscripcion.save(update_fields=['estado', 'ultimo_charge_id', 'processed_charge_ids', 'fecha_actualizacion'])

    # Guardar registro de auditoría si tenemos datos verificados
    if pago_verificado:
        from django.utils.dateparse import parse_datetime
        date_approved_str = pago_verificado.get('date_approved')
        date_approved = parse_datetime(date_approved_str) if date_approved_str else None

        CobroSuscripcion.objects.update_or_create(
            suscripcion=suscripcion,
            charge_id=charge_id_str,
            defaults={
                'payment_id': str(pago_verificado.get('payment_id', '')),
                'status': pago_verificado.get('status', ''),
                'status_detail': pago_verificado.get('status_detail', ''),
                'transaction_amount': pago_verificado.get('transaction_amount', 0),
                'net_received_amount': pago_verificado.get('net_received_amount'),
                'currency_id': pago_verificado.get('currency_id', 'CLP'),
                'collector_id': pago_verificado.get('collector_id', 0),
                'payer_email': pago_verificado.get('payer_email', ''),
                'payer_id': str(pago_verificado.get('payer_id', '')),
                'card_last_four': pago_verificado.get('card_last_four', ''),
                'payment_method': pago_verificado.get('payment_type_id', ''),
                'date_approved': date_approved,
                'creditos_otorgados': creditos,
            },
        )

    logger.info(
        f"[acreditar] +{creditos} créditos para proveedor {suscripcion.proveedor.id} "
        f"(preapproval={preapproval_id}, charge_mp={charge_id_str}). "
        f"Nuevo saldo: {credito_proveedor.saldo_creditos}. "
        f"Cobros procesados: {len(processed_ids)}"
    )

    proveedor_id = suscripcion.proveedor_id

    def _intentar_adjudicaciones_pendientes():
        try:
            from django.contrib.auth import get_user_model
            from mecanimovilapp.apps.ordenes.services.adjudicacion_publica import (
                reintentar_adjudicaciones_pendientes_tras_acreditacion,
            )

            User = get_user_model()
            prov = User.objects.get(pk=proveedor_id)
            reintentar_adjudicaciones_pendientes_tras_acreditacion(prov)
        except Exception as hook_err:
            logger.error(
                f"Hook adjudicaciones tras suscripción (proveedor {proveedor_id}): {hook_err}",
                exc_info=True,
            )

    transaction.on_commit(_intentar_adjudicaciones_pendientes)

    return {
        'acreditado': True,
        'creditos': creditos,
        'saldo_nuevo': credito_proveedor.saldo_creditos,
        'proveedor_id': suscripcion.proveedor.id,
        'charge_id': charge_id_str,
    }


def cancelar_suscripcion(proveedor):
    """
    Cancela la suscripción activa del proveedor en MP y en la BD.

    Args:
        proveedor: Usuario proveedor.

    Returns:
        dict: { 'cancelada': bool, 'mensaje': str }
    """
    try:
        suscripcion = SuscripcionProveedor.objects.get(
            proveedor=proveedor,
            estado__in=['activa', 'pendiente', 'pausada']
        )
    except SuscripcionProveedor.DoesNotExist:
        return {'cancelada': False, 'mensaje': 'No tienes una suscripción activa para cancelar'}

    # Cancelar en MercadoPago via SDK
    if suscripcion.mp_preapproval_id:
        try:
            sdk = _get_mp_sdk()
            result = sdk.preapproval().update(
                suscripcion.mp_preapproval_id,
                {"status": "cancelled"}
            )
            if result.get('status') not in (200, 201):
                logger.warning(
                    f"⚠️ MP devolvió {result.get('status')} al cancelar "
                    f"preapproval {suscripcion.mp_preapproval_id}: {result.get('response')}"
                )
            else:
                logger.info(f"✅ Preapproval {suscripcion.mp_preapproval_id} cancelado en MP")
        except Exception as e:
            logger.error(f"❌ Error cancelando preapproval en MP: {e}")
            # No bloqueamos la cancelación local si MP falla

    suscripcion.estado = 'cancelada'
    suscripcion.fecha_cancelacion = timezone.now()
    suscripcion.save(update_fields=['estado', 'fecha_cancelacion', 'fecha_actualizacion'])

    logger.info(f"✅ Suscripción {suscripcion.id} cancelada para proveedor {proveedor.id}")
    return {'cancelada': True, 'mensaje': 'Suscripción cancelada exitosamente'}


def sincronizar_estado_suscripcion(suscripcion):
    """
    Sincroniza el estado de una suscripción consultando la API de MP.
    Usada principalmente por la tarea Celery diaria.

    Args:
        suscripcion: Instancia de SuscripcionProveedor.

    Returns:
        tuple: (estado_str, cobros_list) — el estado actualizado y lista de resultados de cobros procesados.
    """
    if not suscripcion.mp_preapproval_id:
        return suscripcion.estado, []

    try:
        sdk = _get_mp_sdk()
        result = sdk.preapproval().get(suscripcion.mp_preapproval_id)

        if result.get('status') != 200:
            logger.warning(
                f"MP devolvió {result.get('status')} al consultar "
                f"preapproval {suscripcion.mp_preapproval_id}"
            )
            return suscripcion.estado, []

        mp_data = result.get('response', {})
        mp_status = mp_data.get("status", "")

        # Mapear estados de MP a estados locales
        STATUS_MAP = {
            "authorized": "activa",
            "pending": "pendiente",
            "paused": "pausada",
            "cancelled": "cancelada",
        }
        nuevo_estado = STATUS_MAP.get(mp_status, suscripcion.estado)

        if nuevo_estado != suscripcion.estado:
            logger.info(
                f"🔄 Suscripción {suscripcion.id}: {suscripcion.estado} → {nuevo_estado} "
                f"(MP status: {mp_status})"
            )
            suscripcion.estado = nuevo_estado
            if nuevo_estado == 'cancelada' and not suscripcion.fecha_cancelacion:
                suscripcion.fecha_cancelacion = timezone.now()
            suscripcion.save(update_fields=['estado', 'fecha_cancelacion', 'fecha_actualizacion'])

        # Actualizar fecha_proximo_cobro si viene en la respuesta
        next_payment = mp_data.get("next_payment_date") or mp_data.get("auto_recurring", {}).get("next_payment_date")
        if next_payment:
            from django.utils.dateparse import parse_datetime
            fecha = parse_datetime(next_payment)
            if fecha and fecha != suscripcion.fecha_proximo_cobro:
                suscripcion.fecha_proximo_cobro = fecha
                suscripcion.save(update_fields=['fecha_proximo_cobro', 'fecha_actualizacion'])

        # Si la suscripción está activa, sincronizar posibles cobros pendientes de acreditar
        cobros_res = []
        if suscripcion.estado == 'activa':
            cobros_res = sincronizar_cobros_preapproval(suscripcion.mp_preapproval_id)

        return suscripcion.estado, cobros_res

    except Exception as e:
        logger.error(f"❌ Error sincronizando suscripción {suscripcion.id}: {e}")
        return suscripcion.estado, []


def obtener_suscripcion_activa(proveedor):
    """
    Obtiene la suscripción activa/pendiente del proveedor, o None.

    Args:
        proveedor: Usuario proveedor.

    Returns:
        SuscripcionProveedor | None
    """
    # Solo 'activa' y 'pausada' cuentan como suscripción vigente.
    # 'pendiente' = WebView abierto pero sin pagar → NO es suscripción activa.
    return SuscripcionProveedor.objects.filter(
        proveedor=proveedor,
        estado__in=['activa', 'pausada']
    ).select_related('plan').first()


def _plan_to_dict(plan):
    """Helper para serializar un PlanSuscripcion a dict."""
    return {
        'id': plan.id,
        'nombre': plan.nombre,
        'descripcion': plan.descripcion,
        'precio': float(plan.precio),
        'creditos_mensuales': plan.creditos_mensuales,
        'cotizaciones_ia_mensuales': plan.cotizaciones_ia_mensuales,
        'diagnosticos_ia_mensuales': plan.diagnosticos_ia_mensuales,
        'consultas_patente_mensuales': plan.consultas_patente_mensuales,
        'canales_mensajeria_max': plan.canales_mensajeria_max,
        'conversaciones_salientes_max': plan.conversaciones_salientes_max,
        'overage_cotizaciones_por_credito': plan.overage_cotizaciones_por_credito,
        'overage_diagnosticos_por_credito': plan.overage_diagnosticos_por_credito,
        'overage_patentes_por_credito': plan.overage_patentes_por_credito,
        'acceso_endpoints_patente_pro': plan.acceso_endpoints_patente_pro,
        'destacado': plan.destacado,
    }


@transaction.atomic
def sincronizar_suscripcion_por_email(proveedor):
    """
    Sincroniza el estado de la suscripción del proveedor consultando directamente
    la API de MercadoPago por el email de su cuenta MP conectada.

    Útil cuando el webhook no llegó pero el proveedor ya autorizó el preapproval:
    - Busca preapprovals asociados al payer_email del proveedor
    - Si encuentra uno con status 'authorized' → activa la suscripción local
    - Si la suscripción local tiene mp_preapproval_id, la sincroniza directamente

    Args:
        proveedor: Usuario proveedor autenticado.

    Returns:
        dict: {
            'sincronizado': bool,
            'estado': str,
            'mensaje': str,
            'suscripcion_id': int | None,
        }
    """
    # 1. Obtener email MP del proveedor
    payer_email = None
    try:
        cuenta_mp = proveedor.cuenta_mercadopago
        if cuenta_mp and cuenta_mp.email_mp and cuenta_mp.estado == 'conectada':
            payer_email = cuenta_mp.email_mp
    except Exception:
        pass

    if not payer_email:
        payer_email = proveedor.email
        logger.info(f"📧 Usando email de registro como fallback para sincronización: {payer_email}")

    logger.info(f"🔄 Sincronizando suscripción para proveedor {proveedor.id} (email: {payer_email})")

    sdk = _get_mp_sdk()

    # 2. Si ya tenemos un preapproval_id local, sincronizarlo directamente (más rápido)
    suscripcion_local = SuscripcionProveedor.objects.filter(
        proveedor=proveedor
    ).exclude(estado__in=['cancelada', 'expirada']).select_related('plan').first()

    if suscripcion_local and suscripcion_local.mp_preapproval_id:
        logger.info(
            f"🔍 Sincronizando preapproval local {suscripcion_local.mp_preapproval_id} "
            f"directo desde MP..."
        )
        estado_anterior = suscripcion_local.estado
        estado_actualizado, cobros_res = sincronizar_estado_suscripcion(suscripcion_local)
        suscripcion_local.refresh_from_db()

        if estado_actualizado == 'activa' and estado_anterior != 'activa':
            logger.info(
                f"✅ Suscripción {suscripcion_local.id} activada vía sincronización directa "
                f"(preapproval: {suscripcion_local.mp_preapproval_id})"
            )
            return {
                'sincronizado': True,
                'estado': 'activa',
                'mensaje': '¡Suscripción activada! Tu suscripción fue autorizada en Mercado Pago.',
                'suscripcion_id': suscripcion_local.id,
                'cobros_procesados': cobros_res
            }

        if estado_actualizado == 'activa':
            return {
                'sincronizado': True,
                'estado': 'activa',
                'mensaje': 'Tu suscripción está activa.',
                'suscripcion_id': suscripcion_local.id,
                'cobros_procesados': cobros_res
            }

        if estado_actualizado in ('cancelada', 'expirada'):
            return {
                'sincronizado': True,
                'estado': estado_actualizado,
                'mensaje': f'Tu suscripción fue {estado_actualizado} en Mercado Pago.',
                'suscripcion_id': suscripcion_local.id,
            }

    # 3. Buscar preapprovals en MP por payer_email (descubre suscripciones
    #    autorizadas que no están en la BD o cuyo webhook no llegó)
    logger.info(f"🔍 Buscando preapprovals en MP para email: {payer_email}")
    try:
        result = sdk.preapproval().search({
            "payer_email": payer_email,
            "status": "authorized",
            "limit": 10,
        })

        if result.get('status') not in [200, 201]:
            logger.warning(
                f"⚠️ MP devolvió {result.get('status')} al buscar preapprovals "
                f"por email {payer_email}"
            )
            # Si no pudimos buscar por email, retornar el estado actual
            return {
                'sincronizado': False,
                'estado': suscripcion_local.estado if suscripcion_local else 'sin_suscripcion',
                'mensaje': 'No se pudo verificar el estado en Mercado Pago. Inténtalo más tarde.',
                'suscripcion_id': suscripcion_local.id if suscripcion_local else None,
            }

        preapprovals = result.get('response', {}).get('results', [])
        logger.info(f"📦 MP devolvió {len(preapprovals)} preapprovals autorizados para {payer_email}")

    except Exception as e:
        logger.error(f"❌ Error buscando preapprovals en MP: {e}")
        return {
            'sincronizado': False,
            'estado': suscripcion_local.estado if suscripcion_local else 'sin_suscripcion',
            'mensaje': 'Error al contactar Mercado Pago. Inténtalo más tarde.',
            'suscripcion_id': suscripcion_local.id if suscripcion_local else None,
        }

    for preapproval in preapprovals:
        preapproval_id = preapproval.get('id')
        mp_status = preapproval.get('status', '')

        if mp_status != 'authorized':
            continue

        # Buscar suscripción local por preapproval_id
        suscripcion = SuscripcionProveedor.objects.filter(
            mp_preapproval_id=preapproval_id
        ).select_related('plan').first()

        if not suscripcion:
            # El preapproval existe en MP pero no en BD → puede ser de otro acceso
            logger.warning(
                f"⚠️ Preapproval {preapproval_id} autorizado en MP pero no existe en BD local"
            )
            continue

        # Activar la suscripción si estaba pendiente
        if suscripcion.estado != 'activa':
            logger.info(
                f"✅ Activando suscripción {suscripcion.id} (preapproval {preapproval_id}) "
                f"via sincronización por email"
            )
            suscripcion.estado = 'activa'

            # Actualizar fecha_proximo_cobro si MP la envía
            next_payment = (
                preapproval.get('next_payment_date') or
                preapproval.get('auto_recurring', {}).get('next_payment_date')
            )
            if next_payment:
                from django.utils.dateparse import parse_datetime
                fecha = parse_datetime(next_payment)
                if fecha:
                    suscripcion.fecha_proximo_cobro = fecha

            suscripcion.save(update_fields=['estado', 'fecha_proximo_cobro', 'fecha_actualizacion'])

            # Sincronizar cobros inmediatamente después de activar
            cobros_res = sincronizar_cobros_preapproval(preapproval_id)

            return {
                'sincronizado': True,
                'estado': 'activa',
                'mensaje': '¡Suscripción activada! Mercado Pago confirmó la autorización.',
                'suscripcion_id': suscripcion.id,
                'cobros_procesados': cobros_res
            }

        # Ya estaba activa, sincronizar cobros por si acaso
        cobros_res = sincronizar_cobros_preapproval(preapproval_id)
        return {
            'sincronizado': True,
            'estado': 'activa',
            'mensaje': 'Tu suscripción está activa en Mercado Pago.',
            'suscripcion_id': suscripcion.id,
            'cobros_procesados': cobros_res
        }

    # No se encontraron preapprovals autorizados
    return {
        'sincronizado': False,
        'estado': suscripcion_local.estado if suscripcion_local else 'sin_suscripcion',
        'mensaje': (
            'No se encontraron suscripciones autorizadas en Mercado Pago para tu cuenta. '
            'Si realizaste un pago, puede tardar unos minutos en procesarse.'
        ),
        'suscripcion_id': suscripcion_local.id if suscripcion_local else None,
    }


MECANIMOVIL_COLLECTOR_ID = int(config('MERCADOPAGO_COLLECTOR_ID', default='2679548244'))


def _mp_headers():
    token = config('MERCADOPAGO_ACCESS_TOKEN', default='')
    if not token:
        raise ValueError("MERCADOPAGO_ACCESS_TOKEN no configurado")
    return {"Authorization": f"Bearer {token}"}


def buscar_cobros_mp(preapproval_id):
    """
    Busca authorized_payments (cobros recurrentes) en MercadoPago para un
    preapproval específico usando el endpoint oficial:
      GET /authorized_payments/search?preapproval_id={id}

    Retorna lista de dicts con los cobros, o [] si falla / no hay cobros.
    """
    try:
        headers = _mp_headers()
    except ValueError as e:
        logger.error(f"[buscar_cobros_mp] {e}")
        return []

    url = "https://api.mercadopago.com/authorized_payments/search"
    params = {"preapproval_id": preapproval_id}
    try:
        resp = http_requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get('results', [])
            logger.info(
                f"[buscar_cobros_mp] MP retornó {len(results)} cobros "
                f"para preapproval {preapproval_id}"
            )
            return results
        else:
            logger.warning(
                f"[buscar_cobros_mp] MP devolvió HTTP {resp.status_code} "
                f"para preapproval {preapproval_id}: {resp.text[:500]}"
            )
            return []
    except Exception as e:
        logger.error(f"[buscar_cobros_mp] Error HTTP: {e}")
        return []


def verificar_pago_mp(payment_id):
    """
    VERIFICACIÓN ANTI-FRAUDE: Consulta GET /v1/payments/{id} para obtener
    la prueba definitiva de que el dinero fue cobrado y acreditado al
    collector (Mecanimovil).

    Retorna dict con los campos esenciales, o None si no se pudo verificar.
    Verifica:
      1. payment.status == 'approved'
      2. payment.status_detail == 'accredited'
      3. payment.collector_id == MECANIMOVIL_COLLECTOR_ID
    """
    try:
        headers = _mp_headers()
    except ValueError as e:
        logger.error(f"[verificar_pago_mp] {e}")
        return None

    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    try:
        resp = http_requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                f"[verificar_pago_mp] MP devolvió HTTP {resp.status_code} "
                f"para payment {payment_id}: {resp.text[:300]}"
            )
            return None

        p = resp.json()
        resultado = {
            'payment_id': p.get('id'),
            'status': p.get('status'),
            'status_detail': p.get('status_detail'),
            'transaction_amount': p.get('transaction_amount'),
            'currency_id': p.get('currency_id'),
            'collector_id': p.get('collector_id'),
            'payer_email': (p.get('payer') or {}).get('email'),
            'payer_id': (p.get('payer') or {}).get('id'),
            'card_last_four': (p.get('card') or {}).get('last_four_digits'),
            'payment_method_id': p.get('payment_method_id'),
            'payment_type_id': p.get('payment_type_id'),
            'date_approved': p.get('date_approved'),
            'date_created': p.get('date_created'),
            'net_received_amount': (p.get('transaction_details') or {}).get('net_received_amount'),
            'operation_type': p.get('operation_type'),
        }

        logger.info(
            f"[verificar_pago_mp] Payment #{payment_id}: "
            f"status={resultado['status']}, detail={resultado['status_detail']}, "
            f"collector={resultado['collector_id']}, amount={resultado['transaction_amount']}, "
            f"card=***{resultado['card_last_four']}"
        )
        return resultado

    except Exception as e:
        logger.error(f"[verificar_pago_mp] Error HTTP: {e}")
        return None


def sincronizar_cobros_preapproval(preapproval_id):
    """
    Busca cobros REALES en MercadoPago para un preapproval y acredita créditos
    con VERIFICACIÓN ANTI-FRAUDE DE DOBLE NIVEL:

      Nivel 1: authorized_payment.status in (approved, processed, authorized)
      Nivel 2: GET /v1/payments/{payment_id} confirma:
               - status == 'approved'
               - status_detail == 'accredited'
               - collector_id == cuenta Mecanimovil

    NUNCA otorga créditos sin un charge_id numérico real y verificado.
    """
    if not preapproval_id:
        return []

    logger.info(f"[sincronizar_cobros] Buscando cobros reales para preapproval {preapproval_id}...")

    try:
        suscripcion = SuscripcionProveedor.objects.filter(
            mp_preapproval_id=preapproval_id
        ).select_related('plan').first()
        precio_plan = float(suscripcion.plan.precio) if suscripcion else None
    except Exception:
        precio_plan = None

    try:
        pagos = buscar_cobros_mp(preapproval_id)
        resultados = []

        for pago in pagos:
            charge_id = pago.get('id')
            mp_status = pago.get('status')
            monto = pago.get('transaction_amount')
            fecha = pago.get('date_created', pago.get('debit_date', ''))
            payment_obj = pago.get('payment') or {}
            payment_id = payment_obj.get('id')
            payment_status = payment_obj.get('status')

            logger.info(
                f"[sincronizar_cobros] Cobro MP #{charge_id}: "
                f"status={mp_status}, monto={monto}, fecha={fecha}, "
                f"payment_id={payment_id}, payment_status={payment_status}"
            )

            if mp_status not in ('authorized', 'processed', 'approved') or not charge_id:
                logger.info(
                    f"[sincronizar_cobros] Cobro #{charge_id} con status '{mp_status}' "
                    f"NO es elegible para acreditación (Nivel 1 fallido)"
                )
                continue

            # NIVEL 2: Verificar el pago real en /v1/payments/
            if not payment_id:
                logger.warning(
                    f"[sincronizar_cobros] Cobro #{charge_id} no tiene payment_id. "
                    f"No se puede verificar el pago real."
                )
                continue

            pago_verificado = verificar_pago_mp(payment_id)
            if not pago_verificado:
                logger.warning(
                    f"[sincronizar_cobros] No se pudo verificar payment {payment_id} "
                    f"para cobro #{charge_id}. Créditos NO otorgados."
                )
                continue

            if pago_verificado['status'] != 'approved':
                logger.warning(
                    f"[sincronizar_cobros] Payment {payment_id} status='{pago_verificado['status']}' "
                    f"(no es approved). Créditos NO otorgados."
                )
                continue

            if pago_verificado['status_detail'] != 'accredited':
                logger.warning(
                    f"[sincronizar_cobros] Payment {payment_id} status_detail='{pago_verificado['status_detail']}' "
                    f"(no es accredited). Créditos NO otorgados."
                )
                continue

            if pago_verificado['collector_id'] != MECANIMOVIL_COLLECTOR_ID:
                logger.error(
                    f"[sincronizar_cobros] ALERTA FRAUDE: Payment {payment_id} "
                    f"collector_id={pago_verificado['collector_id']} != {MECANIMOVIL_COLLECTOR_ID}. "
                    f"Créditos RECHAZADOS."
                )
                continue

            if precio_plan and pago_verificado['transaction_amount'] != precio_plan:
                logger.warning(
                    f"[sincronizar_cobros] Payment {payment_id} amount={pago_verificado['transaction_amount']} "
                    f"!= plan price={precio_plan}. Verificar manualmente."
                )

            logger.info(
                f"[sincronizar_cobros] ✅ Cobro #{charge_id} VERIFICADO: "
                f"payment={payment_id}, status=approved/accredited, "
                f"collector={MECANIMOVIL_COLLECTOR_ID}, "
                f"card=***{pago_verificado.get('card_last_four')}, "
                f"net=${pago_verificado.get('net_received_amount')}"
            )

            try:
                res = acreditar_creditos_suscripcion(
                    preapproval_id,
                    charge_id=str(charge_id),
                    pago_verificado=pago_verificado,
                )
                if res.get('acreditado'):
                    res['verificacion'] = {
                        'payment_id': payment_id,
                        'card_last_four': pago_verificado.get('card_last_four'),
                        'net_received': pago_verificado.get('net_received_amount'),
                        'date_approved': pago_verificado.get('date_approved'),
                        'payer_email': pago_verificado.get('payer_email'),
                    }
                resultados.append(res)
            except Exception as e:
                logger.error(f"[sincronizar_cobros] Error acreditando cobro {charge_id}: {e}")

        if not resultados:
            logger.info(
                f"[sincronizar_cobros] Sin cobros nuevos para acreditar en {preapproval_id}. "
                f"Solo se otorgan créditos contra cobros reales verificados en MP."
            )

        return resultados

    except Exception as e:
        logger.error(f"[sincronizar_cobros] Error crítico para {preapproval_id}: {e}")
        return []

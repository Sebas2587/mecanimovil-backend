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
import mercadopago
from mercadopago.core import MPBase

from .models import PlanSuscripcion, SuscripcionProveedor
from .creditos_services import obtener_credito_proveedor

logger = logging.getLogger(__name__)


def _get_mp_sdk():
    """Retorna el SDK de MercadoPago inicializado, igual que pagos/services.py."""
    token = config('MERCADOPAGO_ACCESS_TOKEN', default='')
    if not token:
        raise ValueError("MERCADOPAGO_ACCESS_TOKEN no está configurado")
    return mercadopago.SDK(token)





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
    notification_url = f"{webhook_base_url}/api/suscripciones/webhook-preapproval/"

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
def acreditar_creditos_suscripcion(preapproval_id, charge_id=None, force_initial=False):
    """
    Acredita créditos mensuales al proveedor cuando MercadoPago confirma
    un cobro recurrente (evento subscription_authorized_payment).

    Idempotente: si el charge_id ya fue procesado, no acredita de nuevo.

    Args:
        preapproval_id: ID del preapproval en MP.
        charge_id: ID del cobro específico (para idempotencia).
        force_initial: Si es True, acredita los créditos del plan incluso si no hay charge_id.
                       Se usa solo para la activación inicial garantizada.
    """
    try:
        suscripcion = SuscripcionProveedor.objects.select_for_update().get(
            mp_preapproval_id=preapproval_id
        )
    except SuscripcionProveedor.DoesNotExist:
        logger.warning(f"⚠️ Suscripción {preapproval_id} no encontrada en BD")
        return {'acreditado': False, 'motivo': 'Suscripción no encontrada'}

    # Si es carga inicial forzada y ya tiene cobros registrados, ignorar para evitar duplicidad
    if force_initial:
        if suscripcion.ultimo_charge_id:
            logger.info(f"ℹ️ Suscripción {preapproval_id} ya tiene créditos acreditados (charge: {suscripcion.ultimo_charge_id})")
            return {'acreditado': False, 'motivo': 'Ya tiene créditos acreditados'}
        charge_id = 'inicial_autorizacion'
        logger.info(f"🚀 Iniciando acreditación inicial forzada para {preapproval_id}")

    # Idempotencia: no procesar dos veces el mismo cobro
    if charge_id and suscripcion.ultimo_charge_id == str(charge_id):
        logger.info(f"ℹ️ Charge {charge_id} ya fue procesado para suscripción {preapproval_id}")
        return {'acreditado': False, 'motivo': 'Cobro ya procesado'}

    # Activar suscripción si estaba pendiente
    if suscripcion.estado == 'pendiente':
        suscripcion.estado = 'activa'
        logger.info(f"✅ Suscripción {preapproval_id} activada tras primer cobro")

    if suscripcion.estado not in ('activa', 'pendiente'):
        logger.warning(f"⚠️ Suscripción {preapproval_id} en estado '{suscripcion.estado}', no se acreditan créditos")
        return {'acreditado': False, 'motivo': f"Estado inválido: {suscripcion.estado}"}

    creditos = suscripcion.plan.creditos_mensuales

    # Sumar créditos al saldo del proveedor
    credito_proveedor = obtener_credito_proveedor(suscripcion.proveedor)
    credito_proveedor.saldo_creditos += creditos
    credito_proveedor.fecha_ultima_compra = timezone.now()
    credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_ultima_compra', 'fecha_actualizacion'])

    # Actualizar suscripción
    if charge_id:
        suscripcion.ultimo_charge_id = str(charge_id)
    suscripcion.estado = 'activa'
    suscripcion.save(update_fields=['estado', 'ultimo_charge_id', 'fecha_actualizacion'])

    logger.info(
        f"✅ Créditos acreditados: {creditos} para proveedor {suscripcion.proveedor.id} "
        f"(preapproval: {preapproval_id}, charge: {charge_id}). Nuevo saldo: {credito_proveedor.saldo_creditos}"
    )

    return {
        'acreditado': True,
        'creditos': creditos,
        'saldo_nuevo': credito_proveedor.saldo_creditos,
        'proveedor_id': suscripcion.proveedor.id,
        'charge_id': charge_id
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
        str: Estado actualizado de la suscripción.
    """
    if not suscripcion.mp_preapproval_id:
        return suscripcion.estado

    try:
        sdk = _get_mp_sdk()
        result = sdk.preapproval().get(suscripcion.mp_preapproval_id)

        if result.get('status') != 200:
            logger.warning(
                f"⚠️ MP devolvió {result.get('status')} al consultar "
                f"preapproval {suscripcion.mp_preapproval_id}"
            )
            return suscripcion.estado

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


class PreapprovalPayment(MPBase):
    """
    Clase auxiliar para extender el SDK de Mercado Pago (v2.2.0) que no incluye 
    el cliente para /preapproval_payment/search.
    """
    def search(self, filters=None, request_options=None):
        return self._get(uri="/preapproval_payment/search", filters=filters, request_options=request_options)


def sincronizar_cobros_preapproval(preapproval_id):
    """
    Busca cobros/pagos en MercadoPago para un preapproval específico
    y los procesa para acreditar créditos si aún no han sido procesados.

    Sincroniza estados: 'authorized', 'processed' y 'approved'.
    """
    if not preapproval_id:
        return []

    logger.info(f"🔍 Iniciando sincronización de cobros para preapproval {preapproval_id}...")
    
    try:
        sdk = _get_mp_sdk()
        
        # Instanciar nuestro cliente auxiliar para buscar pagos de preapproval
        pp_client = PreapprovalPayment(sdk.request_options, sdk.http_client)
        
        # Buscar pagos asociados a este preapproval sin filtro de estado estricto
        # para ver qué está devolviendo MP exactamente.
        result = pp_client.search({
            "preapproval_id": preapproval_id,
            "limit": 20,
        })

        if result.get('status') not in [200, 201]:
            logger.warning(f"⚠️ Error al buscar cobros para {preapproval_id} en MP: {result.get('status')}")
            return [{'error': f"MP Error {result.get('status')}", 'debug': result.get('response')}]

        pagos = result.get('response', {}).get('results', [])
        logger.info(f"📦 Se encontraron {len(pagos)} cobros en total para {preapproval_id}")
        
        # Log del primer pago para debug si existe
        if pagos:
            logger.info(f"🧪 Datos del primer cobro: {pagos[0]}")

        resultados = []
        for pago in pagos:
            charge_id = pago.get('id')
            mp_status = pago.get('status')
            monto = pago.get('transaction_amount')
            
            logger.info(f"📋 Analizando cobro MP {charge_id} con estado '{mp_status}' y monto {monto}")

            # Consideramos exitosos 'authorized', 'processed' y 'approved'
            if mp_status not in ('authorized', 'processed', 'approved'):
                logger.info(f"⏭️ Saltando cobro {charge_id} por estado no exitoso: {mp_status}")
                continue
            
            if not charge_id:
                continue
            
            # Intentar acreditar (la función ya es idempotente vía ultimo_charge_id)
            try:
                res = acreditar_creditos_suscripcion(preapproval_id, charge_id=charge_id)
                if res.get('acreditado'):
                    logger.info(f"✨ Créditos acreditados exitosamente para cobro {charge_id}")
                else:
                    logger.info(f"ℹ️ Cobro {charge_id} no acreditado: {res.get('motivo')}")
                resultados.append(res)
            except Exception as e:
                logger.error(f"❌ Error acreditando cobro {charge_id}: {e}")
        
        # GARANTÍA INICIAL: Si no se encontró ningún cobro específico en MP pero la suscripción 
        # está activa localmente y NUNCA ha recibido créditos, los otorgamos ahora.
        if not resultados:
            try:
                suscripcion = SuscripcionProveedor.objects.get(mp_preapproval_id=preapproval_id)
                if not suscripcion.ultimo_charge_id:
                    logger.info(f"🎁 Aplicando garantía inicial de créditos para preapproval {preapproval_id}")
                    res = acreditar_creditos_suscripcion(preapproval_id, force_initial=True)
                    resultados.append(res)
                else:
                    logger.info(f"ℹ️ No se encontraron nuevos cobros para {preapproval_id} (ya tiene créditos iniciales)")
            except Exception as e:
                logger.error(f"❌ Error en lógica de garantía inicial: {e}")

        return resultados

    except Exception as e:
        logger.error(f"❌ Error crítico en sincronizar_cobros_preapproval para {preapproval_id}: {e}")
        return []

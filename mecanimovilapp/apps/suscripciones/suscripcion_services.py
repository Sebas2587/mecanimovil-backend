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
import requests

from .models import PlanSuscripcion, SuscripcionProveedor
from .creditos_services import obtener_credito_proveedor

logger = logging.getLogger(__name__)


def _get_mp_access_token():
    """Obtiene el Access Token de MercadoPago desde variables de entorno."""
    token = config('MERCADOPAGO_ACCESS_TOKEN', default='')
    if not token:
        raise ValueError("MERCADOPAGO_ACCESS_TOKEN no está configurado")
    return token


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

    # Si ya tiene suscripción activa/pendiente, retornar la existente
    suscripcion_existente = SuscripcionProveedor.objects.filter(
        proveedor=proveedor,
        estado__in=['activa', 'pendiente']
    ).first()

    if suscripcion_existente:
        logger.info(
            f"Proveedor {proveedor.id} ya tiene suscripción en estado "
            f"'{suscripcion_existente.estado}' (ID: {suscripcion_existente.id})"
        )
        return {
            'suscripcion_id': suscripcion_existente.id,
            'init_point': suscripcion_existente.mp_init_point,
            'estado': suscripcion_existente.estado,
            'plan': _plan_to_dict(suscripcion_existente.plan),
            'ya_existia': True,
        }

    # Construir payload para la API de Preapproval de MercadoPago
    # NOTA: back_url debe ser una URL HTTPS válida — MP rechaza deep links (mecanimovil://)
    webhook_base_url = config('WEBHOOK_BASE_URL', default='https://api.mecanimovil.com')

    # back_url: página HTTPS a donde MP redirige al usuario tras autorizar el pago
    back_url = f"{webhook_base_url}/suscripciones-resultado/"

    # notification_url: endpoint de nuestro backend donde MP envía webhooks de cobro
    notification_url = f"{webhook_base_url}/api/suscripciones/webhook-preapproval/"

    precio_entero = int(round(float(plan.precio)))

    # currency_id debe coincidir con el país de la cuenta MercadoPago:
    # La app usa CLP (Chile) — mismo valor que usa el sistema de créditos existente
    # (pagos/views.py usa currency_id='CLP' en todas sus preferencias y funciona OK)
    currency_id = config('MERCADOPAGO_CURRENCY', default='CLP')

    # site_id identifica el país en la API de Preapproval (requerido explícitamente)
    # MLC = MercadoPago Chile  |  MLA = Argentina  |  MCO = Colombia
    site_id = config('MERCADOPAGO_SITE_ID', default='MLC')

    preapproval_data = {
        "reason": f"Suscripción MecaniMovil — {plan.nombre}",
        # payer_email es OPCIONAL para status "pending" según docs MP.
        # Si el email del proveedor pertenece a una cuenta MP de otro país,
        # MP lanza "Cannot operate between different countries".
        # Para status pending, MP genera el link de pago sin requerir el email.
        # "payer_email": proveedor.email,  ← omitido intencionalmente
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

    # Si el plan tiene un mp_preapproval_plan_id, usarlo
    if plan.mp_preapproval_plan_id:
        preapproval_data["preapproval_plan_id"] = plan.mp_preapproval_plan_id

    logger.info(
        f"📤 Creando preapproval MP para proveedor {proveedor.id}, plan '{plan.nombre}' "
        f"| precio={precio_entero} CLP | back_url={back_url}"
    )

    try:
        access_token = _get_mp_access_token()
        response = requests.post(
            "https://api.mercadopago.com/preapproval",
            json=preapproval_data,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        # Loguear siempre el cuerpo de respuesta para facilitar debugging
        logger.info(f"📥 MP Preapproval respuesta [{response.status_code}]: {response.text[:800]}")
        response.raise_for_status()
        mp_response = response.json()
    except requests.exceptions.HTTPError as e:
        # Incluir el body de respuesta de MP en el error para debugging
        error_body = ''
        try:
            error_body = e.response.json()
        except Exception:
            error_body = e.response.text[:400] if e.response else ''
        logger.error(f"❌ MP Preapproval 4xx/5xx [{e.response.status_code if e.response else '?'}]: {error_body}")
        raise ValueError(f"MercadoPago rechazó la solicitud: {error_body}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de red llamando a MP Preapproval API: {e}")
        raise ValueError(f"Error al comunicarse con MercadoPago: {str(e)}")

    preapproval_id = mp_response.get("id")
    init_point = mp_response.get("init_point")

    if not preapproval_id or not init_point:
        logger.error(f"❌ Respuesta inesperada de MP Preapproval: {mp_response}")
        raise ValueError("MercadoPago no retornó un ID de preapproval válido")

    logger.info(f"✅ Preapproval creado: {preapproval_id}")

    # Guardar en BD
    suscripcion = SuscripcionProveedor.objects.create(
        proveedor=proveedor,
        plan=plan,
        estado='pendiente',
        mp_preapproval_id=preapproval_id,
        mp_init_point=init_point,
    )

    return {
        'suscripcion_id': suscripcion.id,
        'init_point': init_point,
        'estado': suscripcion.estado,
        'plan': _plan_to_dict(plan),
        'ya_existia': False,
    }


@transaction.atomic
def acreditar_creditos_suscripcion(preapproval_id, charge_id=None):
    """
    Acredita créditos mensuales al proveedor cuando MercadoPago confirma
    un cobro recurrente (evento subscription_authorized_payment).

    Idempotente: si el charge_id ya fue procesado, no acredita de nuevo.

    Args:
        preapproval_id: ID del preapproval en MP.
        charge_id: ID del cobro específico (para idempotencia).

    Returns:
        dict: { 'acreditado': bool, 'creditos': int, 'saldo_nuevo': int }
    """
    try:
        suscripcion = SuscripcionProveedor.objects.select_for_update().get(
            mp_preapproval_id=preapproval_id
        )
    except SuscripcionProveedor.DoesNotExist:
        logger.warning(f"⚠️ Suscripción {preapproval_id} no encontrada en BD")
        return {'acreditado': False, 'motivo': 'Suscripción no encontrada'}

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
        f"(preapproval: {preapproval_id}). Nuevo saldo: {credito_proveedor.saldo_creditos}"
    )

    return {
        'acreditado': True,
        'creditos': creditos,
        'saldo_nuevo': credito_proveedor.saldo_creditos,
        'proveedor_id': suscripcion.proveedor.id,
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

    # Cancelar en MercadoPago
    if suscripcion.mp_preapproval_id:
        try:
            access_token = _get_mp_access_token()
            response = requests.put(
                f"https://api.mercadopago.com/preapproval/{suscripcion.mp_preapproval_id}",
                json={"status": "cancelled"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if response.status_code not in (200, 201):
                logger.warning(
                    f"⚠️ MP devolvió {response.status_code} al cancelar "
                    f"preapproval {suscripcion.mp_preapproval_id}: {response.text}"
                )
            else:
                logger.info(f"✅ Preapproval {suscripcion.mp_preapproval_id} cancelado en MP")
        except requests.exceptions.RequestException as e:
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
        access_token = _get_mp_access_token()
        response = requests.get(
            f"https://api.mercadopago.com/preapproval/{suscripcion.mp_preapproval_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )

        if response.status_code != 200:
            logger.warning(
                f"⚠️ MP devolvió {response.status_code} al consultar "
                f"preapproval {suscripcion.mp_preapproval_id}"
            )
            return suscripcion.estado

        mp_data = response.json()
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

        return suscripcion.estado

    except Exception as e:
        logger.error(f"❌ Error sincronizando suscripción {suscripcion.id}: {e}")
        return suscripcion.estado


def obtener_suscripcion_activa(proveedor):
    """
    Obtiene la suscripción activa/pendiente del proveedor, o None.

    Args:
        proveedor: Usuario proveedor.

    Returns:
        SuscripcionProveedor | None
    """
    return SuscripcionProveedor.objects.filter(
        proveedor=proveedor,
        estado__in=['activa', 'pendiente', 'pausada']
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

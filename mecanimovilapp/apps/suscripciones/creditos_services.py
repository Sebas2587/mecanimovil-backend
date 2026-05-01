"""
Servicios de lógica de negocio para el sistema Pay-per-Win con créditos.
Gestiona compras, consumos, validaciones y estadísticas de créditos.
"""
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction, models
from datetime import timedelta
from decimal import Decimal
import logging

from .models import (
    CreditoProveedor,
    PaqueteCreditos,
    CompraCreditos,
    ConsumoCredito,
    ConfiguracionCreditos,
    ConfiguracionCreditosServicio,
    ProveedorCancelaciones
)

logger = logging.getLogger(__name__)


def calcular_precio_credito():
    """
    Calcula el precio del crédito según la fórmula: C = (AOV × Tasa) / K_avg
    Obtiene la configuración activa y calcula el precio.
    
    Returns:
        Decimal: Precio del crédito en CLP
    """
    try:
        config = ConfiguracionCreditos.objects.filter(activo=True).first()
        if not config:
            # Si no hay configuración, crear una por defecto
            config = ConfiguracionCreditos.objects.create(
                aov_promedio=Decimal('150000'),
                tasa_comision=Decimal('0.10'),
                k_promedio=3,
                activo=True
            )
            logger.info("Configuración de créditos creada con valores por defecto")
        
        precio = config.calcular_precio_credito()
        logger.debug(f"Precio del crédito calculado: ${precio:,.0f} CLP")
        return precio
    except Exception as e:
        logger.error(f"Error calculando precio del crédito: {e}", exc_info=True)
        # Retornar precio por defecto en caso de error
        return Decimal('5000')


def obtener_creditos_servicio(servicio):
    """
    Obtiene la cantidad de créditos requeridos para un servicio.
    Si no existe configuración específica, retorna valor por defecto.
    
    Args:
        servicio: Instancia del modelo Servicio
    
    Returns:
        int: Cantidad de créditos requeridos
    """
    try:
        config = ConfiguracionCreditosServicio.objects.filter(
            servicio=servicio,
            activo=True
        ).first()
        
        if config:
            return config.creditos_requeridos
        
        # Valor por defecto si no hay configuración específica
        logger.debug(f"No hay configuración específica para servicio {servicio.id}, usando valor por defecto: 2")
        return 2
    except Exception as e:
        logger.error(f"Error obteniendo créditos para servicio {servicio.id}: {e}", exc_info=True)
        return 2


def obtener_credito_proveedor(proveedor):
    """
    Obtiene o crea el registro de créditos de un proveedor.
    
    Args:
        proveedor: Usuario proveedor
    
    Returns:
        CreditoProveedor: Registro de créditos del proveedor
    """
    try:
        credito, created = CreditoProveedor.objects.get_or_create(
            proveedor=proveedor,
            defaults={
                'saldo_creditos': 0,
                'creditos_expirados': 0
            }
        )
        
        if created:
            logger.info(f"Registro de créditos creado para proveedor {proveedor.id}")
        
        return credito
    except Exception as e:
        logger.error(f"Error obteniendo créditos para proveedor {proveedor.id}: {e}", exc_info=True)
        raise


def validar_creditos_suficientes(proveedor, servicio):
    """
    Valida que el proveedor tenga créditos suficientes para adjudicar un servicio.
    
    Args:
        proveedor: Usuario proveedor
        servicio: Instancia del modelo Servicio
    
    Returns:
        tuple: (bool, str, int) - (puede_adjudicar, mensaje, creditos_necesarios)
    """
    try:
        credito_proveedor = obtener_credito_proveedor(proveedor)
        creditos_necesarios = obtener_creditos_servicio(servicio)
        
        if credito_proveedor.saldo_creditos >= creditos_necesarios:
            return True, f"Tienes créditos suficientes ({credito_proveedor.saldo_creditos} disponibles)", creditos_necesarios
        else:
            mensaje = (
                f"No tienes créditos suficientes. "
                f"Necesitas {creditos_necesarios} créditos, pero solo tienes {credito_proveedor.saldo_creditos}."
            )
            return False, mensaje, creditos_necesarios
    except Exception as e:
        logger.error(f"Error validando créditos para proveedor {proveedor.id}: {e}", exc_info=True)
        return False, f"Error al validar créditos: {str(e)}", 0


@transaction.atomic
def consumir_creditos_adjudicacion(proveedor, oferta, servicio):
    """
    Consume créditos al momento de adjudicación de una oferta.
    Maneja expiración FIFO (First In, First Out).
    
    Args:
        proveedor: Usuario proveedor
        oferta: Instancia de OfertaProveedor
        servicio: Instancia del modelo Servicio
    
    Returns:
        ConsumoCredito: Registro del consumo creado
    
    Raises:
        ValidationError: Si no hay créditos suficientes
    """
    try:
        # Validar créditos suficientes
        puede, mensaje, creditos_necesarios = validar_creditos_suficientes(proveedor, servicio)
        if not puede:
            raise ValidationError(mensaje)
        
        # Obtener crédito del proveedor
        credito_proveedor = obtener_credito_proveedor(proveedor)
        
        # Obtener precio del crédito al momento del consumo
        # Redondear a 2 decimales para cumplir con la restricción del modelo
        precio_credito = calcular_precio_credito()
        precio_credito = precio_credito.quantize(Decimal('0.01'))
        
        # Actualizar saldo
        credito_proveedor.saldo_creditos -= creditos_necesarios
        credito_proveedor.fecha_ultimo_consumo = timezone.now()
        credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_ultimo_consumo', 'fecha_actualizacion'])
        
        # Crear registro de consumo
        consumo = ConsumoCredito.objects.create(
            proveedor=proveedor,
            oferta=oferta,
            servicio=servicio,
            creditos_consumidos=creditos_necesarios,
            precio_credito=precio_credito
        )
        
        logger.info(
            f"Créditos consumidos: {creditos_necesarios} para proveedor {proveedor.id}, "
            f"oferta {oferta.id}, servicio {servicio.nombre}. "
            f"Saldo restante: {credito_proveedor.saldo_creditos}"
        )
        
        return consumo
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error consumiendo créditos para proveedor {proveedor.id}: {e}", exc_info=True)
        raise ValidationError(f"Error al consumir créditos: {str(e)}")


def comprar_creditos(proveedor, metodo_pago, paquete_id=None, cantidad_creditos=None):
    """
    Crea un registro de compra de créditos.
    
    - Mercado Pago: Queda pendiente hasta que el webhook confirme el pago
    - Transferencia: Queda pendiente hasta confirmación manual del admin
    - Migración: Se confirma inmediatamente (uso interno)
    
    Args:
        proveedor: Usuario proveedor
        metodo_pago: 'mercadopago', 'transferencia', 'migracion'
        paquete_id: ID del paquete de créditos (opcional)
        cantidad_creditos: Cantidad dinámica de créditos a comprar (opcional)
    
    Returns:
        CompraCreditos: Registro de compra creado
    
    Raises:
        ValidationError: Si el paquete no existe, la cantidad es inválida u ocurre algún error.
    """
    try:
        precio_total = Decimal('0')
        cantidad_total = 0
        paquete = None
        
        # Validar paquete o cantidad
        if paquete_id:
            paquete = PaqueteCreditos.objects.filter(id=paquete_id, activo=True).first()
            if not paquete:
                raise ValidationError("El paquete no existe o no está disponible")
            cantidad_total = paquete.total_creditos
            precio_total = paquete.precio
        elif cantidad_creditos:
            cantidad_total = int(cantidad_creditos)
            if cantidad_total <= 0:
                raise ValidationError("La cantidad de créditos debe ser mayor a cero")
            precio_base = calcular_precio_credito()
            precio_total = precio_base * cantidad_total
        else:
            raise ValidationError("Debe especificar un paquete o una cantidad de créditos")
        
        # Obtener configuración para calcular fecha de expiración
        config = ConfiguracionCreditos.objects.filter(activo=True).first()
        if not config:
            config = ConfiguracionCreditos.objects.create(
                aov_promedio=Decimal('150000'),
                tasa_comision=Decimal('0.10'),
                k_promedio=3,
                activo=True
            )
        
        meses_expiracion = config.creditos_expiracion_meses
        fecha_expiracion = timezone.now() + timedelta(days=30 * meses_expiracion)
        # cantidad_total y precio_total ya vienen del paquete o de cantidad_creditos (no pisar con paquete)

        # Crear registro de compra
        compra = CompraCreditos.objects.create(
            proveedor=proveedor,
            paquete=paquete,
            cantidad_creditos=cantidad_total,
            precio_total=precio_total,
            metodo_pago=metodo_pago,
            estado='pendiente',
            fecha_expiracion_creditos=fecha_expiracion
        )
        
        # Solo confirmar inmediatamente si es migración (uso interno)
        # Las compras por mercadopago se confirman vía webhook
        # Las compras por transferencia se confirman manualmente por admin
        if metodo_pago == 'migracion':
            compra = confirmar_compra_creditos(compra.id)
        
        logger.info(
            f"Compra de créditos creada: {compra.id} para proveedor {proveedor.id}, "
            f"paquete_id: {paquete_id}, {cantidad_total} créditos, "
            f"precio total: ${precio_total}, método: {metodo_pago}"
        )
        
        return compra
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error creando compra de créditos para proveedor {proveedor.id}: {e}", exc_info=True)
        raise ValidationError(f"Error al crear compra de créditos: {str(e)}")


@transaction.atomic
def confirmar_compra_creditos(compra_id, payment_id_mp=None):
    """
    Confirma una compra de créditos y actualiza el saldo del proveedor.
    
    Args:
        compra_id: ID de la compra de créditos
        payment_id_mp: ID del pago en Mercado Pago (opcional)
    
    Returns:
        CompraCreditos: Registro de compra actualizado
    
    Raises:
        ValidationError: Si la compra no existe o ya está completada
    """
    try:
        compra = CompraCreditos.objects.select_for_update().get(id=compra_id)
        
        if compra.estado == 'completada':
            logger.warning(f"Compra {compra_id} ya está completada")
            return compra
        
        if compra.estado != 'pendiente':
            raise ValidationError(f"La compra no puede ser confirmada en estado: {compra.estado}")
        
        # Actualizar estado de la compra
        compra.estado = 'completada'
        if payment_id_mp:
            compra.payment_id_mp = payment_id_mp
        compra.save(update_fields=['estado', 'payment_id_mp', 'fecha_actualizacion'])
        
        # Actualizar saldo del proveedor
        credito_proveedor = obtener_credito_proveedor(compra.proveedor)
        credito_proveedor.saldo_creditos += compra.cantidad_creditos
        credito_proveedor.fecha_ultima_compra = timezone.now()
        credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_ultima_compra', 'fecha_actualizacion'])
        
        logger.info(
            f"Compra de créditos confirmada: {compra_id} para proveedor {compra.proveedor.id}. "
            f"Créditos agregados: {compra.cantidad_creditos}. "
            f"Nuevo saldo: {credito_proveedor.saldo_creditos}"
        )

        proveedor_id = compra.proveedor_id

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
                    f"Hook adjudicaciones tras compra créditos (proveedor {proveedor_id}): {hook_err}",
                    exc_info=True,
                )

        transaction.on_commit(_intentar_adjudicaciones_pendientes)

        # Refrescar la compra desde la base de datos para obtener los campos actualizados
        compra.refresh_from_db()
        return compra
    except CompraCreditos.DoesNotExist:
        raise ValidationError(f"Compra de créditos {compra_id} no encontrada")
    except Exception as e:
        logger.error(f"Error confirmando compra de créditos {compra_id}: {e}", exc_info=True)
        raise ValidationError(f"Error al confirmar compra: {str(e)}")


def verificar_creditos_expirados(proveedor):
    """
    Verifica y actualiza créditos expirados para un proveedor.
    Calcula créditos expirados según fecha_expiracion_creditos en compras.
    
    Args:
        proveedor: Usuario proveedor
    
    Returns:
        int: Cantidad de créditos expirados
    """
    try:
        ahora = timezone.now()
        
        # Obtener compras con créditos expirados
        compras_expiradas = CompraCreditos.objects.filter(
            proveedor=proveedor,
            estado='completada',
            fecha_expiracion_creditos__lt=ahora
        )
        
        # Calcular créditos expirados totales
        creditos_expirados = 0
        for compra in compras_expiradas:
            # Verificar si estos créditos ya fueron consumidos
            consumos_desde_compra = ConsumoCredito.objects.filter(
                proveedor=proveedor,
                fecha_consumo__gte=compra.fecha_compra
            ).aggregate(total=models.Sum('creditos_consumidos'))['total'] or 0
            
            # Los créditos expirados son los que no se consumieron antes de expirar
            creditos_disponibles = compra.cantidad_creditos - consumos_desde_compra
            if creditos_disponibles > 0:
                creditos_expirados += creditos_disponibles
        
        # Actualizar registro
        credito_proveedor = obtener_credito_proveedor(proveedor)
        credito_proveedor.creditos_expirados = creditos_expirados
        credito_proveedor.save(update_fields=['creditos_expirados', 'fecha_actualizacion'])
        
        if creditos_expirados > 0:
            logger.info(f"Créditos expirados detectados para proveedor {proveedor.id}: {creditos_expirados}")
        
        return creditos_expirados
    except Exception as e:
        logger.error(f"Error verificando créditos expirados para proveedor {proveedor.id}: {e}", exc_info=True)
        return 0


def obtener_estadisticas_creditos(proveedor):
    """
    Obtiene estadísticas completas de créditos de un proveedor.
    
    Args:
        proveedor: Usuario proveedor
    
    Returns:
        dict: Diccionario con estadísticas completas
    """
    try:
        credito_proveedor = obtener_credito_proveedor(proveedor)
        ahora = timezone.now()
        
        # Créditos consumidos este mes
        consumos_mes = ConsumoCredito.objects.filter(
            proveedor=proveedor,
            fecha_consumo__year=ahora.year,
            fecha_consumo__month=ahora.month
        )
        creditos_consumidos_mes = sum(c.creditos_consumidos for c in consumos_mes)
        
        # Créditos comprados este mes
        compras_mes = CompraCreditos.objects.filter(
            proveedor=proveedor,
            estado='completada',
            fecha_compra__year=ahora.year,
            fecha_compra__month=ahora.month
        )
        creditos_comprados_mes = sum(c.cantidad_creditos for c in compras_mes)
        
        # Próxima expiración
        proxima_expiracion = CompraCreditos.objects.filter(
            proveedor=proveedor,
            estado='completada',
            fecha_expiracion_creditos__gt=ahora
        ).order_by('fecha_expiracion_creditos').first()
        
        # Historial reciente (últimos 10 consumos)
        historial_consumos = ConsumoCredito.objects.filter(
            proveedor=proveedor
        ).order_by('-fecha_consumo')[:10]
        
        # Historial reciente (últimas 10 compras)
        historial_compras = CompraCreditos.objects.filter(
            proveedor=proveedor
        ).order_by('-fecha_compra')[:10]
        
        precio_unit = calcular_precio_credito()
        estadisticas = {
            'saldo_actual': credito_proveedor.saldo_creditos,
            'precio_credito_unitario_clp': float(precio_unit.quantize(Decimal('0.01'))),
            'creditos_consumidos_mes': creditos_consumidos_mes,
            'creditos_comprados_mes': creditos_comprados_mes,
            'creditos_expirados': credito_proveedor.creditos_expirados,
            'fecha_ultima_compra': credito_proveedor.fecha_ultima_compra.isoformat() if credito_proveedor.fecha_ultima_compra else None,
            'fecha_ultimo_consumo': credito_proveedor.fecha_ultimo_consumo.isoformat() if credito_proveedor.fecha_ultimo_consumo else None,
            'proxima_expiracion': {
                'fecha': proxima_expiracion.fecha_expiracion_creditos.isoformat() if proxima_expiracion else None,
                'creditos': proxima_expiracion.cantidad_creditos if proxima_expiracion else None,
                'dias_restantes': (proxima_expiracion.fecha_expiracion_creditos - ahora).days if proxima_expiracion else None
            },
            'historial_consumos': [
                {
                    'id': c.id,
                    'proveedor': c.proveedor.id,
                    'proveedor_nombre': c.proveedor.username,
                    'oferta': str(c.oferta.id),
                    'oferta_id': str(c.oferta.id),
                    'servicio': c.servicio.id,
                    'servicio_nombre': c.servicio.nombre,
                    'creditos_consumidos': c.creditos_consumidos,
                    'precio_credito': float(c.precio_credito),
                    'fecha_consumo': c.fecha_consumo.isoformat()
                }
                for c in historial_consumos
            ],
            'historial_compras': [
                {
                    'id': c.id,
                    'proveedor': c.proveedor.id,
                    'proveedor_nombre': c.proveedor.username,
                    'paquete': (
                        {
                            'id': c.paquete.id,
                            'nombre': c.paquete.nombre,
                            'cantidad_creditos': c.paquete.cantidad_creditos,
                            'precio': float(c.paquete.precio),
                            'precio_por_credito': float(c.paquete.precio_por_credito),
                            'bonificacion_creditos': c.paquete.bonificacion_creditos,
                            'total_creditos': c.paquete.total_creditos,
                            'activo': c.paquete.activo,
                            'orden': c.paquete.orden,
                            'destacado': c.paquete.destacado,
                            'fecha_creacion': c.paquete.fecha_creacion.isoformat(),
                            'fecha_actualizacion': c.paquete.fecha_actualizacion.isoformat(),
                        }
                        if c.paquete_id
                        else None
                    ),
                    'cantidad_creditos': c.cantidad_creditos,
                    'precio_total': float(c.precio_total),
                    'metodo_pago': c.metodo_pago,
                    'metodo_pago_display': c.get_metodo_pago_display(),
                    'estado': c.estado,
                    'estado_display': c.get_estado_display(),
                    'payment_id_mp': c.payment_id_mp,
                    'fecha_compra': c.fecha_compra.isoformat(),
                    'fecha_expiracion_creditos': c.fecha_expiracion_creditos.isoformat() if c.fecha_expiracion_creditos else None,
                    'fecha_actualizacion': c.fecha_actualizacion.isoformat(),
                }
                for c in historial_compras
            ]
        }
        
        return estadisticas
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas para proveedor {proveedor.id}: {e}", exc_info=True)
        raise


# ============================================================================
# FUNCIONES ANTI-GAMING
# ============================================================================

def puede_adjudicar(proveedor):
    """
    Verifica si el proveedor puede adjudicar ofertas.
    Verifica límite de cancelaciones y suspensión.
    
    Args:
        proveedor: Usuario proveedor
    
    Returns:
        tuple: (bool, str) - (puede_adjudicar, mensaje)
    """
    try:
        # Verificar suspensión
        suspension = verificar_suspension(proveedor)
        if suspension[0]:  # Está suspendido
            dias_restantes = suspension[1]
            mensaje = f"Tu cuenta está suspendida temporalmente. Días restantes: {dias_restantes}"
            return False, mensaje
        
        # Verificar cancelaciones del mes
        cancelaciones = ProveedorCancelaciones.objects.filter(proveedor=proveedor).first()
        if cancelaciones:
            # Resetear contador si cambió de mes
            ahora = timezone.now()
            if cancelaciones.fecha_reset_cancelaciones.month != ahora.month:
                cancelaciones.cancelaciones_mes_actual = 0
                cancelaciones.fecha_reset_cancelaciones = ahora
                cancelaciones.save(update_fields=['cancelaciones_mes_actual', 'fecha_reset_cancelaciones'])
            
            # Verificar límite (máximo 2 cancelaciones por mes)
            if cancelaciones.cancelaciones_mes_actual >= 2:
                mensaje = "Has alcanzado el límite de cancelaciones este mes (2 cancelaciones). Tu cuenta ha sido suspendida temporalmente."
                return False, mensaje
            
            if cancelaciones.cancelaciones_mes_actual > 0:
                mensaje = f"Has alcanzado {cancelaciones.cancelaciones_mes_actual} de 2 cancelaciones permitidas este mes."
                # No bloquea, solo advierte
                return True, mensaje
        
        return True, "OK"
    except Exception as e:
        logger.error(f"Error verificando si proveedor {proveedor.id} puede adjudicar: {e}", exc_info=True)
        return False, f"Error al verificar estado: {str(e)}"


def registrar_cancelacion(proveedor, es_proveedor=True):
    """
    Registra una cancelación de oferta.
    Si cancela el proveedor: NO devolver créditos, incrementar contador.
    Si cancela el cliente: Devolver créditos, no incrementar contador.
    
    Args:
        proveedor: Usuario proveedor
        es_proveedor: True si cancela el proveedor, False si cancela el cliente
    
    Returns:
        ProveedorCancelaciones: Registro actualizado
    """
    try:
        cancelaciones, created = ProveedorCancelaciones.objects.get_or_create(
            proveedor=proveedor,
            defaults={
                'cancelaciones_mes_actual': 0,
                'fecha_reset_cancelaciones': timezone.now()
            }
        )
        
        # Resetear contador si cambió de mes
        ahora = timezone.now()
        if cancelaciones.fecha_reset_cancelaciones.month != ahora.month:
            cancelaciones.cancelaciones_mes_actual = 0
            cancelaciones.fecha_reset_cancelaciones = ahora
        
        if es_proveedor:
            # Incrementar contador solo si cancela el proveedor
            cancelaciones.cancelaciones_mes_actual += 1
            cancelaciones.save(update_fields=['cancelaciones_mes_actual', 'fecha_reset_cancelaciones', 'fecha_actualizacion'])
            
            # Si alcanza el límite (2 cancelaciones), suspender
            if cancelaciones.cancelaciones_mes_actual >= 2:
                cancelaciones.suspension_temporal = True
                cancelaciones.fecha_suspension = ahora
                cancelaciones.save(update_fields=['suspension_temporal', 'fecha_suspension', 'fecha_actualizacion'])
                logger.warning(f"Proveedor {proveedor.id} suspendido por alcanzar límite de cancelaciones")
            
            logger.info(
                f"Cancelación registrada para proveedor {proveedor.id}. "
                f"Total este mes: {cancelaciones.cancelaciones_mes_actual}"
            )
        else:
            # Si cancela el cliente, no incrementar contador
            # Los créditos se devuelven en otra función
            logger.info(f"Cancelación por cliente registrada para proveedor {proveedor.id}. No se incrementa contador.")
        
        return cancelaciones
    except Exception as e:
        logger.error(f"Error registrando cancelación para proveedor {proveedor.id}: {e}", exc_info=True)
        raise


def verificar_suspension(proveedor):
    """
    Verifica si el proveedor está suspendido y calcula días restantes.
    
    Args:
        proveedor: Usuario proveedor
    
    Returns:
        tuple: (bool, int) - (esta_suspendido, dias_restantes)
    """
    try:
        cancelaciones = ProveedorCancelaciones.objects.filter(proveedor=proveedor).first()
        
        if not cancelaciones or not cancelaciones.suspension_temporal:
            return False, 0
        
        # La suspensión dura 30 días desde la fecha de suspensión
        if cancelaciones.fecha_suspension:
            ahora = timezone.now()
            dias_transcurridos = (ahora - cancelaciones.fecha_suspension).days
            dias_restantes = max(0, 30 - dias_transcurridos)
            
            # Si ya pasaron 30 días, quitar suspensión
            if dias_restantes == 0:
                cancelaciones.suspension_temporal = False
                cancelaciones.cancelaciones_mes_actual = 0
                cancelaciones.save(update_fields=['suspension_temporal', 'cancelaciones_mes_actual', 'fecha_actualizacion'])
                logger.info(f"Suspensión removida para proveedor {proveedor.id} (30 días completados)")
                return False, 0
            
            return True, dias_restantes
        
        return False, 0
    except Exception as e:
        logger.error(f"Error verificando suspensión para proveedor {proveedor.id}: {e}", exc_info=True)
        return False, 0


@transaction.atomic
def devolver_creditos_cancelacion(proveedor, consumo_credito):
    """
    Devuelve créditos cuando el cliente cancela una oferta adjudicada.
    Solo se devuelven si cancela el cliente, no si cancela el proveedor.
    
    Args:
        proveedor: Usuario proveedor
        consumo_credito: Instancia de ConsumoCredito a revertir
    
    Returns:
        CreditoProveedor: Registro actualizado de créditos
    """
    try:
        credito_proveedor = obtener_credito_proveedor(proveedor)
        
        # Devolver créditos al saldo
        credito_proveedor.saldo_creditos += consumo_credito.creditos_consumidos
        credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_actualizacion'])
        
        logger.info(
            f"Créditos devueltos: {consumo_credito.creditos_consumidos} para proveedor {proveedor.id}, "
            f"consumo {consumo_credito.id}. Nuevo saldo: {credito_proveedor.saldo_creditos}"
        )
        
        return credito_proveedor
    except Exception as e:
        logger.error(f"Error devolviendo créditos para proveedor {proveedor.id}: {e}", exc_info=True)
        raise


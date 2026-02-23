from rest_framework import permissions
from rest_framework.permissions import BasePermission
import logging

logger = logging.getLogger(__name__)


class IsProveedor(BasePermission):
    """
    Permiso que permite acceso solo a usuarios que sean talleres o mecánicos
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            logger.warning(f"Usuario no autenticado intentando acceder a {view.__class__.__name__}")
            return False
        
        # Debug: información del usuario
        logger.info(f"🔍 Verificando permisos para usuario {request.user.username} (ID: {request.user.id})")
        logger.info(f"   Usuario completo: {request.user}")
        logger.info(f"   Es staff: {request.user.is_staff}")
        logger.info(f"   Está activo: {request.user.is_active}")
        
        # Verificar si el usuario tiene perfil de taller usando hasattr
        tiene_taller = hasattr(request.user, 'taller')
        tiene_mecanico = hasattr(request.user, 'mecanico_domicilio')
        
        logger.info(f"   hasattr(user, 'taller'): {tiene_taller}")
        logger.info(f"   hasattr(user, 'mecanico_domicilio'): {tiene_mecanico}")
        
        # También verificar usando queries directas para debugging
        try:
            from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
            
            taller_query = Taller.objects.filter(usuario=request.user).first()
            mecanico_query = MecanicoDomicilio.objects.filter(usuario=request.user).first()
            
            logger.info(f"   Query directa taller: {taller_query}")
            logger.info(f"   Query directa mecánico: {mecanico_query}")
            
            if taller_query:
                logger.info(f"   Taller encontrado: {taller_query.nombre}, verificado: {taller_query.verificado}")
            if mecanico_query:
                logger.info(f"   Mecánico encontrado: {mecanico_query.nombre}, verificado: {mecanico_query.verificado}")
                
        except Exception as e:
            logger.error(f"   Error en query directa: {e}")
        
        # Verificar con hasattr primero
        if tiene_taller:
            try:
                taller = request.user.taller
                logger.info(f"✅ Usuario {request.user.username} tiene taller: {taller.nombre} (verificado: {taller.verificado})")
                return True
            except Exception as e:
                logger.error(f"❌ Error accediendo a taller via hasattr: {e}")
                
        elif tiene_mecanico:
            try:
                mecanico = request.user.mecanico_domicilio
                logger.info(f"✅ Usuario {request.user.username} tiene mecánico: {mecanico.nombre} (verificado: {mecanico.verificado})")
                return True
            except Exception as e:
                logger.error(f"❌ Error accediendo a mecánico via hasattr: {e}")
        else:
            logger.warning(f"❌ Usuario {request.user.username} no tiene perfil de taller ni mecánico")
            
            # Listar todos los atributos del usuario para debugging
            user_attrs = [attr for attr in dir(request.user) if not attr.startswith('_')]
            logger.info(f"   Atributos del usuario: {user_attrs}")
            
            # Verificar específicamente atributos relacionados
            related_attrs = []
            for attr in ['taller', 'mecanico_domicilio', 'cliente']:
                if hasattr(request.user, attr):
                    related_attrs.append(attr)
            logger.info(f"   Atributos relacionados encontrados: {related_attrs}")
            
            return False


class IsOrderOwnerForProvider(BasePermission):
    """
    Permiso que permite a un proveedor acceder solo a sus propias órdenes
    """
    
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Verificar si el usuario es el proveedor asignado a la orden
        if hasattr(request.user, 'taller'):
            return obj.taller == request.user.taller
        elif hasattr(request.user, 'mecanico_domicilio'):
            return obj.mecanico == request.user.mecanico_domicilio
        
        return False


class IsProveedorOrCliente(BasePermission):
    """
    Permiso que permite acceso a proveedores o clientes
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return (
            hasattr(request.user, 'cliente') or
            hasattr(request.user, 'taller') or 
            hasattr(request.user, 'mecanico_domicilio')
        )


class CanManageOrder(BasePermission):
    """
    Permiso que permite gestionar órdenes según el rol del usuario
    """
    
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Los clientes pueden ver y gestionar sus propias órdenes
        if hasattr(request.user, 'cliente'):
            return obj.cliente == request.user.cliente
        
        # Los proveedores pueden ver y gestionar órdenes asignadas a ellos
        if hasattr(request.user, 'taller'):
            return obj.taller == request.user.taller
        elif hasattr(request.user, 'mecanico_domicilio'):
            return obj.mecanico == request.user.mecanico_domicilio
        
        # Los administradores pueden gestionar todas las órdenes
        return request.user.is_staff


class IsProveedorConMP(IsProveedor):
    """
    Permiso que exige: usuario autenticado + perfil de proveedor + cuenta MercadoPago conectada.
    Usado para bloquear acciones que requieren poder recibir/realizar pagos (crear ofertas,
    suscribirse a planes, etc.) si el proveedor no ha vinculado su cuenta de Mercado Pago.
    """

    message = (
        "Debes conectar tu cuenta de Mercado Pago antes de realizar esta acción. "
        "Ve a Configuración → Mercado Pago para vincularla."
    )

    def has_permission(self, request, view):
        # Primero verificar que sea un proveedor válido
        if not super().has_permission(request, view):
            return False

        # Luego verificar que tenga cuenta MP conectada
        try:
            cuenta_mp = request.user.cuenta_mercadopago
            if not cuenta_mp or cuenta_mp.estado != 'conectada':
                logger.warning(
                    f"⛔ Proveedor {request.user.id} intentó acceder sin cuenta MP conectada "
                    f"(estado: {cuenta_mp.estado if cuenta_mp else 'sin cuenta'})"
                )
                return False
        except Exception:
            logger.warning(
                f"⛔ Proveedor {request.user.id} no tiene cuenta_mercadopago configurada"
            )
            return False

        return True
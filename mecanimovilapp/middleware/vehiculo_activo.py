from django.utils.deprecation import MiddlewareMixin
from mecanimovilapp.apps.personalizacion.models import VehiculoActivo


class VehiculoActivoMiddleware(MiddlewareMixin):
    """
    Middleware para agregar el vehículo activo al contexto de la request
    """
    
    def process_request(self, request):
        """
        Agrega el vehículo activo al request si el usuario está autenticado
        """
        request.vehiculo_activo = None
        
        if request.user.is_authenticated and hasattr(request.user, 'cliente'):
            try:
                vehiculo_activo = VehiculoActivo.objects.select_related(
                    'vehiculo', 'vehiculo__marca', 'vehiculo__modelo'
                ).get(cliente=request.user.cliente)
                
                request.vehiculo_activo = vehiculo_activo.vehiculo
                
                # También agregar a la sesión para uso en templates
                request.session['vehiculo_activo_id'] = vehiculo_activo.vehiculo.id
                request.session['vehiculo_activo_info'] = {
                    'id': vehiculo_activo.vehiculo.id,
                    'marca': vehiculo_activo.vehiculo.marca_nombre,
                    'modelo': vehiculo_activo.vehiculo.modelo_nombre,
                    'patente': vehiculo_activo.vehiculo.patente
                }
                
            except VehiculoActivo.DoesNotExist:
                # Si no hay vehículo activo, limpiar la sesión
                request.session.pop('vehiculo_activo_id', None)
                request.session.pop('vehiculo_activo_info', None)
        
        return None 
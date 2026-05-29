from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

from .models import VehiculoActivo, PerfilVehiculo, RecomendacionPersonalizada
from .serializers import (
    VehiculoActivoSerializer, 
    PerfilVehiculoSerializer,
    RecomendacionPersonalizadaSerializer
)
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
from .ml_engine import MotorRecomendaciones


class VehiculoActivoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar el vehículo activo del cliente
    """
    serializer_class = VehiculoActivoSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Solo devolver el vehículo activo del cliente autenticado"""
        if hasattr(self.request.user, 'cliente'):
            return VehiculoActivo.objects.filter(cliente=self.request.user.cliente)
        return VehiculoActivo.objects.none()
    
    @action(detail=False, methods=['post'])
    def establecer_vehiculo_activo(self, request):
        """
        Establece o cambia el vehículo activo del cliente
        """
        vehiculo_id = request.data.get('vehiculo_id')
        
        if not vehiculo_id:
            return Response(
                {'error': 'vehiculo_id es requerido'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verificar que el vehículo pertenezca al cliente
        try:
            vehiculo = Vehiculo.objects.get(
                id=vehiculo_id, 
                cliente=request.user.cliente
            )
        except Vehiculo.DoesNotExist:
            return Response(
                {'error': 'Vehículo no encontrado o no pertenece al cliente'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Crear o actualizar el vehículo activo
        vehiculo_activo, created = VehiculoActivo.objects.update_or_create(
            cliente=request.user.cliente,
            defaults={'vehiculo': vehiculo}
        )
        
        # Generar recomendaciones para el nuevo vehículo activo
        motor = MotorRecomendaciones()
        motor.generar_recomendaciones_vehiculo(vehiculo)
        
        serializer = self.get_serializer(vehiculo_activo)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def obtener_vehiculo_activo(self, request):
        """
        Obtiene el vehículo activo actual del cliente
        """
        try:
            vehiculo_activo = VehiculoActivo.objects.get(
                cliente=request.user.cliente
            )
            serializer = self.get_serializer(vehiculo_activo)
            return Response(serializer.data)
        except VehiculoActivo.DoesNotExist:
            return Response(
                {'message': 'No hay vehículo activo seleccionado'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class RecomendacionesViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para obtener recomendaciones personalizadas
    """
    serializer_class = RecomendacionPersonalizadaSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar recomendaciones por cliente y vehículo activo"""
        if not hasattr(self.request.user, 'cliente'):
            return RecomendacionPersonalizada.objects.none()
        
        cliente = self.request.user.cliente
        
        # Obtener vehículo activo
        try:
            vehiculo_activo = VehiculoActivo.objects.get(cliente=cliente)
            vehiculo = vehiculo_activo.vehiculo
        except VehiculoActivo.DoesNotExist:
            return RecomendacionPersonalizada.objects.none()
        
        # Filtrar recomendaciones activas y no expiradas
        return RecomendacionPersonalizada.objects.filter(
            cliente=cliente,
            vehiculo=vehiculo,
            activa=True,
            fecha_expiracion__gt=timezone.now()
        )
    
    @action(detail=False, methods=['get'])
    def mantenimiento_sugerido(self, request):
        """
        Obtiene recomendaciones de mantenimiento para el vehículo activo
        """
        recomendaciones = self.get_queryset().filter(
            tipo='mantenimiento'
        ).order_by('-score_relevancia')[:5]
        
        serializer = self.get_serializer(recomendaciones, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def proveedores_destacados(self, request):
        """
        Obtiene proveedores recomendados para el vehículo activo
        """
        recomendaciones = self.get_queryset().filter(
            tipo='proveedor'
        ).order_by('-score_relevancia')[:10]
        
        serializer = self.get_serializer(recomendaciones, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def servicios_populares(self, request):
        """
        Obtiene servicios populares para el vehículo activo
        """
        recomendaciones = self.get_queryset().filter(
            tipo='servicio_popular'
        ).order_by('-score_relevancia')[:8]
        
        serializer = self.get_serializer(recomendaciones, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def marcar_vista(self, request, pk=None):
        """
        Marca una recomendación como vista (para métricas)
        """
        recomendacion = self.get_object()
        recomendacion.veces_mostrada += 1
        recomendacion.save(update_fields=['veces_mostrada'])
        
        return Response({'status': 'vista registrada'})
    
    @action(detail=True, methods=['post'])
    def marcar_click(self, request, pk=None):
        """
        Marca una recomendación como clickeada (para métricas)
        """
        recomendacion = self.get_object()
        recomendacion.veces_clickeada += 1
        recomendacion.save(update_fields=['veces_clickeada'])
        
        return Response({'status': 'click registrado'})
    
    @action(detail=False, methods=['post'])
    def regenerar_recomendaciones(self, request):
        """
        Regenera las recomendaciones para el vehículo activo
        """
        try:
            vehiculo_activo = VehiculoActivo.objects.get(
                cliente=request.user.cliente
            )
            
            motor = MotorRecomendaciones()
            motor.generar_recomendaciones_vehiculo(vehiculo_activo.vehiculo)
            
            return Response({'status': 'recomendaciones regeneradas'})
        except VehiculoActivo.DoesNotExist:
            return Response(
                {'error': 'No hay vehículo activo seleccionado'}, 
                status=status.HTTP_400_BAD_REQUEST
            )


class BusquedaPersonalizadaViewSet(viewsets.ViewSet):
    """
    ViewSet para búsquedas personalizadas de servicios
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def buscar_servicios(self, request):
        """
        Búsqueda de servicios personalizada basada en el vehículo activo
        """
        query = request.query_params.get('q', '')
        ordenar_por = request.query_params.get('ordenar', 'recomendado')
        tipo_proveedor = request.query_params.get('tipo_proveedor', '')
        precio_max = request.query_params.get('precio_max', '')
        
        # Obtener vehículo activo
        try:
            vehiculo_activo = VehiculoActivo.objects.get(
                cliente=request.user.cliente
            )
            vehiculo = vehiculo_activo.vehiculo
        except VehiculoActivo.DoesNotExist:
            return Response(
                {'error': 'No hay vehículo activo seleccionado'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Filtrar servicios compatibles con el vehículo (marca/modelo)
        from mecanimovilapp.apps.servicios.compatibilidad_vehiculo import (
            queryset_servicios_compatibles_vehiculo,
        )

        servicios = queryset_servicios_compatibles_vehiculo(vehiculo)
        
        # Aplicar filtro de búsqueda por texto
        if query:
            servicios = servicios.filter(nombre__icontains=query)
        
        # Obtener ofertas de servicios
        ofertas = OfertaServicio.objects.filter(
            servicio__in=servicios,
            disponible=True
        )
        
        # Aplicar filtros adicionales
        if tipo_proveedor:
            ofertas = ofertas.filter(tipo_proveedor=tipo_proveedor)
        
        if precio_max:
            try:
                precio_max = float(precio_max)
                ofertas = ofertas.filter(precio_sin_repuestos__lte=precio_max)
            except ValueError:
                pass
        
        # Aplicar ordenamiento
        if ordenar_por == 'recomendado':
            # Usar motor de ML para ordenar por relevancia
            motor = MotorRecomendaciones()
            ofertas = motor.ordenar_por_relevancia(ofertas, vehiculo)
        elif ordenar_por == 'precio':
            ofertas = ofertas.order_by('precio_sin_repuestos')
        elif ordenar_por == 'calificacion':
            ofertas = ofertas.order_by('-servicio__calificacion_promedio')
        elif ordenar_por == 'distancia':
            # TODO: Implementar ordenamiento por distancia
            pass
        
        # Serializar resultados
        from mecanimovilapp.apps.servicios.serializers import OfertaServicioSerializer
        serializer = OfertaServicioSerializer(ofertas[:20], many=True)
        
        return Response({
            'resultados': serializer.data,
            'total': ofertas.count(),
            'vehiculo_activo': {
                'id': vehiculo.id,
                'marca': vehiculo.marca_nombre,
                'modelo': vehiculo.modelo_nombre
            }
        })

# Alias para compatibilidad con tests
RecomendacionPersonalizadaViewSet = RecomendacionesViewSet 
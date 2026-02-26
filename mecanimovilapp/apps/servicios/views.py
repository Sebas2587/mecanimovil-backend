from rest_framework import viewsets, permissions, serializers
from .models import (
    CategoriaServicio, Servicio, DetalleServicio, OfertaServicio, Repuesto, ServicioRepuesto, FotoServicio
)
from .serializers import (
    CategoriaServicioSerializer, ServicioSerializer, DetalleServicioSerializer,
    OfertaServicioSerializer, OfertaServicioBasicSerializer, ServicioListSerializer,
    OfertaServicioProveedorSerializer, RepuestoSerializer, ServicioRepuestoSerializer,
    FotoServicioSerializer, FotoServicioUploadSerializer
)
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework import filters
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from mecanimovilapp.apps.vehiculos.models import Marca, Vehiculo, Modelo
from django.db import models
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page


class CategoriaServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo CategoriaServicio
    """
    queryset = CategoriaServicio.objects.all().order_by('orden', 'nombre')
    serializer_class = CategoriaServicioSerializer
    permission_classes = [AllowAny]  # Permitir acceso sin autenticación a todos los endpoints
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'descripcion']
    pagination_class = None  # Deshabilitar paginación para categorías
    
    @method_decorator(cache_page(60*60*24)) # Cache por 24 horas
    def list(self, request, *args, **kwargs):
        """
        Sobrescribir el método list para devolver todas las categorías sin filtros
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    @method_decorator(cache_page(60*60*24))
    def principales(self, request):
        """
        Obtiene solo las categorías principales (sin categoría padre)
        """
        categorias = CategoriaServicio.objects.filter(categoria_padre__isnull=True)
        serializer = self.get_serializer(categorias, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    @method_decorator(cache_page(60*60*24))
    def subcategorias(self, request, pk=None):
        """
        Obtiene las subcategorías de una categoría específica
        """
        categoria = self.get_object()
        subcategorias = categoria.subcategorias.all()
        serializer = self.get_serializer(subcategorias, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    @method_decorator(cache_page(60*60*24))
    def arbol(self, request):
        """
        Devuelve todas las categorías organizadas jerárquicamente
        """
        # Obtenemos solo las categorías principales
        categorias_principales = CategoriaServicio.objects.filter(categoria_padre__isnull=True)
        serializer = self.get_serializer(categorias_principales, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def buscar(self, request):
        """
        Busca categorías por nombre o descripción
        """
        termino = request.query_params.get('q', '')
        if not termino:
            return Response([])
        
        categorias = CategoriaServicio.objects.filter(
            models.Q(nombre__icontains=termino) | 
            models.Q(descripcion__icontains=termino)
        )
        serializer = self.get_serializer(categorias, many=True)
        return Response(serializer.data)


class ServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo Servicio
    """
    queryset = Servicio.objects.all()
    serializer_class = ServicioSerializer
    permission_classes = [AllowAny]  # Permitir acceso sin autenticación
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'descripcion']
    
    def get_queryset(self):
        """Optimizar queryset con prefetch_related para repuestos"""
        return Servicio.objects.prefetch_related('repuestos_necesarios__repuesto')
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ServicioListSerializer
        return ServicioSerializer
    
    @action(detail=False, methods=['get'])
    def por_categoria(self, request):
        """
        Endpoint para obtener servicios de una categoría específica
        Incluye información de ofertas disponibles de talleres y mecánicos
        """
        categoria_id = request.query_params.get('categoria')
        if not categoria_id:
            return Response(
                {"error": "Se requiere el parámetro 'categoria'"},
                status=400
            )
        
        try:
            # Verificar que la categoría existe
            categoria = CategoriaServicio.objects.get(id=categoria_id)
            
            # Obtener servicios de la categoría (usar 'categorias' porque es ManyToMany)
            servicios = self.queryset.filter(
                categorias=categoria
            ).prefetch_related(
                'ofertas', 
                'ofertas__taller__usuario',
                'ofertas__mecanico__usuario',
                'repuestos_necesarios__repuesto'
            ).distinct()
            
            # Serializar con información de ofertas
            serializer = ServicioListSerializer(servicios, many=True)
            return Response(serializer.data)
            
        except CategoriaServicio.DoesNotExist:
            return Response(
                {"error": f"La categoría con ID {categoria_id} no existe"},
                status=404
            )
    
    @action(detail=False, methods=['get'])
    def por_modelo(self, request):
        """
        Endpoint para obtener servicios compatibles con un modelo específico
        También incluye servicios que tienen ofertas disponibles para la marca del vehículo
        """
        modelo_id = request.query_params.get('modelo')
        if not modelo_id:
            return Response(
                {"error": "Se requiere el parámetro 'modelo'"},
                status=400
            )
        
        try:
            modelo = Modelo.objects.select_related('marca').get(id=modelo_id)
            marca = modelo.marca
            
            # Opción 1: Servicios que tienen el modelo específico en modelos_compatibles
            servicios_por_modelo = self.queryset.filter(modelos_compatibles=modelo).distinct()
            
            # Opción 2: Servicios que tienen ofertas disponibles para la marca del vehículo
            # (incluso si el modelo específico no está en modelos_compatibles)
            from .models import OfertaServicio
            servicios_con_ofertas = Servicio.objects.filter(
                ofertas__marca_vehiculo_seleccionada=marca,
                ofertas__disponible=True
            ).distinct()
            
            # También incluir servicios con ofertas sin marca específica (NULL) si hay proveedores que atienden la marca
            from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
            from django.db.models import Q
            
            talleres_ids = Taller.objects.filter(
                marcas_atendidas=marca,
                verificado=True,
                activo=True
            ).values('id')

            mecanicos_ids = MecanicoDomicilio.objects.filter(
                marcas_atendidas=marca,
                verificado=True,
                activo=True
            ).values('id')
            
            servicios_con_ofertas_genericas = Servicio.objects.filter(
                Q(ofertas__marca_vehiculo_seleccionada__isnull=True) &
                Q(ofertas__disponible=True) &
                (
                    Q(ofertas__taller_id__in=talleres_ids) |
                    Q(ofertas__mecanico_id__in=mecanicos_ids)
                )
            ).distinct()
            
            # Combinar todas las opciones (OR): servicios por modelo O servicios con ofertas para la marca
            servicios = (servicios_por_modelo | servicios_con_ofertas | servicios_con_ofertas_genericas).distinct()
            
            # PREFETCH MANUAL PARA EVITAR N+1
            # Como los querysets combinados (OR) a veces pierden el prefetch o son difíciles de prefetcher antes,
            # lo hacemos sobre los IDs resultantes para garantizar eficiencia.
            servicios_ids = list(servicios.values_list('id', flat=True))
            servicios_finales = Servicio.objects.filter(id__in=servicios_ids).prefetch_related(
                'ofertas',
                'ofertas__taller',
                'ofertas__mecanico__usuario',
                'categorias'
            )
            
            serializer = ServicioListSerializer(servicios_finales, many=True)
            return Response(serializer.data)
        except Modelo.DoesNotExist:
            return Response(
                {"error": f"El modelo con ID {modelo_id} no existe"},
                status=404
            )
    
    @action(detail=True, methods=['get'])
    def detalles(self, request, pk=None):
        """
        Endpoint para obtener todos los detalles de un servicio específico
        """
        servicio = self.get_object()
        detalles = DetalleServicio.objects.filter(servicio=servicio)
        serializer = DetalleServicioSerializer(detalles, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def ofertas(self, request, pk=None):
        """
        Endpoint para obtener todas las ofertas disponibles para un servicio específico
        """
        servicio = self.get_object()
        ofertas = OfertaServicio.objects.filter(servicio=servicio, disponible=True)
        serializer = OfertaServicioSerializer(ofertas, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def talleres(self, request, pk=None):
        """
        Endpoint para obtener todos los talleres que ofrecen un servicio específico
        """
        servicio = self.get_object()
        ofertas = OfertaServicio.objects.filter(
            servicio=servicio, 
            tipo_proveedor='taller',
            disponible=True
        )
        talleres = [oferta.taller for oferta in ofertas]
        
        # Usar un serializador personalizado para incluir precios
        resultados = []
        for taller in talleres:
            oferta = OfertaServicio.objects.get(servicio=servicio, taller=taller)
            resultados.append({
                'taller': {
                    'id': taller.id,
                    'nombre': taller.nombre,
                    'telefono': taller.telefono,
                    'calificacion_promedio': taller.calificacion_promedio
                },
                'precio_con_repuestos': oferta.precio_con_repuestos,
                'precio_sin_repuestos': oferta.precio_sin_repuestos
            })
        
        return Response(resultados)
    
    @action(detail=True, methods=['get'])
    def mecanicos(self, request, pk=None):
        """
        Endpoint para obtener todos los mecánicos que ofrecen un servicio específico
        """
        servicio = self.get_object()
        ofertas = OfertaServicio.objects.filter(
            servicio=servicio, 
            tipo_proveedor='mecanico',
            disponible=True
        )
        mecanicos = [oferta.mecanico for oferta in ofertas]
        
        # Usar un serializador personalizado para incluir precios
        resultados = []
        for mecanico in mecanicos:
            oferta = OfertaServicio.objects.get(servicio=servicio, mecanico=mecanico)
            resultados.append({
                'mecanico': {
                    'id': mecanico.id,
                    'nombre': mecanico.nombre,
                    'telefono': mecanico.telefono,
                    'calificacion_promedio': mecanico.calificacion_promedio
                },
                'precio_con_repuestos': oferta.precio_con_repuestos,
                'precio_sin_repuestos': oferta.precio_sin_repuestos
            })
        
        return Response(resultados)
    
    @action(detail=True, methods=['get'])
    def resenas(self, request, pk=None):
        """
        Endpoint para obtener las reseñas de un servicio específico
        """
        servicio = self.get_object()
        
        # Generar reseñas de ejemplo ya que no existe un modelo de reseñas
        import random
        from datetime import datetime, timedelta
        
        # Generar entre 3 y 7 reseñas de ejemplo
        num_reviews = random.randint(3, 7)
        reviews = []
        
        for i in range(num_reviews):
            # Generar fecha aleatoria en los últimos 30 días
            days_ago = random.randint(1, 30)
            review_date = datetime.now() - timedelta(days=days_ago)
            
            # Generar calificación aleatoria entre 3 y 5
            rating = random.randint(3, 5)
            
            # Seleccionar comentario aleatorio
            comments = [
                'Excelente servicio, muy profesional.',
                'Buen trabajo, pero un poco caro.',
                'El técnico fue muy amable y resolvió el problema rápidamente.',
                'Recomiendo este servicio, quedé muy conforme.',
                'Terminaron antes del tiempo estimado, muy eficientes.'
            ]
            comment = random.choice(comments)
            
            # Generar nombre de usuario aleatorio
            user_names = ['Juan Pérez', 'María García', 'Carlos López', 'Ana Martínez', 'Roberto Sánchez']
            user_name = random.choice(user_names)
            
            reviews.append({
                'id': i + 1,
                'usuario': {
                    'nombre': user_name,
                    'foto': None
                },
                'calificacion': rating,
                'comentario': comment,
                'fecha': review_date.isoformat()
            })
        
        return Response(reviews)


class DetalleServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo DetalleServicio
    """
    queryset = DetalleServicio.objects.all()
    serializer_class = DetalleServicioSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['caracteristica']


class OfertaServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo OfertaServicio
    """
    queryset = OfertaServicio.objects.all()
    serializer_class = OfertaServicioSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['servicio__nombre', 'taller__nombre', 'mecanico__nombre']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return OfertaServicioBasicSerializer
        return OfertaServicioSerializer
    
    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def por_taller(self, request):
        """
        Obtiene todas las ofertas de servicios disponibles para un taller específico
        """
        taller_id = request.query_params.get('taller')
        if not taller_id:
            return Response({"error": "Se requiere el parámetro 'taller'"}, status=400)
        
        ofertas = OfertaServicio.objects.filter(taller_id=taller_id, disponible=True)
        serializer = self.get_serializer(ofertas, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def por_mecanico(self, request):
        """
        Obtiene todas las ofertas de servicios disponibles para un mecánico específico
        """
        mecanico_id = request.query_params.get('mecanico')
        if not mecanico_id:
            return Response({"error": "Se requiere el parámetro 'mecanico'"}, status=400)
        
        # Validate that mecanico_id is an integer
        if not str(mecanico_id).isdigit():
            return Response([])

        ofertas = OfertaServicio.objects.filter(mecanico_id=mecanico_id, disponible=True)
        serializer = self.get_serializer(ofertas, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def mejores_precios(self, request):
        """
        Obtiene las ofertas con los mejores precios para cada servicio
        """
        servicio_id = request.query_params.get('servicio')
        tipo = request.query_params.get('tipo', 'todos')  # 'taller', 'mecanico' o 'todos'
        
        # Filtrar por servicio específico si se proporciona
        queryset = OfertaServicio.objects.filter(disponible=True)
        if servicio_id:
            queryset = queryset.filter(servicio_id=servicio_id)
        
        # Filtrar por tipo de proveedor si se especifica
        if tipo == 'taller':
            queryset = queryset.filter(tipo_proveedor='taller')
        elif tipo == 'mecanico':
            queryset = queryset.filter(tipo_proveedor='mecanico')
        
        # Obtener la oferta más económica por servicio
        servicios_ids = queryset.values_list('servicio_id', flat=True).distinct()
        mejores_ofertas = []
        
        for sid in servicios_ids:
            # Mejor oferta con repuestos
            mejor_con_repuestos = queryset.filter(
                servicio_id=sid
            ).order_by('precio_con_repuestos').first()
            
            # Mejor oferta sin repuestos
            mejor_sin_repuestos = queryset.filter(
                servicio_id=sid
            ).order_by('precio_sin_repuestos').first()
            
            if mejor_con_repuestos:
                mejores_ofertas.append(mejor_con_repuestos)
            
            # Añadir la mejor oferta sin repuestos solo si es diferente
            if mejor_sin_repuestos and mejor_sin_repuestos.id != mejor_con_repuestos.id:
                mejores_ofertas.append(mejor_sin_repuestos)
        
        serializer = OfertaServicioSerializer(mejores_ofertas, many=True)
        return Response(serializer.data)


# Nuevo endpoint público para obtener servicios por vehículo
@api_view(['GET'])
@permission_classes([AllowAny])
def servicios_por_vehiculo(request):
    """
    Obtiene servicios compatibles con un vehículo específico
    Utiliza el modelo del vehículo Y también incluye servicios con ofertas para la marca
    """
    vehiculo_id = request.query_params.get('vehiculo', None)
    
    if not vehiculo_id:
        return Response(
            {"error": "Se requiere el parámetro 'vehiculo'"},
            status=400
        )
    
    try:
        vehiculo = Vehiculo.objects.select_related('modelo', 'marca').get(id=vehiculo_id)
    except Vehiculo.DoesNotExist:
        return Response(
            {"error": f"El vehículo con ID {vehiculo_id} no existe"},
            status=404
        )
    
    # Obtener el modelo y marca del vehículo
    modelo = vehiculo.modelo
    marca = vehiculo.marca
    
    if not modelo or not marca:
        return Response(
            {"error": "El vehículo no tiene modelo o marca asociada"},
            status=400
        )
    
    # Opción 1: Servicios que tienen el modelo específico en modelos_compatibles
    servicios_por_modelo = Servicio.objects.filter(modelos_compatibles=modelo).distinct()
    
    # Opción 2: Servicios que tienen ofertas disponibles para la marca del vehículo
    # (incluso si el modelo específico no está en modelos_compatibles)
    from .models import OfertaServicio
    servicios_con_ofertas = Servicio.objects.filter(
        ofertas__marca_vehiculo_seleccionada=marca,
        ofertas__disponible=True
    ).distinct()
    
    # Opción 3: Servicios con ofertas sin marca específica (NULL) si hay proveedores que atienden la marca
    from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
    from django.db.models import Q
    
    talleres_ids = Taller.objects.filter(
        marcas_atendidas=marca,
        verificado=True,
        activo=True
    ).values('id')

    mecanicos_ids = MecanicoDomicilio.objects.filter(
        marcas_atendidas=marca,
        verificado=True,
        activo=True
    ).values('id')
    
    servicios_con_ofertas_genericas = Servicio.objects.filter(
        Q(ofertas__marca_vehiculo_seleccionada__isnull=True) &
        Q(ofertas__disponible=True) &
        (
            Q(ofertas__taller_id__in=talleres_ids) |
            Q(ofertas__mecanico_id__in=mecanicos_ids)
        )
    ).distinct()
    
    # Combinar todas las opciones (OR): servicios por modelo O servicios con ofertas para la marca
    servicios = (servicios_por_modelo | servicios_con_ofertas | servicios_con_ofertas_genericas).distinct()
    
    # PREFETCH MANUAL PARA EVITAR N+1
    servicios_ids = list(servicios.values_list('id', flat=True))
    servicios_finales = Servicio.objects.filter(id__in=servicios_ids).prefetch_related(
        'ofertas',
        'ofertas__taller',
        'ofertas__mecanico__usuario',
        'categorias'
    )
    
    serializer = ServicioListSerializer(servicios_finales, many=True)
    return Response(serializer.data)


# ========================================
# ViewSets específicos para PROVEEDORES
# ========================================

class ProveedorOfertaServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet específico para que los proveedores gestionen sus propias ofertas de servicios
    """
    serializer_class = OfertaServicioProveedorSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['servicio__nombre', 'tipo_servicio']
    
    def _get_proveedor_data(self, user):
        """
        Helper para obtener información del proveedor autenticado
        """
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
        
        try:
            # Buscar si es mecánico
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            return {'tipo': 'mecanico', 'proveedor': mecanico}
        except MecanicoDomicilio.DoesNotExist:
            try:
                # Buscar si es taller
                taller = Taller.objects.get(usuario=user)
                return {'tipo': 'taller', 'proveedor': taller}
            except Taller.DoesNotExist:
                # Usuario no tiene perfil de proveedor
                return {'tipo': None, 'proveedor': None}
    
    def get_queryset(self):
        """Filtrar ofertas solo del proveedor autenticado"""
        proveedor_data = self._get_proveedor_data(self.request.user)
        
        if proveedor_data['tipo'] == 'mecanico':
            return OfertaServicio.objects.filter(mecanico=proveedor_data['proveedor'])
        elif proveedor_data['tipo'] == 'taller':
            return OfertaServicio.objects.filter(taller=proveedor_data['proveedor'])
        else:
            return OfertaServicio.objects.none()
    
    @action(detail=False, methods=['get'])
    def resumen_estadisticas(self, request):
        """Obtiene estadísticas resumen para el proveedor"""
        queryset = self.get_queryset()
        
        total_ofertas = queryset.count()
        ofertas_activas = queryset.filter(disponible=True).count()
        ofertas_con_repuestos = queryset.filter(tipo_servicio='con_repuestos').count()
        ofertas_sin_repuestos = queryset.filter(tipo_servicio='sin_repuestos').count()
        
        # Calcular ganancias estimadas
        ganancia_total = sum([
            float(oferta.ganancia_neta_proveedor) 
            for oferta in queryset 
            if oferta.ganancia_neta_proveedor
        ])
        
        return Response({
            'total_ofertas': total_ofertas,
            'ofertas_activas': ofertas_activas,
            'ofertas_con_repuestos': ofertas_con_repuestos,
            'ofertas_sin_repuestos': ofertas_sin_repuestos,
            'ganancia_potencial_total': ganancia_total
        })
    
    @action(detail=True, methods=['post'])
    def cambiar_disponibilidad(self, request, pk=None):
        """Cambiar la disponibilidad de una oferta específica"""
        oferta = self.get_object()
        nueva_disponibilidad = request.data.get('disponible')
        
        if nueva_disponibilidad is not None:
            oferta.disponible = bool(nueva_disponibilidad)
            oferta.save()
            
            return Response({
                'mensaje': f'Oferta {"activada" if oferta.disponible else "desactivada"} correctamente',
                'disponible': oferta.disponible
            })
        
        return Response({'error': 'Se requiere el campo "disponible"'}, status=400)
    
    @action(detail=False, methods=['get'])
    def calcular_preview(self, request):
        """Calcular preview de precios sin guardar"""
        costo_mano_obra = float(request.query_params.get('costo_mano_obra', 0))
        costo_repuestos = float(request.query_params.get('costo_repuestos', 0))
        
        from decimal import Decimal
        
        # Constantes
        IVA_RATE = Decimal('0.19')
        COMISION_RATE = Decimal('0.20')
        
        # Cálculos
        costo_total_sin_iva = Decimal(str(costo_mano_obra)) + Decimal(str(costo_repuestos))
        iva = costo_total_sin_iva * IVA_RATE
        precio_final_cliente = costo_total_sin_iva + iva
        comision = costo_total_sin_iva * COMISION_RATE
        iva_comision = comision * IVA_RATE
        ganancia_neta = costo_total_sin_iva - comision
        monto_transferido = precio_final_cliente - (comision + iva_comision)
        
        return Response({
            'costo_total_sin_iva': float(costo_total_sin_iva),
            'iva_19_porciento': float(iva),
            'precio_final_cliente': float(precio_final_cliente),
            'comision_mecanmovil_20_porciento': float(comision),
            'iva_sobre_comision': float(iva_comision),
            'ganancia_neta_proveedor': float(ganancia_neta),
            'monto_transferido': float(monto_transferido)
        })

    @action(detail=False, methods=['get'])
    def mis_marcas(self, request):
        """
        Devuelve las marcas de vehículos que atiende el proveedor
        """
        try:
            proveedor_data = self._get_proveedor_data(request.user)
            if not proveedor_data['proveedor']:
                return Response(
                    {'error': 'No se encontró información del proveedor'},
                    status=404
                )
            
            proveedor = proveedor_data['proveedor']
            marcas_ids = proveedor.marcas_atendidas.values_list('id', flat=True)
            
            # Importar el modelo de marcas
            from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo
            marcas = MarcaVehiculo.objects.filter(id__in=marcas_ids).values('id', 'nombre')
            
            return Response(list(marcas))
            
        except Exception as e:
            return Response(
                {'error': f'Error obteniendo marcas del proveedor: {str(e)}'},
                status=500
            )

    @action(detail=False, methods=['get'])
    def servicios_por_marca(self, request):
        """
        Devuelve los servicios disponibles para una marca específica del proveedor
        """
        try:
            marca_id = request.query_params.get('marca_id')
            if not marca_id:
                return Response(
                    {'error': 'Debe especificar marca_id'},
                    status=400
                )
            
            proveedor_data = self._get_proveedor_data(request.user)
            if not proveedor_data['proveedor']:
                return Response(
                    {'error': 'No se encontró información del proveedor'},
                    status=404
                )
            
            proveedor = proveedor_data['proveedor']
            
            # permitimos que el endpoint responda incluso si el proveedor ha desmarcado esta marca,
            # para no romper la pantalla de EDICIÓN de un servicio previamente configurado.
            
            # Obtener especialidades del proveedor
            especialidades_ids = proveedor.especialidades.values_list('id', flat=True)
            
            # Obtener servicios relacionados con las especialidades del proveedor Y la marca específica
            servicios = Servicio.objects.filter(
                categorias__in=especialidades_ids,
                modelos_compatibles__marca_id=marca_id  # ✅ FILTRAR POR MARCA
            ).prefetch_related('categorias').values(
                'id', 'nombre', 'descripcion', 'requiere_repuestos'
            ).distinct()  # ✅ EVITAR DUPLICADOS
            
            return Response(list(servicios))
            
        except Exception as e:
            return Response(
                {'error': f'Error obteniendo servicios: {str(e)}'},
                status=500
            )

    @action(detail=False, methods=['get'])
    def para_solicitud(self, request):
        """
        Obtiene el servicio configurado del proveedor para una solicitud específica.
        Busca OfertaServicio que coincida con el servicio solicitado y la marca del vehículo.
        
        Parámetros:
        - solicitud_id: UUID de la solicitud pública
        - servicio_id: ID del servicio solicitado
        
        Retorna el servicio configurado con toda la información (repuestos, precios, tipo)
        o null si no existe un servicio configurado para esa combinación.
        """
        from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica
        from django.shortcuts import get_object_or_404
        
        try:
            import logging
            logger = logging.getLogger(__name__)
            
            solicitud_id = request.query_params.get('solicitud_id')
            servicio_id_str = request.query_params.get('servicio_id')
            
            if not solicitud_id or not servicio_id_str:
                return Response(
                    {'error': 'Debe especificar solicitud_id y servicio_id'},
                    status=400
                )
            
            # Convertir servicio_id a entero
            try:
                servicio_id = int(servicio_id_str)
            except (ValueError, TypeError):
                logger.error(f'Error: servicio_id no es un número válido: {servicio_id_str}')
                return Response(
                    {'error': f'servicio_id debe ser un número válido, recibido: {servicio_id_str}'},
                    status=400
                )
            
            logger.info(f'🔍 Buscando servicio configurado - solicitud_id: {solicitud_id}, servicio_id: {servicio_id}, usuario: {request.user.username}')
            
            # Obtener la solicitud y validar que existe
            try:
                solicitud = SolicitudServicioPublica.objects.select_related(
                    'vehiculo', 'vehiculo__marca'
                ).get(id=solicitud_id)
            except SolicitudServicioPublica.DoesNotExist:
                logger.error(f'❌ Solicitud no encontrada: {solicitud_id}')
                return Response(
                    {'error': 'Solicitud no encontrada'},
                    status=404
                )
            
            # Obtener la marca del vehículo
            marca_vehiculo = solicitud.vehiculo.marca if solicitud.vehiculo and solicitud.vehiculo.marca else None
            
            if not marca_vehiculo:
                logger.error(f'❌ El vehículo de la solicitud no tiene marca asociada')
                return Response(
                    {'error': 'El vehículo de la solicitud no tiene marca asociada'},
                    status=400
                )
            
            logger.info(f'📋 Solicitud encontrada - Vehículo: {solicitud.vehiculo.modelo if solicitud.vehiculo else "N/A"}, Marca: {marca_vehiculo.nombre} (ID: {marca_vehiculo.id})')
            
            # Obtener información del proveedor autenticado
            proveedor_data = self._get_proveedor_data(request.user)
            if not proveedor_data['proveedor']:
                logger.error(f'❌ No se encontró información del proveedor para usuario: {request.user.username}')
                return Response(
                    {'error': 'No se encontró información del proveedor'},
                    status=404
                )
            
            proveedor = proveedor_data['proveedor']
            logger.info(f'👤 Proveedor: {proveedor.nombre if hasattr(proveedor, "nombre") else "N/A"} (Tipo: {proveedor_data["tipo"]})')
            
            # Buscar OfertaServicio que coincida:
            # 1. Servicio solicitado
            # 2. Marca del vehículo (o NULL para servicios genéricos)
            # 3. Proveedor autenticado
            
            queryset = self.get_queryset()
            total_ofertas = queryset.count()
            logger.info(f'📊 Total de ofertas del proveedor: {total_ofertas}')
            
            # Log de todas las ofertas del proveedor para debug
            todas_ofertas = queryset.values('id', 'servicio_id', 'servicio__nombre', 'marca_vehiculo_seleccionada_id', 'marca_vehiculo_seleccionada__nombre')
            logger.info(f'📋 Ofertas del proveedor: {list(todas_ofertas)}')
            
            # Buscar primero por marca específica
            oferta_servicio = queryset.filter(
                servicio_id=servicio_id,
                marca_vehiculo_seleccionada=marca_vehiculo
            ).select_related(
                'servicio', 'marca_vehiculo_seleccionada'
            ).prefetch_related(
                'servicio__categorias'
            ).first()
            
            logger.info(f'🔎 Búsqueda por marca específica ({marca_vehiculo.id}): {"✅ Encontrado" if oferta_servicio else "❌ No encontrado"}')
            
            # Si no se encuentra, buscar servicio genérico (sin marca específica)
            if not oferta_servicio:
                oferta_servicio = queryset.filter(
                    servicio_id=servicio_id,
                    marca_vehiculo_seleccionada__isnull=True
                ).select_related(
                    'servicio'
                ).prefetch_related(
                    'servicio__categorias'
                ).first()
                
                logger.info(f'🔎 Búsqueda genérica (sin marca): {"✅ Encontrado" if oferta_servicio else "❌ No encontrado"}')
            
            # Si no se encuentra ningún servicio configurado, retornar null con información de debug
            if not oferta_servicio:
                logger.warning(f'⚠️ No se encontró servicio configurado - servicio_id: {servicio_id}, marca_id: {marca_vehiculo.id}')
                return Response({
                    'servicio_configurado': None,
                    'mensaje': 'No se encontró un servicio configurado para esta combinación',
                    'debug_info': {
                        'servicio_id_buscado': servicio_id,
                        'marca_id_buscada': marca_vehiculo.id,
                        'marca_nombre': marca_vehiculo.nombre,
                        'total_ofertas_proveedor': total_ofertas,
                        'ofertas_disponibles': list(todas_ofertas)
                    }
                })
            
            # Serializar el servicio configurado
            serializer = self.get_serializer(oferta_servicio)
            return Response({
                'servicio_configurado': serializer.data,
                'mensaje': 'Servicio configurado encontrado'
            })
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Error obteniendo servicio para solicitud: {str(e)}', exc_info=True)
            return Response(
                {'error': f'Error obteniendo servicio configurado: {str(e)}'},
                status=500
            )


class RepuestoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para consultar repuestos disponibles
    """
    queryset = Repuesto.objects.filter(activo=True)
    serializer_class = RepuestoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'descripcion', 'marca', 'categoria_repuesto']
    
    @action(detail=False, methods=['get'])
    def por_servicio(self, request):
        """Obtiene repuestos asociados a un servicio específico"""
        servicio_id = request.query_params.get('servicio')
        if not servicio_id:
            return Response({'error': 'Se requiere el parámetro servicio'}, status=400)
        
        try:
            servicio = Servicio.objects.get(id=servicio_id)
            relaciones = ServicioRepuesto.objects.filter(servicio=servicio)
            repuestos_data = []
            
            for relacion in relaciones:
                repuesto_data = RepuestoSerializer(relacion.repuesto).data
                repuesto_data['cantidad_estimada'] = relacion.cantidad_estimada
                repuesto_data['es_opcional'] = relacion.es_opcional
                repuestos_data.append(repuesto_data)
            
            return Response(repuestos_data)
            
        except Servicio.DoesNotExist:
            return Response({'error': 'Servicio no encontrado'}, status=404)
    
    @action(detail=False, methods=['get'])
    def por_categoria(self, request):
        """Obtiene repuestos filtrados por categoría"""
        categoria = request.query_params.get('categoria')
        if not categoria:
            return Response({'error': 'Se requiere el parámetro categoria'}, status=400)
        
        repuestos = self.queryset.filter(categoria_repuesto=categoria)
        serializer = self.get_serializer(repuestos, many=True)
        return Response(serializer.data)


class FotoServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar fotos de servicios
    """
    serializer_class = FotoServicioSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar fotos por ofertas del proveedor autenticado"""
        user = self.request.user
        
        # Obtener ofertas del proveedor autenticado
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
        
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            ofertas_ids = OfertaServicio.objects.filter(mecanico=mecanico).values_list('id', flat=True)
        except MecanicoDomicilio.DoesNotExist:
            try:
                taller = Taller.objects.get(usuario=user)
                ofertas_ids = OfertaServicio.objects.filter(taller=taller).values_list('id', flat=True)
            except Taller.DoesNotExist:
                return FotoServicio.objects.none()
        
        return FotoServicio.objects.filter(oferta_servicio_id__in=ofertas_ids)
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return FotoServicioUploadSerializer
        return FotoServicioSerializer
    
    def perform_create(self, serializer):
        """Asociar la foto con la oferta del proveedor autenticado"""
        oferta_id = self.request.data.get('oferta_servicio')
        if not oferta_id:
            raise serializers.ValidationError({'oferta_servicio': 'Este campo es requerido'})
        
        # Verificar que la oferta pertenece al proveedor autenticado
        user = self.request.user
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
        
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            oferta = OfertaServicio.objects.get(id=oferta_id, mecanico=mecanico)
        except MecanicoDomicilio.DoesNotExist:
            try:
                taller = Taller.objects.get(usuario=user)
                oferta = OfertaServicio.objects.get(id=oferta_id, taller=taller)
            except (Taller.DoesNotExist, OfertaServicio.DoesNotExist):
                raise serializers.ValidationError({'oferta_servicio': 'Oferta no encontrada o no autorizada'})
        
        serializer.save(oferta_servicio=oferta)
    
    @action(detail=False, methods=['post'])
    def subir_multiple(self, request):
        """Subir múltiples fotos para una oferta de servicio"""
        oferta_id = request.data.get('oferta_servicio')
        if not oferta_id:
            return Response({'error': 'Se requiere oferta_servicio'}, status=400)
        
        # Verificar que la oferta pertenece al proveedor autenticado
        user = request.user
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
        
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            oferta = OfertaServicio.objects.get(id=oferta_id, mecanico=mecanico)
        except MecanicoDomicilio.DoesNotExist:
            try:
                taller = Taller.objects.get(usuario=user)
                oferta = OfertaServicio.objects.get(id=oferta_id, taller=taller)
            except (Taller.DoesNotExist, OfertaServicio.DoesNotExist):
                return Response({'error': 'Oferta no encontrada o no autorizada'}, status=403)
        
        # Procesar múltiples archivos
        fotos = request.FILES.getlist('fotos')
        if not fotos:
            return Response({'error': 'No se proporcionaron fotos'}, status=400)
        
        fotos_creadas = []
        for i, foto in enumerate(fotos):
            foto_servicio = FotoServicio.objects.create(
                oferta_servicio=oferta,
                imagen=foto,
                descripcion=f"Foto {i + 1}",
                orden=i + 1
            )
            fotos_creadas.append(FotoServicioSerializer(foto_servicio, context={'request': request}).data)
        
        return Response({
            'mensaje': f'{len(fotos_creadas)} fotos subidas exitosamente',
            'fotos': fotos_creadas
        }) 
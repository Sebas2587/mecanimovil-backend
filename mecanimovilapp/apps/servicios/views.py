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
from django.http import FileResponse, Http404
from mecanimovilapp.apps.vehiculos.models import Marca, Vehiculo, Modelo
from django.db import models
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
import mimetypes

from .compatibilidad_vehiculo import (
    queryset_servicios_catalogo_por_marca,
    servicios_comunes_por_marcas_queryset,
)


def _precio_oferta_publica(oferta):
    pub = float(oferta.precio_publicado_cliente or 0)
    if pub > 0:
        return pub
    return float(oferta.precio_sin_repuestos or 0)


_SKIP_NUMERO = frozenset({'s/n', 'sn', 's/n.', '-', '0', 'null', 'undefined', ''})


def _clean_dir_part(raw):
    s = str(raw or '').strip()
    if not s:
        return ''
    lower = s.lower()
    if lower.startswith('provincia de '):
        return ''
    if lower.startswith('región ') or lower.startswith('region '):
        return ''
    if lower == 'chile':
        return ''
    return s


def _resolve_provider_direccion_payload(proveedor):
    """
    Dirección legible + campos estructurados para cards.
    Taller usa `direccion_fisica`; evita exponer solo "1499" o "s/n".
    """
    if proveedor is None:
        return {'direccion': None, 'direccion_fisica': None, 'comuna': None}

    df = getattr(proveedor, 'direccion_fisica', None)
    if df is not None:
        calle = _clean_dir_part(getattr(df, 'calle', None))
        numero_raw = str(getattr(df, 'numero', None) or '').strip()
        numero = '' if numero_raw.lower() in _SKIP_NUMERO else numero_raw
        comuna = _clean_dir_part(getattr(df, 'comuna', None))
        ciudad = _clean_dir_part(getattr(df, 'ciudad', None))
        street = ' '.join(p for p in (calle, numero) if p).strip()
        place = comuna or ciudad or ''
        parts = []
        if street:
            parts.append(street)
        if place and (not street or place.lower() not in street.lower()):
            parts.append(place)
        direccion = ', '.join(parts) if parts else None
        return {
            'direccion': direccion,
            'comuna': comuna or None,
            'direccion_fisica': {
                'calle': calle or None,
                'numero': numero or None,
                'comuna': comuna or None,
                'ciudad': ciudad or None,
                'direccion_completa': direccion,
            },
        }

    raw = getattr(proveedor, 'direccion', None)
    text = str(raw).strip() if raw else ''
    return {
        'direccion': text or None,
        'comuna': None,
        'direccion_fisica': None,
    }


def _proveedor_payload_publico(oferta):
    proveedor = oferta.taller if oferta.tipo_proveedor == 'taller' else oferta.mecanico
    if not proveedor:
        return None
    foto = getattr(proveedor, 'foto_perfil', None)
    dir_payload = _resolve_provider_direccion_payload(proveedor)
    return {
        'id': proveedor.id,
        'nombre': proveedor.nombre,
        'tipo': oferta.tipo_proveedor,
        'foto_perfil': foto.url if foto else None,
        'calificacion_promedio': getattr(proveedor, 'calificacion_promedio', 0) or 0,
        'direccion': dir_payload['direccion'],
        'comuna': dir_payload['comuna'],
        'direccion_fisica': dir_payload['direccion_fisica'],
        'verificado': bool(getattr(proveedor, 'verificado', False)),
        'tipo_cobertura_marca': getattr(proveedor, 'tipo_cobertura_marca', 'especialista'),
    }


def _cobertura_vehiculo_payload(oferta, provider_data):
    """
    Para qué vehículo aplica esta oferta: marca/modelo específicos de la oferta
    si existen, o el alcance del proveedor (multimarca vs especialista) como fallback.
    Requiere prefetch de marcas_atendidas y select_related de marca/modelo.
    """
    marca = getattr(oferta, 'marca_vehiculo_seleccionada', None)
    modelo = getattr(oferta, 'modelo_vehiculo_seleccionado', None)
    modelo_nombre = modelo.nombre if modelo is not None else None
    if marca is not None:
        return {
            'alcance': 'marca',
            'marca_nombre': marca.nombre,
            'modelo_nombre': modelo_nombre,
            'marcas_nombres': [],
        }
    if provider_data and provider_data.get('tipo_cobertura_marca') == 'multimarca':
        return {
            'alcance': 'multimarca',
            'marca_nombre': None,
            'modelo_nombre': None,
            'marcas_nombres': [],
        }

    proveedor = oferta.taller if oferta.tipo_proveedor == 'taller' else oferta.mecanico
    marcas_nombres = []
    if proveedor is not None:
        marcas_nombres = [m.nombre for m in list(proveedor.marcas_atendidas.all())[:4]]
    return {
        'alcance': 'especialista',
        'marca_nombre': None,
        'modelo_nombre': None,
        'marcas_nombres': marcas_nombres,
    }


def _serializar_servicios_con_ofertas(servicio_ids, totales_por_servicio=None):
    """
    Payload público compartido (`buscar` + `mas_solicitados`): por cada servicio,
    todas sus ofertas disponibles (talleres/mecánicos) con precio, tipo de servicio
    (con/sin repuestos) y cobertura de vehículo (marca específica / multimarca).
    Mantiene el orden de `servicio_ids`.
    """
    totales_por_servicio = totales_por_servicio or {}

    servicios_map = {
        s.id: s
        for s in Servicio.objects.filter(id__in=servicio_ids).prefetch_related('categorias')
    }

    ofertas_qs = (
        OfertaServicio.objects
        .filter(servicio_id__in=servicio_ids, disponible=True)
        .select_related(
            'taller',
            'taller__direccion_fisica',
            'mecanico',
            'marca_vehiculo_seleccionada',
            'modelo_vehiculo_seleccionado',
        )
        .prefetch_related('taller__marcas_atendidas', 'mecanico__marcas_atendidas')
        .order_by('precio_publicado_cliente')
    )

    ofertas_por_servicio = {}
    for oferta in ofertas_qs:
        ofertas_por_servicio.setdefault(oferta.servicio_id, []).append(oferta)

    resultado = []
    for sid in servicio_ids:
        servicio = servicios_map.get(sid)
        if not servicio:
            continue

        ofertas_payload = []
        precios = []
        for oferta in ofertas_por_servicio.get(sid, []):
            provider_data = _proveedor_payload_publico(oferta)
            if not provider_data:
                continue
            precio = _precio_oferta_publica(oferta)
            if precio > 0:
                precios.append(precio)
            ofertas_payload.append({
                'oferta_id': oferta.id,
                'servicio_id': sid,
                'nombre': servicio.nombre,
                'precio': precio,
                'precio_publicado_cliente': float(oferta.precio_publicado_cliente or 0),
                'tipo_servicio': oferta.tipo_servicio or 'sin_repuestos',
                'provider': provider_data,
                'provider_type': oferta.tipo_proveedor,
                'cobertura_vehiculo': _cobertura_vehiculo_payload(oferta, provider_data),
            })

        if not ofertas_payload:
            continue

        categoria = servicio.categorias.first()
        proveedores_unicos = {
            (o.get('provider_type'), (o.get('provider') or {}).get('id'))
            for o in ofertas_payload
            if (o.get('provider') or {}).get('id') is not None
        }

        resultado.append({
            # `id` = alias de servicio_id para clientes legacy (p. ej. precompra).
            'id': sid,
            'servicio_id': sid,
            'nombre': servicio.nombre,
            'descripcion': servicio.descripcion or '',
            'categoria_nombre': categoria.nombre if categoria else None,
            'foto': servicio.foto.url if servicio.foto else None,
            'precio_referencia': (
                float(servicio.precio_referencia)
                if servicio.precio_referencia is not None
                else None
            ),
            'total_solicitudes': totales_por_servicio.get(sid),
            'precio_desde': min(precios) if precios else None,
            'precio_hasta': max(precios) if precios else None,
            # Talleres/mecánicos distintos (no cantidad de ofertas por marca).
            'total_proveedores': len(proveedores_unicos),
            'ofertas': ofertas_payload,
        })

    return resultado


def servicios_catalogo_por_marca_queryset(marca_id, tipo_motor=None):
    """
    Servicios del catálogo filtrados por compatibilidad de marca/modelo,
    sin usar las categorías/especialidades del proveedor.
    - marca_id 0: servicios sin marcas ni modelos asignados (genéricos).
    - otro id: servicios con marca directa o legacy vía modelos de esa marca.
    - tipo_motor opcional: filtra por tipos_motor_compatibles.
    """
    return queryset_servicios_catalogo_por_marca(marca_id, tipo_motor=tipo_motor)


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

    @action(detail=True, methods=['get'], url_path='imagen')
    def imagen(self, request, pk=None):
        """
        Sirve la imagen de categoría vía API (CORS de Django).
        Necesario en web: R2 privado sin CORS bloquea expo-image en el browser.
        """
        categoria = self.get_object()
        if not categoria.imagen:
            raise Http404('Categoría sin imagen')
        try:
            file_handle = categoria.imagen.open('rb')
        except Exception as exc:
            raise Http404('Imagen no disponible') from exc

        content_type = mimetypes.guess_type(categoria.imagen.name)[0] or 'application/octet-stream'
        response = FileResponse(file_handle, content_type=content_type)
        response['Cache-Control'] = 'public, max-age=86400'
        response['Access-Control-Allow-Origin'] = '*'
        return response

    @method_decorator(cache_page(60 * 15))  # 15 min — iconos nuevos deben verse pronto
    def list(self, request, *args, **kwargs):
        """
        Sobrescribir el método list para devolver todas las categorías sin filtros
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    @method_decorator(cache_page(60 * 15))
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

    @action(detail=False, methods=['get'], url_path='buscar')
    def buscar(self, request):
        """
        Busca servicios por nombre o descripción (query param q). Público (AllowAny).

        Devuelve, para cada servicio que coincide, TODAS las ofertas disponibles
        (talleres + mecánicos) con precio, tipo (con/sin repuestos) y marca/vehículo
        para el que aplica — igual forma que `mas_solicitados` — en vez de un único
        taller "adivinado". Así el cliente ve el servicio y elige entre talleres.
        """
        termino = (request.query_params.get('q') or '').strip()
        if not termino:
            return Response([])
        servicio_ids = list(
            self.get_queryset().filter(
                models.Q(nombre__icontains=termino) | models.Q(descripcion__icontains=termino)
            ).distinct().values_list('id', flat=True)[:30]
        )
        if not servicio_ids:
            return Response([])

        resultado = _serializar_servicios_con_ofertas(servicio_ids)
        return Response(resultado)

    @action(detail=False, methods=['get'], url_path='mas_solicitados')
    def mas_solicitados(self, request):
        """
        Servicios realmente más solicitados (demanda histórica de solicitudes reales),
        no solo catálogo. Público (AllowAny): usado en la landing de invitado y en el
        panel de usuarios logueados.

        Para cada servicio top, devuelve TODAS las ofertas disponibles (talleres +
        mecánicos) con su propio precio, para que el cliente compare y elija proveedor
        en vez de ver un único taller "adivinado".

        `marca_id` opcional: acota la demanda a solicitudes de vehículos de esa marca
        (usuarios logueados con auto registrado ven lo que realmente pidieron otros
        dueños de su misma marca, no el ranking genérico global).
        """
        from mecanimovilapp.apps.ordenes.models import LineaServicio

        try:
            limit = max(1, min(int(request.query_params.get('limit', 12)), 24))
        except (TypeError, ValueError):
            limit = 12

        estados_excluidos = [
            'cancelado',
            'rechazada_por_proveedor',
            'solicitud_cancelacion',
        ]

        marca_id = request.query_params.get('marca_id')
        try:
            marca_id = int(marca_id) if marca_id not in (None, '') else None
        except (TypeError, ValueError):
            marca_id = None

        conteos = (
            LineaServicio.objects
            .exclude(solicitud__estado__in=estados_excluidos)
            .exclude(oferta_servicio__isnull=True)
        )
        if marca_id is not None:
            conteos = conteos.filter(solicitud__vehiculo__marca_id=marca_id)
        conteos = (
            conteos
            .values('oferta_servicio__servicio_id')
            .annotate(total=models.Count('id'))
            .order_by('-total')
        )

        ranking = []
        seen_ids = set()
        for row in conteos:
            sid = row['oferta_servicio__servicio_id']
            if sid is None or sid in seen_ids:
                continue
            seen_ids.add(sid)
            ranking.append((sid, row['total']))
            if len(ranking) >= limit:
                break

        if not ranking:
            return Response([])

        servicio_ids = [sid for sid, _ in ranking]
        totales_por_servicio = dict(ranking)
        resultado = _serializar_servicios_con_ofertas(
            servicio_ids, totales_por_servicio=totales_por_servicio,
        )
        return Response(resultado)

    @action(detail=False, methods=['get'], url_path='catalogo_por_marca')
    def catalogo_por_marca(self, request):
        """
        Catálogo público de servicios por marca (onboarding / referencia).
        No depende de las especialidades del proveedor.
        """
        marca_id = request.query_params.get('marca_id')
        if not marca_id:
            return Response(
                {'error': 'Debe especificar marca_id'},
                status=400
            )
        tipo_motor = request.query_params.get('tipo_motor')
        try:
            qs = servicios_catalogo_por_marca_queryset(marca_id, tipo_motor=tipo_motor)
            return Response(
                list(qs.values('id', 'nombre', 'descripcion', 'requiere_repuestos', 'tipos_motor_compatibles'))
            )
        except Exception as e:
            return Response(
                {'error': f'Error obteniendo servicios: {str(e)}'},
                status=500
            )

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
            
            # Servicios de la categoría y de sus subcategorías (explore por categoría padre)
            categoria_ids = [categoria.id]
            categoria_ids.extend(
                categoria.subcategorias.values_list('id', flat=True)
            )
            servicios = self.queryset.filter(
                categorias__id__in=categoria_ids
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
        tipo_motor = request.query_params.get('tipo_motor')
        if not modelo_id:
            return Response(
                {"error": "Se requiere el parámetro 'modelo'"},
                status=400
            )
        
        try:
            from .catalogo_vehiculo import queryset_servicios_disponibles_para_modelo_marca

            modelo = Modelo.objects.select_related('marca').get(id=modelo_id)
            marca = modelo.marca
            servicios_finales = queryset_servicios_disponibles_para_modelo_marca(
                modelo, marca, tipo_motor=tipo_motor
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
        Endpoint para obtener todas las ofertas disponibles para un servicio específico.
        Puede filtrar por marca de vehículo.
        """
        servicio = self.get_object()
        marca_id = request.query_params.get('marca')
        
        queryset = OfertaServicio.objects.filter(servicio=servicio, disponible=True)
        
        if marca_id:
            from django.db.models import Q
            from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
            
            # Obtener IDs de proveedores verificados que atienden la marca
            talleres_ids = Taller.objects.filter(
                marcas_atendidas__id=marca_id, verificado=True, activo=True
            ).values_list('id', flat=True)
            
            mecanicos_ids = MecanicoDomicilio.objects.filter(
                marcas_atendidas__id=marca_id, verificado=True, activo=True
            ).values_list('id', flat=True)
            
            # Filtro: Ofertas para la marca exacta OR Ofertas genéricas de proveedores aptos
            queryset = queryset.filter(
                Q(marca_vehiculo_seleccionada_id=marca_id) |
                (
                    Q(marca_vehiculo_seleccionada__isnull=True) &
                    (Q(taller_id__in=talleres_ids) | Q(mecanico_id__in=mecanicos_ids))
                )
            ).distinct()
            
        serializer = OfertaServicioSerializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def talleres(self, request, pk=None):
        """
        Endpoint para obtener todos los talleres que ofrecen un servicio específico.
        Puede filtrar opcionalmente por la marca_id.
        """
        servicio = self.get_object()
        marca_id = request.query_params.get('marca')
        
        ofertas = OfertaServicio.objects.filter(
            servicio=servicio, 
            tipo_proveedor='taller',
            disponible=True
        )
        
        if marca_id:
            from django.db.models import Q
            from mecanimovilapp.apps.usuarios.models import Taller
            talleres_ids = Taller.objects.filter(
                marcas_atendidas__id=marca_id, verificado=True, activo=True
            ).values_list('id', flat=True)
            
            ofertas = ofertas.filter(
                Q(marca_vehiculo_seleccionada_id=marca_id) |
                (
                    Q(marca_vehiculo_seleccionada__isnull=True) &
                    Q(taller_id__in=talleres_ids)
                )
            ).distinct()
            
        talleres = [oferta.taller for oferta in ofertas if oferta.taller]
        
        # Usar un serializador personalizado para incluir precios
        resultados = []
        for taller in talleres:
            oferta = ofertas.filter(taller=taller).first()
            if oferta:
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
        Endpoint para obtener todos los mecánicos que ofrecen un servicio específico.
        Puede filtrar opcionalmente por marca_id.
        """
        servicio = self.get_object()
        marca_id = request.query_params.get('marca')
        
        ofertas = OfertaServicio.objects.filter(
            servicio=servicio, 
            tipo_proveedor='mecanico',
            disponible=True
        )
        
        if marca_id:
            from django.db.models import Q
            from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio
            mecanicos_ids = MecanicoDomicilio.objects.filter(
                marcas_atendidas__id=marca_id, verificado=True, activo=True
            ).values_list('id', flat=True)
            
            ofertas = ofertas.filter(
                Q(marca_vehiculo_seleccionada_id=marca_id) |
                (
                    Q(marca_vehiculo_seleccionada__isnull=True) &
                    Q(mecanico_id__in=mecanicos_ids)
                )
            ).distinct()
            
        mecanicos = [oferta.mecanico for oferta in ofertas if oferta.mecanico]
        
        # Usar un serializador personalizado para incluir precios
        resultados = []
        for mecanico in mecanicos:
            oferta = ofertas.filter(mecanico=mecanico).first()
            if oferta:
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
        Obtiene todas las ofertas de servicios disponibles para un taller específico.
        Usa select_related + prefetch_related para evitar N+1 queries:
        sin esto, cada oferta dispara queries adicionales por servicio, categorías y modelos.
        """
        taller_id = request.query_params.get('taller')
        if not taller_id:
            return Response({"error": "Se requiere el parámetro 'taller'"}, status=400)

        ofertas = (
            OfertaServicio.objects
            .filter(taller_id=taller_id, disponible=True)
            .select_related(
                'servicio',
                'taller',
                'taller__usuario',
                'marca_vehiculo_seleccionada',
            )
            .prefetch_related(
                'servicio__categorias',
                'servicio__marcas_compatibles',
                'servicio__modelos_compatibles',
                'servicio__modelos_compatibles__marca',
                'fotos_servicio',
            )
        )
        serializer = OfertaServicioSerializer(ofertas, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def por_mecanico(self, request):
        """
        Obtiene todas las ofertas de servicios disponibles para un mecánico específico.
        Usa select_related + prefetch_related para evitar N+1 queries.
        """
        mecanico_id = request.query_params.get('mecanico')
        if not mecanico_id:
            return Response({"error": "Se requiere el parámetro 'mecanico'"}, status=400)

        if not str(mecanico_id).isdigit():
            return Response([])

        ofertas = (
            OfertaServicio.objects
            .filter(mecanico_id=mecanico_id, disponible=True)
            .select_related(
                'servicio',
                'mecanico',
                'mecanico__usuario',
                'marca_vehiculo_seleccionada',
            )
            .prefetch_related(
                'servicio__categorias',
                'servicio__marcas_compatibles',
                'servicio__modelos_compatibles',
                'servicio__modelos_compatibles__marca',
                'fotos_servicio',
            )
        )
        serializer = OfertaServicioSerializer(ofertas, many=True, context={'request': request})
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
    
    from .catalogo_vehiculo import queryset_servicios_disponibles_para_modelo_marca

    servicios_finales = queryset_servicios_disponibles_para_modelo_marca(modelo, marca)
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
    # Lista completa: la app proveedor usa badges/filtros por marca; paginar en 10 ocultaba ofertas.
    pagination_class = None
    
    def _get_proveedor_data(self, user):
        """
        Helper para obtener información del proveedor autenticado.

        Incluye al supervisor con login propio, que opera sobre el taller del
        mandante (se marca con rol='supervisor' para validar permisos).
        """
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller, MiembroTaller
        
        try:
            # Buscar si es mecánico
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            return {'tipo': 'mecanico', 'proveedor': mecanico, 'rol': 'mandante'}
        except MecanicoDomicilio.DoesNotExist:
            try:
                # Buscar si es taller
                taller = Taller.objects.get(usuario=user)
                return {'tipo': 'taller', 'proveedor': taller, 'rol': 'mandante'}
            except Taller.DoesNotExist:
                # Supervisor con login propio: opera el taller del mandante
                supervisor = (
                    MiembroTaller.objects
                    .filter(usuario=user, rol='supervisor', activo=True)
                    .select_related('taller')
                    .first()
                )
                if supervisor is not None:
                    return {
                        'tipo': 'taller',
                        'proveedor': supervisor.taller,
                        'rol': 'supervisor',
                        'miembro': supervisor,
                    }
                # Usuario no tiene perfil de proveedor
                return {'tipo': None, 'proveedor': None, 'rol': None}

    def _exigir_permiso_servicios(self):
        """Escrituras del catálogo requieren permiso 'servicios' (o ser mandante)."""
        if self.request.method in permissions.SAFE_METHODS:
            return
        data = self._get_proveedor_data(self.request.user)
        if data.get('rol') == 'supervisor':
            miembro = data.get('miembro')
            if not (miembro and miembro.tiene_permiso('servicios')):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('No tienes permiso para gestionar servicios.')

    def perform_create(self, serializer):
        self._exigir_permiso_servicios()
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._exigir_permiso_servicios()
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._exigir_permiso_servicios()
        super().perform_destroy(instance)
    
    def get_queryset(self):
        """Filtrar ofertas solo del proveedor autenticado"""
        proveedor_data = self._get_proveedor_data(self.request.user)
        
        base = OfertaServicio.objects.select_related(
            'marca_vehiculo_seleccionada',
            'modelo_vehiculo_seleccionado',
            'modelo_vehiculo_seleccionado__marca',
            'servicio',
        ).prefetch_related('servicio__categorias')
        if proveedor_data['tipo'] == 'mecanico':
            return base.filter(mecanico=proveedor_data['proveedor'])
        if proveedor_data['tipo'] == 'taller':
            return base.filter(taller=proveedor_data['proveedor'])
        return OfertaServicio.objects.none()
    
    @action(detail=False, methods=['post'])
    def crear_catalogo_inicial(self, request):
        """
        Crea registros OfertaServicio como catálogo inicial de onboarding.
        Body: { "servicios": [{"servicio_id": 1, "marca_id": 2, "modelo_id": 3}, ...] }
        Los registros se crean con disponible=False y precios en 0 para configurar después.
        Si el par (proveedor, servicio, marca) ya existe, se omite silenciosamente.
        """
        self._exigir_permiso_servicios()
        proveedor_data = self._get_proveedor_data(request.user)
        if not proveedor_data['proveedor']:
            return Response({'error': 'No se encontró información del proveedor'}, status=404)

        servicios_raw = request.data.get('servicios', [])
        if not isinstance(servicios_raw, list):
            return Response({'error': 'El campo "servicios" debe ser una lista'}, status=400)

        tipo = proveedor_data['tipo']
        proveedor = proveedor_data['proveedor']

        from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo

        creados = 0
        omitidos = 0
        errores = []
        servicios_ok = []

        for item in servicios_raw:
            servicio_id = item.get('servicio_id')
            marca_id = item.get('marca_id')
            modelo_id = item.get('modelo_id')

            if not servicio_id:
                errores.append({'item': item, 'error': 'Falta servicio_id'})
                continue

            try:
                servicio = Servicio.objects.get(id=servicio_id)
            except Servicio.DoesNotExist:
                errores.append({'item': item, 'error': f'Servicio {servicio_id} no encontrado'})
                continue
            servicios_ok.append(servicio)

            marca = None
            if marca_id:
                try:
                    marca = MarcaVehiculo.objects.get(id=marca_id)
                except MarcaVehiculo.DoesNotExist:
                    errores.append({'item': item, 'error': f'Marca {marca_id} no encontrada'})
                    continue

            modelo = None
            if modelo_id:
                try:
                    modelo = Modelo.objects.get(id=modelo_id)
                except Modelo.DoesNotExist:
                    errores.append({'item': item, 'error': f'Modelo {modelo_id} no encontrado'})
                    continue
                if marca and modelo.marca_id != marca.id:
                    errores.append({
                        'item': item,
                        'error': f'El modelo {modelo_id} no pertenece a la marca {marca_id}',
                    })
                    continue
                if not marca:
                    marca = modelo.marca

            # Verificar duplicado
            filtros = {
                'servicio': servicio,
                'marca_vehiculo_seleccionada': marca,
                'modelo_vehiculo_seleccionado': modelo,
                'tipo_motor': '',
            }
            if tipo == 'taller':
                filtros['taller'] = proveedor
            else:
                filtros['mecanico'] = proveedor

            if OfertaServicio.objects.filter(**filtros).exists():
                omitidos += 1
                continue

            try:
                kwargs = {
                    'servicio': servicio,
                    'marca_vehiculo_seleccionada': marca,
                    'modelo_vehiculo_seleccionado': modelo,
                    'tipo_proveedor': tipo,
                    'disponible': False,
                    'tipo_servicio': 'sin_repuestos',
                    'costo_mano_de_obra_sin_iva': 0,
                    'costo_repuestos_sin_iva': 0,
                }
                if tipo == 'taller':
                    kwargs['taller'] = proveedor
                else:
                    kwargs['mecanico'] = proveedor

                OfertaServicio.objects.create(**kwargs)
                creados += 1
            except Exception as e:
                errores.append({'item': item, 'error': str(e)})

        # Derivar especialidades desde los servicios elegidos (categorías asociadas).
        # Esto permite que, al terminar onboarding, el proveedor vea especialidades coherentes
        # incluso si no las eligió manualmente.
        try:
            if servicios_ok:
                categorias_ids = set()
                for s in servicios_ok:
                    try:
                        categorias_ids.update(list(s.categorias.values_list('id', flat=True)))
                    except Exception:
                        continue
                if categorias_ids:
                    from mecanimovilapp.apps.servicios.models import CategoriaServicio
                    categorias = list(CategoriaServicio.objects.filter(id__in=list(categorias_ids)))
                    if hasattr(proveedor, 'especialidades'):
                        proveedor.especialidades.add(*categorias)
        except Exception as e:
            # No bloquear creación de catálogo por fallo de especialidades.
            errores.append({'item': 'especialidades', 'error': str(e)})

        return Response({
            'creados': creados,
            'omitidos': omitidos,
            'errores': errores,
        }, status=201 if creados > 0 else 200)

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
        self._exigir_permiso_servicios()
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
        """Calcular preview de precios sin guardar.

        El precio que verá y pagará el cliente se redondea a peso entero (CLP no admite
        decimales), igual que en OfertaServicio.calcular_precios y que el cobro en MP.
        """
        costo_mano_obra = float(request.query_params.get('costo_mano_obra', 0))
        costo_repuestos = float(request.query_params.get('costo_repuestos', 0))
        
        from decimal import Decimal, ROUND_HALF_UP

        def _clp(monto):
            return Decimal(str(monto)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        
        # Constantes
        IVA_RATE = Decimal('0.19')
        COMISION_RATE = Decimal('0.20')
        
        # Cálculos
        costo_total_sin_iva = Decimal(str(costo_mano_obra)) + Decimal(str(costo_repuestos))
        iva = costo_total_sin_iva * IVA_RATE
        precio_final_cliente = _clp(costo_total_sin_iva + iva)
        comision = _clp(costo_total_sin_iva * COMISION_RATE)
        iva_comision = _clp(comision * IVA_RATE)
        ganancia_neta = _clp(costo_total_sin_iva - (costo_total_sin_iva * COMISION_RATE))
        monto_transferido = _clp(precio_final_cliente - (comision + iva_comision))
        
        return Response({
            'costo_total_sin_iva': float(costo_total_sin_iva),
            'iva_19_porciento': float(_clp(iva)),
            'precio_final_cliente': float(precio_final_cliente),
            'comision_mecanmovil_20_porciento': float(comision),
            'iva_sobre_comision': float(iva_comision),
            'ganancia_neta_proveedor': float(ganancia_neta),
            'monto_transferido': float(monto_transferido)
        })

    @action(detail=False, methods=['get'])
    def mis_marcas(self, request):
        """
        Devuelve marcas para configurar ofertas.
        - Especialista: solo marcas_atendidas.
        - Multimarca: catálogo completo (precio por marca + precio base opcional).
        """
        try:
            proveedor_data = self._get_proveedor_data(request.user)
            if not proveedor_data['proveedor']:
                return Response(
                    {'error': 'No se encontró información del proveedor'},
                    status=404
                )

            from mecanimovilapp.apps.usuarios.proveedor_cobertura import TIPO_COBERTURA_MULTIMARCA
            from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo

            proveedor = proveedor_data['proveedor']
            es_multimarca = (
                getattr(proveedor, 'tipo_cobertura_marca', None) == TIPO_COBERTURA_MULTIMARCA
            )

            if es_multimarca:
                marcas_qs = MarcaVehiculo.objects.all().order_by('nombre')
            else:
                marcas_ids = proveedor.marcas_atendidas.values_list('id', flat=True)
                marcas_qs = MarcaVehiculo.objects.filter(id__in=marcas_ids).order_by('nombre')

            marcas = list(marcas_qs.values('id', 'nombre', 'logo'))

            return Response({
                'es_multimarca': es_multimarca,
                'marcas': marcas,
            })
            
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
            tipo_motor = request.query_params.get('tipo_motor')
            
            proveedor_data = self._get_proveedor_data(request.user)
            if not proveedor_data['proveedor']:
                return Response(
                    {'error': 'No se encontró información del proveedor'},
                    status=404
                )

            # Catálogo por compatibilidad de marca/modelo únicamente (sin filtrar por categorías del proveedor).
            qs = servicios_catalogo_por_marca_queryset(marca_id, tipo_motor=tipo_motor)
            from mecanimovilapp.apps.servicios.tipos_motor_utils import normalizar_lista_tipos_motor

            servicios = []
            for row in qs.values(
                'id', 'nombre', 'descripcion', 'requiere_repuestos', 'tipos_motor_compatibles'
            ):
                motores = normalizar_lista_tipos_motor(row.get('tipos_motor_compatibles'))
                row['tipos_motor_compatibles'] = motores
                row['motores_info'] = motores
                servicios.append(row)
            return Response(servicios)
            
        except Exception as e:
            return Response(
                {'error': f'Error obteniendo servicios: {str(e)}'},
                status=500
            )

    @action(detail=False, methods=['get'], url_path='servicios_comunes_por_marcas')
    def servicios_comunes_por_marcas(self, request):
        """
        Servicios del catálogo presentes en todas las marcas indicadas (intersección).
        Query: marca_ids=1,2,3
        """
        try:
            raw = request.query_params.get('marca_ids', '')
            if not raw or not str(raw).strip():
                return Response(
                    {'error': 'Debe especificar marca_ids (ej: 1,2,3)'},
                    status=400,
                )
            marca_ids = []
            for part in str(raw).split(','):
                part = part.strip()
                if not part:
                    continue
                try:
                    mid = int(part)
                except ValueError:
                    return Response(
                        {'error': f'marca_id inválido: {part}'},
                        status=400,
                    )
                if mid == 0:
                    return Response(
                        {
                            'error': (
                                'Para servicios genéricos use servicios_por_marca con marca_id=0'
                            )
                        },
                        status=400,
                    )
                marca_ids.append(mid)
            if len(marca_ids) < 2:
                return Response(
                    {
                        'error': (
                            'Indique al menos 2 marcas o use servicios_por_marca para una sola'
                        )
                    },
                    status=400,
                )

            proveedor_data = self._get_proveedor_data(request.user)
            if not proveedor_data['proveedor']:
                return Response(
                    {'error': 'No se encontró información del proveedor'},
                    status=404,
                )
            proveedor = proveedor_data['proveedor']
            from mecanimovilapp.apps.usuarios.proveedor_cobertura import TIPO_COBERTURA_MULTIMARCA
            from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo

            es_multimarca = (
                getattr(proveedor, 'tipo_cobertura_marca', None) == TIPO_COBERTURA_MULTIMARCA
            )

            if es_multimarca:
                existentes = set(
                    MarcaVehiculo.objects.filter(id__in=marca_ids).values_list('id', flat=True)
                )
                invalidas = [m for m in marca_ids if m not in existentes]
            else:
                atendidas = set(
                    proveedor.marcas_atendidas.values_list('id', flat=True)
                )
                invalidas = [m for m in marca_ids if m not in atendidas]

            if invalidas:
                return Response(
                    {
                        'error': (
                            'Algunas marcas no son válidas para tu perfil'
                            if es_multimarca
                            else 'Algunas marcas no están en tu configuración de especialidades'
                        ),
                        'marcas_invalidas': invalidas,
                    },
                    status=400,
                )

            qs = servicios_comunes_por_marcas_queryset(marca_ids)
            return Response(
                list(
                    qs.values(
                        'id',
                        'nombre',
                        'descripcion',
                        'requiere_repuestos',
                        'tipos_motor_compatibles',
                    )
                )
            )
        except Exception as e:
            return Response(
                {'error': f'Error obteniendo servicios comunes: {str(e)}'},
                status=500,
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
                    'vehiculo', 'vehiculo__marca', 'vehiculo__modelo'
                ).get(id=solicitud_id)
            except SolicitudServicioPublica.DoesNotExist:
                logger.error(f'❌ Solicitud no encontrada: {solicitud_id}')
                return Response(
                    {'error': 'Solicitud no encontrada'},
                    status=404
                )
            
            # Obtener la marca y modelo del vehículo
            marca_vehiculo = solicitud.vehiculo.marca if solicitud.vehiculo and solicitud.vehiculo.marca else None
            modelo_vehiculo = solicitud.vehiculo.modelo if solicitud.vehiculo and solicitud.vehiculo.modelo else None
            
            if not marca_vehiculo:
                logger.error(f'❌ El vehículo de la solicitud no tiene marca asociada')
                return Response(
                    {'error': 'El vehículo de la solicitud no tiene marca asociada'},
                    status=400
                )
            
            logger.info(
                f'📋 Solicitud encontrada - Vehículo: '
                f'{modelo_vehiculo.nombre if modelo_vehiculo else "N/A"}, '
                f'Marca: {marca_vehiculo.nombre} (ID: {marca_vehiculo.id})'
            )
            
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
            
            from mecanimovilapp.apps.servicios.oferta_resolucion import elegir_mejor_oferta_entre
            from django.db.models import Q
            
            queryset = self.get_queryset()
            total_ofertas = queryset.count()
            logger.info(f'📊 Total de ofertas del proveedor: {total_ofertas}')
            
            candidatas = queryset.filter(
                servicio_id=servicio_id,
            ).filter(
                Q(marca_vehiculo_seleccionada=marca_vehiculo)
                | Q(marca_vehiculo_seleccionada__isnull=True)
            ).select_related(
                'servicio',
                'marca_vehiculo_seleccionada',
                'modelo_vehiculo_seleccionado',
            ).prefetch_related(
                'servicio__categorias'
            )
            
            tipo_motor = getattr(solicitud.vehiculo, 'tipo_motor', None)
            oferta_servicio = elegir_mejor_oferta_entre(
                candidatas,
                marca_vehiculo,
                tipo_motor=tipo_motor,
                modelo=modelo_vehiculo,
            )
            
            logger.info(
                f'🔎 Búsqueda por marca/modelo ({marca_vehiculo.id}/'
                f'{modelo_vehiculo.id if modelo_vehiculo else "null"}): '
                f'{"✅ Encontrado" if oferta_servicio else "❌ No encontrado"}'
            )
            
            # Si no se encuentra ningún servicio configurado, retornar null con información de debug
            if not oferta_servicio:
                logger.warning(
                    f'⚠️ No se encontró servicio configurado - servicio_id: {servicio_id}, '
                    f'marca_id: {marca_vehiculo.id}, modelo_id: '
                    f'{modelo_vehiculo.id if modelo_vehiculo else None}'
                )
                todas_ofertas = queryset.values(
                    'id',
                    'servicio_id',
                    'servicio__nombre',
                    'marca_vehiculo_seleccionada_id',
                    'marca_vehiculo_seleccionada__nombre',
                    'modelo_vehiculo_seleccionado_id',
                    'modelo_vehiculo_seleccionado__nombre',
                )
                return Response({
                    'servicio_configurado': None,
                    'mensaje': 'No se encontró un servicio configurado para esta combinación',
                    'debug_info': {
                        'servicio_id_buscado': servicio_id,
                        'marca_id_buscada': marca_vehiculo.id,
                        'marca_nombre': marca_vehiculo.nombre,
                        'modelo_id_buscado': modelo_vehiculo.id if modelo_vehiculo else None,
                        'modelo_nombre': modelo_vehiculo.nombre if modelo_vehiculo else None,
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
    queryset = Repuesto.objects.filter(activo=True).prefetch_related(
        'marcas_compatibles',
        'modelos_compatibles',
        'modelos_compatibles__marca',
    )
    serializer_class = RepuestoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'descripcion', 'marca', 'categoria_repuesto']

    def get_queryset(self):
        qs = super().get_queryset()
        vehiculo_id = self.request.query_params.get('vehiculo')
        if vehiculo_id:
            from mecanimovilapp.apps.vehiculos.models import Vehiculo
            from .compatibilidad_repuesto import queryset_repuestos_compatibles_vehiculo

            try:
                vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(
                    id=vehiculo_id,
                    cliente__usuario=self.request.user,
                )
                compatibles = queryset_repuestos_compatibles_vehiculo(vehiculo)
                return qs.filter(id__in=compatibles.values_list('id', flat=True))
            except Vehiculo.DoesNotExist:
                return qs.none()
        return qs
    
    @action(detail=False, methods=['get'])
    def por_servicio(self, request):
        """Obtiene repuestos asociados a un servicio específico (opcional: ?vehiculo=id)."""
        servicio_id = request.query_params.get('servicio')
        if not servicio_id:
            return Response({'error': 'Se requiere el parámetro servicio'}, status=400)

        try:
            servicio = Servicio.objects.get(id=servicio_id)
            relaciones = ServicioRepuesto.objects.filter(servicio=servicio).select_related(
                'repuesto'
            ).prefetch_related(
                'repuesto__marcas_compatibles',
                'repuesto__modelos_compatibles',
                'repuesto__modelos_compatibles__marca',
            )
            vehiculo_id = request.query_params.get('vehiculo')
            vehiculo = None
            if vehiculo_id:
                from mecanimovilapp.apps.vehiculos.models import Vehiculo
                from .compatibilidad_repuesto import repuesto_compatible_con_marca_modelo

                vehiculo = Vehiculo.objects.select_related('marca', 'modelo').filter(
                    id=vehiculo_id,
                    cliente__usuario=request.user,
                ).first()

            repuestos_data = []
            for relacion in relaciones:
                repuesto = relacion.repuesto
                if vehiculo and not repuesto_compatible_con_marca_modelo(
                    repuesto, vehiculo.marca, vehiculo.modelo
                ):
                    continue
                repuesto_data = RepuestoSerializer(repuesto).data
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


def _sync_oferta_fotos_urls(oferta, request):
    """Mantiene fotos_urls alineado con FotoServicio (listados y edición)."""
    from mecanimovilapp.storage.utils import get_image_url

    urls = []
    for foto in oferta.fotos_servicio.order_by('orden', 'id'):
        url = get_image_url(foto.imagen, request)
        if url:
            urls.append(url)
    if oferta.fotos_urls != urls:
        oferta.fotos_urls = urls
        oferta.save(update_fields=['fotos_urls'])


class FotoServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar fotos de servicios
    """
    serializer_class = FotoServicioSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Fotos solo de ofertas del proveedor autenticado.
        Si viene ?oferta_servicio=<id>, limitar a esa oferta (evita devolver todas las fotos
        en cada detalle y que parezcan “compartidas” entre servicios).
        """
        user = self.request.user

        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller

        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            ofertas_ids_qs = OfertaServicio.objects.filter(mecanico=mecanico).values_list('id', flat=True)
        except MecanicoDomicilio.DoesNotExist:
            try:
                taller = Taller.objects.get(usuario=user)
                ofertas_ids_qs = OfertaServicio.objects.filter(taller=taller).values_list('id', flat=True)
            except Taller.DoesNotExist:
                return FotoServicio.objects.none()

        ofertas_ids = set(ofertas_ids_qs)
        qs = FotoServicio.objects.filter(oferta_servicio_id__in=ofertas_ids)

        oferta_param = self.request.query_params.get('oferta_servicio')
        if oferta_param is not None and str(oferta_param).strip() != '':
            try:
                oid = int(oferta_param)
            except (TypeError, ValueError):
                return FotoServicio.objects.none()
            if oid not in ofertas_ids:
                return FotoServicio.objects.none()
            qs = qs.filter(oferta_servicio_id=oid)

        return qs
    
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
        _sync_oferta_fotos_urls(oferta, self.request)
    
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
        
        _sync_oferta_fotos_urls(oferta, request)

        return Response({
            'mensaje': f'{len(fotos_creadas)} fotos subidas exitosamente',
            'fotos': fotos_creadas,
            'fotos_urls': oferta.fotos_urls,
        })


@api_view(['GET'])
@permission_classes([AllowAny])
def servicios_buscar_alias(request):
    """
    GET /api/servicios/buscar/?q=...
    Alias porque el router registra la acción en .../servicios/servicios/buscar/.

    Misma forma que `mas_solicitados` / ViewSet.buscar: grupos por servicio con
    TODAS las ofertas (talleres + precios), no un único taller_principal.
    """
    termino = (request.query_params.get('q') or '').strip()
    if not termino:
        return Response([])
    servicio_ids = list(
        Servicio.objects.filter(
            models.Q(nombre__icontains=termino) | models.Q(descripcion__icontains=termino)
        ).distinct().values_list('id', flat=True)[:30]
    )
    if not servicio_ids:
        return Response([])
    return Response(_serializar_servicios_con_ofertas(servicio_ids))
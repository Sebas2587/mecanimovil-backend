import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Count, Avg, Sum, Q, F
from typing import List, Dict, Tuple

from .models import PerfilVehiculo, RecomendacionPersonalizada, ConfiguracionPersonalizacion
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, LineaServicio
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio


class MotorRecomendaciones:
    """
    Motor de recomendaciones basado en Machine Learning usando NumPy y Pandas
    """
    
    def __init__(self):
        self.configuraciones = self._cargar_configuraciones()
    
    def _cargar_configuraciones(self) -> Dict:
        """Carga las configuraciones del sistema de recomendaciones"""
        configs = ConfiguracionPersonalizacion.objects.all()
        return {config.clave: config.valor for config in configs}
    
    def _normalizar_scores(self, scores: np.ndarray) -> np.ndarray:
        """
        Normaliza un array de scores usando NumPy para que estén en el rango [0, 1]
        """
        if len(scores) == 0:
            return scores
        
        min_score = scores.min()
        max_score = scores.max()
        
        # Evitar división por cero
        if max_score == min_score:
            return np.full_like(scores, 0.5)
        
        return (scores - min_score) / (max_score - min_score)
    
    def _obtener_configuracion(self, clave: str, default=None):
        """Obtiene una configuración del sistema"""
        try:
            config = ConfiguracionPersonalizacion.objects.get(clave=clave)
            # Intentar convertir a float si es posible
            try:
                return float(config.valor)
            except ValueError:
                return config.valor
        except ConfiguracionPersonalizacion.DoesNotExist:
            return default
    
    def _obtener_datos_vehiculo(self, vehiculo: Vehiculo) -> Dict:
        """Obtiene datos estructurados del vehículo para análisis"""
        edad_vehiculo = datetime.now().year - vehiculo.year
        
        # Calcular días desde último mantenimiento
        ultimo_mantenimiento_dias = 365  # Default si no hay historial
        try:
            ultima_solicitud = SolicitudServicio.objects.filter(
                vehiculo=vehiculo,
                estado='completado'
            ).order_by('-fecha_servicio').first()
            
            if ultima_solicitud:
                ultimo_mantenimiento_dias = (timezone.now().date() - ultima_solicitud.fecha_servicio).days
        except:
            pass
        
        return {
            'kilometraje': vehiculo.kilometraje,
            'edad_vehiculo': edad_vehiculo,
            'ultimo_mantenimiento_dias': ultimo_mantenimiento_dias,
            'marca': vehiculo.marca.nombre,
            'modelo': vehiculo.modelo.nombre
        }
    
    def _calcular_score_mantenimiento(self, vehiculo_data: Dict) -> float:
        """
        Calcula score de mantenimiento basado en datos del vehículo
        """
        # Normalizar factores individuales
        km_norm = min(vehiculo_data['kilometraje'] / 200000, 1.0)
        edad_norm = min(vehiculo_data['edad_vehiculo'] / 15, 1.0)
        dias_norm = min(vehiculo_data['ultimo_mantenimiento_dias'] / 365, 1.0)
        
        # Combinar factores con pesos
        score = (km_norm * 0.4) + (edad_norm * 0.3) + (dias_norm * 0.3)
        
        return min(score, 1.0)
    
    def _calcular_score_proveedor(self, oferta, cliente) -> float:
        """Calcula score de un proveedor basado en métricas"""
        score = 0.0
        
        # Factor por calificación
        if hasattr(oferta, 'calificacion_promedio') and oferta.calificacion_promedio:
            score += (oferta.calificacion_promedio / 5.0) * 0.4
        
        # Factor por experiencia (número de servicios)
        if hasattr(oferta, 'total_servicios') and oferta.total_servicios:
            experiencia_norm = min(oferta.total_servicios / 100, 1.0)
            score += experiencia_norm * 0.3
        
        # Factor por proximidad (si está disponible)
        score += 0.3  # Base score
        
        return min(score, 1.0)
    
    def _calcular_score_popularidad(self, popularidad_data: Dict) -> float:
        """Calcula score basado en popularidad del servicio"""
        score = 0.0
        
        # Factor por número de solicitudes
        if 'total_solicitudes' in popularidad_data:
            popularidad_norm = min(popularidad_data['total_solicitudes'] / 100, 1.0)
            score += popularidad_norm * 0.4
        
        # Factor por popularidad en el modelo específico
        if 'solicitudes_modelo' in popularidad_data:
            modelo_norm = min(popularidad_data['solicitudes_modelo'] / 50, 1.0)
            score += modelo_norm * 0.3
        
        # Factor por calificación promedio
        if 'calificacion_promedio' in popularidad_data:
            cal_norm = popularidad_data['calificacion_promedio'] / 5.0
            score += cal_norm * 0.3
        
        return min(score, 1.0)
    
    def generar_recomendaciones_vehiculo(self, vehiculo: Vehiculo) -> None:
        """
        Genera todas las recomendaciones para un vehículo específico
        """
        # Actualizar perfil del vehículo
        self.actualizar_perfil_vehiculo(vehiculo)
        
        # Generar diferentes tipos de recomendaciones
        self._generar_mantenimiento_sugerido(vehiculo)
        self._generar_proveedores_destacados(vehiculo)
        self._generar_servicios_populares(vehiculo)
    
    def actualizar_perfil_vehiculo(self, vehiculo: Vehiculo) -> PerfilVehiculo:
        """
        Actualiza el perfil analítico del vehículo usando Pandas para análisis
        """
        perfil, created = PerfilVehiculo.objects.get_or_create(vehiculo=vehiculo)
        
        # Obtener datos históricos del vehículo
        solicitudes = SolicitudServicio.objects.filter(
            vehiculo=vehiculo,
            estado='completado'
        ).select_related('taller', 'mecanico')
        
        if not solicitudes.exists():
            return perfil
        
        # Convertir a DataFrame para análisis con Pandas
        solicitudes_data = []
        for solicitud in solicitudes:
            for linea in solicitud.lineas.all():
                solicitudes_data.append({
                    'fecha': solicitud.fecha_servicio,
                    'servicio_id': linea.oferta_servicio.servicio.id if linea.oferta_servicio else None,
                    'categoria_id': linea.oferta_servicio.servicio.categorias.first().id if linea.oferta_servicio and linea.oferta_servicio.servicio.categorias.exists() else None,
                    'precio': float(linea.precio_final),
                    'taller_id': solicitud.taller.id if solicitud.taller else None,
                    'mecanico_id': solicitud.mecanico.id if solicitud.mecanico else None,
                    'kilometraje': vehiculo.kilometraje  # Aproximado
                })
        
        if not solicitudes_data:
            return perfil
        
        df = pd.DataFrame(solicitudes_data)
        df['fecha'] = pd.to_datetime(df['fecha'])
        
        # Calcular métricas usando Pandas
        perfil.servicios_realizados = len(df)
        
        # Gasto promedio mensual
        df_monthly = df.groupby(df['fecha'].dt.to_period('M'))['precio'].sum()
        perfil.gasto_promedio_mensual = float(df_monthly.mean()) if len(df_monthly) > 0 else 0
        
        # Frecuencia de mantenimiento (días promedio entre servicios)
        if len(df) > 1:
            df_sorted = df.sort_values('fecha')
            dias_entre_servicios = df_sorted['fecha'].diff().dt.days.dropna()
            perfil.frecuencia_mantenimiento = int(dias_entre_servicios.mean()) if len(dias_entre_servicios) > 0 else 0
        
        # Categorías más frecuentes
        if 'categoria_id' in df.columns:
            categorias_freq = df['categoria_id'].value_counts().to_dict()
            # Convertir keys a string para JSON
            perfil.categorias_frecuentes = {str(k): v for k, v in categorias_freq.items() if k is not None}
        
        # Proveedores frecuentes
        talleres_freq = df[df['taller_id'].notna()]['taller_id'].value_counts().head(5).index.tolist()
        mecanicos_freq = df[df['mecanico_id'].notna()]['mecanico_id'].value_counts().head(5).index.tolist()
        
        perfil.talleres_frecuentes = [int(x) for x in talleres_freq]
        perfil.mecanicos_frecuentes = [int(x) for x in mecanicos_freq]
        
        # Score de mantenimiento urgente basado en kilometraje y tiempo
        vehiculo_data = self._obtener_datos_vehiculo(vehiculo)
        perfil.score_mantenimiento_urgente = self._calcular_score_mantenimiento(vehiculo_data)
        
        # Actualizar datos del último servicio
        if len(df) > 0:
            ultimo_servicio = df.loc[df['fecha'].idxmax()]
            perfil.km_ultimo_servicio = vehiculo.kilometraje
            perfil.dias_ultimo_servicio = (timezone.now().date() - ultimo_servicio['fecha'].date()).days
        
        perfil.save()
        return perfil
    
    def _generar_mantenimiento_sugerido(self, vehiculo: Vehiculo) -> None:
        """
        Genera recomendaciones de mantenimiento basadas en el perfil del vehículo
        """
        perfil = PerfilVehiculo.objects.get(vehiculo=vehiculo)
        
        # Obtener servicios compatibles con el vehículo (marca/modelo)
        from mecanimovilapp.apps.servicios.compatibilidad_vehiculo import (
            queryset_servicios_compatibles_vehiculo,
        )

        servicios_compatibles = queryset_servicios_compatibles_vehiculo(vehiculo)
        
        # Análisis de servicios recomendados por kilometraje
        servicios_km = self._servicios_por_kilometraje(vehiculo.kilometraje)
        
        # Análisis de servicios basado en historial
        servicios_historial = self._servicios_por_historial(perfil)
        
        # Combinar y puntuar recomendaciones
        recomendaciones_data = []
        
        for servicio in servicios_compatibles:
            score = 0.0
            razones = []
            
            # Score por kilometraje
            if servicio.id in servicios_km:
                score += 0.4
                razones.append(f"Recomendado para vehículos con {vehiculo.kilometraje:,} km")
            
            # Score por historial
            if str(servicio.categorias.first().id) in perfil.categorias_frecuentes:
                score += 0.3
                razones.append("Basado en tu historial de servicios")
            
            # Score por urgencia de mantenimiento
            score += perfil.score_mantenimiento_urgente * 0.3
            
            if score > 0.3:  # Umbral mínimo
                recomendaciones_data.append({
                    'servicio': servicio,
                    'score': score,
                    'razon': '. '.join(razones)
                })
        
        # Crear recomendaciones en la base de datos
        self._crear_recomendaciones(
            vehiculo, 
            recomendaciones_data, 
            'mantenimiento',
            max_recomendaciones=5
        )
    
    def _generar_proveedores_destacados(self, vehiculo: Vehiculo) -> None:
        """
        Genera recomendaciones de proveedores basadas en análisis de datos
        """
        perfil = PerfilVehiculo.objects.get(vehiculo=vehiculo)
        
        # Obtener ofertas de servicios para el vehículo (marca/modelo + ofertas por marca)
        from django.db.models import Q

        from mecanimovilapp.apps.servicios.compatibilidad_vehiculo import (
            queryset_servicios_compatibles_vehiculo,
        )

        servicios_ids = queryset_servicios_compatibles_vehiculo(vehiculo).values_list('id', flat=True)
        ofertas = OfertaServicio.objects.filter(
            Q(servicio_id__in=servicios_ids)
            | Q(marca_vehiculo_seleccionada_id=vehiculo.marca_id),
            disponible=True,
        ).select_related('servicio', 'taller', 'mecanico')
        
        if not ofertas.exists():
            return
        
        # Convertir a DataFrame para análisis
        ofertas_data = []
        for oferta in ofertas:
            proveedor = oferta.taller or oferta.mecanico
            ofertas_data.append({
                'oferta_id': oferta.id,
                'proveedor_id': proveedor.id,
                'proveedor_tipo': oferta.tipo_proveedor,
                'calificacion': proveedor.calificacion_promedio,
                'precio': float(oferta.precio_sin_repuestos),
                'servicio_id': oferta.servicio.id,
                'categoria_id': oferta.servicio.categorias.first().id if oferta.servicio.categorias.exists() else None
            })
        
        df_ofertas = pd.DataFrame(ofertas_data)
        
        # Calcular scores para cada proveedor
        recomendaciones_data = []
        
        for _, row in df_ofertas.iterrows():
            score = 0.0
            razones = []
            
            # Score por calificación (normalizado)
            score += (row['calificacion'] / 5.0) * 0.4
            razones.append(f"Calificación: {row['calificacion']:.1f}/5.0")
            
            # Score por historial del usuario
            if row['proveedor_tipo'] == 'taller' and row['proveedor_id'] in perfil.talleres_frecuentes:
                score += 0.3
                razones.append("Taller que has usado anteriormente")
            elif row['proveedor_tipo'] == 'mecanico' and row['proveedor_id'] in perfil.mecanicos_frecuentes:
                score += 0.3
                razones.append("Mecánico que has usado anteriormente")
            
            # Score por categoría frecuente
            if str(row['categoria_id']) in perfil.categorias_frecuentes:
                score += 0.2
                razones.append("Especialista en servicios que sueles usar")
            
            # Score por precio competitivo
            precio_promedio = df_ofertas[df_ofertas['servicio_id'] == row['servicio_id']]['precio'].mean()
            if row['precio'] <= precio_promedio:
                score += 0.1
                razones.append("Precio competitivo")
            
            if score > 0.4:  # Umbral mínimo
                oferta = OfertaServicio.objects.get(id=row['oferta_id'])
                recomendaciones_data.append({
                    'oferta_servicio': oferta,
                    'score': score,
                    'razon': '. '.join(razones)
                })
        
        # Crear recomendaciones en la base de datos
        self._crear_recomendaciones_ofertas(
            vehiculo,
            recomendaciones_data,
            'proveedor',
            max_recomendaciones=10
        )
    
    def _generar_servicios_populares(self, vehiculo: Vehiculo) -> None:
        """
        Genera recomendaciones de servicios populares para el modelo del vehículo
        """
        # Análisis de popularidad usando Pandas
        solicitudes = SolicitudServicio.objects.filter(
            vehiculo__modelo=vehiculo.modelo,
            estado='completado'
        ).select_related('vehiculo')
        
        # Obtener datos de líneas de servicio
        lineas_data = []
        for solicitud in solicitudes:
            for linea in solicitud.lineas.all():
                if linea.oferta_servicio:
                    lineas_data.append({
                        'servicio_id': linea.oferta_servicio.servicio.id,
                        'servicio_nombre': linea.oferta_servicio.servicio.nombre,
                        'fecha': solicitud.fecha_servicio,
                        'vehiculo_year': solicitud.vehiculo.year,
                        'precio': float(linea.precio_final)
                    })
        
        if not lineas_data:
            return
        
        df_servicios = pd.DataFrame(lineas_data)
        
        # Calcular popularidad por servicio
        popularidad = df_servicios.groupby(['servicio_id', 'servicio_nombre']).agg({
            'servicio_id': 'count',  # Frecuencia
            'precio': 'mean'  # Precio promedio
        }).rename(columns={'servicio_id': 'frecuencia'})
        
        # Normalizar scores
        popularidad['score_frecuencia'] = popularidad['frecuencia'] / popularidad['frecuencia'].max()
        
        # Filtrar por vehículos similares (±3 años)
        vehiculos_similares = df_servicios[
            abs(df_servicios['vehiculo_year'] - vehiculo.year) <= 3
        ]
        
        if len(vehiculos_similares) > 0:
            popularidad_similar = vehiculos_similares.groupby(['servicio_id', 'servicio_nombre']).size()
            popularidad['score_similar'] = popularidad.index.get_level_values(0).map(
                popularidad_similar.to_dict()
            ).fillna(0)
            popularidad['score_similar'] = popularidad['score_similar'] / popularidad['score_similar'].max()
        else:
            popularidad['score_similar'] = 0
        
        # Score final combinado
        popularidad['score_final'] = (
            popularidad['score_frecuencia'] * 0.6 + 
            popularidad['score_similar'] * 0.4
        )
        
        # Crear recomendaciones
        recomendaciones_data = []
        top_servicios = popularidad.nlargest(8, 'score_final')
        
        for (servicio_id, servicio_nombre), row in top_servicios.iterrows():
            try:
                servicio = Servicio.objects.get(id=servicio_id)
                recomendaciones_data.append({
                    'servicio': servicio,
                    'score': row['score_final'],
                    'razon': f"Popular entre vehículos {vehiculo.marca_nombre} {vehiculo.modelo_nombre} ({int(row['frecuencia'])} servicios realizados)"
                })
            except Servicio.DoesNotExist:
                continue
        
        self._crear_recomendaciones(
            vehiculo,
            recomendaciones_data,
            'servicio_popular',
            max_recomendaciones=8
        )
    
    def _servicios_por_kilometraje(self, kilometraje: int) -> List[int]:
        """
        Retorna servicios recomendados basados en el kilometraje
        """
        servicios_recomendados = []
        
        # Lógica basada en intervalos de kilometraje
        if kilometraje >= 10000 and kilometraje % 10000 <= 2000:
            # Servicios cada 10k km
            servicios_recomendados.extend([1, 2, 3])  # IDs de servicios básicos
        
        if kilometraje >= 20000 and kilometraje % 20000 <= 2000:
            # Servicios cada 20k km
            servicios_recomendados.extend([4, 5])  # IDs de servicios intermedios
        
        if kilometraje >= 40000 and kilometraje % 40000 <= 2000:
            # Servicios cada 40k km
            servicios_recomendados.extend([6, 7, 8])  # IDs de servicios mayores
        
        return servicios_recomendados
    
    def _servicios_por_historial(self, perfil: PerfilVehiculo) -> List[int]:
        """
        Retorna servicios recomendados basados en el historial del vehículo
        """
        servicios_recomendados = []
        
        # Basado en categorías frecuentes
        for categoria_id, frecuencia in perfil.categorias_frecuentes.items():
            if frecuencia >= 2:  # Si ha usado la categoría al menos 2 veces
                # Obtener servicios de esa categoría
                servicios = Servicio.objects.filter(
                    categorias__id=int(categoria_id)
                ).values_list('id', flat=True)
                servicios_recomendados.extend(list(servicios))
        
        return servicios_recomendados
    
    def _crear_recomendaciones(self, vehiculo: Vehiculo, recomendaciones_data: List[Dict], 
                              tipo: str, max_recomendaciones: int = 5) -> None:
        """
        Crea recomendaciones en la base de datos
        """
        # Limpiar recomendaciones anteriores del mismo tipo
        RecomendacionPersonalizada.objects.filter(
            vehiculo=vehiculo,
            tipo=tipo
        ).delete()
        
        # Ordenar por score y tomar las mejores
        recomendaciones_data.sort(key=lambda x: x['score'], reverse=True)
        recomendaciones_data = recomendaciones_data[:max_recomendaciones]
        
        # Crear nuevas recomendaciones
        for data in recomendaciones_data:
            RecomendacionPersonalizada.objects.create(
                cliente=vehiculo.cliente,
                vehiculo=vehiculo,
                tipo=tipo,
                servicio=data['servicio'],
                score_relevancia=data['score'],
                razon_recomendacion=data['razon'],
                fecha_expiracion=timezone.now() + timedelta(days=30)
            )
    
    def _crear_recomendaciones_ofertas(self, vehiculo: Vehiculo, recomendaciones_data: List[Dict], 
                                      tipo: str, max_recomendaciones: int = 10) -> None:
        """
        Crea recomendaciones de ofertas en la base de datos
        """
        # Limpiar recomendaciones anteriores del mismo tipo
        RecomendacionPersonalizada.objects.filter(
            vehiculo=vehiculo,
            tipo=tipo
        ).delete()
        
        # Ordenar por score y tomar las mejores
        recomendaciones_data.sort(key=lambda x: x['score'], reverse=True)
        recomendaciones_data = recomendaciones_data[:max_recomendaciones]
        
        # Crear nuevas recomendaciones
        for data in recomendaciones_data:
            RecomendacionPersonalizada.objects.create(
                cliente=vehiculo.cliente,
                vehiculo=vehiculo,
                tipo=tipo,
                servicio=data['oferta_servicio'].servicio,
                oferta_servicio=data['oferta_servicio'],
                score_relevancia=data['score'],
                razon_recomendacion=data['razon'],
                fecha_expiracion=timezone.now() + timedelta(days=30)
            )
    
    def ordenar_por_relevancia(self, ofertas, vehiculo: Vehiculo):
        """
        Ordena ofertas por relevancia usando el scorer unificado de motor_match.
        """
        from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match_scoring import (
            CoincidenciaCatalogoContext,
            calcular_score_coincidencia,
        )

        if hasattr(ofertas, 'exists') and not ofertas.exists():
            return ofertas

        ofertas_list = list(ofertas)
        if not ofertas_list:
            return ofertas_list

        perfil = PerfilVehiculo.objects.filter(vehiculo=vehiculo).first()
        marca_id = getattr(getattr(vehiculo, 'marca', None), 'id', None)

        def _ofrece_repuestos(oferta) -> bool:
            if getattr(oferta, 'tipo_servicio', None) == 'sin_repuestos':
                return False
            if float(oferta.costo_repuestos_sin_iva or 0) > 0:
                return True
            rep = float(oferta.precio_con_repuestos or 0)
            sin = float(oferta.precio_sin_repuestos or 0)
            return rep > 0 and sin > 0 and rep > sin * 1.005

        ofertas_scores = []
        for oferta in ofertas_list:
            ctx = CoincidenciaCatalogoContext(
                vehiculo=vehiculo,
                marca_id=marca_id,
                requiere_repuestos=True,
                dist_km=None,
                con_ubicacion_cliente=False,
                catalogo_completo=True,
                oferta_ofrece_repuestos=_ofrece_repuestos(oferta),
            )
            resultado = calcular_score_coincidencia(oferta, ctx, perfil=perfil)
            ofertas_scores.append((oferta, resultado.score))

        ofertas_scores.sort(key=lambda x: x[1], reverse=True)
        return [oferta for oferta, _score in ofertas_scores] 
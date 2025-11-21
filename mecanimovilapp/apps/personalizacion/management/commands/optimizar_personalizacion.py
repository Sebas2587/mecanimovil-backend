from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import time


class Command(BaseCommand):
    help = 'Optimiza el sistema de personalización'

    def add_arguments(self, parser):
        parser.add_argument(
            '--crear-indices',
            action='store_true',
            help='Crear índices de base de datos',
        )
        parser.add_argument(
            '--limpiar-cache',
            action='store_true',
            help='Limpiar cache de recomendaciones',
        )
        parser.add_argument(
            '--analizar-queries',
            action='store_true',
            help='Analizar queries lentas',
        )
        parser.add_argument(
            '--limpiar-datos',
            action='store_true',
            help='Limpiar datos obsoletos',
        )
        parser.add_argument(
            '--optimizar-todo',
            action='store_true',
            help='Ejecutar todas las optimizaciones',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar qué se haría sin ejecutar',
        )

    def handle(self, *args, **options):
        self.stdout.write("⚡ Iniciando optimización del sistema de personalización...")
        self.stdout.write("=" * 60)
        
        start_time = time.time()
        
        # Si se especifica optimizar todo, activar todas las opciones
        if options['optimizar_todo']:
            options['crear_indices'] = True
            options['limpiar_cache'] = True
            options['analizar_queries'] = True
            options['limpiar_datos'] = True
        
        # Verificar que al menos una opción esté seleccionada
        if not any([options['crear_indices'], options['limpiar_cache'], 
                   options['analizar_queries'], options['limpiar_datos']]):
            self.stdout.write(
                self.style.WARNING("⚠️ No se especificó ninguna optimización. Use --help para ver opciones.")
            )
            return
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("🔍 Modo DRY RUN - Solo mostrando qué se haría"))
        
        # Ejecutar optimizaciones
        resultados = {}
        
        if options['crear_indices']:
            self.stdout.write("\n1. Creando índices de base de datos...")
            resultados['indices'] = self._crear_indices(options['dry_run'])
        
        if options['limpiar_cache']:
            self.stdout.write("\n2. Limpiando cache...")
            resultados['cache'] = self._limpiar_cache(options['dry_run'])
        
        if options['limpiar_datos']:
            self.stdout.write("\n3. Limpiando datos obsoletos...")
            resultados['datos'] = self._limpiar_datos_obsoletos(options['dry_run'])
        
        if options['analizar_queries']:
            self.stdout.write("\n4. Analizando queries...")
            resultados['queries'] = self._analizar_queries()
        
        end_time = time.time()
        tiempo_total = end_time - start_time
        
        # Mostrar resumen
        self._mostrar_resumen(resultados, tiempo_total, options['dry_run'])

    def _crear_indices(self, dry_run=False):
        """Crea índices optimizados para personalización"""
        indices = [
            {
                'nombre': 'idx_vehiculo_activo_cliente',
                'sql': 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vehiculo_activo_cliente ON personalizacion_vehiculoactivo(cliente_id);',
                'descripcion': 'Índice para búsquedas de vehículo activo por cliente'
            },
            {
                'nombre': 'idx_recomendacion_vehiculo_tipo_activa',
                'sql': 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_recomendacion_vehiculo_tipo_activa ON personalizacion_recomendacionpersonalizada(vehiculo_id, tipo, activa);',
                'descripcion': 'Índice compuesto para filtros de recomendaciones'
            },
            {
                'nombre': 'idx_recomendacion_score_fecha',
                'sql': 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_recomendacion_score_fecha ON personalizacion_recomendacionpersonalizada(score_relevancia DESC, fecha_generacion DESC);',
                'descripcion': 'Índice para ordenamiento por relevancia y fecha'
            },
            {
                'nombre': 'idx_perfil_vehiculo_actualizado',
                'sql': 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perfil_vehiculo_actualizado ON personalizacion_perfilvehiculo(vehiculo_id, fecha_actualizacion);',
                'descripcion': 'Índice para perfiles de vehículos'
            },
            {
                'nombre': 'idx_recomendacion_cliente_tipo_activa_score',
                'sql': 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_recomendacion_cliente_tipo_activa_score ON personalizacion_recomendacionpersonalizada(cliente_id, tipo, activa, score_relevancia DESC);',
                'descripcion': 'Índice compuesto optimizado para consultas principales'
            },
            {
                'nombre': 'idx_recomendacion_expiracion',
                'sql': 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_recomendacion_expiracion ON personalizacion_recomendacionpersonalizada(fecha_expiracion) WHERE activa = true;',
                'descripcion': 'Índice parcial para recomendaciones activas por expiración'
            }
        ]
        
        indices_creados = 0
        indices_existentes = 0
        errores = 0
        
        for indice in indices:
            try:
                if dry_run:
                    self.stdout.write(f"   🔍 [DRY RUN] Crearía índice: {indice['nombre']}")
                    self.stdout.write(f"      📝 {indice['descripcion']}")
                    indices_creados += 1
                else:
                    with connection.cursor() as cursor:
                        # Verificar si el índice ya existe
                        cursor.execute("""
                            SELECT indexname FROM pg_indexes 
                            WHERE indexname = %s
                        """, [indice['nombre']])
                        
                        if cursor.fetchone():
                            self.stdout.write(f"   ✅ Índice ya existe: {indice['nombre']}")
                            indices_existentes += 1
                        else:
                            cursor.execute(indice['sql'])
                            self.stdout.write(f"   ✅ Índice creado: {indice['nombre']}")
                            self.stdout.write(f"      📝 {indice['descripcion']}")
                            indices_creados += 1
                            
            except Exception as e:
                self.stdout.write(f"   ❌ Error creando índice {indice['nombre']}: {str(e)}")
                errores += 1
        
        return {
            'creados': indices_creados,
            'existentes': indices_existentes,
            'errores': errores,
            'total': len(indices)
        }

    def _limpiar_cache(self, dry_run=False):
        """Limpia cache de recomendaciones"""
        try:
            if dry_run:
                self.stdout.write("   🔍 [DRY RUN] Limpiaría todo el cache")
                return {'limpiado': True, 'keys_eliminadas': 'N/A (dry run)'}
            else:
                # Obtener estadísticas antes de limpiar
                try:
                    from django.core.cache.backends.base import BaseCache
                    if hasattr(cache, '_cache'):
                        keys_antes = len(cache._cache.keys()) if hasattr(cache._cache, 'keys') else 'N/A'
                    else:
                        keys_antes = 'N/A'
                except:
                    keys_antes = 'N/A'
                
                # Limpiar cache
                cache.clear()
                
                self.stdout.write("   ✅ Cache limpiado completamente")
                self.stdout.write(f"      📊 Keys eliminadas: {keys_antes}")
                
                return {'limpiado': True, 'keys_eliminadas': keys_antes}
                
        except Exception as e:
            self.stdout.write(f"   ❌ Error limpiando cache: {str(e)}")
            return {'limpiado': False, 'error': str(e)}

    def _limpiar_datos_obsoletos(self, dry_run=False):
        """Limpia datos obsoletos del sistema"""
        from mecanimovilapp.apps.personalizacion.models import RecomendacionPersonalizada
        
        # Fecha límite para considerar datos obsoletos
        fecha_limite = timezone.now() - timedelta(days=90)  # 3 meses
        
        try:
            # 1. Recomendaciones expiradas
            recomendaciones_expiradas = RecomendacionPersonalizada.objects.filter(
                fecha_expiracion__lt=timezone.now()
            )
            count_expiradas = recomendaciones_expiradas.count()
            
            # 2. Recomendaciones muy antiguas
            recomendaciones_antiguas = RecomendacionPersonalizada.objects.filter(
                fecha_generacion__lt=fecha_limite,
                activa=False
            )
            count_antiguas = recomendaciones_antiguas.count()
            
            if dry_run:
                self.stdout.write(f"   🔍 [DRY RUN] Eliminaría {count_expiradas} recomendaciones expiradas")
                self.stdout.write(f"   🔍 [DRY RUN] Eliminaría {count_antiguas} recomendaciones antiguas inactivas")
                
                return {
                    'expiradas_eliminadas': count_expiradas,
                    'antiguas_eliminadas': count_antiguas,
                    'total_eliminadas': count_expiradas + count_antiguas,
                    'dry_run': True
                }
            else:
                with transaction.atomic():
                    # Eliminar recomendaciones expiradas
                    eliminadas_expiradas = recomendaciones_expiradas.delete()[0]
                    
                    # Eliminar recomendaciones antiguas inactivas
                    eliminadas_antiguas = recomendaciones_antiguas.delete()[0]
                    
                    total_eliminadas = eliminadas_expiradas + eliminadas_antiguas
                    
                    self.stdout.write(f"   ✅ Eliminadas {eliminadas_expiradas} recomendaciones expiradas")
                    self.stdout.write(f"   ✅ Eliminadas {eliminadas_antiguas} recomendaciones antiguas")
                    self.stdout.write(f"   📊 Total eliminadas: {total_eliminadas}")
                    
                    return {
                        'expiradas_eliminadas': eliminadas_expiradas,
                        'antiguas_eliminadas': eliminadas_antiguas,
                        'total_eliminadas': total_eliminadas,
                        'dry_run': False
                    }
                    
        except Exception as e:
            self.stdout.write(f"   ❌ Error limpiando datos: {str(e)}")
            return {'error': str(e)}

    def _analizar_queries(self):
        """Analiza queries lentas y uso de índices"""
        try:
            with connection.cursor() as cursor:
                # 1. Verificar queries lentas relacionadas con personalización
                self.stdout.write("   📊 Analizando queries de personalización...")
                
                # 2. Verificar uso de índices
                cursor.execute("""
                    SELECT 
                        schemaname,
                        tablename,
                        indexname,
                        idx_scan,
                        idx_tup_read,
                        idx_tup_fetch
                    FROM pg_stat_user_indexes 
                    WHERE schemaname = 'public' 
                    AND tablename LIKE 'personalizacion_%'
                    ORDER BY idx_scan DESC;
                """)
                
                indices_stats = cursor.fetchall()
                
                if indices_stats:
                    self.stdout.write("   📈 Estadísticas de uso de índices:")
                    for stat in indices_stats[:10]:  # Top 10
                        schema, tabla, indice, scans, reads, fetches = stat
                        self.stdout.write(f"      • {indice}: {scans} scans, {reads} reads")
                else:
                    self.stdout.write("   ⚠️ No se encontraron estadísticas de índices")
                
                # 3. Verificar tamaño de tablas
                cursor.execute("""
                    SELECT 
                        tablename,
                        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
                    FROM pg_tables 
                    WHERE schemaname = 'public' 
                    AND tablename LIKE 'personalizacion_%'
                    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
                """)
                
                tamaños = cursor.fetchall()
                
                if tamaños:
                    self.stdout.write("   💾 Tamaño de tablas:")
                    for tabla, tamaño in tamaños:
                        self.stdout.write(f"      • {tabla}: {tamaño}")
                
                # 4. Sugerencias de optimización
                self._generar_sugerencias_optimizacion(indices_stats, tamaños)
                
                return {
                    'indices_analizados': len(indices_stats),
                    'tablas_analizadas': len(tamaños),
                    'sugerencias_generadas': True
                }
                
        except Exception as e:
            self.stdout.write(f"   ❌ Error analizando queries: {str(e)}")
            return {'error': str(e)}

    def _generar_sugerencias_optimizacion(self, indices_stats, tamaños):
        """Genera sugerencias de optimización basadas en el análisis"""
        self.stdout.write("\n   💡 SUGERENCIAS DE OPTIMIZACIÓN:")
        
        # Analizar índices poco usados
        indices_poco_usados = [stat for stat in indices_stats if stat[3] < 10]  # menos de 10 scans
        if indices_poco_usados:
            self.stdout.write("   ⚠️ Índices poco utilizados (considerar eliminar):")
            for stat in indices_poco_usados:
                self.stdout.write(f"      • {stat[2]} - Solo {stat[3]} scans")
        
        # Analizar tablas grandes
        if tamaños:
            tabla_mas_grande = tamaños[0]
            self.stdout.write(f"   📊 Tabla más grande: {tabla_mas_grande[0]} ({tabla_mas_grande[1]})")
            
            if 'GB' in tabla_mas_grande[1] or ('MB' in tabla_mas_grande[1] and 
                                               int(tabla_mas_grande[1].split()[0]) > 100):
                self.stdout.write("   💡 Considerar particionado para tablas grandes")
        
        # Sugerencias generales
        self.stdout.write("   🚀 Recomendaciones generales:")
        self.stdout.write("      • Ejecutar VACUUM ANALYZE periódicamente")
        self.stdout.write("      • Monitorear queries lentas con pg_stat_statements")
        self.stdout.write("      • Considerar cache de aplicación para consultas frecuentes")
        self.stdout.write("      • Implementar archivado de datos históricos")

    def _mostrar_resumen(self, resultados, tiempo_total, dry_run):
        """Muestra resumen de la optimización"""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("📊 RESUMEN DE OPTIMIZACIÓN")
        self.stdout.write("=" * 60)
        
        if dry_run:
            self.stdout.write("🔍 MODO DRY RUN - Ningún cambio fue aplicado")
        
        # Resumen de índices
        if 'indices' in resultados:
            indices = resultados['indices']
            if 'error' not in indices:
                self.stdout.write(f"📈 Índices:")
                self.stdout.write(f"   • Creados: {indices['creados']}")
                self.stdout.write(f"   • Ya existían: {indices['existentes']}")
                self.stdout.write(f"   • Errores: {indices['errores']}")
                self.stdout.write(f"   • Total procesados: {indices['total']}")
        
        # Resumen de cache
        if 'cache' in resultados:
            cache_result = resultados['cache']
            if cache_result['limpiado']:
                self.stdout.write(f"🗑️ Cache limpiado exitosamente")
                if cache_result['keys_eliminadas'] != 'N/A':
                    self.stdout.write(f"   • Keys eliminadas: {cache_result['keys_eliminadas']}")
        
        # Resumen de datos
        if 'datos' in resultados:
            datos = resultados['datos']
            if 'error' not in datos:
                self.stdout.write(f"🧹 Limpieza de datos:")
                self.stdout.write(f"   • Recomendaciones expiradas: {datos['expiradas_eliminadas']}")
                self.stdout.write(f"   • Recomendaciones antiguas: {datos['antiguas_eliminadas']}")
                self.stdout.write(f"   • Total eliminadas: {datos['total_eliminadas']}")
        
        # Resumen de análisis
        if 'queries' in resultados:
            queries = resultados['queries']
            if 'error' not in queries:
                self.stdout.write(f"🔍 Análisis completado:")
                self.stdout.write(f"   • Índices analizados: {queries['indices_analizados']}")
                self.stdout.write(f"   • Tablas analizadas: {queries['tablas_analizadas']}")
        
        self.stdout.write(f"\n⏱️ Tiempo total: {tiempo_total:.2f} segundos")
        
        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS("\n✅ Optimización completada exitosamente")
            )
            self.stdout.write("💡 Ejecute este comando periódicamente para mantener el rendimiento")
        else:
            self.stdout.write(
                self.style.WARNING("\n🔍 Simulación completada - Use sin --dry-run para aplicar cambios")
            )
        
        # Próximos pasos
        self.stdout.write("\n🚀 PRÓXIMOS PASOS RECOMENDADOS:")
        self.stdout.write("   1. Monitorear performance después de los cambios")
        self.stdout.write("   2. Configurar alertas para queries lentas")
        self.stdout.write("   3. Implementar cache distribuido (Redis)")
        self.stdout.write("   4. Configurar backup automático de configuraciones")
        self.stdout.write("   5. Programar limpieza automática de datos obsoletos") 
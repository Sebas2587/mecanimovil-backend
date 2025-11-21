from django.core.management.base import BaseCommand
from django.test.utils import get_runner
from django.conf import settings
import subprocess
import time
import sys
import os


class Command(BaseCommand):
    help = 'Ejecuta suite completa de tests para personalización'

    def add_arguments(self, parser):
        parser.add_argument(
            '--coverage',
            action='store_true',
            help='Ejecutar con coverage',
        )
        parser.add_argument(
            '--performance',
            action='store_true',
            help='Incluir tests de performance',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Salida detallada',
        )

    def handle(self, *args, **options):
        self.stdout.write("🧪 Iniciando Tests de Personalización...")
        self.stdout.write("=" * 60)
        
        start_time = time.time()
        
        # 1. Tests unitarios
        self.stdout.write("\n1. Ejecutando tests unitarios...")
        success_unitarios = self._ejecutar_tests_unitarios(options['coverage'], options['verbose'])
        
        # 2. Tests de integración
        self.stdout.write("\n2. Ejecutando tests de integración...")
        success_integracion = self._ejecutar_tests_integracion(options['verbose'])
        
        # 3. Tests de performance (opcional)
        success_performance = True
        if options['performance']:
            self.stdout.write("\n3. Ejecutando tests de performance...")
            success_performance = self._ejecutar_tests_performance()
        
        # 4. Validación de APIs
        self.stdout.write("\n4. Validando APIs...")
        success_apis = self._validar_apis()
        
        # 5. Verificar cobertura si se solicitó
        if options['coverage']:
            self.stdout.write("\n5. Generando reporte de cobertura...")
            self._generar_reporte_coverage()
        
        end_time = time.time()
        tiempo_total = end_time - start_time
        
        # Resumen final
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("📊 RESUMEN DE TESTS")
        self.stdout.write("=" * 60)
        
        resultados = {
            "Tests Unitarios": "✅ PASSED" if success_unitarios else "❌ FAILED",
            "Tests Integración": "✅ PASSED" if success_integracion else "❌ FAILED",
            "Tests Performance": "✅ PASSED" if success_performance else "❌ FAILED" if options['performance'] else "⏭️ SKIPPED",
            "Validación APIs": "✅ PASSED" if success_apis else "❌ FAILED"
        }
        
        for categoria, resultado in resultados.items():
            self.stdout.write(f"{categoria}: {resultado}")
        
        self.stdout.write(f"\n⏱️ Tiempo total: {tiempo_total:.2f} segundos")
        
        # Determinar éxito general
        all_success = success_unitarios and success_integracion and success_performance and success_apis
        
        if all_success:
            self.stdout.write(
                self.style.SUCCESS("\n🎉 ¡Suite de tests completada exitosamente!")
            )
            self.stdout.write("✅ El sistema de personalización está listo para producción")
        else:
            self.stdout.write(
                self.style.ERROR("\n❌ Algunos tests fallaron")
            )
            self.stdout.write("⚠️ Revisar los errores antes de continuar")
            
        return all_success

    def _ejecutar_tests_unitarios(self, with_coverage, verbose):
        """Ejecuta tests unitarios con o sin coverage"""
        self.stdout.write("   🔬 Ejecutando tests del motor ML...")
        
        try:
            if with_coverage:
                cmd = [
                    'coverage', 'run', '--source=mecanimovilapp.apps.personalizacion', 
                    'manage.py', 'test', 
                    'mecanimovilapp.apps.personalizacion.tests.test_ml_engine'
                ]
            else:
                cmd = [
                    'python', 'manage.py', 'test', 
                    'mecanimovilapp.apps.personalizacion.tests.test_ml_engine'
                ]
            
            if verbose:
                cmd.append('-v')
                cmd.append('2')
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=settings.BASE_DIR)
            
            if result.returncode == 0:
                self.stdout.write(self.style.SUCCESS("   ✅ Tests unitarios: PASSED"))
                if verbose:
                    self.stdout.write(f"   📝 Output: {result.stdout}")
                return True
            else:
                self.stdout.write(self.style.ERROR("   ❌ Tests unitarios: FAILED"))
                self.stdout.write(f"   📝 Error: {result.stderr}")
                return False
                
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR("   ❌ Error: No se encontró el comando python o coverage"))
            return False
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ❌ Error inesperado: {str(e)}"))
            return False

    def _ejecutar_tests_integracion(self, verbose):
        """Ejecuta tests de integración de APIs"""
        self.stdout.write("   🔗 Ejecutando tests de APIs...")
        
        try:
            cmd = [
                'python', 'manage.py', 'test', 
                'mecanimovilapp.apps.personalizacion.tests.test_apis'
            ]
            
            if verbose:
                cmd.append('-v')
                cmd.append('2')
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=settings.BASE_DIR)
            
            if result.returncode == 0:
                self.stdout.write(self.style.SUCCESS("   ✅ Tests de integración: PASSED"))
                if verbose:
                    self.stdout.write(f"   📝 Output: {result.stdout}")
                return True
            else:
                self.stdout.write(self.style.ERROR("   ❌ Tests de integración: FAILED"))
                self.stdout.write(f"   📝 Error: {result.stderr}")
                return False
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ❌ Error en tests de integración: {str(e)}"))
            return False

    def _ejecutar_tests_performance(self):
        """Ejecuta tests de performance"""
        self.stdout.write("   ⚡ Ejecutando tests de performance...")
        
        try:
            from mecanimovilapp.apps.personalizacion.ml_engine import MotorRecomendaciones
            from mecanimovilapp.apps.vehiculos.models import Vehiculo
            from django.contrib.auth.models import User
            from mecanimovilapp.apps.usuarios.models import Cliente
            from mecanimovilapp.apps.vehiculos.models import Marca, Modelo
            from mecanimovilapp.apps.personalizacion.models import PerfilVehiculo
            
            # Test de generación de recomendaciones para múltiples vehículos
            start_time = time.time()
            
            # Crear datos de prueba si no existen
            user, created = User.objects.get_or_create(
                username='perftest',
                defaults={'email': 'perf@test.com'}
            )
            cliente, created = Cliente.objects.get_or_create(usuario=user)
            marca, created = Marca.objects.get_or_create(nombre='TestMarca')
            modelo, created = Modelo.objects.get_or_create(nombre='TestModelo', marca=marca)
            
            # Crear vehículos de prueba
            vehiculos_test = []
            for i in range(10):
                vehiculo, created = Vehiculo.objects.get_or_create(
                    patente=f'PERF{i:03d}',
                    defaults={
                        'cliente': cliente,
                        'marca': marca,
                        'modelo': modelo,
                        'año': 2020,
                        'kilometraje': 30000 + (i * 5000)
                    }
                )
                vehiculos_test.append(vehiculo)
                
                # Crear perfil si no existe
                PerfilVehiculo.objects.get_or_create(
                    vehiculo=vehiculo,
                    defaults={
                        'gasto_promedio_mensual': 50000,
                        'frecuencia_mantenimiento': 120,
                        'servicios_frecuentes': ['Cambio de Aceite']
                    }
                )
            
            # Ejecutar generación de recomendaciones
            motor = MotorRecomendaciones()
            for vehiculo in vehiculos_test:
                motor.generar_recomendaciones_vehiculo(vehiculo)
            
            end_time = time.time()
            tiempo_total = end_time - start_time
            tiempo_por_vehiculo = tiempo_total / len(vehiculos_test)
            
            # Verificar performance
            if tiempo_por_vehiculo < 2.0:  # Menos de 2 segundos por vehículo
                self.stdout.write(
                    self.style.SUCCESS(f"   ✅ Performance: {tiempo_por_vehiculo:.2f}s por vehículo")
                )
                return True
            else:
                self.stdout.write(
                    self.style.WARNING(f"   ⚠️ Performance lenta: {tiempo_por_vehiculo:.2f}s por vehículo")
                )
                return False
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ❌ Error en tests de performance: {str(e)}"))
            return False

    def _validar_apis(self):
        """Valida que las APIs respondan correctamente"""
        self.stdout.write("   🌐 Validando endpoints de APIs...")
        
        try:
            import requests
            from django.conf import settings
            
            # Verificar que el servidor esté corriendo
            base_url = 'http://localhost:8000'
            
            endpoints_to_test = [
                ('/api/personalizacion/vehiculo-activo/', 'GET', 'Vehículo activo'),
                ('/api/personalizacion/recomendaciones/', 'GET', 'Recomendaciones'),
                ('/admin/personalizacion/', 'GET', 'Admin personalización'),
            ]
            
            all_success = True
            
            for endpoint, method, description in endpoints_to_test:
                try:
                    if method == 'GET':
                        response = requests.get(f'{base_url}{endpoint}', timeout=5)
                    else:
                        response = requests.post(f'{base_url}{endpoint}', timeout=5)
                    
                    # Códigos esperados: 200 (OK), 401 (sin auth), 302 (redirect), 403 (forbidden)
                    if response.status_code in [200, 401, 302, 403]:
                        self.stdout.write(f"   ✅ {description}: {response.status_code}")
                    else:
                        self.stdout.write(f"   ⚠️ {description}: {response.status_code}")
                        all_success = False
                        
                except requests.exceptions.ConnectionError:
                    self.stdout.write(f"   ⚠️ {description}: Servidor no disponible")
                    all_success = False
                except requests.exceptions.Timeout:
                    self.stdout.write(f"   ⚠️ {description}: Timeout")
                    all_success = False
                except Exception as e:
                    self.stdout.write(f"   ❌ {description}: Error - {str(e)}")
                    all_success = False
            
            return all_success
            
        except ImportError:
            self.stdout.write("   ⚠️ requests no disponible, saltando validación de APIs")
            return True
        except Exception as e:
            self.stdout.write(f"   ❌ Error en validación de APIs: {str(e)}")
            return False

    def _generar_reporte_coverage(self):
        """Genera reporte de cobertura de código"""
        try:
            # Generar reporte en terminal
            result = subprocess.run(
                ['coverage', 'report', '--include=mecanimovilapp/apps/personalizacion/*'],
                capture_output=True, text=True, cwd=settings.BASE_DIR
            )
            
            if result.returncode == 0:
                self.stdout.write("   📊 Reporte de cobertura:")
                self.stdout.write(result.stdout)
                
                # Generar reporte HTML
                html_result = subprocess.run(
                    ['coverage', 'html', '--include=mecanimovilapp/apps/personalizacion/*'],
                    capture_output=True, text=True, cwd=settings.BASE_DIR
                )
                
                if html_result.returncode == 0:
                    self.stdout.write("   📄 Reporte HTML generado en htmlcov/")
                    
            else:
                self.stdout.write("   ⚠️ Error generando reporte de cobertura")
                
        except FileNotFoundError:
            self.stdout.write("   ⚠️ coverage no disponible")
        except Exception as e:
            self.stdout.write(f"   ❌ Error en reporte de cobertura: {str(e)}")

    def _mostrar_estadisticas_finales(self):
        """Muestra estadísticas finales del sistema"""
        try:
            from mecanimovilapp.apps.personalizacion.models import (
                RecomendacionPersonalizada, VehiculoActivo, PerfilVehiculo, ConfiguracionPersonalizacion
            )
            
            self.stdout.write("\n📈 ESTADÍSTICAS DEL SISTEMA")
            self.stdout.write("-" * 40)
            
            # Contar elementos
            total_recomendaciones = RecomendacionPersonalizada.objects.count()
            recomendaciones_activas = RecomendacionPersonalizada.objects.filter(activa=True).count()
            vehiculos_activos = VehiculoActivo.objects.count()
            perfiles_vehiculos = PerfilVehiculo.objects.count()
            configuraciones = ConfiguracionPersonalizacion.objects.count()
            
            self.stdout.write(f"Recomendaciones totales: {total_recomendaciones}")
            self.stdout.write(f"Recomendaciones activas: {recomendaciones_activas}")
            self.stdout.write(f"Vehículos activos: {vehiculos_activos}")
            self.stdout.write(f"Perfiles de vehículos: {perfiles_vehiculos}")
            self.stdout.write(f"Configuraciones: {configuraciones}")
            
            # CTR promedio si hay datos
            if recomendaciones_activas > 0:
                from django.db.models import Avg, Sum
                metricas = RecomendacionPersonalizada.objects.filter(activa=True).aggregate(
                    total_vistas=Sum('veces_mostrada'),
                    total_clicks=Sum('veces_clickeada'),
                    score_promedio=Avg('score_relevancia')
                )
                
                total_vistas = metricas['total_vistas'] or 0
                total_clicks = metricas['total_clicks'] or 0
                ctr = (total_clicks / total_vistas * 100) if total_vistas > 0 else 0
                score_promedio = metricas['score_promedio'] or 0
                
                self.stdout.write(f"CTR promedio: {ctr:.2f}%")
                self.stdout.write(f"Score promedio: {score_promedio:.3f}")
                
        except Exception as e:
            self.stdout.write(f"Error obteniendo estadísticas: {str(e)}")

    def _mostrar_recomendaciones_siguientes(self):
        """Muestra recomendaciones para siguientes pasos"""
        self.stdout.write("\n🚀 PRÓXIMOS PASOS RECOMENDADOS")
        self.stdout.write("-" * 40)
        self.stdout.write("1. Ejecutar tests en entorno de staging")
        self.stdout.write("2. Configurar monitoreo de performance")
        self.stdout.write("3. Implementar A/B testing")
        self.stdout.write("4. Configurar alertas de sistema")
        self.stdout.write("5. Optimizar índices de base de datos")
        self.stdout.write("6. Implementar cache distribuido")
        self.stdout.write("7. Configurar métricas de negocio")
        self.stdout.write("8. Documentar APIs para frontend")
        
        self.stdout.write("\n📚 DOCUMENTACIÓN")
        self.stdout.write("-" * 40)
        self.stdout.write("• FASE4_TESTING_OPTIMIZACION.md - Guía completa")
        self.stdout.write("• INTEGRACION_PERSONALIZACION.md - Frontend")
        self.stdout.write("• PLAN_IMPLEMENTACION_PERSONALIZACION.md - Roadmap") 
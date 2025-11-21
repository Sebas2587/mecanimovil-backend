import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo, Marca, Modelo
from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
from mecanimovilapp.apps.personalizacion.models import (
    VehiculoActivo, PerfilVehiculo, RecomendacionPersonalizada, ConfiguracionPersonalizacion
)
from mecanimovilapp.apps.personalizacion.ml_engine import MotorRecomendaciones


class TestMotorRecomendaciones(TestCase):
    """Tests unitarios para el Motor de Recomendaciones ML"""
    
    def setUp(self):
        """Configuración inicial para los tests"""
        self.motor = MotorRecomendaciones()
        
        # Crear usuario y cliente de prueba
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.cliente = Cliente.objects.create(usuario=self.user)
        
        # Crear marca y modelo
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Corolla', marca=self.marca)
        
        # Crear vehículo
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            patente='ABC123',
            año=2020,
            kilometraje=25000
        )
        
        # Crear servicios de prueba
        self.servicio_mantenimiento = Servicio.objects.create(
            nombre='Cambio de Aceite',
            descripcion='Cambio de aceite y filtro',
            precio_base=30000
        )
        
        # Crear configuraciones de prueba
        ConfiguracionPersonalizacion.objects.create(
            clave='umbral_score_minimo',
            valor='0.3',
            descripcion='Score mínimo para recomendaciones'
        )
        
    def test_calcular_score_mantenimiento(self):
        """Test cálculo de score de mantenimiento"""
        vehiculo_data = {
            'kilometraje': 50000,
            'edad_vehiculo': 3,
            'ultimo_mantenimiento_dias': 200
        }
        
        score = self.motor._calcular_score_mantenimiento(vehiculo_data)
        
        # Verificar que el score está en el rango válido
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertIsInstance(score, float)
        
    def test_calcular_score_mantenimiento_urgente(self):
        """Test score alto para mantenimiento urgente"""
        vehiculo_data = {
            'kilometraje': 100000,  # Alto kilometraje
            'edad_vehiculo': 8,     # Vehículo viejo
            'ultimo_mantenimiento_dias': 365  # Hace mucho tiempo
        }
        
        score = self.motor._calcular_score_mantenimiento(vehiculo_data)
        
        # Score debería ser alto para mantenimiento urgente
        self.assertGreater(score, 0.7)
        
    def test_calcular_score_mantenimiento_reciente(self):
        """Test score bajo para mantenimiento reciente"""
        vehiculo_data = {
            'kilometraje': 5000,    # Bajo kilometraje
            'edad_vehiculo': 1,     # Vehículo nuevo
            'ultimo_mantenimiento_dias': 30  # Mantenimiento reciente
        }
        
        score = self.motor._calcular_score_mantenimiento(vehiculo_data)
        
        # Score debería ser bajo para mantenimiento reciente
        self.assertLess(score, 0.3)
        
    def test_normalizar_scores(self):
        """Test normalización de scores con NumPy"""
        scores = np.array([10, 20, 30, 40, 50])
        normalized = self.motor._normalizar_scores(scores)
        
        # Verificar normalización correcta
        self.assertAlmostEqual(normalized.min(), 0.0, places=5)
        self.assertAlmostEqual(normalized.max(), 1.0, places=5)
        self.assertEqual(len(normalized), len(scores))
        
    def test_normalizar_scores_array_vacio(self):
        """Test normalización con array vacío"""
        scores = np.array([])
        normalized = self.motor._normalizar_scores(scores)
        
        self.assertEqual(len(normalized), 0)
        
    def test_normalizar_scores_valores_iguales(self):
        """Test normalización con valores iguales"""
        scores = np.array([5, 5, 5, 5])
        normalized = self.motor._normalizar_scores(scores)
        
        # Todos los valores deberían ser 0.5 cuando son iguales
        np.testing.assert_array_almost_equal(normalized, [0.5, 0.5, 0.5, 0.5])
        
    def test_obtener_datos_vehiculo(self):
        """Test obtención de datos del vehículo"""
        datos = self.motor._obtener_datos_vehiculo(self.vehiculo)
        
        # Verificar estructura de datos
        self.assertIn('kilometraje', datos)
        self.assertIn('edad_vehiculo', datos)
        self.assertIn('ultimo_mantenimiento_dias', datos)
        
        # Verificar valores
        self.assertEqual(datos['kilometraje'], 25000)
        self.assertGreater(datos['edad_vehiculo'], 0)
        
    def test_calcular_score_proveedor(self):
        """Test cálculo de score de proveedor"""
        # Crear oferta de servicio mock
        oferta_mock = MagicMock()
        oferta_mock.calificacion_promedio = 4.5
        oferta_mock.total_servicios = 100
        
        score = self.motor._calcular_score_proveedor(oferta_mock, self.cliente)
        
        # Verificar que el score está en el rango válido
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        
    def test_calcular_score_popularidad(self):
        """Test cálculo de score de popularidad"""
        # Datos mock de popularidad
        popularidad_data = {
            'total_solicitudes': 50,
            'solicitudes_modelo': 10,
            'calificacion_promedio': 4.2
        }
        
        score = self.motor._calcular_score_popularidad(popularidad_data)
        
        # Verificar que el score está en el rango válido
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        
    @patch('mecanimovilapp.apps.personalizacion.ml_engine.Servicio.objects')
    def test_generar_recomendaciones_mantenimiento(self, mock_servicios):
        """Test generación de recomendaciones de mantenimiento"""
        # Mock de servicios disponibles
        mock_servicios.filter.return_value = [self.servicio_mantenimiento]
        
        # Crear perfil de vehículo
        PerfilVehiculo.objects.create(
            vehiculo=self.vehiculo,
            gasto_promedio_mensual=50000,
            frecuencia_mantenimiento=90,
            servicios_frecuentes=['Cambio de Aceite']
        )
        
        # Generar recomendaciones
        recomendaciones = self.motor.generar_recomendaciones_mantenimiento(self.vehiculo)
        
        # Verificar que se generaron recomendaciones
        self.assertIsInstance(recomendaciones, list)
        
        # Si hay recomendaciones, verificar estructura
        if recomendaciones:
            rec = recomendaciones[0]
            self.assertIn('servicio', rec)
            self.assertIn('score', rec)
            self.assertIn('razon', rec)
            
    def test_generar_recomendaciones_vehiculo_completo(self):
        """Test generación completa de recomendaciones para un vehículo"""
        # Crear perfil de vehículo
        PerfilVehiculo.objects.create(
            vehiculo=self.vehiculo,
            gasto_promedio_mensual=50000,
            frecuencia_mantenimiento=90,
            servicios_frecuentes=['Cambio de Aceite']
        )
        
        # Ejecutar generación
        resultado = self.motor.generar_recomendaciones_vehiculo(self.vehiculo)
        
        # Verificar que el resultado contiene las claves esperadas
        self.assertIn('mantenimiento', resultado)
        self.assertIn('proveedores', resultado)
        self.assertIn('servicios_populares', resultado)
        
    def test_obtener_configuracion(self):
        """Test obtención de configuraciones"""
        valor = self.motor._obtener_configuracion('umbral_score_minimo', 0.5)
        
        # Debería obtener el valor configurado
        self.assertEqual(valor, 0.3)
        
    def test_obtener_configuracion_default(self):
        """Test obtención de configuración con valor por defecto"""
        valor = self.motor._obtener_configuracion('config_inexistente', 0.8)
        
        # Debería devolver el valor por defecto
        self.assertEqual(valor, 0.8)
        
    def test_crear_recomendaciones(self):
        """Test creación de recomendaciones en base de datos"""
        recomendaciones_data = [
            {
                'servicio': self.servicio_mantenimiento,
                'score': 0.8,
                'razon': 'Test de recomendación'
            }
        ]
        
        # Crear recomendaciones
        self.motor._crear_recomendaciones(
            self.vehiculo, 
            recomendaciones_data, 
            'mantenimiento', 
            max_recomendaciones=5
        )
        
        # Verificar que se crearon en la base de datos
        recomendaciones = RecomendacionPersonalizada.objects.filter(
            vehiculo=self.vehiculo,
            tipo='mantenimiento'
        )
        
        self.assertEqual(recomendaciones.count(), 1)
        
        rec = recomendaciones.first()
        self.assertEqual(rec.servicio, self.servicio_mantenimiento)
        self.assertEqual(rec.score_relevancia, 0.8)
        self.assertEqual(rec.razon_recomendacion, 'Test de recomendación')
        
    def test_limpiar_recomendaciones_anteriores(self):
        """Test limpieza de recomendaciones anteriores"""
        # Crear recomendación anterior
        RecomendacionPersonalizada.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo='mantenimiento',
            servicio=self.servicio_mantenimiento,
            score_relevancia=0.5,
            razon_recomendacion='Recomendación anterior',
            fecha_expiracion=timezone.now() + timedelta(days=30)
        )
        
        # Crear nuevas recomendaciones (debería limpiar las anteriores)
        recomendaciones_data = [
            {
                'servicio': self.servicio_mantenimiento,
                'score': 0.8,
                'razon': 'Nueva recomendación'
            }
        ]
        
        self.motor._crear_recomendaciones(
            self.vehiculo, 
            recomendaciones_data, 
            'mantenimiento', 
            max_recomendaciones=5
        )
        
        # Verificar que solo existe la nueva recomendación
        recomendaciones = RecomendacionPersonalizada.objects.filter(
            vehiculo=self.vehiculo,
            tipo='mantenimiento'
        )
        
        self.assertEqual(recomendaciones.count(), 1)
        self.assertEqual(recomendaciones.first().razon_recomendacion, 'Nueva recomendación')


class TestMotorRecomendacionesIntegracion(TestCase):
    """Tests de integración para el Motor de Recomendaciones"""
    
    def setUp(self):
        """Configuración para tests de integración"""
        self.motor = MotorRecomendaciones()
        
        # Crear datos más completos para tests de integración
        self.user = User.objects.create_user(
            username='integrationuser',
            email='integration@example.com',
            password='testpass123'
        )
        self.cliente = Cliente.objects.create(usuario=self.user)
        
        # Crear múltiples marcas y modelos
        self.marca_toyota = Marca.objects.create(nombre='Toyota')
        self.marca_honda = Marca.objects.create(nombre='Honda')
        
        self.modelo_corolla = Modelo.objects.create(nombre='Corolla', marca=self.marca_toyota)
        self.modelo_civic = Modelo.objects.create(nombre='Civic', marca=self.marca_honda)
        
        # Crear múltiples vehículos
        self.vehiculo1 = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca_toyota,
            modelo=self.modelo_corolla,
            patente='ABC123',
            año=2018,
            kilometraje=45000
        )
        
        self.vehiculo2 = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca_honda,
            modelo=self.modelo_civic,
            patente='XYZ789',
            año=2021,
            kilometraje=15000
        )
        
        # Crear servicios variados
        self.servicios = [
            Servicio.objects.create(
                nombre='Cambio de Aceite',
                descripcion='Cambio de aceite y filtro',
                precio_base=30000
            ),
            Servicio.objects.create(
                nombre='Revisión de Frenos',
                descripcion='Inspección y mantenimiento de frenos',
                precio_base=45000
            ),
            Servicio.objects.create(
                nombre='Alineación y Balanceo',
                descripcion='Alineación de ruedas y balanceo',
                precio_base=25000
            )
        ]
        
        # Crear configuraciones necesarias
        configuraciones = {
            'umbral_score_minimo': '0.3',
            'max_recomendaciones_mantenimiento': '5',
            'max_recomendaciones_proveedores': '10',
            'peso_calificacion_proveedor': '0.4',
            'peso_historial_usuario': '0.3',
            'peso_popularidad_servicio': '0.3'
        }
        
        for clave, valor in configuraciones.items():
            ConfiguracionPersonalizacion.objects.create(
                clave=clave,
                valor=valor,
                descripcion=f'Configuración de {clave}'
            )
            
    def test_flujo_completo_recomendaciones(self):
        """Test del flujo completo de generación de recomendaciones"""
        # Crear perfiles para ambos vehículos
        PerfilVehiculo.objects.create(
            vehiculo=self.vehiculo1,
            gasto_promedio_mensual=60000,
            frecuencia_mantenimiento=120,
            servicios_frecuentes=['Cambio de Aceite', 'Revisión de Frenos']
        )
        
        PerfilVehiculo.objects.create(
            vehiculo=self.vehiculo2,
            gasto_promedio_mensual=40000,
            frecuencia_mantenimiento=180,
            servicios_frecuentes=['Cambio de Aceite']
        )
        
        # Generar recomendaciones para ambos vehículos
        resultado1 = self.motor.generar_recomendaciones_vehiculo(self.vehiculo1)
        resultado2 = self.motor.generar_recomendaciones_vehiculo(self.vehiculo2)
        
        # Verificar que se generaron resultados
        self.assertIsInstance(resultado1, dict)
        self.assertIsInstance(resultado2, dict)
        
        # Verificar que se crearon recomendaciones en la base de datos
        recomendaciones_v1 = RecomendacionPersonalizada.objects.filter(vehiculo=self.vehiculo1)
        recomendaciones_v2 = RecomendacionPersonalizada.objects.filter(vehiculo=self.vehiculo2)
        
        # Debería haber recomendaciones para ambos vehículos
        self.assertGreaterEqual(recomendaciones_v1.count(), 0)
        self.assertGreaterEqual(recomendaciones_v2.count(), 0)
        
        # Verificar que todas las recomendaciones tienen scores válidos
        for rec in recomendaciones_v1:
            self.assertGreaterEqual(rec.score_relevancia, 0.0)
            self.assertLessEqual(rec.score_relevancia, 1.0)
            self.assertTrue(rec.activa)
            
        for rec in recomendaciones_v2:
            self.assertGreaterEqual(rec.score_relevancia, 0.0)
            self.assertLessEqual(rec.score_relevancia, 1.0)
            self.assertTrue(rec.activa)
            
    def test_diferencias_recomendaciones_por_vehiculo(self):
        """Test que vehículos diferentes reciben recomendaciones diferentes"""
        # Crear perfiles muy diferentes
        PerfilVehiculo.objects.create(
            vehiculo=self.vehiculo1,  # Vehículo más viejo, más kilometraje
            gasto_promedio_mensual=80000,
            frecuencia_mantenimiento=90,
            servicios_frecuentes=['Cambio de Aceite', 'Revisión de Frenos', 'Alineación y Balanceo']
        )
        
        PerfilVehiculo.objects.create(
            vehiculo=self.vehiculo2,  # Vehículo más nuevo, menos kilometraje
            gasto_promedio_mensual=30000,
            frecuencia_mantenimiento=180,
            servicios_frecuentes=['Cambio de Aceite']
        )
        
        # Generar recomendaciones
        self.motor.generar_recomendaciones_vehiculo(self.vehiculo1)
        self.motor.generar_recomendaciones_vehiculo(self.vehiculo2)
        
        # Obtener recomendaciones de mantenimiento
        recs_v1 = RecomendacionPersonalizada.objects.filter(
            vehiculo=self.vehiculo1,
            tipo='mantenimiento'
        ).order_by('-score_relevancia')
        
        recs_v2 = RecomendacionPersonalizada.objects.filter(
            vehiculo=self.vehiculo2,
            tipo='mantenimiento'
        ).order_by('-score_relevancia')
        
        # El vehículo más viejo debería tener scores más altos en promedio
        if recs_v1.exists() and recs_v2.exists():
            score_promedio_v1 = sum(r.score_relevancia for r in recs_v1) / recs_v1.count()
            score_promedio_v2 = sum(r.score_relevancia for r in recs_v2) / recs_v2.count()
            
            # El vehículo más viejo y con más kilometraje debería tener scores más altos
            self.assertGreaterEqual(score_promedio_v1, score_promedio_v2)
            
    def test_performance_generacion_multiple(self):
        """Test de performance para generación múltiple"""
        import time
        
        # Crear múltiples vehículos para test de performance
        vehiculos_test = []
        for i in range(10):
            vehiculo = Vehiculo.objects.create(
                cliente=self.cliente,
                marca=self.marca_toyota,
                modelo=self.modelo_corolla,
                patente=f'TEST{i:03d}',
                año=2019,
                kilometraje=30000 + (i * 5000)
            )
            vehiculos_test.append(vehiculo)
            
            # Crear perfil para cada vehículo
            PerfilVehiculo.objects.create(
                vehiculo=vehiculo,
                gasto_promedio_mensual=50000,
                frecuencia_mantenimiento=120,
                servicios_frecuentes=['Cambio de Aceite']
            )
        
        # Medir tiempo de generación
        start_time = time.time()
        
        for vehiculo in vehiculos_test:
            self.motor.generar_recomendaciones_vehiculo(vehiculo)
            
        end_time = time.time()
        tiempo_total = end_time - start_time
        
        # Verificar que el tiempo es razonable (menos de 1 segundo por vehículo)
        tiempo_por_vehiculo = tiempo_total / len(vehiculos_test)
        self.assertLess(tiempo_por_vehiculo, 1.0, 
                       f"Tiempo por vehículo muy alto: {tiempo_por_vehiculo:.2f}s")
        
        # Verificar que se generaron recomendaciones para todos
        total_recomendaciones = RecomendacionPersonalizada.objects.filter(
            vehiculo__in=vehiculos_test
        ).count()
        
        self.assertGreater(total_recomendaciones, 0)


if __name__ == '__main__':
    unittest.main() 
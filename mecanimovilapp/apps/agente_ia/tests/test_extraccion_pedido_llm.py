"""Tests para extracción estructurada del pedido con LLM."""
from django.test import TestCase
from unittest.mock import patch, Mock

from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import (
    extraer_pedido_con_llm,
    PedidoExtraido,
    VehiculoExtraido,
    ServicioExtraido,
    RepuestoMencionado,
    _fallback_regex,
)


class ExtraicionPedidoLLMTestCase(TestCase):
    """Tests de extracción con LLM."""
    
    def test_extraccion_filtro_aire_simple(self):
        """Test: extraer pedido simple de filtro de aire."""
        texto = "Hola necesito cambio de filtro de aire para mi Yaris 2018"
        vehiculo_ctx = {
            'marca': 'Toyota',
            'modelo': 'Yaris',
            'anio': 2018,
        }
        
        with patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion') as mock_llm:
            mock_llm.return_value = PedidoExtraido(
                vehiculo=VehiculoExtraido(
                    marca='Toyota',
                    modelo='Yaris',
                    anio=2018,
                ),
                servicios=[
                    ServicioExtraido(nombre='Cambio de filtro de aire', cantidad=1)
                ],
                repuestos_mencionados=[
                    RepuestoMencionado(nombre='Filtro de aire', cantidad=1)
                ],
                alcance_repuestos='con_repuestos',
                descripcion_problema=texto,
            )
            
            resultado = extraer_pedido_con_llm(texto, vehiculo_ctx)
            
            self.assertEqual(resultado.vehiculo.marca, 'Toyota')
            self.assertEqual(resultado.vehiculo.modelo, 'Yaris')
            self.assertEqual(resultado.vehiculo.anio, 2018)
            self.assertEqual(len(resultado.servicios), 1)
            self.assertEqual(resultado.servicios[0].nombre, 'Cambio de filtro de aire')
            self.assertEqual(len(resultado.repuestos_mencionados), 1)
            self.assertEqual(resultado.alcance_repuestos, 'con_repuestos')
    
    def test_extraccion_pack_pastillas_discos(self):
        """Test: extraer pack pastillas + discos."""
        texto = "Necesito cambio de pastillas y discos delanteros para Mazda 3 2015"
        
        with patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion') as mock_llm:
            mock_llm.return_value = PedidoExtraido(
                vehiculo=VehiculoExtraido(
                    marca='Mazda',
                    modelo='3',
                    anio=2015,
                ),
                servicios=[
                    ServicioExtraido(nombre='Cambio de pastillas y discos de freno delanteros', cantidad=1)
                ],
                repuestos_mencionados=[
                    RepuestoMencionado(nombre='Pastillas de freno delanteras', cantidad=1),
                    RepuestoMencionado(nombre='Discos de freno delanteros', cantidad=2),
                ],
                alcance_repuestos='con_repuestos',
            )
            
            resultado = extraer_pedido_con_llm(texto, {})
            
            self.assertEqual(resultado.vehiculo.marca, 'Mazda')
            self.assertEqual(len(resultado.servicios), 1)
            self.assertIn('pastillas', resultado.servicios[0].nombre.lower())
            self.assertEqual(len(resultado.repuestos_mencionados), 2)
    
    def test_extraccion_embrague_completo(self):
        """Test: extraer embrague completo con kit + volante + aceite."""
        texto = "Cambio de embrague completo con kit, volante bimasa y aceite de caja para Chevrolet Cruze 2012 1.8"
        
        with patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion') as mock_llm:
            mock_llm.return_value = PedidoExtraido(
                vehiculo=VehiculoExtraido(
                    marca='Chevrolet',
                    modelo='Cruze',
                    anio=2012,
                    motor='1.8',
                ),
                servicios=[
                    ServicioExtraido(nombre='Cambio de embrague', cantidad=1)
                ],
                repuestos_mencionados=[
                    RepuestoMencionado(nombre='Kit de embrague', cantidad=1),
                    RepuestoMencionado(nombre='Volante bimasa', cantidad=1),
                    RepuestoMencionado(nombre='Aceite de caja de cambios', cantidad=1),
                ],
                alcance_repuestos='con_repuestos',
            )
            
            resultado = extraer_pedido_con_llm(texto, {})
            
            self.assertEqual(len(resultado.servicios), 1)
            self.assertEqual(len(resultado.repuestos_mencionados), 3)
            nombres_repuestos = [r.nombre.lower() for r in resultado.repuestos_mencionados]
            self.assertTrue(any('kit' in n for n in nombres_repuestos))
            self.assertTrue(any('volante' in n for n in nombres_repuestos))
            self.assertTrue(any('aceite' in n for n in nombres_repuestos))
    
    def test_extraccion_con_patente_y_anio(self):
        """Test: extraer con patente chilena y año."""
        texto = "Cotización cambio de aceite para ABCD12, Toyota Corolla 2019"
        
        with patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion') as mock_llm:
            mock_llm.return_value = PedidoExtraido(
                vehiculo=VehiculoExtraido(
                    marca='Toyota',
                    modelo='Corolla',
                    anio=2019,
                    patente='ABCD12',
                ),
                servicios=[
                    ServicioExtraido(nombre='Cambio de aceite', cantidad=1)
                ],
                alcance_repuestos='con_repuestos',
            )
            
            resultado = extraer_pedido_con_llm(texto, {})
            
            self.assertEqual(resultado.vehiculo.patente, 'ABCD12')
            self.assertEqual(resultado.vehiculo.anio, 2019)
    
    def test_llm_falla_fallback_regex(self):
        """Test: si LLM falla, usar fallback a regex."""
        texto = "Cambio de aceite y filtro"
        
        with patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion') as mock_llm:
            mock_llm.return_value = None  # Simular falla LLM
            
            resultado = extraer_pedido_con_llm(texto, {'marca': 'Toyota', 'modelo': 'Yaris'})
            
            # Debe tener datos del fallback regex
            self.assertIsInstance(resultado, PedidoExtraido)
            self.assertEqual(resultado.vehiculo.marca, 'Toyota')
            # Puede tener servicios detectados por regex
            self.assertIn(resultado.alcance_repuestos, ['con_repuestos', 'solo_mano_obra', 'no_definido'])
    
    def test_validacion_anio_invalido(self):
        """Test: validación Pydantic rechaza año inválido."""
        from pydantic import ValidationError
        
        with self.assertRaises(ValidationError):
            VehiculoExtraido(
                marca='Toyota',
                modelo='Yaris',
                anio=1800,  # Año inválido (< 1980)
            )
        
        with self.assertRaises(ValidationError):
            VehiculoExtraido(
                marca='Toyota',
                modelo='Yaris',
                anio=2050,  # Año inválido (> 2030)
            )
    
    def test_alcance_solo_mano_obra(self):
        """Test: detectar alcance 'solo mano de obra'."""
        texto = "Cambio de pastillas, yo pongo las pastillas"
        
        with patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion') as mock_llm:
            mock_llm.return_value = PedidoExtraido(
                vehiculo=VehiculoExtraido(marca='Toyota', modelo='Yaris'),
                servicios=[ServicioExtraido(nombre='Cambio de pastillas', cantidad=1)],
                alcance_repuestos='solo_mano_obra',
            )
            
            resultado = extraer_pedido_con_llm(texto, {})
            
            self.assertEqual(resultado.alcance_repuestos, 'solo_mano_obra')
    
    def test_tipo_motor_validacion(self):
        """Test: validar tipo de motor."""
        # Tipos válidos
        v1 = VehiculoExtraido(tipo_motor='GASOLINA')
        self.assertEqual(v1.tipo_motor, 'GASOLINA')
        
        v2 = VehiculoExtraido(tipo_motor='DIESEL')
        self.assertEqual(v2.tipo_motor, 'DIESEL')
        
        # Tipo inválido se convierte a None
        v3 = VehiculoExtraido(tipo_motor='INVALID')
        self.assertIsNone(v3.tipo_motor)


class FallbackRegexTestCase(TestCase):
    """Tests del fallback a regex."""
    
    def test_fallback_extrae_servicios(self):
        """Test: fallback extrae servicios con regex."""
        texto = "Cambio de aceite y filtro"
        vehiculo_ctx = {'marca': 'Toyota', 'modelo': 'Yaris'}
        
        resultado = _fallback_regex(texto, vehiculo_ctx)
        
        self.assertIsInstance(resultado, PedidoExtraido)
        self.assertEqual(resultado.vehiculo.marca, 'Toyota')
        # Regex debe detectar servicios mencionados
        self.assertGreaterEqual(len(resultado.servicios), 0)
    
    def test_fallback_preserva_contexto_vehiculo(self):
        """Test: fallback preserva contexto de vehículo."""
        texto = "Diagnostico de frenos"
        vehiculo_ctx = {
            'marca': 'Honda',
            'modelo': 'Civic',
            'anio': 2020,
            'patente': 'XYZ123',
        }
        
        resultado = _fallback_regex(texto, vehiculo_ctx)
        
        self.assertEqual(resultado.vehiculo.marca, 'Honda')
        self.assertEqual(resultado.vehiculo.modelo, 'Civic')
        self.assertEqual(resultado.vehiculo.anio, 2020)
        self.assertEqual(resultado.vehiculo.patente, 'XYZ123')

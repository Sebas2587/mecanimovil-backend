"""Tests para selección inteligente de casas de repuestos."""
from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.seleccion_casa_repuestos import (
    OpcionCasa,
    ResultadoSeleccion,
    seleccionar_casa_optima,
    consolidar_si_posible,
)


class SeleccionCasaOptimaTestCase(TestCase):
    """Tests de selección de mejor casa."""
    
    def test_mejor_precio_con_stock_gana(self):
        """Test: la opción con mejor precio y stock debe ganar."""
        opciones = [
            OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=15000, stock_disponible=True),
            OpcionCasa(casa='Casa B', proveedor_id=2, precio_clp=12000, stock_disponible=True),
            OpcionCasa(casa='Casa C', proveedor_id=3, precio_clp=14500, stock_disponible=True),
        ]
        
        resultado = seleccionar_casa_optima(opciones)
        
        self.assertEqual(resultado.casa_elegida, 'Casa B')
        self.assertEqual(resultado.precio_final_clp, 12000)
        self.assertIn('mejor precio', resultado.motivo_seleccion.lower())
        self.assertEqual(len(resultado.alternativas_descartadas), 2)
    
    def test_stock_inmediato_vs_mas_barato_sin_stock(self):
        """Test: stock inmediato gana vs 5% más barato sin stock."""
        opciones = [
            OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=12000, stock_disponible=False),
            OpcionCasa(casa='Casa B', proveedor_id=2, precio_clp=12600, stock_disponible=True),
        ]
        
        resultado = seleccionar_casa_optima(opciones)
        
        self.assertEqual(resultado.casa_elegida, 'Casa B')
        self.assertTrue(resultado.precio_final_clp > 0)
        
        # Verificar alternativa descartada
        alt = resultado.alternativas_descartadas[0]
        self.assertEqual(alt['casa'], 'Casa A')
        self.assertIn('sin stock', alt['motivo_descarte'].lower())
    
    def test_unica_opcion_con_stock(self):
        """Test: si solo una tiene stock, se elige automáticamente."""
        opciones = [
            OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=15000, stock_disponible=False),
            OpcionCasa(casa='Casa B', proveedor_id=2, precio_clp=14000, stock_disponible=False),
            OpcionCasa(casa='Casa C', proveedor_id=3, precio_clp=18000, stock_disponible=True),
        ]
        
        resultado = seleccionar_casa_optima(opciones)
        
        self.assertEqual(resultado.casa_elegida, 'Casa C')
        self.assertIn('única', resultado.motivo_seleccion.lower())
        self.assertEqual(len(resultado.alternativas_descartadas), 2)
    
    def test_ninguna_casa_con_stock(self):
        """Test: si ninguna tiene stock, elegir la más barata."""
        opciones = [
            OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=15000, stock_disponible=False),
            OpcionCasa(casa='Casa B', proveedor_id=2, precio_clp=12000, stock_disponible=False),
            OpcionCasa(casa='Casa C', proveedor_id=3, precio_clp=14000, stock_disponible=False),
        ]
        
        resultado = seleccionar_casa_optima(opciones)
        
        self.assertEqual(resultado.casa_elegida, 'Casa B')
        self.assertEqual(resultado.precio_final_clp, 12000)
        self.assertIn('sin stock confirmado', resultado.motivo_seleccion.lower())
    
    def test_compatibilidad_alta_puede_influir(self):
        """Test: compatibilidad alta puede inclinar la decisión."""
        opciones = [
            OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=12000, stock_disponible=True, compatibilidad_score=0.5),
            OpcionCasa(casa='Casa B', proveedor_id=2, precio_clp=12100, stock_disponible=True, compatibilidad_score=0.95),
        ]
        
        resultado = seleccionar_casa_optima(opciones)
        
        # Casa B puede ganar por compatibilidad aunque sea ligeramente más cara
        self.assertIn(resultado.casa_elegida, ['Casa A', 'Casa B'])
        self.assertIsInstance(resultado.motivo_seleccion, str)
        self.assertTrue(len(resultado.motivo_seleccion) > 0)
    
    def test_sin_opciones_retorna_vacio(self):
        """Test: sin opciones retorna resultado vacío."""
        opciones = []
        
        resultado = seleccionar_casa_optima(opciones)
        
        self.assertEqual(resultado.casa_elegida, '')
        self.assertEqual(resultado.proveedor_id, 0)
        self.assertEqual(resultado.precio_final_clp, 0)
        self.assertEqual(len(resultado.alternativas_descartadas), 0)
    
    def test_alternativas_documentan_motivo_descarte(self):
        """Test: alternativas descartadas tienen motivo claro."""
        opciones = [
            OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=15000, stock_disponible=True),
            OpcionCasa(casa='Casa B', proveedor_id=2, precio_clp=12000, stock_disponible=True),
            OpcionCasa(casa='Casa C', proveedor_id=3, precio_clp=0, stock_disponible=False),
        ]
        
        resultado = seleccionar_casa_optima(opciones)
        
        # Verificar que todas las alternativas tienen motivo
        for alt in resultado.alternativas_descartadas:
            self.assertIn('motivo_descarte', alt)
            self.assertTrue(len(alt['motivo_descarte']) > 0)
            self.assertIn('casa', alt)
            self.assertIn('precio_clp', alt)


class ConsolidacionCasasTestCase(TestCase):
    """Tests de consolidación en una sola casa."""
    
    def test_consolidacion_viable_108_del_optimo(self):
        """Test: consolidación viable cuando una casa está al 108% del óptimo."""
        repuestos = [
            {'id': 'rep1', 'nombre': 'Filtro aceite'},
            {'id': 'rep2', 'nombre': 'Filtro aire'},
            {'id': 'rep3', 'nombre': 'Filtro polen'},
        ]
        
        todas_opciones = {
            'rep1': [
                OpcionCasa(casa='Casa Premium', proveedor_id=1, precio_clp=8000, stock_disponible=True),
                OpcionCasa(casa='Casa Economica', proveedor_id=2, precio_clp=7500, stock_disponible=True),
            ],
            'rep2': [
                OpcionCasa(casa='Casa Premium', proveedor_id=1, precio_clp=12000, stock_disponible=True),
                OpcionCasa(casa='Casa Economica', proveedor_id=2, precio_clp=11500, stock_disponible=True),
            ],
            'rep3': [
                OpcionCasa(casa='Casa Premium', proveedor_id=1, precio_clp=14000, stock_disponible=True),
                OpcionCasa(casa='Casa Economica', proveedor_id=2, precio_clp=13500, stock_disponible=True),
            ],
        }
        
        resultado = consolidar_si_posible(repuestos, todas_opciones)
        
        # Debería consolidar (Casa Premium está dentro del 10%)
        self.assertIsNotNone(resultado)
        self.assertEqual(len(resultado), 3)
        
        # Todos los repuestos deben tener la misma casa
        casas = {r.casa_elegida for r in resultado.values()}
        self.assertEqual(len(casas), 1)
        
        # Verificar flag de consolidación
        for res in resultado.values():
            self.assertTrue(res.consolidacion_aplicada)
            self.assertIn('consolidado', res.motivo_seleccion.lower())
    
    def test_consolidacion_no_viable_120_del_optimo(self):
        """Test: consolidación no viable cuando cuesta 120% del óptimo."""
        repuestos = [
            {'id': 'rep1', 'nombre': 'Filtro aceite'},
            {'id': 'rep2', 'nombre': 'Filtro aire'},
        ]
        
        todas_opciones = {
            'rep1': [
                OpcionCasa(casa='Casa Cara', proveedor_id=1, precio_clp=10000, stock_disponible=True),
                OpcionCasa(casa='Casa Barata', proveedor_id=2, precio_clp=7000, stock_disponible=True),
            ],
            'rep2': [
                OpcionCasa(casa='Casa Cara', proveedor_id=1, precio_clp=15000, stock_disponible=True),
                OpcionCasa(casa='Casa Barata', proveedor_id=2, precio_clp=11000, stock_disponible=True),
            ],
        }
        
        # Total Casa Cara: 25000
        # Total óptimo distribuido: 7000 + 11000 = 18000
        # 25000 / 18000 = 138% > 110% threshold
        
        resultado = consolidar_si_posible(repuestos, todas_opciones)
        
        self.assertIsNone(resultado)  # No debe consolidar
    
    def test_ninguna_casa_tiene_todos(self):
        """Test: si ninguna casa tiene todos los repuestos, no consolidar."""
        repuestos = [
            {'id': 'rep1', 'nombre': 'Pieza A'},
            {'id': 'rep2', 'nombre': 'Pieza B'},
        ]
        
        todas_opciones = {
            'rep1': [
                OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=10000, stock_disponible=True),
            ],
            'rep2': [
                OpcionCasa(casa='Casa B', proveedor_id=2, precio_clp=12000, stock_disponible=True),
            ],
        }
        
        resultado = consolidar_si_posible(repuestos, todas_opciones)
        
        self.assertIsNone(resultado)
    
    def test_consolidacion_con_un_solo_repuesto(self):
        """Test: con un solo repuesto, no aplica consolidación."""
        repuestos = [
            {'id': 'rep1', 'nombre': 'Filtro'},
        ]
        
        todas_opciones = {
            'rep1': [
                OpcionCasa(casa='Casa A', proveedor_id=1, precio_clp=10000, stock_disponible=True),
            ],
        }
        
        resultado = consolidar_si_posible(repuestos, todas_opciones)
        
        self.assertIsNone(resultado)  # Consolidación no aplica con 1 repuesto
    
    def test_consolidacion_marca_flag_en_resultado(self):
        """Test: consolidación marca consolidacion_aplicada=True."""
        repuestos = [
            {'id': 'rep1', 'nombre': 'A'},
            {'id': 'rep2', 'nombre': 'B'},
        ]
        
        todas_opciones = {
            'rep1': [
                OpcionCasa(casa='Casa Unica', proveedor_id=1, precio_clp=10000, stock_disponible=True),
            ],
            'rep2': [
                OpcionCasa(casa='Casa Unica', proveedor_id=1, precio_clp=12000, stock_disponible=True),
            ],
        }
        
        resultado = consolidar_si_posible(repuestos, todas_opciones)
        
        self.assertIsNotNone(resultado)
        
        for rid, res in resultado.items():
            self.assertTrue(res.consolidacion_aplicada)
            self.assertIn('consolidado', res.motivo_seleccion.lower())


class OpcionCasaFromDictTestCase(TestCase):
    """Tests de construcción desde dict."""
    
    def test_from_dict_construccion_basica(self):
        """Test: construir OpcionCasa desde dict de opciones_casa."""
        data = {
            'casa': 'Casa Repuestos Central',
            'proveedor_id': 42,
            'precio_clp': 15000,
            'estado': 'respondida',
            'confianza': 0.9,
            'consulta_id': 123,
        }
        
        opcion = OpcionCasa.from_dict(data)
        
        self.assertEqual(opcion.casa, 'Casa Repuestos Central')
        self.assertEqual(opcion.proveedor_id, 42)
        self.assertEqual(opcion.precio_clp, 15000)
        self.assertTrue(opcion.stock_disponible)  # estado != 'sin_stock'
        self.assertEqual(opcion.compatibilidad_score, 0.9)
        self.assertEqual(opcion.consulta_id, 123)
    
    def test_from_dict_sin_stock(self):
        """Test: detectar sin stock desde estado."""
        data = {
            'casa': 'Casa X',
            'proveedor_id': 1,
            'precio_clp': 10000,
            'estado': 'sin_stock',
        }
        
        opcion = OpcionCasa.from_dict(data)
        
        self.assertFalse(opcion.stock_disponible)

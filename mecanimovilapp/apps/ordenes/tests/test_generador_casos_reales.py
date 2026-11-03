"""Tests end-to-end de generar_cotizacion_ia con casos reales de producción."""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
    generar_cotizacion_ia,
)
from mecanimovilapp.apps.usuarios.models import Taller


class GeneradorCasosRealesTestCase(TestCase):
    """Tests reproduciendo casos reales de producción (cotizaciones #181, #174)."""

    def setUp(self):
        """Setup taller y mocks."""
        self.taller = Taller.objects.create(
            nombre='Taller Test',
            telefono='123456789',
        )

    @patch('django.conf.settings.ASISTENTE_COTIZACION_IA_ENABLED', True)
    @patch('mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador._llamar_gemini')
    @patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion')
    def test_fiat_bravo_aceite_con_filtro(self, mock_extraccion, mock_gemini):
        """
        Caso FIAT BRAVO 2010 (cotización #181):
        "Cambio de aceite de motor con filtro" debe incluir:
        - Aceite de motor (4 litros para 1.4L)
        - Filtro de aceite
        
        Y NO debe matchear "aceite" con "enfriador de aceite".
        """
        # Mock extracción estructurada
        from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import (
            PedidoExtraido,
            RepuestoMencionado,
            ServicioExtraido,
            VehiculoExtraido,
        )

        mock_extraccion.return_value = PedidoExtraido(
            vehiculo=VehiculoExtraido(
                marca='FIAT',
                modelo='BRAVO SPORT TJET',
                anio=2010,
                motor='1.4',
                tipo_motor='GASOLINA',
            ),
            servicios=[
                ServicioExtraido(
                    nombre='Cambio de aceite de motor con filtro',
                    incluye_repuestos=True,
                ),
            ],
            repuestos_mencionados=[
                RepuestoMencionado(nombre='Aceite de motor', cantidad=4),
                RepuestoMencionado(nombre='Filtro de aceite', cantidad=1),
            ],
            alcance_repuestos='con_repuestos',
        )

        # Mock respuesta Gemini
        gemini_response = {
            "servicio_nombre": "Cambio de aceite de motor con filtro",
            "descripcion_resumen": "Cambio de aceite y filtro",
            "tipo_motor_efectivo": "GASOLINA",
            "tipo_motor_label": "Bencinero",
            "duracion_minutos_estimada": 45,
            "mano_obra_clp": 15000,
            "servicios_lineas": [
                {"nombre": "Cambio de aceite de motor con filtro", "monto_clp": 15000}
            ],
            "repuestos": [
                {
                    "nombre": "Aceite de motor",
                    "cantidad": 4,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 8000,
                    "precio_max_clp": 15000,
                    "especificacion": "5W30 sintético",
                    "marca_repuesto": "",
                    "fuente_marketplace": "",
                    "comentario": "Aceite sintético para motor 1.4 T-Jet",
                },
                {
                    "nombre": "Filtro de aceite",
                    "cantidad": 1,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 5000,
                    "precio_max_clp": 12000,
                    "especificacion": "",
                    "marca_repuesto": "",
                    "fuente_marketplace": "",
                    "comentario": "Filtro compatible FIAT Bravo 1.4",
                },
            ],
            "advertencias": ["Precios referenciales con IVA incluido"],
        }
        mock_gemini.return_value = (
            gemini_response,
            {'tokens_entrada': 1000, 'tokens_salida': 500, 'modelo': 'gemini-test'},
            None,
        )

        # Ejecutar generador
        resultado = generar_cotizacion_ia(
            servicio_nombre='Cambio de aceite de motor con filtro',
            descripcion_problema='',
            vehiculo={
                'marca': 'FIAT',
                'modelo': 'BRAVO SPORT TJET',
                'anio': 2010,
                'motor': '1.4',
                'patente': 'CJXP98',
            },
            taller=self.taller,
            enriquecer_marketplace=False,  # Sin enriquecimiento real
        )

        # Verificar resultado
        self.assertTrue(resultado['disponible'])
        contenido = resultado['contenido']
        repuestos = contenido['repuestos']

        # Debe tener ambos repuestos
        self.assertEqual(len(repuestos), 2, 'Debe tener 2 repuestos: aceite + filtro')

        nombres = [r['nombre'] for r in repuestos]
        self.assertIn('Aceite de motor', nombres, 'Debe incluir aceite de motor')
        self.assertIn('Filtro de aceite', nombres, 'Debe incluir filtro de aceite')

        # Aceite: 4 litros (capacidad motor 1.4L)
        aceite = next(r for r in repuestos if 'Aceite' in r['nombre'])
        self.assertEqual(aceite['cantidad'], 4, 'Motor 1.4L requiere ~4 litros de aceite')

        # Filtro: 1 unidad
        filtro = next(r for r in repuestos if 'Filtro' in r['nombre'])
        self.assertEqual(filtro['cantidad'], 1, 'Debe incluir 1 filtro de aceite')

    @patch('django.conf.settings.ASISTENTE_COTIZACION_IA_ENABLED', True)
    @patch('mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador._llamar_gemini')
    @patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion')
    def test_fiat_bravo_pastillas_freno(self, mock_extraccion, mock_gemini):
        """
        Caso FIAT BRAVO 2010 (cotización #181):
        "Cambio de pastillas de freno delanteras" NO debe matchear con discos.
        """
        from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import (
            PedidoExtraido,
            RepuestoMencionado,
            ServicioExtraido,
            VehiculoExtraido,
        )

        mock_extraccion.return_value = PedidoExtraido(
            vehiculo=VehiculoExtraido(
                marca='FIAT',
                modelo='BRAVO',
                anio=2010,
                motor='1.4',
            ),
            servicios=[
                ServicioExtraido(nombre='Cambio de pastillas de freno delanteras'),
            ],
            repuestos_mencionados=[
                RepuestoMencionado(nombre='Pastillas de freno delanteras', cantidad=1),
            ],
        )

        gemini_response = {
            "servicio_nombre": "Cambio de pastillas de freno delanteras",
            "descripcion_resumen": "Cambio de pastillas delanteras",
            "tipo_motor_efectivo": "GASOLINA",
            "duracion_minutos_estimada": 60,
            "mano_obra_clp": 25000,
            "servicios_lineas": [
                {"nombre": "Cambio de pastillas de freno delanteras", "monto_clp": 25000}
            ],
            "repuestos": [
                {
                    "nombre": "Pastillas de freno delanteras",
                    "cantidad": 1,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 40000,
                    "precio_max_clp": 80000,
                    "especificacion": "Cerámica",
                    "marca_repuesto": "",
                    "comentario": "Juego pastillas delanteras",
                },
            ],
            "advertencias": ["Precios referenciales"],
        }
        mock_gemini.return_value = (gemini_response, {'modelo': 'test'}, None)

        resultado = generar_cotizacion_ia(
            servicio_nombre='Cambio de pastillas de freno delanteras',
            vehiculo={'marca': 'FIAT', 'modelo': 'BRAVO', 'anio': 2010},
            taller=self.taller,
            enriquecer_marketplace=False,
        )

        self.assertTrue(resultado['disponible'])
        repuestos = resultado['contenido']['repuestos']
        self.assertEqual(len(repuestos), 1)
        self.assertIn('Pastillas', repuestos[0]['nombre'])
        # Verificar que NO hay discos
        self.assertNotIn('Disco', repuestos[0]['nombre'])

    @patch('django.conf.settings.ASISTENTE_COTIZACION_IA_ENABLED', True)
    @patch('mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador._llamar_gemini')
    @patch('mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm._llamar_gemini_extraccion')
    def test_suzuki_celerio_embrague_sin_extras(self, mock_extraccion, mock_gemini):
        """
        Caso Suzuki Celerio (cotización #174):
        "Cambio de embrague" NO debe agregar:
        - Piola (salvo que sea a cable)
        - Aceites extra no solicitados
        - Volante bimasa no solicitado
        
        SÍ debe incluir:
        - Kit de embrague
        - Rodamiento piloto
        - Aceite de caja (cantidad razonable ~2-3L)
        - Retén trasero cigüeñal
        """
        from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import (
            PedidoExtraido,
            RepuestoMencionado,
            ServicioExtraido,
            VehiculoExtraido,
        )

        mock_extraccion.return_value = PedidoExtraido(
            vehiculo=VehiculoExtraido(
                marca='Suzuki',
                modelo='Celerio',
                anio=2015,
                motor='1.0',
            ),
            servicios=[
                ServicioExtraido(nombre='Cambio de embrague'),
            ],
            repuestos_mencionados=[],  # No mencionó partes específicas
        )

        gemini_response = {
            "servicio_nombre": "Cambio de embrague",
            "descripcion_resumen": "Cambio kit embrague completo",
            "tipo_motor_efectivo": "GASOLINA",
            "duracion_minutos_estimada": 240,
            "mano_obra_clp": 120000,
            "servicios_lineas": [
                {"nombre": "Cambio de embrague", "monto_clp": 120000}
            ],
            "repuestos": [
                {
                    "nombre": "Kit de embrague",
                    "cantidad": 1,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 80000,
                    "precio_max_clp": 150000,
                    "comentario": "Disco + prensa + collarin",
                },
                {
                    "nombre": "Rodamiento de volante",
                    "cantidad": 1,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 15000,
                    "precio_max_clp": 30000,
                    "comentario": "Rodamiento piloto",
                },
                {
                    "nombre": "Aceite de caja de cambios",
                    "cantidad": 2,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 8000,
                    "precio_max_clp": 15000,
                    "comentario": "Litros de aceite para transmisión manual",
                },
                {
                    "nombre": "Retén trasero de cigüeñal",
                    "cantidad": 1,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 5000,
                    "precio_max_clp": 12000,
                },
            ],
            "advertencias": ["Precios referenciales"],
        }
        mock_gemini.return_value = (gemini_response, {'modelo': 'test'}, None)

        resultado = generar_cotizacion_ia(
            servicio_nombre='Cambio de embrague',
            vehiculo={'marca': 'Suzuki', 'modelo': 'Celerio', 'anio': 2015},
            taller=self.taller,
            enriquecer_marketplace=False,
        )

        self.assertTrue(resultado['disponible'])
        repuestos = resultado['contenido']['repuestos']

        nombres = [r['nombre'].lower() for r in repuestos]

        # Debe incluir
        self.assertTrue(any('kit' in n and 'embrague' in n for n in nombres), 'Debe incluir kit de embrague')
        self.assertTrue(any('rodamiento' in n for n in nombres), 'Debe incluir rodamiento piloto')
        self.assertTrue(any('aceite' in n and 'caja' in n for n in nombres), 'Debe incluir aceite de caja')
        self.assertTrue(any('reten' in n or 'retén' in n for n in nombres), 'Debe incluir retén cigüeñal')

        # NO debe incluir extras no solicitados
        self.assertFalse(
            any('piola' in n or 'cable' in n or 'guaya' in n for n in nombres),
            'NO debe agregar piola/cable salvo que sea a cable'
        )
        self.assertFalse(
            any('volante bimasa' in n or 'dual mass' in n for n in nombres),
            'NO debe agregar volante bimasa no solicitado'
        )

        # Aceite de caja: cantidad razonable (2-3L para manual)
        aceite_caja = next((r for r in repuestos if 'aceite' in r['nombre'].lower() and 'caja' in r['nombre'].lower()), None)
        if aceite_caja:
            self.assertLessEqual(aceite_caja['cantidad'], 3, 'Cantidad de aceite caja debe ser ≤3L para manual')

    @patch('django.conf.settings.ASISTENTE_COTIZACION_IA_ENABLED', True)
    @patch('mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador._llamar_gemini')
    def test_campos_seleccion_casa_expuestos(self, mock_gemini):
        """
        Verificar que los campos de selección de casa se exponen en el resultado:
        - casa_repuesto_nombre
        - motivo_seleccion
        - alternativas_descartadas
        - consolidacion_aplicada
        """
        gemini_response = {
            "servicio_nombre": "Cambio de bujías",
            "duracion_minutos_estimada": 30,
            "mano_obra_clp": 20000,
            "servicios_lineas": [{"nombre": "Cambio de bujías", "monto_clp": 20000}],
            "repuestos": [
                {
                    "nombre": "Bujías iridio",
                    "cantidad": 4,
                    "precio_unitario_clp": 0,
                    "precio_min_clp": 15000,
                    "precio_max_clp": 30000,
                },
            ],
            "advertencias": [],
        }
        mock_gemini.return_value = (gemini_response, {'modelo': 'test'}, None)

        resultado = generar_cotizacion_ia(
            servicio_nombre='Cambio de bujías',
            vehiculo={'marca': 'Toyota', 'modelo': 'Yaris', 'anio': 2018},
            taller=self.taller,
            enriquecer_marketplace=True,  # TRUE para que se aplique selección de casas
            enriquecer_ml=False,
            usar_web=False,
        )

        self.assertTrue(resultado['disponible'])
        repuestos = resultado['contenido']['repuestos']
        self.assertEqual(len(repuestos), 1)

        rep = repuestos[0]
        # Verificar que los campos existen
        self.assertIn('casa_repuesto_nombre', rep, 'Debe exponer casa_repuesto_nombre')
        self.assertIn('motivo_seleccion', rep, 'Debe exponer motivo_seleccion')
        self.assertIn('alternativas_descartadas', rep, 'Debe exponer alternativas_descartadas')
        self.assertIn('consolidacion_aplicada', rep, 'Debe exponer consolidacion_aplicada')
        
        # Sin enriquecimiento real, el motivo debe explicar por qué no hay casa
        self.assertIsInstance(rep['casa_repuesto_nombre'], str)
        self.assertIsInstance(rep['motivo_seleccion'], str)
        self.assertIsInstance(rep['alternativas_descartadas'], list)
        self.assertIsInstance(rep['consolidacion_aplicada'], bool)

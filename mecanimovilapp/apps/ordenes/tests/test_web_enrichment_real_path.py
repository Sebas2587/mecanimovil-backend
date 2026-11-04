"""
Tests para el flujo REAL de enriquecimiento web de cotizaciones.

Este test verifica el camino real de producción:
1. generar_cotizacion_ia crea cotización sin web
2. buscar_precios_web_cotizacion_task enriquece asíncronamente
3. Valida tipo de parte (_validar_tipo_parte)
4. Aplica selección de casa (_aplicar_seleccion_casa_repuestos)
5. Ajusta rangos (_ajustar_rangos_consistentes)
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import CotizacionCanal, PrecioRepuestoWeb
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class WebEnrichmentRealPathTestCase(TestCase):
    """
    Reproduce el flujo completo de producción donde el taller reporta:
    - "Aceite de motor TISS" x4 matcha "Enfriador aceite Fiat Bravo" (BUG)
    - "Pastillas freno" matcha "Repuestos Fiat Bravo | Mundo Repuestos" genérico (BUG)
    - motivo_seleccion dice "No se encontraron proveedores..." aunque hay store chip (BUG)
    - Rango de aceite $30k-$50k pero line total es $125.960 (BUG)
    """
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Importar aquí para evitar AppRegistryNotReady
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _clave_fuzzy,
        )
        cls._clave_fuzzy = _clave_fuzzy
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='provider_test',
            email='provider@test.com',
            password='test123',
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Test Real Path',
            telefono='+56912345678',
            estado_verificacion='aprobado',
        )
    
    def _crear_cotizacion_base(self, repuestos_list):
        """Crea una cotización como lo hace generar_ia (sin web enrichment)."""
        cot = CotizacionCanal.objects.create(
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            vehiculo_cilindraje='1.4',
            tipo_motor='',
            servicio_nombre='Cambio aceite y pastillas',
            repuestos=repuestos_list,
            costo_repuestos_clp=0,
            mano_obra_clp=25000,
            descuento_clp=0,
            total_clp=25000,
            metadata={'busqueda_web_estado': 'pendiente'},
        )
        return cot
    
    def _poblar_cache_web(self, hits_dict):
        """
        Pobla PrecioRepuestoWeb como si buscar_repuestos_web hubiera corrido.
        
        hits_dict: {clave_fuzzy: {'nombre_producto': ..., 'precio_clp': ..., 'tienda': ..., 'url': ...}}
        """
        expira = timezone.now() + timedelta(days=14)
        for clave, hit in hits_dict.items():
            PrecioRepuestoWeb.objects.update_or_create(
                clave=clave,
                dominio=hit.get('dominio', 'tienda.cl'),
                defaults={
                    'nombre_producto': hit['nombre_producto'],
                    'marca_repuesto': hit.get('marca_repuesto', ''),
                    'precio_clp': hit['precio_clp'],
                    'tienda': hit['tienda'],
                    'url': hit['url'],
                    'compatibilidad': 'ok',
                    'confianza': hit.get('confianza', 0.8),
                    'tipo_motor': '',
                    'cilindraje': '1.4',
                    'calidad': hit.get('calidad', 'alternativo'),
                    'expira_en': expira,
                },
            )
    
    def test_tipo_parte_validation_rechaza_mismatch_aceite_enfriador(self):
        """
        BUG 1 - Part Validation:
        "Aceite de motor TISS" NO debe matchear "Enfriador aceite Fiat Bravo 1.4 | Euroespecialista"
        
        El código viejo usaba _ficha_cubre_pieza que permitía este mismatch.
        El nuevo código usa _validar_tipo_parte que debe rechazarlo.
        """
        repuestos = [
            {
                'id': str(uuid.uuid4()),
                'nombre': 'Aceite de motor TISS 5W-30',
                'cantidad': 4,
                'unidad_medida': 'litro',
                'precio_unitario_clp': 0,
                'precio_min_clp': 30000,
                'precio_max_clp': 50000,
                'certeza': 'estimado',
            }
        ]
        cot = self._crear_cotizacion_base(repuestos)
        
        # Cache web con MISMATCH (enfriador vs aceite)
        clave_aceite = self.__class__._clave_fuzzy('Aceite de motor TISS 5W-30')
        self._poblar_cache_web({
            clave_aceite: {
                'nombre_producto': 'Enfriador aceite Fiat Bravo 1.4 | Euroespecialista',
                'precio_clp': 31490,
                'tienda': 'Euroespecialista',
                'url': 'https://euroespecialista.cl/enfriador-aceite-fiat-bravo',
                'dominio': 'euroespecialista.cl',
            }
        })
        
        # Mock para que nombres_sin_cache_vigente devuelva cache hit
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.nombres_sin_cache_vigente',
        ) as mock_cache:
            mock_cache.return_value = ([], {clave_aceite: {
                'nombre_producto': 'Enfriador aceite Fiat Bravo 1.4 | Euroespecialista',
                'precio_clp': 31490,
                'tienda': 'Euroespecialista',
                'url': 'https://euroespecialista.cl/enfriador-aceite-fiat-bravo',
            }})
            
            with patch(
                'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            ) as mock_web:
                mock_web.return_value = {}
                
                from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task
                result = buscar_precios_web_cotizacion_task(cot.id)
        
        self.assertTrue(result.get('ok'))
        cot.refresh_from_db()
        
        rep_enriquecido = cot.repuestos[0]
        
        # Verificación 1: NO debe tener proveedor_nombre del mismatch
        self.assertNotIn('Euroespecialista', rep_enriquecido.get('proveedor_nombre', ''))
        
        # Verificación 2: NO debe tener el nombre_producto del enfriador
        self.assertNotIn('Enfriador', rep_enriquecido.get('nombre_producto', ''))
        
        # Verificación 3: no se queda el precio del enfriador. La banda de la IA
        # puede seguir en la línea; el hit rechazado no.
        self.assertNotEqual(rep_enriquecido.get('precio_unitario_clp'), 31490)

    def test_busqueda_vacia_conserva_el_precio_asumido_y_escribe_el_motivo(self):
        """Cotización 5: pastillas asumidas se buscan; un reintento vacío no las borra."""
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        pastillas = {
            'id': 'rep-pastillas',
            'nombre': 'Pastillas de freno cerámica delanteras',
            'cantidad': 1,
            'precio_unitario_clp': 70000,
            'certeza': 'asumido',
            'precio_estimado': True,
            'motivo_seleccion': (
                'No se encontraron proveedores con este repuesto en stock para el vehículo'
            ),
        }
        aceite = {
            'id': 'rep-aceite',
            'nombre': 'Aceite 5W40 sintético',
            'cantidad': 4,
            'precio_unitario_clp': 0,
            'precio_min_clp': 18000,
            'precio_max_clp': 42000,
            'certeza': 'sin_precio',
            'motivo_seleccion': (
                'No se encontraron proveedores con este repuesto en stock para el vehículo'
            ),
        }
        filtro = {
            'id': 'rep-filtro',
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 10990,
            'fuente_marketplace': 'web',
            'proveedor_nombre': 'Todoautochile',
            'url_producto': 'https://todoautochile.cl/filtro-aceite',
            'certeza': 'referencial',
        }
        cot = self._crear_cotizacion_base([pastillas, aceite, filtro])
        consultadas: list[str] = []

        def _vacio(nombres, **kwargs):
            consultadas.extend(nombres)
            avisos = kwargs.get('avisos')
            if isinstance(avisos, dict):
                for nombre in nombres:
                    avisos[nombre] = {
                        'motivo': 'sin_ficha',
                        'detalle': (
                            f'Se buscó "{nombre}" en tiendas de Chile. '
                            'Se descartó "Enfriador aceite Fiat Bravo" '
                            'porque el título no es esa pieza.'
                        ),
                    }
            return {}

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_vacio,
        ), self.assertLogs('mecanimovilapp.apps.ordenes.tasks', level='INFO') as logs:
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'))
        self.assertIn('Pastillas de freno cerámica delanteras', consultadas)
        self.assertIn('Aceite 5W40 sintético', consultadas)
        self.assertNotIn('Filtro de aceite', consultadas)
        texto = '\n'.join(logs.output)
        self.assertIn('Tavily lineas=', texto)
        self.assertIn('Pastillas de freno cerámica delanteras', texto)
        self.assertIn('tavily hits=', texto)

        cot.refresh_from_db()
        por_id = {r['id']: r for r in cot.repuestos}
        self.assertEqual(por_id['rep-pastillas']['precio_unitario_clp'], 70000)
        self.assertIn('Se buscó', por_id['rep-pastillas']['motivo_seleccion'])
        self.assertNotIn(
            'No se encontraron proveedores con este repuesto en stock',
            por_id['rep-pastillas']['motivo_seleccion'],
        )
        self.assertEqual(por_id['rep-aceite']['precio_unitario_clp'], 42000)
        self.assertGreater(por_id['rep-aceite']['precio_min_clp'], 0)
        self.assertGreater(por_id['rep-aceite']['precio_max_clp'], 0)
        self.assertEqual(por_id['rep-aceite']['certeza'], 'asumido')
        self.assertIn('Se buscó', por_id['rep-aceite']['motivo_seleccion'])
        self.assertEqual(por_id['rep-filtro']['precio_unitario_clp'], 10990)
        self.assertEqual(por_id['rep-filtro']['proveedor_nombre'], 'Todoautochile')

        cot.metadata = {
            **(cot.metadata or {}),
            'busqueda_web_estado': 'pendiente',
            'busqueda_web_ids': ['rep-aceite'],
        }
        cot.save(update_fields=['metadata'])
        consultadas.clear()

        def _reintento_vacio(nombres, **kwargs):
            consultadas.extend(nombres)
            avisos = kwargs.get('avisos')
            if isinstance(avisos, dict):
                for nombre in nombres:
                    avisos[nombre] = {
                        'motivo': 'sin_ficha',
                        'detalle': f'Se buscó "{nombre}" otra vez. Sin ficha de tienda.',
                    }
            return {}

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_reintento_vacio,
        ):
            buscar_precios_web_cotizacion_task(cot.id)

        cot.refresh_from_db()
        por_id = {r['id']: r for r in cot.repuestos}
        self.assertEqual(consultadas, ['Aceite 5W40 sintético'])
        self.assertEqual(por_id['rep-aceite']['precio_unitario_clp'], 42000)
        self.assertIn('Se buscó', por_id['rep-aceite']['motivo_seleccion'])
        self.assertEqual(por_id['rep-pastillas']['precio_unitario_clp'], 70000)
        self.assertEqual(por_id['rep-filtro']['proveedor_nombre'], 'Todoautochile')

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            _marcar_cola_caida,
        )

        _marcar_cola_caida(cot.id, TimeoutError('Timeout reading from redis:6379'))
        cot.refresh_from_db()
        por_id = {r['id']: r for r in cot.repuestos}
        self.assertEqual(cot.metadata.get('busqueda_web_estado'), 'error')
        self.assertIn('cola no respondió', por_id['rep-pastillas']['motivo_seleccion'])
        self.assertEqual(por_id['rep-pastillas']['precio_unitario_clp'], 70000)
        self.assertEqual(por_id['rep-aceite']['precio_unitario_clp'], 42000)
        self.assertIn('cola no respondió', por_id['rep-aceite']['motivo_seleccion'])
        self.assertEqual(por_id['rep-filtro']['precio_unitario_clp'], 10990)
        self.assertEqual(por_id['rep-filtro']['proveedor_nombre'], 'Todoautochile')
        self.assertNotIn('cola no respondió', por_id['rep-filtro'].get('motivo_seleccion') or '')

    def test_pastillas_asumidas_se_buscan_y_la_bomba_no_cotiza_el_aceite(self):
        """Cotización 6: pastillas a $55.000 se buscan; la bomba de aceite no es el lubricante."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            clave_cache_repuesto,
        )
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        clave = clave_cache_repuesto(
            'Aceite de motor TISS',
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio=2010,
            cilindraje='1.4',
        )
        PrecioRepuestoWeb.objects.create(
            clave=clave,
            dominio='euroespecialista.cl',
            nombre_producto='Bomba de aceite Fiat Bravo 1.4',
            precio_clp=62991,
            tienda='Euroespecialista',
            url='https://euroespecialista.cl/bomba-aceite-fiat-bravo-1-4',
            confianza=0.9,
            cilindraje='1.4',
            expira_en=timezone.now() + timedelta(days=7),
        )
        cot = self._crear_cotizacion_base([
            {
                'id': 'rep-pastillas',
                'nombre': 'Pastillas de freno delanteras',
                'cantidad': 1,
                'precio_unitario_clp': 55000,
                'precio_min_clp': 28000,
                'precio_max_clp': 55000,
                'certeza': 'asumido',
                'comentario': 'Juego completo para eje delantero',
                'especificacion': 'Cerámica',
            },
            {
                'id': 'rep-aceite',
                'nombre': 'Aceite de motor TISS',
                'cantidad': 3,
                'precio_unitario_clp': 0,
                'precio_min_clp': 8000,
                'precio_max_clp': 15000,
                'comentario': '5W40 sintético',
            },
        ])
        consultadas: list[str] = []

        def _tavily(nombres, **kwargs):
            consultadas.extend(nombres)
            avisos = kwargs.get('avisos')
            if isinstance(avisos, dict):
                for nombre in nombres:
                    if 'pastilla' in nombre.lower():
                        avisos[nombre] = {
                            'motivo': 'sin_ficha',
                            'detalle': f'Se buscó "{nombre}". Sin ficha de pastillas.',
                        }
            return {
                self.__class__._clave_fuzzy('Aceite de motor TISS'): {
                    'nombre_producto': 'Aceite 5W40 4L',
                    'precio_clp': 39960,
                    'tienda': 'Todoautochile',
                    'url': 'https://todoautochile.cl/aceite-5w40-4l',
                    'dominio': 'todoautochile.cl',
                },
            }

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_tavily,
        ):
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'))
        self.assertIn('Pastillas de freno delanteras', consultadas)
        self.assertIn('Aceite de motor TISS', consultadas)
        cot.refresh_from_db()
        por_id = {r['id']: r for r in cot.repuestos}
        self.assertEqual(por_id['rep-pastillas']['precio_unitario_clp'], 55000)
        self.assertIn('Se buscó', por_id['rep-pastillas']['motivo_seleccion'])
        self.assertNotIn('Juego completo', por_id['rep-pastillas']['motivo_seleccion'])
        self.assertEqual(por_id['rep-aceite']['precio_unitario_clp'], 9990)
        self.assertEqual(por_id['rep-aceite']['proveedor_nombre'], 'Todoautochile')
        self.assertNotIn('Bomba', por_id['rep-aceite'].get('nombre_producto') or '')
        self.assertNotEqual(por_id['rep-aceite']['precio_unitario_clp'], 62991)

    def test_filtro_en_el_medio_no_le_pasa_el_aceite_a_las_pastillas(self):
        """Tres líneas: el filtro se inserta al medio y el aceite vuelve renombrado.

        El write-back tiene que usar el id de la línea. Por posición, el
        filtro nuevo se quedaría con las pastillas y las pastillas con el aceite.
        """
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = self._crear_cotizacion_base([
            {
                'id': 'rep-pastillas',
                'nombre': 'Pastillas de freno delanteras',
                'cantidad': 1,
                'precio_unitario_clp': 0,
                'precio_min_clp': 28000,
                'precio_max_clp': 70000,
                'certeza': 'sin_precio',
            },
            {
                'id': 'rep-aceite',
                'nombre': 'Aceite de motor',
                'cantidad': 3,
                'precio_unitario_clp': 0,
                'precio_min_clp': 8000,
                'precio_max_clp': 15000,
                'certeza': 'sin_precio',
            },
        ])
        filtro = {
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 10990,
            'proveedor_nombre': 'Todoautochile',
            'fuente_marketplace': 'catalogo',
            'nombre_producto': 'Filtro de aceite Mann',
            'url_producto': 'https://www.todoautochile.cl/filtro-aceite-bravo',
        }

        def _tavily(nombres, **kwargs):
            cot.repuestos = [filtro, *list(cot.repuestos or [])]
            cot.save(update_fields=['repuestos', 'actualizado_en'])
            return {
                'aceite motor liqui moly': {
                    'linea_id': 'rep-aceite',
                    'nombre_buscado': 'Aceite de motor Liqui Moly',
                    'nombre_producto': 'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
                    'precio_clp': 39960,
                    'tienda': 'Repuestos Sergio Escobar',
                    'url': 'https://www.mundorepuestos.cl/producto/aceite-liqui-moly-5w40-4l',
                    'dominio': 'mundorepuestos.cl',
                },
                'pastillas freno delanteras': {
                    'linea_id': 'rep-pastillas',
                    'nombre_buscado': 'Pastillas de freno delanteras',
                    'nombre_producto': 'Pastillas de Freno Delanteras Fiat Bravo 1.4 T-Jet',
                    'precio_clp': 28990,
                    'tienda': 'Frenos Vergara',
                    'url': 'https://frenosvergara.shop/products/pastillas-fiat-bravo',
                    'dominio': 'frenosvergara.shop',
                },
            }

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_tavily,
        ), self.assertLogs('mecanimovilapp.apps.ordenes.tasks', level='INFO') as logs:
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'))
        cot.refresh_from_db()
        nombres = [r.get('nombre') for r in cot.repuestos]
        self.assertIn('Filtro de aceite', nombres)
        por_id = {r['id']: r for r in cot.repuestos if r.get('id')}
        pads = por_id['rep-pastillas']
        aceite = por_id['rep-aceite']
        self.assertIn('frenosvergara.shop', pads.get('url_producto') or '')
        self.assertIn('Pastillas', pads.get('nombre_producto') or '')
        self.assertNotIn('Liqui', pads.get('nombre_producto') or '')
        self.assertEqual(pads.get('precio_unitario_clp'), 28990)
        self.assertIn('mundorepuestos.cl', aceite.get('url_producto') or '')
        self.assertIn('Liqui Moly', aceite.get('nombre_producto') or '')
        self.assertNotIn('Pastillas', aceite.get('nombre_producto') or '')
        filtro_guardado = next(r for r in cot.repuestos if r.get('nombre') == 'Filtro de aceite')
        self.assertEqual(filtro_guardado.get('proveedor_nombre'), 'Todoautochile')
        self.assertNotIn('frenosvergara', filtro_guardado.get('url_producto') or '')
        texto = '\n'.join(logs.output)
        self.assertIn('elegido id=rep-pastillas', texto)
        self.assertIn('Pastillas de Freno Delanteras Fiat Bravo', texto)
        self.assertIn('elegido id=rep-aceite', texto)

    def test_bidon_de_4l_guarda_el_estante_y_cotiza_el_litro(self):
        """$52.650 / 4 = $13.162. El cache se queda con el precio de la ficha."""
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        cot = self._crear_cotizacion_base([
            {
                'id': 'rep-aceite',
                'nombre': 'Aceite de motor',
                'cantidad': 3,
                'precio_unitario_clp': 0,
                'precio_min_clp': 8000,
                'precio_max_clp': 20000,
                'certeza': 'sin_precio',
            },
        ])

        def _tavily(nombres, **kwargs):
            self.assertEqual(kwargs.get('bandas_min', {}).get('Aceite de motor'), 8000)
            return {
                'aceite motor': {
                    'linea_id': 'rep-aceite',
                    'nombre_buscado': 'Aceite de motor',
                    'nombre_producto': 'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
                    'marca_repuesto': 'Liqui',
                    'precio_clp': 52650,
                    'tienda': 'Repuestos Sergio Escobar',
                    'url': 'https://repuestos.sergioescobar.cl/tienda/lubricantes/aceite-4l/',
                    'dominio': 'repuestos.sergioescobar.cl',
                },
            }

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_tavily,
        ), self.assertLogs('mecanimovilapp.apps.ordenes.tasks', level='INFO') as logs:
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'))
        cot.refresh_from_db()
        aceite = next(r for r in cot.repuestos if r.get('id') == 'rep-aceite')
        self.assertEqual(aceite.get('precio_unitario_clp'), 13162)
        self.assertEqual(aceite.get('nombre'), 'Aceite de motor Liqui Moly')
        self.assertNotEqual(aceite.get('nombre'), 'Aceite de motor Liqui')
        self.assertEqual(aceite.get('proveedor_nombre'), 'Repuestos Sergio Escobar')
        self.assertIn('Repuestos Sergio Escobar', aceite.get('motivo_seleccion') or '')
        fila = PrecioRepuestoWeb.objects.get(dominio='repuestos.sergioescobar.cl')
        self.assertEqual(fila.precio_clp, 52650)
        texto = '\n'.join(logs.output)
        self.assertIn('precio_estante=52650', texto)
        self.assertIn('litros=4', texto)
        self.assertIn('precio_unitario=13162', texto)


_HTML_ACEITE_ESCOBAR = """
<html><head>
  <title>Aceite Para Motor Liqui Moly Sintético 5w-40 4L | Sergio Escobar Repuestos</title>
  <script type="application/ld+json">
    {"@type":"Product","name":"Aceite Para Motor Liqui Moly Sintético 5w-40 4L",
     "offers":{"@type":"Offer","price":"58500","priceCurrency":"CLP"}}
  </script>
</head><body>
  <h1>Aceite Para Motor Liqui Moly Sintético 5w-40 4L</h1>
  <p class="price">
    <del><span class="woocommerce-Price-amount amount"><bdi>$58.500</bdi></span></del>
    <ins><span class="woocommerce-Price-amount amount"><bdi>$52.650</bdi></span></ins>
  </p>
  <p>El precio original era: $58.500. El precio actual es: $52.650.</p>
  <p>Marca: Liqui Moly</p>
</body></html>
"""

_URL_ACEITE_ESCOBAR = (
    'https://repuestos.sergioescobar.cl/tienda/lubricantes/'
    'aceite-para-motor-liqui-moly-sintetico-5w-40-para-auto-camioneta-x-4l/'
)
_URL_PASTILLA_LISTADO = (
    'https://www.mundorepuestos.com/producto/juego-pastillas-freno-fiat/'
)
_TITULO_PASTILLA_LISTADO = (
    'Juego Pastillas Freno Fiat | Envío gratis - Mundo Repuestos Chile'
)


def _html_cache_quote12(urls):
    out = {}
    for url in urls:
        if 'sergioescobar' in str(url):
            out[url] = _HTML_ACEITE_ESCOBAR
    return out


class Quote12CachePathTests(TestCase):
    """Cotización 12: la caché vigente se saltaba el modelo de la pastilla y el precio actual."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='quote12_cache',
            email='quote12@test.com',
            password='test123',
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Quote 12',
            telefono='+56912345678',
            estado_verificacion='aprobado',
        )

    def _crear_cotizacion_base(self, repuestos_list):
        return CotizacionCanal.objects.create(
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            vehiculo_cilindraje='1.4',
            tipo_motor='',
            servicio_nombre='Cambio aceite y pastillas',
            repuestos=repuestos_list,
            costo_repuestos_clp=0,
            mano_obra_clp=25000,
            descuento_clp=0,
            total_clp=25000,
            metadata={'busqueda_web_estado': 'pendiente'},
        )

    def test_la_cantidad_sale_de_la_capacidad_y_no_del_bidon(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            aplicar_cantidad_aceite_motor,
            cantidad_aceite_segun_motor,
        )

        kwargs = dict(marca='Fiat', modelo='Bravo', cilindraje='1.4', tipo_motor='T-Jet')
        self.assertEqual(cantidad_aceite_segun_motor('Aceite de motor', **kwargs), 4)
        self.assertEqual(
            cantidad_aceite_segun_motor(
                'Aceite de motor',
                marca='Fiat',
                modelo='BRAVO SPORT TJET',
                cilindraje='',
                tipo_motor='',
            ),
            4,
        )
        self.assertIsNone(cantidad_aceite_segun_motor(
            'Aceite de motor', marca='Fiat', modelo='Bravo', cilindraje='1.4', tipo_motor='',
        ))
        self.assertIsNone(cantidad_aceite_segun_motor(
            'Aceite de motor', marca='Fiat', modelo='Bravo', cilindraje='1.6', tipo_motor='T-Jet',
        ))
        self.assertIsNone(cantidad_aceite_segun_motor('Filtro de aceite', **kwargs))
        # 1 L y 8 L son el envase o un estimado; la capacidad del T-Jet es 4.
        for llegada in (1, 8):
            linea = aplicar_cantidad_aceite_motor(
                {'nombre': 'Aceite de motor', 'cantidad': llegada},
                **kwargs,
            )
            self.assertEqual(linea['cantidad'], 4)
        otro = aplicar_cantidad_aceite_motor(
            {'nombre': 'Aceite de motor', 'cantidad': 3},
            marca='Fiat',
            modelo='Bravo',
            cilindraje='1.4',
            tipo_motor='',
        )
        self.assertEqual(otro['cantidad'], 3)

    def _sembrar_cache_quote12(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            clave_cache_repuesto,
        )

        veh = dict(
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio=2010,
            tipo_motor='T-Jet',
            cilindraje='1.4',
        )
        expira = timezone.now() + timedelta(days=14)
        viejo = timezone.now() - timedelta(days=3)
        pastilla = PrecioRepuestoWeb.objects.create(
            clave=clave_cache_repuesto('Pastillas de freno delanteras', **veh),
            dominio='mundorepuestos.com',
            nombre_producto=_TITULO_PASTILLA_LISTADO,
            precio_clp=11920,
            tienda='Mundo Repuestos',
            url=_URL_PASTILLA_LISTADO,
            confianza=0.9,
            cilindraje='1.4',
            tipo_motor='T-Jet',
            expira_en=expira,
        )
        aceite = PrecioRepuestoWeb.objects.create(
            clave=clave_cache_repuesto('Aceite de motor', **veh),
            dominio='repuestos.sergioescobar.cl',
            nombre_producto='Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
            marca_repuesto='Liqui Moly',
            precio_clp=58500,
            tienda='Repuestos Sergio Escobar',
            url=_URL_ACEITE_ESCOBAR,
            confianza=0.9,
            cilindraje='1.4',
            tipo_motor='T-Jet',
            expira_en=expira,
        )
        # auto_now deja consultado_en en este instante. La relectura es para filas viejas.
        PrecioRepuestoWeb.objects.filter(pk__in=[pastilla.pk, aceite.pk]).update(consultado_en=viejo)
        pastilla.refresh_from_db()
        aceite.refresh_from_db()
        return pastilla, aceite

    def _lineas_quote12(self):
        return [
            {
                'id': 'rep-pastillas',
                'nombre': 'Pastillas de freno delanteras',
                'cantidad': 1,
                'precio_unitario_clp': 0,
                'precio_min_clp': 28000,
                'precio_max_clp': 55000,
                'certeza': 'sin_precio',
            },
            {
                'id': 'rep-aceite',
                'nombre': 'Aceite de motor',
                'cantidad': 5,
                'precio_unitario_clp': 0,
                'precio_min_clp': 8000,
                'precio_max_clp': 20000,
                'certeza': 'sin_precio',
            },
        ]

    def test_cache_rechaza_listado_y_relee_el_precio_actual(self):
        """El task no puede volver a cotizar el listado ni el $58.500 tachado."""
        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        pastilla, aceite = self._sembrar_cache_quote12()
        cot = self._crear_cotizacion_base(self._lineas_quote12())
        cot.tipo_motor = 'T-Jet'
        cot.save(update_fields=['tipo_motor'])
        consultadas: list[str] = []

        def _vacio(nombres, **kwargs):
            consultadas.extend(nombres)
            return {}

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_vacio,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._leer_html_fichas',
            side_effect=_html_cache_quote12,
        ), self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'))
        self.assertTrue(any('Pastilla' in nombre for nombre in consultadas))
        self.assertFalse(any('Aceite' in nombre for nombre in consultadas))
        cot.refresh_from_db()
        por_id = {r['id']: r for r in cot.repuestos}
        pads = por_id['rep-pastillas']
        aceite_linea = por_id['rep-aceite']
        self.assertNotIn('mundo', (pads.get('proveedor_nombre') or '').lower())
        self.assertNotIn('mundorepuestos', (pads.get('url_producto') or '').lower())
        self.assertNotEqual(pads.get('precio_unitario_clp'), 11920)
        self.assertNotIn('Envío gratis', pads.get('nombre_producto') or '')
        self.assertEqual(aceite_linea.get('precio_unitario_clp'), 13162)
        self.assertEqual(aceite_linea.get('cantidad'), 4)
        self.assertEqual(aceite_linea.get('proveedor_nombre'), 'Repuestos Sergio Escobar')
        self.assertEqual(aceite_linea.get('nombre'), 'Aceite de motor Liqui Moly')
        self.assertIn('52.650', aceite_linea.get('comentario') or '')
        self.assertNotIn('58.500', aceite_linea.get('comentario') or '')
        pastilla.refresh_from_db()
        aceite.refresh_from_db()
        self.assertLessEqual(pastilla.expira_en, timezone.now())
        self.assertEqual(aceite.precio_clp, 52650)
        texto = '\n'.join(logs.output)
        self.assertIn('motivo=listado', texto)
        self.assertIn('precio_actualizado', texto)
        self.assertIn('guardado=58500', texto)
        self.assertIn('actual=52650', texto)

    def test_enrich_sincrono_tampoco_aplica_la_cache_vieja(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        pastilla, aceite = self._sembrar_cache_quote12()
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos._leer_html_fichas',
            side_effect=_html_cache_quote12,
        ):
            out = enriquecer_repuestos_cotizacion(
                self._lineas_quote12(),
                marca_vehiculo='Fiat',
                modelo_vehiculo='Bravo',
                anio_vehiculo=2010,
                cilindraje='1.4',
                tipo_motor='T-Jet',
                taller=self.taller,
                usar_ml=False,
                usar_web=True,
            )
        por_id = {r['id']: r for r in out}
        pads = por_id['rep-pastillas']
        aceite_linea = por_id['rep-aceite']
        self.assertNotIn('mundo', (pads.get('proveedor_nombre') or '').lower())
        self.assertNotEqual(pads.get('precio_unitario_clp'), 11920)
        self.assertEqual(aceite_linea.get('precio_unitario_clp'), 13162)
        self.assertEqual(aceite_linea.get('cantidad'), 4)
        self.assertEqual(aceite_linea.get('proveedor_nombre'), 'Repuestos Sergio Escobar')
        self.assertIn('Liqui Moly', aceite_linea.get('nombre') or '')
        pastilla.refresh_from_db()
        aceite.refresh_from_db()
        self.assertLessEqual(pastilla.expira_en, timezone.now())
        self.assertEqual(aceite.precio_clp, 52650)

    def test_cache_sin_modelo_y_precio_bajo_banda_vencen_la_fila(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            clave_cache_repuesto,
            hits_cache_vigentes_para_nombres,
        )

        veh = dict(
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio=2010,
            tipo_motor='T-Jet',
            cilindraje='1.4',
        )
        expira = timezone.now() + timedelta(days=7)
        barata = PrecioRepuestoWeb.objects.create(
            clave=clave_cache_repuesto('Pastillas de freno baratas', **veh),
            dominio='tienda-barata.cl',
            nombre_producto='Juego Pastillas Freno Fiat',
            precio_clp=11920,
            tienda='Tienda Barata',
            url='https://tienda-barata.cl/pastillas-fiat',
            confianza=0.8,
            expira_en=expira,
        )
        sin_modelo = PrecioRepuestoWeb.objects.create(
            clave=clave_cache_repuesto('Pastillas de freno genericas', **veh),
            dominio='tienda-generica.cl',
            nombre_producto='Juego Pastillas Freno Fiat',
            precio_clp=45000,
            tienda='Tienda Generica',
            url='https://tienda-generica.cl/pastillas-fiat',
            confianza=0.8,
            expira_en=expira,
        )
        with self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos',
            level='INFO',
        ) as logs:
            hits = hits_cache_vigentes_para_nombres(
                ['Pastillas de freno baratas', 'Pastillas de freno genericas'],
                **veh,
                bandas_min={
                    'Pastillas de freno baratas': 28000,
                    'Pastillas de freno genericas': 28000,
                },
            )
        self.assertEqual(hits, {})
        barata.refresh_from_db()
        sin_modelo.refresh_from_db()
        self.assertLessEqual(barata.expira_en, timezone.now())
        self.assertLessEqual(sin_modelo.expira_en, timezone.now())
        texto = '\n'.join(logs.output)
        self.assertIn('motivo=precio_bajo_banda', texto)
        self.assertIn('motivo=sin_modelo', texto)

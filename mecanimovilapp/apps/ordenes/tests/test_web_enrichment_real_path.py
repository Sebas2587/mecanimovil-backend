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

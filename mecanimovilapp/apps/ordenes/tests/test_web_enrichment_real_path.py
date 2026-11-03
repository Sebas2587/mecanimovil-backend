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
            is_taller_rep=True,
        )
        self.taller = Taller.objects.create(
            nombre='Taller Test Real Path',
            telefono='+56912345678',
            es_taller_autorizado=True,
        )
        self.taller.miembros_taller.add(self.user, through_defaults={'rol': 'mandante'})
    
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
        clave_aceite = self._clave_fuzzy('Aceite de motor TISS 5W-30')
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
        with patch('mecanimovilapp.apps.ordenes.tasks.nombres_sin_cache_vigente') as mock_cache:
            mock_cache.return_value = ([], {clave_aceite: {
                'nombre_producto': 'Enfriador aceite Fiat Bravo 1.4 | Euroespecialista',
                'precio_clp': 31490,
                'tienda': 'Euroespecialista',
                'url': 'https://euroespecialista.cl/enfriador-aceite-fiat-bravo',
            }})
            
            with patch('mecanimovilapp.apps.ordenes.tasks.buscar_repuestos_web') as mock_web:
                mock_web.return_value = {}
                
                from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task
                result = buscar_precios_web_cotizacion_task(None, cot.id)
        
        self.assertTrue(result.get('ok'))
        cot.refresh_from_db()
        
        rep_enriquecido = cot.repuestos[0]
        
        # Verificación 1: NO debe tener proveedor_nombre del mismatch
        self.assertNotIn('Euroespecialista', rep_enriquecido.get('proveedor_nombre', ''))
        
        # Verificación 2: NO debe tener el nombre_producto del enfriador
        self.assertNotIn('Enfriador', rep_enriquecido.get('nombre_producto', ''))
        
        # Verificación 3: Debe quedar sin precio (rechazó el único hit)
        self.assertLessEqual(rep_enriquecido.get('precio_unitario_clp', 0), 0)

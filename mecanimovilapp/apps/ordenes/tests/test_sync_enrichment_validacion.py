"""Regresión del enriquecimiento síncrono (cotización 183).

- Un historial previo con ficha de enfriador no puede cotizar aceite de motor.
- Un listado genérico en caché web no puede cotizar pastillas.
- 'Una sola casa' solo si esa tienda cubre todas las líneas, y queda en cada una.
- El rango mostrado cubre cantidad × precio unitario.
"""
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import CotizacionCanal, PrecioRepuestoWeb
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
    clave_cache_repuesto,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    enriquecer_repuestos_cotizacion,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
    _ajustar_rangos_consistentes,
    _aplicar_seleccion_casa_repuestos,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class SyncEnrichmentValidacionTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='sync_enrich',
            email='sync-enrich@test.com',
            password='test123',
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Sync',
            telefono='+56912345678',
            estado_verificacion='aprobado',
        )

    def _cotizacion_previa(self, *, estado, repuestos):
        return CotizacionCanal.objects.create(
            taller=self.taller,
            creado_por=self.user,
            estado=estado,
            modalidad='taller',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            servicio_nombre='',
            repuestos=repuestos,
        )

    def _linea_aceite(self):
        return {
            'nombre': 'Aceite de motor',
            'cantidad': 3,
            'precio_unitario_clp': 0,
            'precio_min_clp': 9000,
            'precio_max_clp': 14000,
        }

    def test_historial_rechaza_enfriador_guardado_en_cotizacion_previa(self):
        ficha_mala = {
            'nombre': 'Aceite de motor',
            'nombre_producto': 'Enfriador aceite Fiat Bravo 1.4 | Euroespecialista',
            'cantidad': 3,
            'precio_unitario_clp': 31490,
            'proveedor_nombre': 'Euroespecialista',
            'fuente_marketplace': 'web',
            'url_producto': 'https://euroespecialista.cl/enfriador-aceite-fiat-bravo',
            'precio_estimado': True,
        }
        self._cotizacion_previa(estado='borrador', repuestos=[ficha_mala])
        self._cotizacion_previa(estado='enviada', repuestos=[ficha_mala])

        out = enriquecer_repuestos_cotizacion(
            [self._linea_aceite()],
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio_vehiculo=2010,
            taller=self.taller,
            usar_ml=False,
            usar_web=False,
        )
        aceite = out[0]
        self.assertNotIn('Euroespecialista', aceite.get('proveedor_nombre') or '')
        self.assertNotIn('Enfriador', aceite.get('nombre_producto') or '')
        self.assertEqual(aceite.get('precio_unitario_clp') or 0, 0)

    def test_historial_reusa_aceite_real(self):
        self._cotizacion_previa(
            estado='enviada',
            repuestos=[{
                'nombre': 'Aceite de motor',
                'nombre_producto': 'Aceite de motor 5W30 1L',
                'cantidad': 3,
                'precio_unitario_clp': 8900,
                'proveedor_nombre': 'Casa Aceites',
                'fuente_marketplace': 'web',
                'url_producto': 'https://casaaceites.cl/aceite-5w30',
            }],
        )
        out = enriquecer_repuestos_cotizacion(
            [self._linea_aceite()],
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio_vehiculo=2010,
            taller=self.taller,
            usar_ml=False,
            usar_web=False,
        )
        aceite = out[0]
        self.assertEqual(aceite.get('proveedor_nombre'), 'Casa Aceites')
        self.assertEqual(aceite.get('precio_unitario_clp'), 8900)
        self.assertIn('Aceite', aceite.get('nombre_producto') or '')

    def test_cache_rechaza_enfriador_y_listado_generico(self):
        expira = timezone.now() + timedelta(days=7)
        aceite_clave = clave_cache_repuesto(
            'Aceite de motor',
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio=2010,
            cilindraje='1.4',
        )
        pastilla_clave = clave_cache_repuesto(
            'Pastillas de freno',
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio=2010,
            cilindraje='1.4',
        )
        PrecioRepuestoWeb.objects.create(
            clave=aceite_clave,
            dominio='euroespecialista.cl',
            nombre_producto='Enfriador aceite Fiat Bravo 1.4 | Euroespecialista',
            precio_clp=31490,
            tienda='Euroespecialista',
            url='https://euroespecialista.cl/enfriador-aceite-fiat-bravo',
            confianza=0.8,
            cilindraje='1.4',
            expira_en=expira,
        )
        PrecioRepuestoWeb.objects.create(
            clave=pastilla_clave,
            dominio='mundorepuestos.cl',
            nombre_producto='Repuestos Fiat Bravo | Mundo Repuestos Chile',
            precio_clp=18990,
            tienda='Mundorepuestos',
            url='https://mundorepuestos.cl/repuestos-fiat-bravo',
            confianza=0.8,
            cilindraje='1.4',
            expira_en=expira,
        )

        out = enriquecer_repuestos_cotizacion(
            [
                self._linea_aceite(),
                {
                    'nombre': 'Pastillas de freno',
                    'cantidad': 1,
                    'precio_unitario_clp': 0,
                },
            ],
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio_vehiculo=2010,
            cilindraje='1.4',
            taller=self.taller,
            usar_ml=False,
            usar_web=True,
        )
        aceite, pastillas = out
        self.assertNotIn('Euroespecialista', aceite.get('proveedor_nombre') or '')
        self.assertNotIn('Enfriador', aceite.get('nombre_producto') or '')
        self.assertNotIn('Mundorepuestos', pastillas.get('proveedor_nombre') or '')
        self.assertNotIn('Mundo Repuestos', pastillas.get('nombre_producto') or '')
        self.assertEqual(pastillas.get('precio_unitario_clp') or 0, 0)

    def test_bomba_de_aceite_no_cotiza_el_lubricante_y_el_bidon_queda_por_litro(self):
        expira = timezone.now() + timedelta(days=7)
        clave = clave_cache_repuesto(
            'Aceite de motor TISS',
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio=2010,
            cilindraje='1.4',
        )
        bomba = PrecioRepuestoWeb.objects.create(
            clave=clave,
            dominio='euroespecialista.cl',
            nombre_producto='Bomba de aceite Fiat Bravo 1.4',
            precio_clp=62991,
            tienda='Euroespecialista',
            url='https://euroespecialista.cl/bomba-aceite-fiat-bravo-1-4',
            confianza=0.9,
            cilindraje='1.4',
            expira_en=expira,
        )
        PrecioRepuestoWeb.objects.create(
            clave=clave,
            dominio='todoautochile.cl',
            nombre_producto='Aceite 5W40 4L',
            precio_clp=39960,
            tienda='Todoautochile',
            url='https://todoautochile.cl/aceite-5w40-4l',
            confianza=0.8,
            cilindraje='1.4',
            expira_en=expira,
        )
        out = enriquecer_repuestos_cotizacion(
            [{
                'nombre': 'Aceite de motor TISS',
                'cantidad': 3,
                'precio_unitario_clp': 0,
                'precio_min_clp': 8000,
                'precio_max_clp': 15000,
            }],
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio_vehiculo=2010,
            cilindraje='1.4',
            taller=self.taller,
            usar_ml=False,
            usar_web=True,
        )
        aceite = out[0]
        self.assertEqual(aceite.get('proveedor_nombre'), 'Todoautochile')
        self.assertEqual(aceite.get('nombre_producto'), 'Aceite 5W40 4L')
        self.assertEqual(aceite.get('precio_unitario_clp'), 9990)
        self.assertNotIn('Bomba', aceite.get('nombre_producto') or '')
        self.assertNotEqual(aceite.get('precio_unitario_clp'), 62991)
        bomba.refresh_from_db()
        self.assertLessEqual(bomba.expira_en, timezone.now())

    def test_cobertura_parcial_no_se_reporta_como_una_sola_casa(self):
        repuestos = [
            {
                'id': 'pastillas',
                'nombre': 'Pastillas de freno',
                'cantidad': 1,
                'precio_unitario_clp': 18990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Mundorepuestos',
                'url_producto': 'https://mundorepuestos.cl/pastillas-bravo',
            },
            {
                'id': 'filtro',
                'nombre': 'Filtro de aceite',
                'cantidad': 1,
                'precio_unitario_clp': 11990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Todoautochile',
                'url_producto': 'https://todoautochile.cl/filtro-aceite',
            },
            {
                'id': 'aceite',
                'nombre': 'Aceite de motor',
                'cantidad': 3,
                'precio_unitario_clp': 31490,
            },
        ]
        out = _aplicar_seleccion_casa_repuestos(repuestos)
        for rep in out:
            self.assertFalse(rep['consolidacion_aplicada'])
            self.assertNotIn('una sola casa', (rep.get('motivo_seleccion') or '').lower())
        self.assertEqual(out[0]['proveedor_nombre'], 'Mundorepuestos')
        self.assertEqual(out[0]['casa_repuesto_nombre'], 'Mundorepuestos')
        self.assertIn('mundorepuestos', out[0]['motivo_seleccion'].lower())
        self.assertIn('mejor precio encontrado', out[0]['motivo_seleccion'].lower())
        self.assertLessEqual(len(out[0]['motivo_seleccion']), 160)
        self.assertEqual(out[1]['proveedor_nombre'], 'Todoautochile')
        self.assertIn('todoautochile', out[1]['motivo_seleccion'].lower())
        self.assertIn('no encontramos', out[2]['motivo_seleccion'].lower())
        self.assertLessEqual(len(out[2]['motivo_seleccion']), 160)

    def test_tiendas_distintas_no_se_consolidan_aunque_el_id_sea_cero(self):
        repuestos = [
            {
                'id': 'pastillas',
                'nombre': 'Pastillas de freno',
                'cantidad': 1,
                'precio_unitario_clp': 18990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Mundorepuestos',
                'proveedor_id': 0,
                'url_producto': 'https://mundorepuestos.cl/pastillas',
            },
            {
                'id': 'filtro',
                'nombre': 'Filtro de aceite',
                'cantidad': 1,
                'precio_unitario_clp': 11990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Todoautochile',
                'proveedor_id': 0,
                'url_producto': 'https://todoautochile.cl/filtro',
            },
        ]
        out = _aplicar_seleccion_casa_repuestos(repuestos)
        self.assertEqual(out[0]['proveedor_nombre'], 'Mundorepuestos')
        self.assertEqual(out[1]['proveedor_nombre'], 'Todoautochile')
        for rep in out:
            self.assertFalse(rep['consolidacion_aplicada'])
            self.assertNotIn('una sola casa', rep['motivo_seleccion'].lower())

    def test_una_sola_casa_cubre_todas_las_lineas_y_se_escribe_en_cada_una(self):
        repuestos = [
            {
                'id': 'pastillas',
                'nombre': 'Pastillas de freno',
                'cantidad': 1,
                'precio_unitario_clp': 18990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Mundorepuestos',
                'url_producto': 'https://mundorepuestos.cl/pastillas',
            },
            {
                'id': 'filtro',
                'nombre': 'Filtro de aceite',
                'cantidad': 1,
                'precio_unitario_clp': 11990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Mundorepuestos',
                'url_producto': 'https://mundorepuestos.cl/filtro',
            },
            {
                'id': 'aceite',
                'nombre': 'Aceite de motor',
                'cantidad': 3,
                'precio_unitario_clp': 31490,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Mundorepuestos',
                'url_producto': 'https://mundorepuestos.cl/aceite',
            },
        ]
        out = _aplicar_seleccion_casa_repuestos(repuestos)
        self.assertEqual(len(out), 3)
        for rep in out:
            self.assertTrue(rep['consolidacion_aplicada'])
            self.assertEqual(rep['proveedor_nombre'], 'Mundorepuestos')
            self.assertEqual(rep['casa_repuesto_nombre'], 'Mundorepuestos')
            self.assertIn('mundorepuestos', rep['motivo_seleccion'].lower())
            self.assertIn('mejor precio encontrado', rep['motivo_seleccion'].lower())
            self.assertLessEqual(len(rep['motivo_seleccion']), 160)
            self.assertNotIn('una sola casa', rep['motivo_seleccion'].lower())
        self.assertEqual(out[2]['precio_unitario_clp'], 31490)

    def test_rango_aceite_cubre_cantidad_por_unitario(self):
        out = _ajustar_rangos_consistentes([{
            'nombre': 'Aceite de motor TISS',
            'cantidad': 3,
            'precio_unitario_clp': 31490,
            'precio_min_clp': 9000,
            'precio_max_clp': 14000,
        }])
        total = 3 * 31490
        aceite = out[0]
        self.assertLessEqual(aceite['precio_min_clp'], total)
        self.assertGreaterEqual(aceite['precio_max_clp'], total)
        self.assertGreater(aceite['precio_min_clp'], 14000)

    def test_la_banda_de_un_hit_web_no_se_recalcula(self):
        # $11.920 elegido reescribía la banda de la IA a $9.536–$14.304.
        out = _ajustar_rangos_consistentes([{
            'nombre': 'Pastillas de freno delanteras',
            'cantidad': 1,
            'precio_unitario_clp': 11920,
            'precio_min_clp': 28000,
            'precio_max_clp': 55000,
            'fuente_marketplace': 'web',
            'precio_referencia_mercado': True,
        }])
        self.assertEqual(out[0]['precio_min_clp'], 28000)
        self.assertEqual(out[0]['precio_max_clp'], 55000)

    def test_sin_tienda_el_motivo_dice_que_se_busco(self):
        detalle = (
            'Se buscó "pastillas freno delanteras fiat bravo". '
            'Se descartó "Repuestos Fiat Bravo | Mundo Repuestos Chile" '
            'porque el título no es esa pieza.'
        )
        out = _aplicar_seleccion_casa_repuestos([{
            'id': 'pastillas',
            'nombre': 'Pastillas de freno cerámica delanteras',
            'cantidad': 1,
            'precio_unitario_clp': 0,
            'comentario': detalle,
        }])
        motivo = out[0]['motivo_seleccion']
        self.assertLessEqual(len(motivo), 160)
        self.assertIn('Precio estimado', motivo)
        self.assertIn('otra pieza', motivo)
        self.assertNotIn('Se buscó', motivo)
        self.assertNotIn('Repuestos Fiat Bravo', motivo)
        self.assertNotIn('http', motivo)
        self.assertNotEqual(
            motivo,
            'No se encontraron proveedores con este repuesto en stock para el vehículo',
        )

    def test_reintento_vacio_conserva_el_precio_asumido_y_el_motivo(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            anotar_busqueda_sin_ficha,
            linea_necesita_busqueda_web,
        )

        nota = {
            'motivo': 'sin_ficha',
            'detalle': (
                'Se buscó "aceite motor 5w40 fiat bravo". '
                'Se descartó "Enfriador aceite Fiat Bravo" porque el título no es esa pieza.'
            ),
        }
        with self.assertLogs(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos',
            level='INFO',
        ) as logs:
            aceite = anotar_busqueda_sin_ficha({
                'nombre': 'Aceite 5W40 sintético',
                'cantidad': 4,
                'precio_unitario_clp': 0,
                'precio_min_clp': 18000,
                'precio_max_clp': 42000,
                'certeza': 'sin_precio',
            }, nota, modelo='Bravo', anio=2010, tipo_motor='T-Jet', cilindraje='1.4')
        self.assertEqual(aceite['precio_min_clp'], 18000)
        self.assertEqual(aceite['precio_max_clp'], 42000)
        self.assertLessEqual(len(aceite['motivo_seleccion']), 160)
        self.assertIn('Precio estimado', aceite['motivo_seleccion'])
        self.assertIn('Bravo 1.4 T-Jet 2010', aceite['motivo_seleccion'])
        self.assertIn('otra pieza', aceite['motivo_seleccion'])
        self.assertNotIn('Se buscó', aceite['motivo_seleccion'])
        self.assertNotIn('Enfriador', aceite['comentario'])
        self.assertNotIn('5w40', aceite['motivo_seleccion'].lower())
        self.assertIn('Enfriador', '\n'.join(logs.output))
        self.assertIn('5w40', '\n'.join(logs.output).lower())

        pastillas = {
            'nombre': 'Pastillas de freno cerámica delanteras',
            'precio_unitario_clp': 70000,
            'certeza': 'asumido',
            'precio_estimado': True,
        }
        self.assertTrue(linea_necesita_busqueda_web(pastillas))
        pastillas = anotar_busqueda_sin_ficha(pastillas, {
            'motivo': 'sin_ficha',
            'detalle': 'Se buscó "pastillas freno delanteras fiat bravo". Sin ficha.',
        })
        self.assertEqual(pastillas['precio_unitario_clp'], 70000)
        self.assertIn('Precio estimado', pastillas['motivo_seleccion'])
        self.assertNotIn('Se buscó', pastillas['motivo_seleccion'])
        self.assertLessEqual(len(pastillas['motivo_seleccion']), 160)

        out = _aplicar_seleccion_casa_repuestos([pastillas, aceite])
        for rep in out:
            self.assertIn('Precio estimado', rep['motivo_seleccion'])
            self.assertNotIn('Se buscó', rep['motivo_seleccion'])
            self.assertLessEqual(len(rep['motivo_seleccion']), 160)
            self.assertNotEqual(
                rep['motivo_seleccion'],
                'No se encontraron proveedores con este repuesto en stock para el vehículo',
            )

    def test_cache_de_bidon_4l_se_guarda_como_precio_por_litro(self):
        expira = timezone.now() + timedelta(days=7)
        clave = clave_cache_repuesto(
            'Aceite 5W40 sintético',
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio=2010,
            cilindraje='1.4',
        )
        PrecioRepuestoWeb.objects.create(
            clave=clave,
            dominio='todoautochile.cl',
            nombre_producto='Aceite 5W40 4L',
            precio_clp=39960,
            tienda='Todoautochile',
            url='https://todoautochile.cl/aceite-5w40-4l',
            confianza=0.8,
            cilindraje='1.4',
            expira_en=expira,
        )
        out = enriquecer_repuestos_cotizacion(
            [{
                'nombre': 'Aceite 5W40 sintético',
                'cantidad': 3,
                'precio_unitario_clp': 0,
            }],
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            anio_vehiculo=2010,
            cilindraje='1.4',
            taller=self.taller,
            usar_ml=False,
            usar_web=True,
        )
        aceite = out[0]
        self.assertEqual(aceite.get('proveedor_nombre'), 'Todoautochile')
        self.assertEqual(aceite.get('precio_unitario_clp'), 9990)
        self.assertIn('litro', (aceite.get('comentario') or '').lower())

    def test_mejor_hit_no_prueba_el_aceite_contra_las_pastillas(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            _mejor_hit,
        )

        log = logging.getLogger(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos',
        )
        candidatos = [
            {
                'clave': 'pastillas freno delanteras',
                'nombre_producto': 'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
                'fuente_marketplace': 'web',
                'confianza': 0.9,
                'precio_unitario_clp': 39960,
                'url_producto': 'https://www.mundorepuestos.cl/producto/aceite-liqui-moly-5w40-4l',
            },
            {
                'clave': 'pastillas freno delanteras fiat bravo',
                'nombre_producto': 'Pastillas de Freno Delanteras Fiat Bravo',
                'fuente_marketplace': 'web',
                'confianza': 0.8,
                'precio_unitario_clp': 28990,
                'url_producto': 'https://frenosvergara.shop/products/pastillas-fiat-bravo',
            },
        ]
        with self.assertLogs(log.name, level='INFO') as logs:
            log.info('sentinel')
            hit = _mejor_hit('Pastillas de freno delanteras', candidatos, min_score=40)
        self.assertIn('Pastillas', hit['nombre_producto'])
        self.assertNotIn('Liqui', hit['nombre_producto'])
        self.assertNotIn('listado_generico_rechazado', '\n'.join(logs.output))

    def test_historial_no_intenta_el_aceite_sobre_las_pastillas(self):
        self._cotizacion_previa(
            estado='enviada',
            repuestos=[{
                'nombre': 'Pastillas de freno delanteras',
                'nombre_producto': 'Aceite Para Motor Liqui Moly Sintético 5w-40 4L',
                'cantidad': 1,
                'precio_unitario_clp': 39960,
                'proveedor_nombre': 'Mundo Repuestos',
                'fuente_marketplace': 'web',
                'url_producto': 'https://www.mundorepuestos.cl/producto/aceite-liqui-moly-5w40-4l',
            }],
        )
        log = logging.getLogger(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos',
        )
        with self.assertLogs(log.name, level='INFO') as logs:
            log.info('sentinel')
            out = enriquecer_repuestos_cotizacion(
                [{
                    'nombre': 'Pastillas de freno delanteras',
                    'cantidad': 1,
                    'precio_unitario_clp': 0,
                }],
                marca_vehiculo='Fiat',
                modelo_vehiculo='Bravo',
                anio_vehiculo=2010,
                taller=self.taller,
                usar_ml=False,
                usar_web=False,
            )
        pastillas = out[0]
        self.assertNotIn('Liqui', pastillas.get('nombre_producto') or '')
        self.assertNotIn('Mundo', pastillas.get('proveedor_nombre') or '')
        self.assertEqual(pastillas.get('precio_unitario_clp') or 0, 0)
        self.assertNotIn('listado_generico_rechazado', '\n'.join(logs.output))

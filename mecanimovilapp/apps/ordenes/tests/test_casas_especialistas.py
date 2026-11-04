"""Casas especialistas, prioridad de taller y orden de compra."""
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from pypdf import PdfReader
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.casas_especialistas import (
    PERFILES,
    es_solo_en_linea,
    nota_especialista,
    prioridad_candidato,
    sucursal_para,
)
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
    _consultas_sitio_especialista,
    _motivo_calidad_pastilla,
    _ordenar_candidatos,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    sanear_notas_linea,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
    _aplicar_seleccion_casa_repuestos,
)
from mecanimovilapp.apps.ordenes.services.orden_compra_pdf import generar_pdf_orden_compra
from mecanimovilapp.apps.usuarios.models import DireccionUsuario, Taller, TallerDireccion
from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import _origen_precio

User = get_user_model()


def _texto_pdf(pdf: bytes) -> str:
    reader = PdfReader(BytesIO(pdf))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


class CasasEspecialistasTests(TestCase):
    def test_las_casas_pedidas_existen_y_no_se_inventa_precio(self):
        por_nombre = {p['nombre']: p for p in PERFILES}
        indra = por_nombre['Indra']
        self.assertIn('fiat', indra['marcas'])
        self.assertTrue(indra['fisica'])
        self.assertFalse(indra['catalogo_online'])
        self.assertIn('Lira 664', indra['sucursales'][0]['direccion'])
        self.assertTrue(indra['telefono'])

        adriazola = por_nombre['Adriazola']
        self.assertTrue(adriazola['catalogo_online'])
        self.assertIn('peugeot', adriazola['marcas'])
        self.assertIn('citroen', adriazola['marcas'])
        self.assertEqual(adriazola['telefono'], '+56 2 2350 3300')

        comauto = por_nombre['Comauto']
        self.assertFalse(comauto['catalogo_online'])
        self.assertEqual(comauto['sucursales'][0]['direccion'], 'Av. 10 de Julio 370')
        self.assertEqual(por_nombre['Casa Citroën']['sucursales'][0]['direccion'], 'Av. 10 de Julio 380')
        self.assertTrue(por_nombre['Vimae']['fisica'])
        self.assertIn('kia', por_nombre['Ciper']['marcas'])

    def test_peugeot_consulta_el_sitio_de_adriazola_e_indra_no_tiene_catalogo(self):
        peugeot = _consultas_sitio_especialista(
            'filtro de aceite', marca='Peugeot', modelo='308', cilindraje='1.6',
        )
        self.assertTrue(any('site:adriazolarepuestos.com' in q for q in peugeot))
        fiat = _consultas_sitio_especialista(
            'filtro de aceite', marca='Fiat', modelo='Bravo', cilindraje='1.4',
        )
        self.assertFalse(any('indra.cl' in q for q in fiat))

    def test_la_especialista_gana_a_mercado_libre_si_la_ficha_sirve(self):
        self.assertLess(
            prioridad_candidato('https://indra.cl/producto/pastilla-original', 'Pastilla original Fiat', 'Fiat'),
            prioridad_candidato('https://articulo.mercadolibre.cl/MLC-1', 'Pastilla Fiat', 'Fiat'),
        )
        self.assertTrue(es_solo_en_linea('Mercado Libre', 'https://articulo.mercadolibre.cl/MLC-1'))
        ordenados = _ordenar_candidatos(
            [
                {
                    'url': 'https://articulo.mercadolibre.cl/MLC-123',
                    'title': 'Pastillas freno Fiat Bravo',
                    'content': 'Pastillas freno Fiat Bravo. Precio: $24990',
                },
                {
                    'url': 'https://indra.cl/producto/pastillas-bravo',
                    'title': 'Pastillas freno Fiat Bravo original',
                    'content': 'Pastillas freno Fiat Bravo original. Precio: $28990',
                },
            ],
            nombre_linea='Pastillas de freno',
            modelo='Bravo',
            marca='Fiat',
        )
        self.assertIn('indra.cl', ordenados[0]['url'])

    def test_la_compuerta_de_anio_sigue_botando_la_ficha_de_indra(self):
        motivo = _motivo_calidad_pastilla(
            {
                'url': 'https://indra.cl/producto/bujia-1995',
                'title': 'Bujía Fiat Bravo 1.4 1995-2001',
                'content': 'Bujía Fiat Bravo 1.4 1995-2001. Precio: $8000',
                'ficha_leida': True,
            },
            nombre='Bujías',
            modelo='Bravo',
            tipo_motor='T-Jet',
            anio=2010,
            cilindraje='1.4',
        )
        self.assertEqual(motivo, 'anio_incompatible')

    def test_fiat_sin_casa_fisica_recomienda_indra_sin_inventarle_el_precio(self):
        linea = _aplicar_seleccion_casa_repuestos([{
            'id': 'filtro',
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 4990,
            'fuente_marketplace': 'web',
            'proveedor_nombre': 'Todoautochile',
            'url_producto': 'https://todoautochile.cl/filtro',
        }], marca_vehiculo='Fiat', modelo_vehiculo='Bravo')[0]
        self.assertEqual(linea['casa_repuesto_nombre'], 'Indra')
        self.assertEqual(linea['proveedor_nombre'], 'TodoAuto')
        self.assertTrue(linea['precio_a_consultar'])
        self.assertEqual(linea['precio_unitario_clp'], 4990)
        self.assertEqual(linea['referencia_tienda'], 'TodoAuto')
        self.assertEqual(linea['precio_referencia_clp'], 4990)
        self.assertEqual(
            linea['motivo_seleccion'],
            'Indra (especialista Fiat): consulta disponibilidad y precio. Referencia: TodoAuto $4.990.',
        )
        self.assertLessEqual(len(linea['motivo_seleccion']), 160)
        self.assertIn('Lira 664', linea['casa_sucursal'])

    def test_el_historial_no_es_la_casa_de_las_pastillas(self):
        linea = _aplicar_seleccion_casa_repuestos([{
            'id': 'pastillas',
            'nombre': 'Pastillas de freno',
            'cantidad': 1,
            'precio_unitario_clp': 40000,
            'fuente_marketplace': 'historial',
            'proveedor_nombre': 'Historial del taller',
            'casa_repuesto_nombre': 'Historial del taller',
            'fuentes_detalle': [{
                'fuente': 'historial',
                'tienda': 'Historial del taller',
                'precio_clp': 40000,
            }],
        }], marca_vehiculo='Fiat', modelo_vehiculo='Bravo')[0]
        self.assertEqual(linea['casa_repuesto_nombre'], 'Indra')
        self.assertEqual(linea['proveedor_nombre'], 'Indra')
        self.assertEqual(linea['precio_unitario_clp'], 40000)
        self.assertEqual(linea['referencia_tienda'], 'historial del taller')
        self.assertEqual(linea['precio_referencia_clp'], 40000)
        self.assertTrue(linea['precio_a_consultar'])
        self.assertIn('Referencia: historial del taller $40.000', linea['motivo_seleccion'])
        self.assertNotEqual(linea['fuentes_detalle'][0]['tienda'], 'Historial del taller')

    def test_cerca_de_la_florida_elige_esa_sucursal(self):
        user = User.objects.create_user(username='taller_florida', password='x', email='f@test.cl')
        taller = Taller.objects.create(usuario=user, nombre='Taller Florida', telefono='1')
        TallerDireccion.objects.create(
            taller=taller, calle='Walker Martínez', numero='100',
            comuna='La Florida', ciudad='Santiago', region='Metropolitana',
        )
        perfil = next(p for p in PERFILES if p['nombre'] == 'Indra')
        sucursal = sucursal_para(perfil, 'Fiat', 'La Florida')
        self.assertIn('Vicuña Mackenna', sucursal['direccion'])
        linea = _aplicar_seleccion_casa_repuestos([{
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 0,
            'fuente_marketplace': 'estimado',
        }], marca_vehiculo='Fiat', taller=taller)[0]
        self.assertIn('Vicuña Mackenna', linea['casa_sucursal'])

    def test_la_florida_en_la_calle_gana_a_santiago(self):
        user = User.objects.create_user(username='taller_kennedy', password='x', email='k@test.cl')
        taller = Taller.objects.create(usuario=user, nombre='MecaniMovil', telefono='1')
        TallerDireccion.objects.create(
            taller=taller,
            calle='John Kennedy 709, La Florida',
            numero='709',
            comuna='Santiago',
            ciudad='Santiago',
            region='Metropolitana',
        )
        linea = _aplicar_seleccion_casa_repuestos([{
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 0,
            'fuente_marketplace': 'estimado',
        }], marca_vehiculo='FIAT', taller=taller)[0]
        self.assertIn('Vicuña Mackenna 8580', linea['casa_sucursal'])
        self.assertIn('La Florida', linea['casa_sucursal'])
        self.assertNotIn('Lira', linea['casa_sucursal'])
        self.assertIn('Fiat', linea['motivo_seleccion'])
        self.assertNotIn('FIAT', linea['motivo_seleccion'])

    def test_sin_ficha_cada_linea_conserva_su_referencia(self):
        out = _aplicar_seleccion_casa_repuestos([
            {
                'nombre': 'Pastillas de freno delanteras',
                'cantidad': 1,
                'precio_unitario_clp': 21390,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Lider',
                'url_producto': 'https://www.lider.cl/pastillas',
            },
            {
                'nombre': 'Filtro de aire',
                'cantidad': 1,
                'precio_unitario_clp': 15000,
                'fuente_marketplace': 'estimado',
            },
        ], marca_vehiculo='FIAT')
        self.assertEqual(
            out[0]['motivo_seleccion'],
            'Indra (especialista Fiat): consulta disponibilidad y precio. Referencia: Lider $21.390.',
        )
        self.assertEqual(
            out[1]['motivo_seleccion'],
            'Indra (especialista Fiat): consulta disponibilidad y precio.',
        )
        self.assertNotIn('tiene todos', out[0]['motivo_seleccion'].lower())
        self.assertNotIn('tiene todos', out[1]['motivo_seleccion'].lower())
        self.assertLessEqual(len(out[0]['motivo_seleccion']), 160)

    def test_la_especialista_no_sube_la_bujia_asumida(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio import (
            aplicar_techo_ia_si_falta_unitario,
        )

        asumida = aplicar_techo_ia_si_falta_unitario({
            'nombre': 'Bujías iridium',
            'cantidad': 4,
            'precio_unitario_clp': 15000,
            'precio_min_clp': 8000,
            'precio_max_clp': 11250,
        })
        self.assertEqual(asumida['precio_unitario_clp'], 11250)
        juego = aplicar_techo_ia_si_falta_unitario({
            'nombre': 'Bujías iridium',
            'cantidad': 4,
            'precio_unitario_clp': 60000,
            'precio_min_clp': 8000,
            'precio_max_clp': 45000,
        })
        self.assertEqual(juego['precio_unitario_clp'], 11250)
        linea = _aplicar_seleccion_casa_repuestos(
            [asumida], marca_vehiculo='Fiat',
        )[0]
        self.assertEqual(linea['precio_unitario_clp'], 11250)
        self.assertTrue(linea['precio_a_consultar'])
        self.assertEqual(linea['casa_repuesto_nombre'], 'Indra')

    def test_dos_fichas_de_indra_dicen_que_tiene_todo(self):
        nota = nota_especialista('Indra', 'Fiat', cubre_todo=True, a_consultar=False)
        self.assertEqual(
            nota,
            'Indra: especialista Fiat, tiene todos los repuestos de esta cotización.',
        )
        out = _aplicar_seleccion_casa_repuestos([
            {
                'nombre': 'Filtro de aceite',
                'cantidad': 1,
                'precio_unitario_clp': 4990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Indra',
                'url_producto': 'https://indra.cl/producto/filtro',
            },
            {
                'nombre': 'Pastillas de freno',
                'cantidad': 1,
                'precio_unitario_clp': 28990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Indra',
                'url_producto': 'https://indra.cl/producto/pastillas',
            },
        ], marca_vehiculo='Fiat')
        for linea in out:
            self.assertEqual(linea['casa_repuesto_nombre'], 'Indra')
            self.assertFalse(linea['precio_a_consultar'])
            self.assertEqual(
                linea['motivo_seleccion'],
                'Indra: especialista Fiat, tiene todos los repuestos de esta cotización.',
            )
            self.assertLessEqual(len(linea['motivo_seleccion']), 160)

    def test_solo_en_linea_cuando_la_marca_no_tiene_especialista(self):
        linea = _aplicar_seleccion_casa_repuestos([{
            'nombre': 'Filtro de polen',
            'cantidad': 1,
            'precio_unitario_clp': 8990,
            'fuente_marketplace': 'mercadolibre',
            'proveedor_nombre': 'Mercado Libre',
            'url_producto': 'https://articulo.mercadolibre.cl/MLC-9',
        }], marca_vehiculo='Tesla')[0]
        self.assertIn('solo en línea', linea['motivo_seleccion'])
        self.assertIn('Mercado Libre', linea['motivo_seleccion'])

    def test_el_origen_no_muestra_el_slug(self):
        linea = sanear_notas_linea({
            'nombre': 'Filtro de aceite',
            'proveedor_nombre': 'TodoAuto',
            'fuente_marketplace': 'web',
            'fuentes_detalle': [{
                'fuente': 'web',
                'tienda': 'Todoautochile',
                'dominio': 'todoautochile.cl',
                'precio_clp': 4990,
                'url': 'https://todoautochile.cl/filtro',
            }],
        })
        self.assertEqual(linea['fuentes_detalle'][0]['tienda'], 'TodoAuto')
        self.assertNotIn('todoautochile', linea['fuentes_detalle'][0]['tienda'].lower())
        origen = _origen_precio({
            'fuente_marketplace': 'web',
            'proveedor_nombre': 'Todoautochile',
            'precio_unitario_clp': 4990,
        }, False)
        self.assertEqual(origen, 'Precio en TodoAuto.')
        self.assertNotIn('Todoautochile', origen)


class OrdenCompraPdfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='taller_oc', password='test123', email='oc@mecanimovil.test',
        )
        self.taller = Taller.objects.create(
            usuario=self.user, nombre='Taller Bravo', telefono='900000009',
            estado_verificacion='aprobado', verificado=True,
        )
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            vehiculo_patente='CJXP98',
            vehiculo_vin='ZFA19800001234567',
            tipo_motor='T-Jet',
            vehiculo_cilindraje='1.4',
            servicio_nombre='Mantención',
            mano_obra_clp=80000,
            total_clp=150000,
            token='tok-orden-compra',
            enviada_en=timezone.now(),
            repuestos=[
                {
                    'nombre': 'Filtro de aceite',
                    'cantidad': 1,
                    'especificacion': 'OEM 71751176',
                    'codigo_parte': '71751176',
                    'precio_unitario_clp': 4990,
                    'precio_a_consultar': True,
                    'precio_referencia_clp': 4990,
                    'referencia_tienda': 'TodoAuto',
                    'casa_repuesto_nombre': 'Indra',
                    'casa_sucursal': 'Lira 664, Santiago',
                    'casa_telefono': '+56 2 2783 8300',
                    'precio_min_clp': 4000,
                    'precio_max_clp': 9000,
                },
                {
                    'nombre': 'Aceite de motor',
                    'cantidad': 4,
                    'especificacion': '5W40 sintético',
                    'precio_unitario_clp': 9990,
                    'casa_repuesto_nombre': 'Indra',
                    'casa_sucursal': 'Lira 664, Santiago',
                    'casa_telefono': '+56 2 2783 8300',
                },
            ],
        )

    def test_el_pdf_no_lleva_mano_de_obra_ni_el_margen(self):
        pdf = generar_pdf_orden_compra(self.cot)
        self.assertTrue(pdf.startswith(b'%PDF'))
        texto = _texto_pdf(pdf)
        self.assertIn('Orden de compra de repuestos', texto)
        self.assertIn('Taller Bravo', texto)
        self.assertIn('CJXP98', texto)
        self.assertIn('ZFA19800001234567', texto)
        self.assertIn('Filtro de aceite', texto)
        self.assertIn('5W40', texto)
        self.assertIn('71751176', texto)
        self.assertIn('Indra', texto)
        self.assertIn('Lira 664, Santiago', texto)
        self.assertIn('+56 2 2783 8300', texto)
        self.assertIn('A consultar', texto)
        self.assertIn('TodoAuto', texto)
        self.assertNotIn('Mano de obra', texto)
        self.assertNotIn('margen', texto.lower())
        self.assertNotIn('80.000', texto)
        self.assertNotIn('150.000', texto)

    def test_el_historial_no_abre_otro_grupo_ni_repite_la_sucursal(self):
        TallerDireccion.objects.create(
            taller=self.taller,
            calle='John Kennedy',
            numero='709',
            comuna='La Florida',
            ciudad='Santiago',
            region='Metropolitana',
        )
        self.cot.repuestos = [
            {
                'nombre': 'Pastillas de freno',
                'cantidad': 1,
                'precio_unitario_clp': 40000,
                'fuente_marketplace': 'historial',
                'proveedor_nombre': 'Historial del taller',
                'casa_repuesto_nombre': 'Historial del taller',
                'casa_sucursal': 'Av. Vicuña Mackenna 8580, La Florida',
                'casa_telefono': '+56 2 2783 8300',
            },
            {
                'nombre': 'Aceite de motor',
                'cantidad': 4,
                'precio_unitario_clp': 9990,
                'casa_repuesto_nombre': 'Indra',
                'casa_sucursal': 'Av. Vicuña Mackenna 8580, La Florida',
                'casa_telefono': '+56 2 2783 8300',
            },
        ]
        self.cot.save(update_fields=['repuestos'])
        texto = _texto_pdf(generar_pdf_orden_compra(self.cot))
        self.assertNotIn('Historial del taller', texto)
        self.assertIn('historial del taller', texto)
        self.assertIn('Pastillas de freno', texto)
        self.assertIn('Indra', texto)
        self.assertIn('A consultar', texto)
        self.assertIn('40.000', texto)
        self.assertEqual(texto.count('Vicuña Mackenna 8580'), 1)
        self.assertEqual(texto.count('La Florida'), 1)

    def test_el_pdf_usa_la_sucursal_de_la_florida(self):
        TallerDireccion.objects.create(
            taller=self.taller,
            calle='John Kennedy',
            numero='709',
            comuna='La Florida',
            ciudad='Santiago',
            region='Metropolitana',
        )
        texto = _texto_pdf(generar_pdf_orden_compra(self.cot))
        self.assertIn('Av. Vicuña Mackenna 8580, La Florida', texto)
        self.assertNotIn('Lira 664', texto)

    def test_el_taller_descarga_el_pdf(self):
        client = APIClient()
        client.force_authenticate(self.user)
        res = client.get(f'/api/ordenes/cotizaciones-canal/{self.cot.pk}/orden-compra-pdf/')
        self.assertEqual(res.status_code, 200, getattr(res, 'data', res.content[:200]))
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('CJXP98', res['Content-Disposition'])
        self.assertTrue(res.content.startswith(b'%PDF'))


class TarifaManoObraTests(TestCase):
    def test_la_tarifa_del_taller_llena_la_faena_que_el_modelo_no_cotizo(self):
        from decimal import Decimal

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            normalizar_cotizacion_ia,
        )
        from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio

        user = User.objects.create_user(username='taller_mo', password='x', email='mo@test.cl')
        taller = Taller.objects.create(usuario=user, nombre='MecaniMovil', telefono='1')
        servicio = Servicio.objects.create(nombre='Cambio de aceite y filtro de aceite')
        OfertaServicio.objects.bulk_create([
            OfertaServicio(
                tipo_proveedor='taller',
                taller=taller,
                servicio=servicio,
                disponible=True,
                precio_sin_repuestos=Decimal('28000'),
                precio_con_repuestos=Decimal('45000'),
            ),
        ])
        pedido = (
            'Cambio de pastillas de freno delanteras, aceite y filtro de aceite, '
            'bujías y filtro de aire'
        )
        out = normalizar_cotizacion_ia(
            {
                'servicio_nombre': pedido,
                'mano_obra_clp': 50000,
                'servicios_lineas': [
                    {'nombre': 'Cambio de pastillas de freno delanteras', 'monto_clp': 35000},
                    {'nombre': 'Cambio de filtro de aire', 'monto_clp': 15000},
                ],
                'repuestos': [],
            },
            {'servicio_nombre': pedido, 'taller': taller, 'marca': 'Fiat', 'modelo': 'Bravo'},
        )
        montos = {lin['nombre']: lin['monto_clp'] for lin in out['servicios_lineas']}
        self.assertEqual(montos['Cambio de aceite y filtro de aceite'], 28000)
        self.assertTrue(all(monto > 0 for monto in montos.values()))
        self.assertEqual(out['mano_obra_clp'], sum(montos.values()))
        self.assertGreater(out['mano_obra_clp'], 50000)


_NOTA_VIEJA = 'Indra: especialista FIAT, tiene todos los repuestos. Precio a consultar.'
_NOTA_LIDER = (
    'Indra (especialista Fiat): consulta disponibilidad y precio. '
    'Referencia: Lider $21.390.'
)
_NOTA_SIN_REF = 'Indra (especialista Fiat): consulta disponibilidad y precio.'


class NotaViejaYSucursalEnLaTareaTests(TestCase):
    """La tarea real y la lectura reescriben la frase vieja y la sucursal."""

    def test_el_saneo_reescribe_la_frase_vieja_con_la_referencia_de_la_linea(self):
        linea = sanear_notas_linea({
            'nombre': 'Pastillas de freno',
            'casa_repuesto_nombre': 'Indra',
            'proveedor_nombre': 'Lider',
            'precio_unitario_clp': 21390,
            'precio_a_consultar': True,
            'referencia_tienda': 'Lider',
            'precio_referencia_clp': 21390,
            'fuente_marketplace': 'web',
            'motivo_seleccion': _NOTA_VIEJA,
            'comentario': _NOTA_VIEJA,
        }, marca='FIAT')
        self.assertEqual(linea['motivo_seleccion'], _NOTA_LIDER)
        self.assertEqual(linea['comentario'], _NOTA_LIDER)
        self.assertNotIn('tiene todos', linea['motivo_seleccion'].lower())
        self.assertNotIn('FIAT', linea['motivo_seleccion'])
        self.assertLessEqual(len(linea['motivo_seleccion']), 160)

    def test_sin_tienda_validada_no_inventa_referencia(self):
        linea = sanear_notas_linea({
            'nombre': 'Filtro de aire',
            'casa_repuesto_nombre': 'Indra',
            'precio_unitario_clp': 0,
            'precio_a_consultar': True,
            'fuente_marketplace': 'estimado',
            'motivo_seleccion': _NOTA_VIEJA,
            'comentario': _NOTA_VIEJA,
        }, marca='FIAT')
        self.assertEqual(linea['motivo_seleccion'], _NOTA_SIN_REF)
        self.assertNotIn('Referencia', linea['motivo_seleccion'])

    def test_la_tarea_y_el_pdf_dejan_la_consulta_y_la_florida(self):
        user = User.objects.create_user(
            username='mecanimovil_209', password='x', email='m209@test.cl',
        )
        user.direccion = 'Oficina virtual, Providencia, Santiago'
        user.save(update_fields=['direccion'])
        taller = Taller.objects.create(usuario=user, nombre='Mecanimovil', telefono='1')
        TallerDireccion.objects.create(
            taller=taller,
            calle='',
            numero='',
            comuna='',
            ciudad='Santiago',
            region='Metropolitana',
        )
        DireccionUsuario.objects.create(
            usuario=user,
            direccion='John Kennedy 709, La Florida',
            etiqueta='Taller',
            es_principal=True,
        )
        vieja = _NOTA_VIEJA
        lineas = [
            {
                'id': 'pastillas',
                'nombre': 'Pastillas de freno delanteras',
                'cantidad': 1,
                'precio_unitario_clp': 21390,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Lider',
                'url_producto': 'https://www.lider.cl/pastillas-fiat',
                'motivo_seleccion': vieja,
                'comentario': vieja,
                'casa_sucursal': 'Avenida Brasil 28, Santiago',
            },
            {
                'id': 'aceite',
                'nombre': 'Aceite de motor',
                'cantidad': 4,
                'precio_unitario_clp': 0,
                'fuente_marketplace': 'estimado',
                'motivo_seleccion': vieja,
                'comentario': vieja,
                'casa_sucursal': 'Avenida Brasil 28, Santiago',
            },
            {
                'id': 'filtro-aceite',
                'nombre': 'Filtro de aceite',
                'cantidad': 1,
                'precio_unitario_clp': 4990,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'Todoautochile',
                'url_producto': 'https://todoautochile.cl/filtro',
                'motivo_seleccion': vieja,
                'comentario': vieja,
                'casa_sucursal': 'Avenida Brasil 28, Santiago',
            },
            {
                'id': 'bujias',
                'nombre': 'Bujías',
                'cantidad': 4,
                'precio_unitario_clp': 0,
                'fuente_marketplace': 'estimado',
                'motivo_seleccion': vieja,
                'comentario': vieja,
                'casa_sucursal': 'Avenida Brasil 28, Santiago',
            },
            {
                'id': 'filtro-aire',
                'nombre': 'Filtro de aire',
                'cantidad': 1,
                'precio_unitario_clp': 0,
                'fuente_marketplace': 'estimado',
                'motivo_seleccion': vieja,
                'comentario': vieja,
                'casa_sucursal': 'Avenida Brasil 28, Santiago',
            },
        ]
        cot = CotizacionCanal.objects.create(
            taller=taller,
            creado_por=user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='FIAT',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            servicio_nombre='Pastillas, aceite, bujías',
            repuestos=lineas,
            metadata={'busqueda_web_estado': 'pendiente'},
        )

        def _sin_fichas(nombres, **kwargs):
            avisos = kwargs.get('avisos')
            if isinstance(avisos, dict):
                for nombre in nombres:
                    avisos[nombre] = {'motivo': 'sin_ficha', 'detalle': 'Sin ficha de Indra.'}
            return {}

        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_sin_fichas,
        ):
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'))
        cot.refresh_from_db()
        por_id = {r['id']: r for r in cot.repuestos}
        self.assertEqual(por_id['pastillas']['motivo_seleccion'], _NOTA_LIDER)
        self.assertEqual(por_id['pastillas']['comentario'], _NOTA_LIDER)
        self.assertEqual(
            por_id['filtro-aceite']['motivo_seleccion'],
            'Indra (especialista Fiat): consulta disponibilidad y precio. '
            'Referencia: TodoAuto $4.990.',
        )
        for rid in ('aceite', 'bujias', 'filtro-aire'):
            self.assertEqual(por_id[rid]['motivo_seleccion'], _NOTA_SIN_REF)
            self.assertNotIn('Referencia', por_id[rid]['motivo_seleccion'])
        for linea in cot.repuestos:
            self.assertNotIn('tiene todos', linea['motivo_seleccion'].lower())
            self.assertNotIn('FIAT', linea['motivo_seleccion'])
            self.assertIn('Vicuña Mackenna 8580', linea['casa_sucursal'])
            self.assertNotIn('Brasil', linea['casa_sucursal'])

        texto = _texto_pdf(generar_pdf_orden_compra(cot))
        self.assertIn('Av. Vicuña Mackenna 8580, La Florida', texto)
        self.assertNotIn('Avenida Brasil 28', texto)
        self.assertNotIn('tiene todos', texto.lower())

        from mecanimovilapp.apps.ordenes.serializers_cotizacion_canal import (
            CotizacionCanalSerializer,
        )

        cot.repuestos = [
            {**r, 'motivo_seleccion': vieja, 'comentario': vieja}
            for r in cot.repuestos
        ]
        cot.save(update_fields=['repuestos'])
        data = CotizacionCanalSerializer(cot).data
        leida = next(r for r in data['repuestos'] if r['id'] == 'pastillas')
        self.assertEqual(leida['motivo_seleccion'], _NOTA_LIDER)
        self.assertNotIn('FIAT', leida['motivo_seleccion'])

    def test_solo_santiago_usa_lira_y_no_brasil(self):
        user = User.objects.create_user(
            username='taller_solo_santiago', password='x', email='s@test.cl',
        )
        user.direccion = 'Oficina virtual, Providencia, Santiago'
        user.save(update_fields=['direccion'])
        taller = Taller.objects.create(usuario=user, nombre='Mecanimovil', telefono='1')
        TallerDireccion.objects.create(
            taller=taller,
            calle='',
            numero='',
            comuna='',
            ciudad='Santiago',
            region='Metropolitana',
        )
        perfil = next(p for p in PERFILES if p['nombre'] == 'Indra')
        sucursal = sucursal_para(perfil, 'Fiat', 'Santiago')
        self.assertEqual(sucursal['direccion'], 'Lira 664')
        cot = CotizacionCanal.objects.create(
            taller=taller,
            creado_por=user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='FIAT',
            vehiculo_modelo='Bravo',
            repuestos=[{
                'nombre': 'Filtro de aceite',
                'cantidad': 1,
                'casa_repuesto_nombre': 'Indra',
                'casa_sucursal': 'Avenida Brasil 28, Santiago',
                'precio_a_consultar': True,
            }],
        )
        texto = _texto_pdf(generar_pdf_orden_compra(cot))
        self.assertIn('Lira 664, Santiago', texto)
        self.assertNotIn('Avenida Brasil 28', texto)


class ReferenciaBujiaEnLaTareaTests(TestCase):
    """La re-búsqueda al abrir no cita ni pega un hit de bujía que no pasó la banda."""

    def _cot(self, user, taller, repuestos):
        return CotizacionCanal.objects.create(
            taller=taller,
            creado_por=user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='FIAT',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            vehiculo_cilindraje='1.4',
            tipo_motor='T-Jet',
            servicio_nombre='Cambio de bujías',
            repuestos=repuestos,
            metadata={'busqueda_web_estado': 'pendiente'},
        )

    def _linea(self, **extra):
        base = {
            'id': 'bujias',
            'nombre': 'Bujías',
            'cantidad': 4,
            'precio_unitario_clp': 12000,
            'precio_min_clp': 8000,
            'precio_max_clp': 12000,
            'certeza': 'asumido',
            'precio_estimado': True,
            'fuente_marketplace': 'estimado',
            'precio_a_consultar': True,
            'referencia_tienda': 'Lider',
            'precio_referencia_clp': 28432,
            'motivo_seleccion': (
                'Indra (especialista Fiat): consulta disponibilidad y precio. '
                'Referencia: Lider $28.432.'
            ),
            'comentario': (
                'Indra (especialista Fiat): consulta disponibilidad y precio. '
                'Referencia: Lider $28.432.'
            ),
        }
        base.update(extra)
        return base

    def test_la_banda_rechaza_la_bujia_suelta_y_parte_el_juego(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _motivo_calidad_pastilla,
            monto_por_unidad_citable,
        )

        suelta = {
            'title': 'Bujía Iridium Fiat Bravo 1.4 T-Jet',
            'url': 'https://www.lider.cl/bujia-iridium-bravo',
            'content': 'Bujía Iridium Fiat Bravo 1.4 T-Jet. Precio $ 28.432',
            'ficha_leida': True,
            'precio_snippet': 28432,
        }
        self.assertEqual(
            _motivo_calidad_pastilla(
                suelta,
                nombre='Bujías',
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=12000,
                anio=2010,
                cilindraje='1.4',
            ),
            'precio_alto_banda',
        )
        self.assertEqual(
            monto_por_unidad_citable(
                suelta,
                nombre='Bujías',
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=12000,
                anio=2010,
                cilindraje='1.4',
                cantidad=4,
                unitario_linea=12000,
            ),
            0,
        )
        juego = {
            'title': 'Juego de 4 bujías NGK Fiat Bravo 1.4 T-Jet',
            'url': 'https://www.lider.cl/juego-4-bujias-bravo',
            'content': 'Juego de 4 bujías NGK Fiat Bravo 1.4 T-Jet. Precio $ 36.000',
            'ficha_leida': True,
            'precio_snippet': 36000,
        }
        self.assertEqual(
            _motivo_calidad_pastilla(
                juego,
                nombre='Bujías',
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=12000,
                anio=2010,
                cilindraje='1.4',
            ),
            '',
        )
        self.assertEqual(
            monto_por_unidad_citable(
                juego,
                nombre='Bujías',
                modelo='Bravo',
                tipo_motor='T-Jet',
                banda_min=8000,
                banda_max=12000,
                anio=2010,
                cilindraje='1.4',
                cantidad=4,
                unitario_linea=12000,
            ),
            9000,
        )

    def test_la_tarea_no_cita_el_hit_de_28432_y_el_pdf_tampoco(self):
        user = User.objects.create_user(
            username='bujia_28432', password='x', email='b28432@test.cl',
        )
        taller = Taller.objects.create(usuario=user, nombre='Mecanimovil', telefono='1')
        cot = self._cot(user, taller, [self._linea()])

        def _hit_suelto(nombres, **kwargs):
            return {
                'bujias': {
                    'nombre_producto': 'Bujía Iridium Fiat Bravo 1.4 T-Jet',
                    'nombre_buscado': 'Bujías',
                    'url': 'https://www.lider.cl/bujia-iridium-bravo',
                    'tienda': 'Lider',
                    'dominio': 'lider.cl',
                    'precio_clp': 28432,
                    'compatibilidad': 'alta',
                    'confianza': 0.9,
                },
            }

        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_hit_suelto,
        ):
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'), result)
        cot.refresh_from_db()
        linea = cot.repuestos[0]
        self.assertEqual(linea['precio_unitario_clp'], 12000)
        self.assertNotIn('28.432', linea.get('motivo_seleccion') or '')
        self.assertNotIn('Referencia: Lider', linea.get('motivo_seleccion') or '')
        self.assertFalse(linea.get('referencia_tienda'))
        self.assertNotEqual(linea.get('proveedor_nombre'), 'Lider')
        texto = _texto_pdf(generar_pdf_orden_compra(cot))
        self.assertNotIn('28.432', texto)
        self.assertNotIn('Lider', texto)

    def test_la_tarea_cita_el_juego_de_4_por_unidad(self):
        user = User.objects.create_user(
            username='bujia_juego', password='x', email='bjuego@test.cl',
        )
        taller = Taller.objects.create(usuario=user, nombre='Mecanimovil', telefono='1')
        linea = self._linea()
        linea['referencia_tienda'] = ''
        linea['precio_referencia_clp'] = 0
        linea['motivo_seleccion'] = 'Indra (especialista Fiat): consulta disponibilidad y precio.'
        linea['comentario'] = linea['motivo_seleccion']
        cot = self._cot(user, taller, [linea])

        def _hit_juego(nombres, **kwargs):
            return {
                'bujias': {
                    'nombre_producto': 'Juego de 4 bujías NGK Fiat Bravo 1.4 T-Jet',
                    'nombre_buscado': 'Bujías',
                    'url': 'https://www.lider.cl/juego-4-bujias-bravo',
                    'tienda': 'Lider',
                    'dominio': 'lider.cl',
                    'precio_clp': 36000,
                    'compatibilidad': 'alta',
                    'confianza': 0.9,
                },
            }

        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_hit_juego,
        ):
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'), result)
        cot.refresh_from_db()
        linea = cot.repuestos[0]
        self.assertEqual(linea.get('referencia_tienda'), 'Lider')
        self.assertEqual(linea.get('precio_referencia_clp'), 9000)
        self.assertIn('$9.000', linea.get('motivo_seleccion') or '')
        self.assertNotIn('36.000', linea.get('motivo_seleccion') or '')
        self.assertNotIn('28.432', linea.get('motivo_seleccion') or '')
        self.assertNotEqual(linea.get('precio_unitario_clp'), 36000)
        self.assertNotEqual(linea.get('precio_unitario_clp'), 28432)
        texto = _texto_pdf(generar_pdf_orden_compra(cot))
        self.assertIn('$9.000', texto)
        self.assertNotIn('36.000', texto)
        self.assertNotIn('28.432', texto)


class PastillaRechazadaSigueEnElPedidoTests(TestCase):
    """Una ficha que no pasa la compuerta no se lleva la línea de pastillas."""

    def test_el_hit_viejo_no_borra_la_linea_ni_el_pdf(self):
        user = User.objects.create_user(
            username='pastilla_210', password='x', email='p210@test.cl',
        )
        taller = Taller.objects.create(usuario=user, nombre='Mecanimovil', telefono='1')
        cot = CotizacionCanal.objects.create(
            taller=taller,
            creado_por=user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='FIAT',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            vehiculo_cilindraje='1.4',
            tipo_motor='T-Jet',
            servicio_nombre='Mantención con pastillas de freno',
            repuestos=[{
                'id': 'pastillas',
                'nombre': 'Pastillas de freno',
                'cantidad': 1,
                'precio_unitario_clp': 55000,
                'precio_min_clp': 28000,
                'precio_max_clp': 55000,
                'certeza': 'asumido',
                'precio_estimado': True,
                'fuente_marketplace': 'estimado',
            }],
            metadata={'busqueda_web_estado': 'pendiente'},
        )

        def _hit_viejo(nombres, **kwargs):
            return {
                'pastillas freno': {
                    'nombre_producto': 'Pastillas Fiat Linea 1.4 1995-2001',
                    'nombre_buscado': 'Pastillas de freno',
                    'url': 'https://www.lider.cl/pastillas-linea-1995',
                    'tienda': 'Lider',
                    'dominio': 'lider.cl',
                    'precio_clp': 21390,
                    'compatibilidad': 'alta',
                    'confianza': 0.9,
                },
            }

        from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.busqueda_web_habilitada',
            return_value=True,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos.buscar_repuestos_web',
            side_effect=_hit_viejo,
        ):
            result = buscar_precios_web_cotizacion_task(cot.id)

        self.assertTrue(result.get('ok'), result)
        cot.refresh_from_db()
        nombres = [str(r.get('nombre') or '') for r in cot.repuestos if isinstance(r, dict)]
        self.assertTrue(any('pastilla' in n.lower() for n in nombres), nombres)
        linea = next(r for r in cot.repuestos if 'pastilla' in str(r.get('nombre') or '').lower())
        self.assertNotEqual(linea.get('proveedor_nombre'), 'Lider')
        self.assertNotIn('1995', linea.get('motivo_seleccion') or '')
        texto = _texto_pdf(generar_pdf_orden_compra(cot))
        self.assertIn('Pastillas', texto)

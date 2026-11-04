"""Casas especialistas, prioridad de taller y orden de compra."""
from io import BytesIO

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
from mecanimovilapp.apps.usuarios.models import Taller, TallerDireccion
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
        self.assertEqual(linea['motivo_seleccion'], 'Indra: especialista Fiat, precio a consultar.')
        self.assertLessEqual(len(linea['motivo_seleccion']), 160)
        self.assertIn('Lira 664', linea['casa_sucursal'])

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

    def test_el_taller_descarga_el_pdf(self):
        client = APIClient()
        client.force_authenticate(self.user)
        res = client.get(f'/api/ordenes/cotizaciones-canal/{self.cot.pk}/orden-compra-pdf/')
        self.assertEqual(res.status_code, 200, getattr(res, 'data', res.content[:200]))
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('CJXP98', res['Content-Disposition'])
        self.assertTrue(res.content.startswith(b'%PDF'))

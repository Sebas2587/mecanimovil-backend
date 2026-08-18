"""Contrato público de cotización: folio, notas, cliente, PDF."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    asegurar_numero_publico,
    preparar_emision_publica,
    serializar_cotizacion_publica,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class CotizacionPublicaDocumentoTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='taller_doc',
            password='test123',
            email='taller@mecanimovil.test',
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Embrague',
            telefono='900000001',
            estado_verificacion='aprobado',
            verificado=True,
        )
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='enviada',
            modalidad='taller',
            cliente_nombre='Ana Pérez',
            cliente_telefono='+56911111111',
            direccion_servicio='Av. Providencia 100, Santiago',
            vehiculo_marca='Nissan',
            vehiculo_modelo='Kicks',
            vehiculo_anio=2018,
            vehiculo_patente='ABCD12',
            servicio_nombre='Cambio de bomba de embrague',
            descripcion_problema='Pedal esponjoso',
            notas_internas='1. Revisar líquido de frenos.\n2. Garantía 30 días.',
            mano_obra_clp=120000,
            costo_repuestos_clp=117000,
            total_clp=237000,
            duracion_minutos_estimada=180,
            token='tok-doc-publico',
            enviada_en=timezone.now(),
            repuestos=[
                {
                    'id': 'rep-1',
                    'nombre': 'Bomba de embrague',
                    'cantidad': 1,
                    'precio_unitario_clp': 117000,
                    'marca_repuesto': 'Sachs',
                    'tienda_ml': 'oculta',
                }
            ],
        )

    def test_folio_inmutable_mm_pk(self):
        asegurar_numero_publico(self.cot)
        expected = f'MM-{self.cot.pk:06d}'
        self.assertEqual(self.cot.numero_publico, expected)
        self.cot.numero_publico = expected
        self.cot.save(update_fields=['numero_publico'])
        asegurar_numero_publico(self.cot)
        self.assertEqual(self.cot.numero_publico, expected)

    def test_payload_publico_incluye_folio_cliente_notas_email(self):
        preparar_emision_publica(self.cot)
        data = serializar_cotizacion_publica(self.cot)
        self.assertEqual(data['numero_publico'], f'MM-{self.cot.pk:06d}')
        self.assertEqual(data['notas_cotizacion'], '1. Revisar líquido de frenos.\n2. Garantía 30 días.')
        self.assertEqual(data['cliente']['nombre'], 'Ana Pérez')
        self.assertEqual(data['cliente']['telefono'], '+56911111111')
        self.assertEqual(data['cliente']['direccion'], 'Av. Providencia 100, Santiago')
        self.assertEqual(data['taller']['email'], 'taller@mecanimovil.test')
        self.assertEqual(data['taller']['nombre'], 'Taller Embrague')
        self.assertNotIn('tienda_ml', data['repuestos'][0])
        self.assertNotIn('advertencias', data)

    def test_get_publico_y_pdf(self):
        preparar_emision_publica(self.cot)
        client = APIClient()
        res = client.get('/api/ordenes/cotizaciones-publicas/tok-doc-publico/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['numero_publico'], f'MM-{self.cot.pk:06d}')
        self.assertTrue(res.data['notas_cotizacion'])

        pdf = client.get('/api/ordenes/cotizaciones-publicas/tok-doc-publico/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertIn(
            f'Cotizacion-MM-{self.cot.pk:06d}.pdf',
            pdf['Content-Disposition'],
        )
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertGreater(len(pdf.content), 20000)

    def test_pdf_disponible_si_expirada(self):
        preparar_emision_publica(self.cot)
        self.cot.estado = 'expirada'
        self.cot.save(update_fields=['estado'])
        client = APIClient()
        pdf = client.get('/api/ordenes/cotizaciones-publicas/tok-doc-publico/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

"""Contrato público de cotización: folio, notas, cliente, PDF."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import CotizacionCanal, CotizacionCanalPlantilla
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import snapshot_desde_cotizacion
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    asegurar_numero_publico,
    enviar_cotizacion_libre,
    preparar_emision_publica,
    resolver_dias_validez,
    serializar_cotizacion_publica,
)
from mecanimovilapp.apps.usuarios.legal_constants import POLITICAS_COTIZACION_FALLBACK
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
        self.assertEqual(data['politicas_cotizacion'], POLITICAS_COTIZACION_FALLBACK)
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

    def test_politicas_del_taller_viven_en_la_cotizacion(self):
        self.taller.politicas_cotizacion = 'Garantía 90 días en mano de obra.'
        self.taller.save(update_fields=['politicas_cotizacion'])
        preparar_emision_publica(self.cot)
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.politicas_cotizacion, 'Garantía 90 días en mano de obra.')
        data = serializar_cotizacion_publica(self.cot)
        self.assertEqual(data['politicas_cotizacion'], 'Garantía 90 días en mano de obra.')

    def test_pdf_disponible_si_expirada(self):
        preparar_emision_publica(self.cot)
        self.cot.estado = 'expirada'
        self.cot.save(update_fields=['estado'])
        client = APIClient()
        pdf = client.get('/api/ordenes/cotizaciones-publicas/tok-doc-publico/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_descuento_publico_persistido_y_derivado(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            aplicar_totales_cotizacion,
        )
        from mecanimovilapp.apps.ordenes.services.cotizacion_pdf import _lineas, generar_pdf_desde_payload

        self.cot.mano_obra_clp = 30000
        self.cot.costo_repuestos_clp = 140000
        self.cot.total_clp = 161500
        self.cot.descuento_clp = 0
        self.cot.descuento_tipo = ''
        self.cot.repuestos = [{
            'id': 'rep-1',
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 140000,
        }]
        self.cot.save()
        data = serializar_cotizacion_publica(self.cot)
        self.assertEqual(int(data['descuento_clp']), 8500)
        self.assertTrue(data['descuento_etiqueta'])

        self.cot.descuento_tipo = 'porcentaje'
        self.cot.descuento_alcance = 'total'
        self.cot.descuento_valor = 5
        aplicar_totales_cotizacion(self.cot)
        self.cot.save()
        data = serializar_cotizacion_publica(self.cot)
        self.assertEqual(int(data['descuento_clp']), 8500)
        self.assertEqual(int(data['total_clp']), 161500)
        self.assertIn('5%', data['descuento_etiqueta'])
        rows = _lineas(data)
        self.assertEqual(rows[0]['nombre'], 'Cambio de bomba de embrague')
        self.assertEqual(rows[0]['tipo'], 'Mano de obra')
        self.assertEqual(len(data.get('mano_obra_lineas') or []), 1)
        pdf = generar_pdf_desde_payload(data)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 15000)

    def test_dias_validez_al_enviar_y_resolver(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            aplicar_fecha_expiracion_publica,
        )

        self.assertEqual(resolver_dias_validez(taller=self.taller), 30)
        self.taller.dias_validez_cotizacion = 45
        self.taller.save(update_fields=['dias_validez_cotizacion'])
        self.assertEqual(resolver_dias_validez(taller=self.taller), 45)
        self.assertEqual(resolver_dias_validez(taller=self.taller, dias=12), 12)
        self.assertEqual(resolver_dias_validez(dias=0), 30)
        self.assertEqual(resolver_dias_validez(dias=99), 30)

        cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            cliente_nombre='Ana Pérez',
            servicio_nombre='Cambio de filtros',
            mano_obra_clp=30000,
            costo_repuestos_clp=140000,
            total_clp=170000,
            dias_validez=15,
            token='tok-validez-15',
        )
        enviar_cotizacion_libre(cot)
        cot.refresh_from_db()
        self.assertEqual(cot.dias_validez, 15)
        self.assertIsNotNone(cot.enviada_en)
        self.assertEqual((cot.fecha_expiracion_publica - cot.enviada_en).days, 15)
        aplicar_fecha_expiracion_publica(cot)
        self.assertEqual((cot.fecha_expiracion_publica - cot.enviada_en).days, 15)

    def test_plantilla_copia_descuento_y_dias_validez(self):
        self.cot.descuento_tipo = 'porcentaje'
        self.cot.descuento_alcance = 'total'
        self.cot.descuento_valor = 5
        self.cot.descuento_clp = 8500
        self.cot.dias_validez = 21
        snap = snapshot_desde_cotizacion(self.cot)
        self.assertEqual(snap['descuento_tipo'], 'porcentaje')
        self.assertEqual(snap['descuento_alcance'], 'total')
        self.assertEqual(float(snap['descuento_valor']), 5)
        self.assertEqual(snap['dias_validez'], 21)

        plantilla = CotizacionCanalPlantilla.objects.create(
            taller=self.taller,
            creado_por=self.user,
            titulo='Cambio filtros',
            snapshot={
                'servicio_nombre': 'Cambio de filtros',
                'mano_obra_clp': 30000,
                'repuestos': [{
                    'nombre': 'Filtro de aceite',
                    'cantidad': 1,
                    'precio_unitario_clp': 140000,
                }],
                'descuento_tipo': 'porcentaje',
                'descuento_alcance': 'total',
                'descuento_valor': 5,
                'dias_validez': 21,
            },
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        res = client.post(
            '/api/ordenes/cotizaciones-canal/generar-ia/',
            {
                'plantilla_id': plantilla.id,
                'cliente_nombre': 'Ana Pérez',
                'es_libre': True,
            },
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.data)
        cot_data = res.data['cotizacion']
        self.assertEqual(cot_data['descuento_tipo'], 'porcentaje')
        self.assertEqual(int(cot_data['descuento_clp']), 8500)
        self.assertEqual(int(cot_data['total_clp']), 161500)
        self.assertEqual(int(cot_data['dias_validez']), 21)

    def test_mano_obra_lineas_publicas_y_pdf(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_pdf import _lineas

        self.cot.metadata = {
            'servicios_lineas': [
                {'nombre': 'Cambio de aceite y filtro', 'monto_clp': 35000},
                {'nombre': 'Rotación de neumáticos', 'monto_clp': 15000},
            ],
        }
        self.cot.mano_obra_clp = 50000
        self.cot.save()
        data = serializar_cotizacion_publica(self.cot)
        self.assertEqual(
            data['mano_obra_lineas'],
            [
                {'nombre': 'Cambio de aceite y filtro', 'monto_clp': 35000},
                {'nombre': 'Rotación de neumáticos', 'monto_clp': 15000},
            ],
        )
        rows = _lineas(data)
        mo_rows = [r for r in rows if r['tipo'] == 'Mano de obra']
        self.assertEqual([r['nombre'] for r in mo_rows], [
            'Cambio de aceite y filtro',
            'Rotación de neumáticos',
        ])
        self.assertEqual(int(data['mano_obra_clp']), 50000)

    def test_edicion_congela_publico_hasta_enviar(self):
        cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            cliente_nombre='Ana Pérez',
            cliente_telefono='+56911111111',
            vehiculo_marca='Nissan',
            vehiculo_modelo='Kicks',
            servicio_nombre='Cambio de aceite',
            mano_obra_clp=35000,
            costo_repuestos_clp=0,
            total_clp=35000,
        )
        enviar_cotizacion_libre(cot)
        cot.refresh_from_db()
        token = cot.token
        public_client = APIClient()
        before = public_client.get(f'/api/ordenes/cotizaciones-publicas/{token}/')
        self.assertEqual(before.status_code, 200)
        self.assertEqual(int(before.data['mano_obra_clp']), 35000)
        self.assertTrue(before.data['puede_responder'])

        taller = APIClient()
        taller.force_authenticate(self.user)
        patch = taller.patch(
            f'/api/ordenes/cotizaciones-canal/{cot.id}/',
            {
                'mano_obra_clp': 50000,
                'servicio_nombre': 'Cambio de aceite y filtro',
            },
            format='json',
        )
        self.assertEqual(patch.status_code, 200, patch.data)
        self.assertEqual(patch.data['estado'], 'borrador')
        self.assertTrue(patch.data['emision_pendiente'])
        self.assertEqual(int(patch.data['mano_obra_clp']), 50000)

        frozen = public_client.get(f'/api/ordenes/cotizaciones-publicas/{token}/')
        self.assertEqual(frozen.status_code, 200)
        self.assertEqual(int(frozen.data['mano_obra_clp']), 35000)
        self.assertEqual(frozen.data['servicio_nombre'], 'Cambio de aceite')
        self.assertFalse(frozen.data['puede_responder'])

        accept = public_client.post(f'/api/ordenes/cotizaciones-publicas/{token}/aceptar/')
        self.assertEqual(accept.status_code, 409)
        self.assertEqual(accept.data.get('codigo'), 'emision_pendiente')

        preview = taller.get(f'/api/ordenes/cotizaciones-canal/{cot.id}/vista-previa/')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(int(preview.data['mano_obra_clp']), 50000)
        self.assertEqual(preview.data['servicio_nombre'], 'Cambio de aceite y filtro')

        sent = taller.post(f'/api/ordenes/cotizaciones-canal/{cot.id}/enviar/')
        self.assertEqual(sent.status_code, 200, sent.data)

        after = public_client.get(f'/api/ordenes/cotizaciones-publicas/{token}/')
        self.assertEqual(after.status_code, 200)
        self.assertEqual(int(after.data['mano_obra_clp']), 50000)
        self.assertEqual(after.data['servicio_nombre'], 'Cambio de aceite y filtro')
        self.assertTrue(after.data['puede_responder'])

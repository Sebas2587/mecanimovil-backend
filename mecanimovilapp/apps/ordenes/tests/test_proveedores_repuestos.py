"""Casas de repuestos, precios propios y gate de documento firme."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import (
    CotizacionCanal,
    PrecioProveedorTaller,
    ProveedorRepuestos,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class ProveedoresRepuestosIsolationTests(TestCase):
    def setUp(self):
        self.u1 = User.objects.create_user(username='taller_a', password='test123')
        self.u2 = User.objects.create_user(username='taller_b', password='test123')
        self.t1 = Taller.objects.create(
            usuario=self.u1, nombre='Taller A', telefono='900000001', estado_verificacion='aprobado',
        )
        self.t2 = Taller.objects.create(
            usuario=self.u2, nombre='Taller B', telefono='900000002', estado_verificacion='aprobado',
        )
        self.c1 = APIClient()
        self.c1.force_authenticate(self.u1)
        self.c2 = APIClient()
        self.c2.force_authenticate(self.u2)

    def test_dedupe_nombre_norm_y_aislamiento(self):
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import (
            get_or_create_proveedor,
        )

        a = get_or_create_proveedor(self.t1, 'Refax Maipú')
        b = get_or_create_proveedor(self.t1, 'REFÁX  MAIPU')
        self.assertEqual(a.id, b.id)
        extra = get_or_create_proveedor(self.t2, 'Refax Maipú')
        self.assertNotEqual(a.id, extra.id)

        r = self.c1.get('/api/ordenes/proveedores-repuestos/')
        self.assertEqual(r.status_code, 200)
        ids = [row['id'] for row in r.data] if isinstance(r.data, list) else [
            row['id'] for row in r.data.get('results', [])
        ]
        self.assertIn(a.id, ids)
        self.assertNotIn(extra.id, ids)

    @override_settings(PRECIO_PROVEEDOR_TALLER_ENABLED=True)
    def test_precio_propio_no_cruza_talleres(self):
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import (
            candidatos_precio_proveedor,
            get_or_create_proveedor,
            upsert_precio_proveedor,
        )

        prov = get_or_create_proveedor(self.t1, 'Refax')
        upsert_precio_proveedor(
            taller=self.t1,
            nombre_repuesto='Bujía iridio',
            precio_clp=21500,
            proveedor=prov,
            especificacion='Iridio',
            origen='compra',
            vehiculo={'marca': 'Nissan', 'modelo': 'X-Trail'},
        )
        hits_a = candidatos_precio_proveedor(self.t1, marca_vehiculo='Nissan', modelo_vehiculo='X-Trail')
        hits_b = candidatos_precio_proveedor(self.t2, marca_vehiculo='Nissan', modelo_vehiculo='X-Trail')
        self.assertTrue(hits_a)
        self.assertEqual(hits_b, [])


class DocumentoFirmeGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_gate', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user, nombre='Taller Gate', telefono='900000003', estado_verificacion='aprobado',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.cot = CotizacionCanal.objects.create(
            taller=self.taller,
            creado_por=self.user,
            es_libre=True,
            cliente_nombre='Ana',
            servicio_nombre='Cambio de bujías',
            vehiculo_marca='Nissan',
            vehiculo_modelo='X-Trail',
            estado='borrador',
            mano_obra_clp=40000,
            repuestos=[{
                'id': 'rep-1',
                'nombre': 'Bujía de encendido',
                'cantidad': 4,
                'precio_unitario_clp': 0,
                'certeza': 'sin_precio',
                'especificacion_pendiente': True,
            }],
        )

    @override_settings(DOCUMENTO_FIRME_GATE_ENABLED=True)
    def test_enviar_firme_con_pendientes_400(self):
        res = self.client.post(
            f'/api/ordenes/cotizaciones-canal/{self.cot.id}/enviar/',
            {'tipo_documento': 'cotizacion'},
            format='json',
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('lineas_pendientes', res.data)

    @override_settings(DOCUMENTO_FIRME_GATE_ENABLED=True)
    def test_asumir_habilita_envio(self):
        self.cot.repuestos = [{
            'id': 'rep-1',
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'precio_unitario_clp': 9000,
            'precio_max_clp': 12000,
            'certeza': 'referencial',
        }]
        self.cot.save(update_fields=['repuestos'])
        asum = self.client.post(
            f'/api/ordenes/cotizaciones-canal/{self.cot.id}/asumir-precio-repuesto/',
            {'repuesto_id': ['rep-1']},
            format='json',
        )
        self.assertEqual(asum.status_code, 200)
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.repuestos[0]['certeza'], 'asumido')
        self.assertEqual(self.cot.repuestos[0]['precio_unitario_clp'], 12000)

"""Costo y ganancia de repuestos en la cotización del taller, y búsqueda."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.serializers_cotizacion_canal import CotizacionCanalSerializer
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import serializar_cotizacion_publica
from mecanimovilapp.apps.ordenes.services.pipeline_comercial import construir_pipeline_comercial
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()

_CLAVES_INTERNAS = (
    'costo_unitario_clp',
    'costo_estimado_clp',
    'costo_registrado_clp',
    'precio_cobrado_clp',
    'margen_clp',
    'margen_pct',
    'costo_total_repuestos_clp',
    'cobrado_total_repuestos_clp',
    'ganancia_repuestos_clp',
    'margen_repuestos_pct',
)


class CostoGananciaRepuestosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_costo', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Costo',
            telefono='900000020',
            estado_verificacion='aprobado',
            margen_ganancia_pct=Decimal('30.00'),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _cot(self, **kwargs):
        datos = {
            'es_libre': True,
            'taller': self.taller,
            'creado_por': self.user,
            'estado': 'enviada',
            'cliente_nombre': 'José Pérez',
            'servicio_nombre': 'Cambio de filtro',
            'vehiculo_marca': 'Fiat',
            'vehiculo_modelo': 'Bravo',
            'vehiculo_patente': 'AB-CD-12',
            'mano_obra_clp': 20000,
            'token': 'tok-costo-ganancia',
        }
        datos.update(kwargs)
        return CotizacionCanal.objects.create(**datos)

    def test_linea_descubierta_expone_costo_cobro_y_ganancia(self):
        cot = self._cot(repuestos=[{
            'id': 'filtro',
            'nombre': 'Filtro de aceite',
            'cantidad': 2,
            'costo_estimado_clp': 10000,
            'precio_unitario_clp': 13000,
        }])
        data = CotizacionCanalSerializer(cot).data
        linea = data['repuestos'][0]
        self.assertEqual(linea['costo_unitario_clp'], 10000)
        self.assertEqual(linea['precio_cobrado_clp'], 13000)
        self.assertEqual(linea['margen_clp'], 6000)
        self.assertEqual(data['costo_total_repuestos_clp'], 20000)
        self.assertEqual(data['cobrado_total_repuestos_clp'], 26000)
        self.assertEqual(data['ganancia_repuestos_clp'], 6000)

        resp = self.client.get(f'/api/ordenes/cotizaciones-canal/{cot.id}/?sin_retry=1')
        self.assertEqual(resp.status_code, 200, resp.content)
        cuerpo = resp.json()
        self.assertEqual(cuerpo['costo_total_repuestos_clp'], 20000)
        self.assertEqual(cuerpo['ganancia_repuestos_clp'], 6000)
        self.assertEqual(cuerpo['repuestos'][0]['precio_cobrado_clp'], 13000)

    def test_linea_manual_con_costo_guardado(self):
        cot = self._cot(repuestos=[{
            'nombre': 'Pastillas',
            'cantidad': 1,
            'costo_unitario_clp': 8000,
            'precio_unitario_clp': 10000,
        }], token='tok-manual-costo')
        data = CotizacionCanalSerializer(cot).data
        linea = data['repuestos'][0]
        self.assertEqual(linea['costo_unitario_clp'], 8000)
        self.assertEqual(linea['precio_cobrado_clp'], 10000)
        self.assertEqual(linea['margen_clp'], 2000)
        self.assertEqual(data['ganancia_repuestos_clp'], 2000)

    def test_linea_manual_sin_costo_no_inventa_ganancia(self):
        """Sin costo guardado, el precio cobrado no se trata como costo."""
        cot = self._cot(repuestos=[{
            'nombre': 'Bujía',
            'cantidad': 1,
            'precio_unitario_clp': 5000,
        }], token='tok-sin-costo')
        data = CotizacionCanalSerializer(cot).data
        linea = data['repuestos'][0]
        self.assertIsNone(linea['costo_unitario_clp'])
        self.assertEqual(linea['precio_cobrado_clp'], 5000)
        self.assertIsNone(linea['margen_clp'])
        self.assertEqual(data['cobrado_total_repuestos_clp'], 5000)
        self.assertIsNone(data['costo_total_repuestos_clp'])
        self.assertIsNone(data['ganancia_repuestos_clp'])

    def test_vista_publica_no_expone_costo_ni_ganancia(self):
        cot = self._cot(repuestos=[{
            'nombre': 'Filtro de aceite',
            'cantidad': 1,
            'costo_estimado_clp': 10000,
            'costo_unitario_clp': 10000,
            'precio_unitario_clp': 13000,
            'precio_cobrado_clp': 13000,
            'margen_clp': 3000,
        }])
        publico = serializar_cotizacion_publica(cot)
        for clave in _CLAVES_INTERNAS:
            self.assertNotIn(clave, publico)
        for linea in publico['repuestos']:
            for clave in _CLAVES_INTERNAS:
                self.assertNotIn(clave, linea)

        anon = APIClient()
        resp = anon.get(f'/api/ordenes/cotizaciones-publicas/{cot.token}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        cuerpo = resp.json()
        for clave in _CLAVES_INTERNAS:
            self.assertNotIn(clave, cuerpo)
            for linea in cuerpo.get('repuestos') or []:
                self.assertNotIn(clave, linea)


class BusquedaCotizacionesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_busca', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Busca',
            telefono='900000021',
            estado_verificacion='aprobado',
        )
        self.otro = User.objects.create_user(username='taller_ajeno', password='test123')
        self.taller_b = Taller.objects.create(
            usuario=self.otro,
            nombre='Otro Taller',
            telefono='900000022',
            estado_verificacion='aprobado',
        )
        ct = ContentType.objects.get_for_model(Taller)
        conexion = ProviderChannelConnection.objects.create(
            content_type=ct,
            object_id=self.taller.id,
            usuario=self.user,
            channel='WHATSAPP',
            enabled=True,
            status='conectada',
            phone_number_id='555',
            access_token='token',
        )
        contacto = ExternalContact.objects.create(
            connection=conexion,
            channel='WHATSAPP',
            external_id='56911110000',
            display_name='Camila Soto',
        )
        self.conversation = Conversation.objects.create(
            type='OMNICHANNEL',
            source_channel='WHATSAPP',
            external_contact=contacto,
        )
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='enviada',
            cliente_nombre='José Pérez',
            servicio_nombre='Frenos',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_patente='AB-CD-12',
            mano_obra_clp=10000,
            total_clp=10000,
            token='tok-busca-a',
        )
        self.canal = CotizacionCanal.objects.create(
            es_libre=False,
            conversation=self.conversation,
            taller=self.taller,
            creado_por=self.user,
            estado='enviada',
            cliente_nombre='',
            servicio_nombre='Alineación',
            vehiculo_marca='Nissan',
            vehiculo_modelo='Kicks',
            vehiculo_patente='XY-99-01',
            token='tok-busca-canal',
        )
        self.ajena = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller_b,
            creado_por=self.otro,
            estado='enviada',
            cliente_nombre='José Pérez',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_patente='AB-CD-12',
            token='tok-busca-b',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _ids(self, q):
        resp = self.client.get('/api/ordenes/cotizaciones-canal/', {'q': q})
        self.assertEqual(resp.status_code, 200, resp.content)
        return {item['id'] for item in resp.json()['results']}

    def test_busca_por_nombre_patente_y_marca_modelo(self):
        self.assertEqual(self._ids('jose'), {self.cot.id})
        self.assertEqual(self._ids('Pérez'), {self.cot.id})
        self.assertEqual(self._ids('abcd12'), {self.cot.id})
        self.assertEqual(self._ids('ab-cd-12'), {self.cot.id})
        self.assertEqual(self._ids('Fiat Bravo'), {self.cot.id})
        self.assertEqual(self._ids('bravo fiat'), {self.cot.id})
        self.assertEqual(self._ids('camila'), {self.canal.id})
        self.assertEqual(self._ids('no-existe'), set())

    def test_search_es_alias_de_q_y_no_cruza_taller(self):
        resp = self.client.get('/api/ordenes/cotizaciones-canal/', {'search': 'José'})
        self.assertEqual(resp.status_code, 200, resp.content)
        ids = {item['id'] for item in resp.json()['results']}
        self.assertEqual(ids, {self.cot.id})
        self.assertNotIn(self.ajena.id, ids)

        ajeno = APIClient()
        ajeno.force_authenticate(user=self.otro)
        resp_b = ajeno.get('/api/ordenes/cotizaciones-canal/', {'q': 'José'})
        self.assertEqual(
            {item['id'] for item in resp_b.json()['results']},
            {self.ajena.id},
        )

    def test_pipeline_encuentra_marca_y_modelo_juntos(self):
        payload = construir_pipeline_comercial(
            user=self.user, taller=self.taller, limite=50, q='Fiat Bravo',
        )
        ids = {f.get('cotizacion_id') for f in payload['results']}
        self.assertIn(self.cot.id, ids)
        self.assertNotIn(self.ajena.id, ids)

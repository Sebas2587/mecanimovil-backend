"""Pipeline clientes: una fila por persona, ficha agrupada por vehículo."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import asegurar_numero_publico
from mecanimovilapp.apps.ordenes.services.pipeline_comercial import (
    construir_pipeline_cliente_detalle,
    construir_pipeline_clientes,
    construir_pipeline_comercial,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class PipelineClientesBandejaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_clientes', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Clientes',
            telefono='900000003',
            estado_verificacion='aprobado',
        )
        ct = ContentType.objects.get_for_model(Taller)
        self.connection = ProviderChannelConnection.objects.create(
            content_type=ct,
            object_id=self.taller.id,
            usuario=self.user,
            channel='WHATSAPP',
            enabled=True,
            status='conectada',
            phone_number_id='999001',
            access_token='token',
        )
        self.contact = ExternalContact.objects.create(
            connection=self.connection,
            channel='WHATSAPP',
            external_id='56987654321',
            display_name='Jennifer',
            phone='56987654321',
        )
        self.conversation = Conversation.objects.create(
            type='OMNICHANNEL',
            source_channel='WHATSAPP',
            external_contact=self.contact,
        )
        self.conversation.participants.add(self.user)

    def _cotizacion(self, **kwargs):
        defaults = {
            'conversation': self.conversation,
            'taller': self.taller,
            'creado_por': self.user,
            'estado': 'enviada',
            'modalidad': 'taller',
            'cliente_nombre': 'Jennifer',
            'cliente_telefono': '+56987654321',
            'vehiculo_marca': 'Nissan',
            'vehiculo_modelo': 'Kicks',
            'vehiculo_patente': 'KGGR22',
            'servicio_nombre': 'Diagnóstico',
            'mano_obra_clp': 40000,
            'total_clp': 40000,
            'enviada_en': timezone.now(),
        }
        defaults.update(kwargs)
        cot = CotizacionCanal.objects.create(**defaults)
        asegurar_numero_publico(cot)
        cot.refresh_from_db()
        return cot

    def test_dos_cotizaciones_mismo_telefono_son_un_cliente(self):
        self._cotizacion(servicio_nombre='Bomba de embrague', total_clp=237000)
        self._cotizacion(
            servicio_nombre='Bujías',
            vehiculo_marca='Chevrolet',
            vehiculo_modelo='Sail',
            vehiculo_patente='ABCD12',
            total_clp=80000,
            enviada_en=timezone.now() - timedelta(days=10),
        )
        folios = construir_pipeline_comercial(user=self.user, taller=self.taller, limite=50)
        self.assertEqual(
            len([f for f in folios['results'] if f['tipo_entidad'] == 'cotizacion_canal']),
            2,
        )
        payload = construir_pipeline_clientes(user=self.user, taller=self.taller, limite=50)
        self.assertEqual(payload['count'], 1)
        row = payload['results'][0]
        self.assertEqual(row['casos_count'], 2)
        self.assertTrue(row['cliente_key'].startswith('tel-'))
        self.assertEqual(row['enviadas'], 2)
        patentes = {v.get('patente') for v in row['vehiculos']}
        self.assertIn('KGGR22', patentes)
        self.assertIn('ABCD12', patentes)

    def test_ficha_agrupa_por_patente(self):
        self._cotizacion(servicio_nombre='Bomba')
        self._cotizacion(
            servicio_nombre='Bujías',
            vehiculo_marca='Chevrolet',
            vehiculo_modelo='Sail',
            vehiculo_patente='ABCD12',
        )
        lista = construir_pipeline_clientes(user=self.user, taller=self.taller, limite=50)
        key = lista['results'][0]['cliente_key']
        ficha = construir_pipeline_cliente_detalle(
            user=self.user, taller=self.taller, cliente_key=key
        )
        self.assertIsNotNone(ficha)
        self.assertEqual(len(ficha['vehiculos']), 2)
        servicios = {
            caso['servicio_resumen']
            for veh in ficha['vehiculos']
            for caso in veh['casos']
        }
        self.assertIn('Bomba', servicios)
        self.assertIn('Bujías', servicios)

    def test_busqueda_por_patente_nombre_y_folio(self):
        cot = self._cotizacion(servicio_nombre='Bomba')
        folio = cot.numero_publico
        for q in ('KGGR22', 'kggr-22', 'jenni', folio, '87654321'):
            payload = construir_pipeline_clientes(user=self.user, taller=self.taller, q=q, limite=50)
            self.assertEqual(payload['count'], 1, msg=f'q={q}')
            self.assertEqual(payload['results'][0]['cliente_nombre'], 'Jennifer')

    def test_homonimos_sin_telefono_no_se_fusionan(self):
        self._cotizacion(
            conversation=None,
            es_libre=True,
            cliente_nombre='Juan',
            cliente_telefono='',
            vehiculo_patente='AAA111',
            servicio_nombre='Frenos',
        )
        self._cotizacion(
            conversation=None,
            es_libre=True,
            cliente_nombre='Juan',
            cliente_telefono='',
            vehiculo_patente='BBB222',
            servicio_nombre='Aceite',
        )
        payload = construir_pipeline_clientes(user=self.user, taller=self.taller, limite=50)
        juans = [r for r in payload['results'] if r['cliente_nombre'] == 'Juan']
        self.assertEqual(len(juans), 2)
        self.assertTrue(all(r['cliente_key'].startswith('caso-') for r in juans))

    def test_prioridad_cerrados_excluye_enviadas_abiertas(self):
        self._cotizacion(estado='enviada')
        cerrados = construir_pipeline_clientes(
            user=self.user, taller=self.taller, prioridad='cerrados', limite=50
        )
        self.assertEqual(cerrados['count'], 0)
        abiertos = construir_pipeline_clientes(
            user=self.user, taller=self.taller, prioridad='con_accion', limite=50
        )
        self.assertEqual(abiertos['count'], 1)

"""Pipeline: una fila por folio MM, reabiertas visibles, búsqueda por código."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CitaAgendaPersonalDetalle,
    CotizacionCanal,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import reabrir_cotizacion_enviada
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import asegurar_numero_publico
from mecanimovilapp.apps.ordenes.services.pipeline_comercial import construir_pipeline_comercial
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class PipelineFolioBandejaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_folio', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Folio',
            telefono='900000002',
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
            phone_number_id='123456',
            access_token='token',
        )
        self.contact = ExternalContact.objects.create(
            connection=self.connection,
            channel='WHATSAPP',
            external_id='56911112222',
            display_name='Gonzalo',
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
            'cliente_nombre': 'Gonzalo',
            'vehiculo_marca': 'Changan',
            'vehiculo_modelo': 'Hunter',
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

    def test_dos_cotizaciones_mismo_chat_son_dos_filas(self):
        a = self._cotizacion(servicio_nombre='Frenos')
        b = self._cotizacion(servicio_nombre='Aceite')
        payload = construir_pipeline_comercial(user=self.user, taller=self.taller, limite=50)
        ids = {
            f['cotizacion_id']
            for f in payload['results']
            if f['tipo_entidad'] == 'cotizacion_canal'
        }
        self.assertIn(a.id, ids)
        self.assertIn(b.id, ids)
        self.assertTrue(any(f.get('numero_publico') == a.numero_publico for f in payload['results']))

    def test_cita_del_mismo_caso_se_fusiona_en_folio(self):
        cot = self._cotizacion()
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            conversation_origen=self.conversation,
            cotizacion_canal_origen=cot,
            fecha_servicio=date(2030, 8, 22),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            horario_por_confirmar=True,
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Gonzalo',
            vehiculo_marca='Changan',
            vehiculo_modelo='Hunter',
            vehiculo_patente='KGGR22',
            servicio_nombre='Diagnóstico',
        )
        payload = construir_pipeline_comercial(user=self.user, taller=self.taller, limite=50)
        filas_caso = [
            f for f in payload['results']
            if f.get('cotizacion_id') == cot.id or f.get('cita_id') == cita.id
        ]
        self.assertEqual(len(filas_caso), 1)
        fila = filas_caso[0]
        self.assertEqual(fila['tipo_entidad'], 'cotizacion_canal')
        self.assertEqual(fila['numero_publico'], cot.numero_publico)
        self.assertEqual(fila['cita_id'], cita.id)
        self.assertTrue(fila['horario_por_confirmar'])

    def test_cita_manual_sin_cotizacion_sigue_apareciendo(self):
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            fecha_servicio=date(2030, 8, 22),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Walk-in',
            vehiculo_marca='Toyota',
            vehiculo_modelo='Yaris',
            servicio_nombre='Revisión',
        )
        payload = construir_pipeline_comercial(user=self.user, taller=self.taller, limite=50)
        self.assertTrue(
            any(f['tipo_entidad'] == 'cita_personal' and f['cita_id'] == cita.id for f in payload['results'])
        )

    def test_reabierta_con_folio_aparece_en_edicion(self):
        cot = self._cotizacion()
        folio = cot.numero_publico
        reabrir_cotizacion_enviada(cot)
        cot.refresh_from_db()
        self.assertEqual(cot.estado, 'borrador')
        payload = construir_pipeline_comercial(user=self.user, taller=self.taller, limite=50)
        fila = next(
            f for f in payload['results']
            if f['tipo_entidad'] == 'cotizacion_canal' and f['cotizacion_id'] == cot.id
        )
        self.assertEqual(fila['numero_publico'], folio)
        self.assertEqual(fila['estado_raw'], 'borrador')
        self.assertEqual(fila['estado_normalizado'], 'nuevo')
        self.assertTrue(fila['en_edicion'])

    def test_busqueda_por_folio_mm_y_digitos(self):
        cot = self._cotizacion()
        folio = cot.numero_publico
        por_folio = construir_pipeline_comercial(
            user=self.user, taller=self.taller, limite=50, q=folio,
        )
        self.assertEqual(len(por_folio['results']), 1)
        self.assertEqual(por_folio['results'][0]['cotizacion_id'], cot.id)

        digits = str(cot.id)
        por_id = construir_pipeline_comercial(
            user=self.user, taller=self.taller, limite=50, q=digits,
        )
        self.assertTrue(any(f['cotizacion_id'] == cot.id for f in por_id['results']))

        por_nombre = construir_pipeline_comercial(
            user=self.user, taller=self.taller, limite=50, q='Gonzalo',
        )
        self.assertTrue(any(f['cotizacion_id'] == cot.id for f in por_nombre['results']))

    def test_busqueda_por_patente_ignora_guion_y_espacios(self):
        cot = self._cotizacion(vehiculo_patente='KGGR-22', vehiculo_marca='Nissan', vehiculo_modelo='Kicks')
        for q in ('KGGR22', 'kggr-22', 'kggr 22', 'KGGR-22'):
            payload = construir_pipeline_comercial(
                user=self.user, taller=self.taller, limite=50, q=q,
            )
            self.assertTrue(
                any(f['cotizacion_id'] == cot.id for f in payload['results']),
                msg=f'No encontró la cotización con q={q!r}',
            )

    def test_borrador_sin_folio_no_aparece(self):
        CotizacionCanal.objects.create(
            conversation=self.conversation,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            cliente_nombre='Borrador fresco',
            servicio_nombre='IA',
        )
        payload = construir_pipeline_comercial(user=self.user, taller=self.taller, limite=50)
        nombres = [f['cliente_nombre'] for f in payload['results'] if f['tipo_entidad'] == 'cotizacion_canal']
        self.assertNotIn('Borrador fresco', nombres)

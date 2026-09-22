"""Rol por teléfono y consulta a casas de repuestos."""
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.ordenes.models import ConsultaRepuesto, CotizacionCanal, ProveedorRepuestos
from mecanimovilapp.apps.ordenes.services.consulta_casas import (
    cerrar_por_silencio,
    extraer_respuesta,
    recordar_consulta,
    texto_consulta,
)
from mecanimovilapp.apps.ordenes.services.horario_habil import sumar_horas_habiles
from mecanimovilapp.apps.ordenes.services.rol_contacto import (
    RequiereConfirmacionCliente,
    aplicar_marca_casa,
    assert_puede_marcar_telefono,
    asegurar_rol_reservado,
    soltar_telefono,
)
from mecanimovilapp.apps.ordenes.services.telefono_cl import normalizar_telefono
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()
TZ = ZoneInfo('America/Santiago')


class TelefonoYRolTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_casas', password='pass')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Casas',
            telefono='900000001',
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
            phone_number_id='123',
            access_token='token',
        )
        self.contact = ExternalContact.objects.create(
            connection=self.connection,
            channel='WHATSAPP',
            external_id='56911112222',
            display_name='Ssangyong Chile',
            phone='+56911112222',
        )
        Conversation.objects.create(
            type='OMNICHANNEL',
            source_channel='WHATSAPP',
            external_contact=self.contact,
        )

    def test_normaliza_movil_chileno(self):
        self.assertEqual(normalizar_telefono('9 1111 2222'), '56911112222')
        self.assertEqual(normalizar_telefono('+56 9 1111 2222'), '56911112222')

    def test_guardar_casa_marca_el_chat(self):
        casa = ProveedorRepuestos.objects.create(
            taller=self.taller,
            nombre='Ssangyong Chile',
            telefono='911112222',
        )
        aplicar_marca_casa(casa)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.rol, ExternalContact.ROL_CASA_REPUESTOS)
        self.assertTrue(self.contact.rol_manual)

    def test_numero_nuevo_queda_reservado_para_el_proximo_hilo(self):
        ProveedorRepuestos.objects.create(
            taller=self.taller,
            nombre='Refax',
            telefono='922223333',
        )
        nuevo = ExternalContact.objects.create(
            connection=self.connection,
            channel='WHATSAPP',
            external_id='56922223333',
            display_name='Refax',
            phone='56922223333',
        )
        asegurar_rol_reservado(nuevo)
        nuevo.refresh_from_db()
        self.assertEqual(nuevo.rol, ExternalContact.ROL_CASA_REPUESTOS)

    def test_cliente_con_servicio_pide_confirmacion(self):
        conv = Conversation.objects.get(external_contact=self.contact)
        CotizacionCanal.objects.create(
            taller=self.taller,
            conversation=conv,
            estado='aceptada',
            servicio_nombre='Aceite',
        )
        with self.assertRaises(RequiereConfirmacionCliente):
            assert_puede_marcar_telefono(self.taller, '911112222', confirmar=False)
        assert_puede_marcar_telefono(self.taller, '911112222', confirmar=True)

    def test_quitar_casa_suelta_la_marca(self):
        casa = ProveedorRepuestos.objects.create(
            taller=self.taller,
            nombre='Ssangyong Chile',
            telefono='911112222',
        )
        aplicar_marca_casa(casa)
        casa.activo = False
        casa.save(update_fields=['activo'])
        soltar_telefono(self.taller, casa.telefono_norm)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.rol, ExternalContact.ROL_SIN_CLASIFICAR)
        self.assertFalse(self.contact.rol_manual)


class ConsultaCasasTests(TestCase):
    def test_plantilla_lleva_el_auto_y_no_al_cliente(self):
        texto = texto_consulta(
            pieza='pastillas delanteras',
            vehiculo={
                'marca': 'Fiat',
                'modelo': 'Bravo',
                'anio': 2018,
                'motor': '1.4',
                'patente': 'CJXP98',
                'calidad': 'oem',
            },
        )
        self.assertIn('pastillas delanteras', texto)
        self.assertIn('Fiat Bravo 2018', texto)
        self.assertIn('CJXP98', texto)
        self.assertNotIn('Juan', texto)

    def test_extrae_un_precio_y_sin_stock(self):
        claro = extraer_respuesta('Sí, OEM a $18.900 con stock')
        self.assertEqual(claro['estado'], ConsultaRepuesto.ESTADO_RESPONDIDA)
        self.assertEqual(claro['precio_clp'], 18900)
        self.assertGreaterEqual(claro['confianza'], 0.8)
        vacio = extraer_respuesta('No tenemos esa pieza')
        self.assertEqual(vacio['estado'], ConsultaRepuesto.ESTADO_SIN_STOCK)

    def test_horario_habil_salta_al_dia_siguiente(self):
        viernes_tarde = timezone.make_aware(datetime(2026, 9, 18, 17, 0), TZ)
        recordatorio = sumar_horas_habiles(viernes_tarde, 2)
        local = recordatorio.astimezone(TZ)
        self.assertEqual(local.weekday(), 0)
        self.assertEqual((local.hour, local.minute), (10, 0))

    def test_silencio_cierra_sin_tercer_mensaje(self):
        user = User.objects.create_user(username='taller_silencio', password='pass')
        taller = Taller.objects.create(
            usuario=user,
            nombre='Taller Silencio',
            telefono='900000002',
            estado_verificacion='aprobado',
        )
        casa = ProveedorRepuestos.objects.create(taller=taller, nombre='Mostrador', telefono='933334444')
        cot = CotizacionCanal.objects.create(
            taller=taller,
            creado_por=user,
            estado='borrador',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            repuestos=[{'id': 'p1', 'nombre': 'Pastillas', 'cantidad': 1, 'precio_unitario_clp': 0, 'certeza': 'sin_precio'}],
        )
        consulta = ConsultaRepuesto.objects.create(
            taller=taller,
            proveedor=casa,
            cotizacion=cot,
            repuesto_id='p1',
            pieza_nombre='Pastillas',
            vehiculo_snapshot={'marca': 'Fiat', 'modelo': 'Bravo'},
            estado=ConsultaRepuesto.ESTADO_RECORDADA,
            unica=True,
            recordatorio_enviado=True,
        )
        with patch('mecanimovilapp.apps.ordenes.services.consulta_casas._avisar'), patch(
            'mecanimovilapp.apps.agente_ia.services.orquestador.enviar_respuesta_agente',
        ) as enviar:
            recordar_consulta(consulta.id)
            cerrar_por_silencio(consulta.id)
        enviar.assert_not_called()
        consulta.refresh_from_db()
        cot.refresh_from_db()
        self.assertEqual(consulta.estado, ConsultaRepuesto.ESTADO_SIN_RESPUESTA)
        self.assertEqual(cot.repuestos[0]['consulta_casas']['estado'], 'sin_respuesta')
        self.assertEqual(int(cot.repuestos[0]['precio_unitario_clp'] or 0), 0)

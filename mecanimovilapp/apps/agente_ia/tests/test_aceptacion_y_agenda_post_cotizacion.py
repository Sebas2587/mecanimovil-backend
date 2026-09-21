"""PRD: aceptación post-envío, silencio sin chat, duración real de agenda."""
from __future__ import annotations

from datetime import date, time
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
from mecanimovilapp.apps.agente_ia.services.aceptacion_conversacional import (
    aceptar_desde_agente,
    cliente_acepta_cotizacion,
    cotizacion_enviada_de_sesion,
    procesar_turno_esperando_aceptacion,
)
from mecanimovilapp.apps.agente_ia.services.duracion_trabajo import (
    duracion_familia_desde_texto,
    formatear_duracion_humana,
    resolver_duracion_trabajo,
)
from mecanimovilapp.apps.agente_ia.services.sesion_cotizacion import (
    liberar_sesiones_tras_cerrar_borrador,
    promover_sesion_si_cotizacion_enviada,
)
from mecanimovilapp.apps.agente_ia.tasks import iniciar_agendamiento_task
from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import on_cotizacion_respondida
from mecanimovilapp.apps.usuarios.models import HorarioProveedor, Taller, Usuario
from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import (
    disponibilidad_con_duracion,
)


class DetectorAceptacionVerbalTest(SimpleTestCase):
    def test_afirmaciones_fuertes(self):
        for texto in (
            'la acepto',
            'acepto la cotización',
            'dale con esa',
            'me parece ok',
            'estoy viendo la coti y me parece ok',
            'ok el precio',
            'la tomo',
        ):
            self.assertTrue(cliente_acepta_cotizacion(texto), texto)

    def test_no_acepta_viendo_sin_valoracion(self):
        self.assertFalse(cliente_acepta_cotizacion('estoy viendo la coti'))

    def test_no_acepta_cara_ni_pensar(self):
        self.assertFalse(cliente_acepta_cotizacion('me parece cara'))
        self.assertFalse(cliente_acepta_cotizacion('la voy a pensar'))

    def test_ok_suelto_ambiguo(self):
        self.assertIsNone(cliente_acepta_cotizacion('ok'))
        self.assertIsNone(cliente_acepta_cotizacion('ok', ultimo_mensaje_agente='¿Qué día te acomoda?'))

    def test_ok_tras_pregunta_de_aceptar(self):
        self.assertTrue(
            cliente_acepta_cotizacion(
                'ok',
                ultimo_mensaje_agente='¿Confirmas que aceptas la cotización del cambio de embrague?',
            )
        )

    def test_modificar_no_acepta(self):
        self.assertFalse(cliente_acepta_cotizacion('súmale el kit'))


class DuracionFamiliaTest(SimpleTestCase):
    def test_embrague_360(self):
        self.assertEqual(duracion_familia_desde_texto('Cambio de embrague Duster'), 360)

    def test_diagnostico_60(self):
        self.assertEqual(duracion_familia_desde_texto('Diagnóstico electrónico scanner'), 60)

    def test_humana(self):
        self.assertEqual(formatear_duracion_humana(360), 'unas 6 horas')
        self.assertEqual(formatear_duracion_humana(60), '1 hora')


class AceptacionPostEnvioTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(
            username='taller_acept',
            email='taller_acept@mecanimovil.cl',
            password='Password123!',
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Aceptación',
        )
        self.conversation = Conversation.objects.create(
            source_channel='WHATSAPP',
        )
        self.conversation.participants.add(self.user)
        self.sesion = AgenteConversacionSesion.objects.create(
            conversation=self.conversation,
            taller=self.taller,
            estado=AgenteConversacionSesion.ESTADO_ESPERANDO_REVISION,
            habilitado_en_chat=True,
        )
        self.cot = CotizacionCanal.objects.create(
            conversation=self.conversation,
            taller=self.taller,
            creado_por=self.user,
            estado='enviada',
            modalidad='taller',
            cliente_nombre='Sebastián',
            cliente_telefono='+56911112222',
            vehiculo_marca='Renault',
            vehiculo_modelo='Duster',
            vehiculo_anio=2019,
            vehiculo_patente='KVXZ17',
            servicio_nombre='Cambio de embrague',
            total_clp=498526,
            duracion_minutos_estimada=360,
            enviada_en=timezone.now(),
        )
        self.sesion.cotizacion_borrador = self.cot
        self.sesion.save(update_fields=['cotizacion_borrador'])

    def test_envio_mueve_sesion_a_esperando_aceptacion(self):
        n = liberar_sesiones_tras_cerrar_borrador(self.cot)
        self.assertEqual(n, 1)
        self.sesion.refresh_from_db()
        self.assertEqual(self.sesion.estado, AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION)

    def test_promueve_sesion_vieja_en_capturando(self):
        self.sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
        self.sesion.save(update_fields=['estado'])
        sesion = promover_sesion_si_cotizacion_enviada(self.sesion)
        self.assertEqual(sesion.estado, AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION)

    def test_cotizacion_enviada_de_sesion(self):
        self.assertEqual(cotizacion_enviada_de_sesion(self.sesion).id, self.cot.id)

    @patch('mecanimovilapp.apps.agente_ia.services.orquestador.enviar_respuesta_agente')
    def test_mismo_dia_no_reserva_ni_acepta(self, _mock_env):
        self.sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION
        self.sesion.save(update_fields=['estado'])
        result = procesar_turno_esperando_aceptacion(
            sesion=self.sesion,
            texto_cliente='Este trabajo lo hacen en el mismo día?',
            conversation=self.conversation,
            proveedor_user_id=self.user.id,
        )
        self.assertEqual(result['accion'], 'duda_duracion')
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.estado, 'enviada')
        self.assertIsNone(self.cot.aceptada_en)
        pref = (self.sesion.datos_capturados or {}).get('preferencias_agenda') or {}
        self.assertFalse(pref.get('confirmado_verbal'))

    @patch('mecanimovilapp.apps.agente_ia.services.orquestador.enviar_respuesta_agente')
    def test_manana_guarda_preferencia_sin_aceptar(self, mock_env):
        self.sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION
        self.sesion.save(update_fields=['estado'])
        result = procesar_turno_esperando_aceptacion(
            sesion=self.sesion,
            texto_cliente='Puede ser mañana a las 9 am',
            conversation=self.conversation,
            proveedor_user_id=self.user.id,
        )
        self.assertEqual(result['accion'], 'preferencia_sin_aceptar')
        self.sesion.refresh_from_db()
        pref = self.sesion.datos_capturados.get('preferencias_agenda') or {}
        self.assertTrue(pref.get('fecha'))
        self.assertEqual(pref.get('hora'), '09:00')
        self.assertFalse(pref.get('confirmado_verbal'))
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.estado, 'enviada')
        texto = mock_env.call_args.kwargs.get('texto') or ''
        self.assertIn('aceptar', texto.lower())
        self.assertNotIn('quedamos listos', texto.lower())

    @patch('mecanimovilapp.apps.agente_ia.tasks.iniciar_agendamiento_task.delay')
    @patch('mecanimovilapp.apps.agente_ia.tasks.aprender_conversacion_exitosa_task.delay')
    @patch('mecanimovilapp.apps.agente_ia.services.notificaciones.notificar_cotizacion_aceptada_agente')
    def test_me_parece_ok_acepta_y_crea_cita(self, _notif, _learn, mock_delay):
        self.sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION
        self.sesion.save(update_fields=['estado'])
        result = aceptar_desde_agente(
            sesion=self.sesion,
            cotizacion=self.cot,
            conversation=self.conversation,
        )
        self.assertEqual(result['accion'], 'aceptada')
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.estado, 'aceptada')
        self.assertIsNotNone(self.cot.aceptada_en)
        self.assertEqual(self.cot.citas_generadas.count(), 1)
        cita = self.cot.citas_generadas.first()
        self.assertEqual(cita.duracion_minutos, 360)
        mock_delay.assert_called_once_with(self.cot.id)

    @patch('mecanimovilapp.apps.agente_ia.tasks.iniciar_agendamiento_task.delay')
    @patch('mecanimovilapp.apps.agente_ia.tasks.aprender_conversacion_exitosa_task.delay')
    @patch('mecanimovilapp.apps.agente_ia.services.notificaciones.notificar_cotizacion_aceptada_agente')
    def test_segunda_aceptacion_no_duplica_cita(self, _notif, _learn, mock_delay):
        aceptar_desde_agente(
            sesion=self.sesion,
            cotizacion=self.cot,
            conversation=self.conversation,
        )
        self.cot.refresh_from_db()
        mock_delay.reset_mock()
        result = aceptar_desde_agente(
            sesion=self.sesion,
            cotizacion=self.cot,
            conversation=self.conversation,
        )
        self.assertEqual(result['accion'], 'ya_aceptada')
        self.assertEqual(self.cot.citas_generadas.count(), 1)

    @patch('mecanimovilapp.apps.agente_ia.services.orquestador.enviar_respuesta_agente')
    def test_ok_ambiguo_pide_confirmacion(self, mock_env):
        self.sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION
        self.sesion.save(update_fields=['estado'])
        result = procesar_turno_esperando_aceptacion(
            sesion=self.sesion,
            texto_cliente='ok',
            conversation=self.conversation,
            proveedor_user_id=self.user.id,
        )
        self.assertEqual(result['accion'], 'confirmar_aceptacion')
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.estado, 'enviada')
        texto = mock_env.call_args.kwargs.get('texto') or ''
        self.assertIn('aceptas', texto.lower())

    def test_resolver_embrague_aunque_estimada_sea_60(self):
        self.cot.duracion_minutos_estimada = 60
        self.cot.save(update_fields=['duracion_minutos_estimada'])
        self.assertEqual(resolver_duracion_trabajo(self.cot), 360)


class IniciarAgendamientoTaskTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(
            username='taller_task',
            email='taller_task@mecanimovil.cl',
            password='Password123!',
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Task',
        )

    def test_sin_conversacion_silencio(self):
        cot = CotizacionCanal.objects.create(
            conversation=None,
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            modalidad='taller',
            servicio_nombre='Cambio de aceite',
            total_clp=40000,
        )
        result = iniciar_agendamiento_task(cot.id)
        self.assertEqual(result, {'ok': False, 'reason': 'sin_conversacion'})

    def test_agente_off_no_escribe(self):
        conv = Conversation.objects.create(source_channel='WHATSAPP')
        conv.participants.add(self.user)
        cot = CotizacionCanal.objects.create(
            conversation=conv,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            modalidad='taller',
            servicio_nombre='Cambio de aceite',
            total_clp=40000,
        )
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            crear_cita_desde_cotizacion_aceptada,
        )

        crear_cita_desde_cotizacion_aceptada(cot)
        AgenteConversacionSesion.objects.create(
            conversation=conv,
            taller=self.taller,
            cotizacion_borrador=cot,
            habilitado_en_chat=False,
            estado=AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION,
        )
        result = iniciar_agendamiento_task(cot.id)
        self.assertEqual(result.get('reason'), 'agente_off')

    @patch('mecanimovilapp.apps.agente_ia.tasks.iniciar_agendamiento_task.delay')
    @patch('mecanimovilapp.apps.agente_ia.tasks.aprender_conversacion_exitosa_task.delay')
    @patch('mecanimovilapp.apps.agente_ia.services.notificaciones.notificar_cotizacion_aceptada_agente')
    def test_pagina_con_chat_encola_agenda(self, _notif, _learn, mock_delay):
        conv = Conversation.objects.create(source_channel='WHATSAPP')
        conv.participants.add(self.user)
        cot = CotizacionCanal.objects.create(
            conversation=conv,
            taller=self.taller,
            creado_por=self.user,
            estado='enviada',
            modalidad='taller',
            servicio_nombre='Diagnóstico',
            total_clp=30000,
            enviada_en=timezone.now(),
        )
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            aceptar_cotizacion_publica,
        )

        cot, cita = aceptar_cotizacion_publica(cot)
        on_cotizacion_respondida(cot, 'aceptar', conversation=conv, cita_id=cita.id)
        mock_delay.assert_called_once_with(cot.id)


class DisponibilidadDuracionOverrideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = Usuario.objects.create_user(
            username='taller_dur',
            email='taller_dur@mecanimovil.cl',
            password='x',
        )
        cls.taller = Taller.objects.create(
            usuario=user,
            nombre='Taller Duración',
            estado_verificacion='aprobado',
            activo=True,
        )
        HorarioProveedor.objects.create(
            taller=cls.taller,
            dia_semana=0,
            activo=True,
            hora_inicio=time(8, 0),
            hora_fin=time(18, 0),
            duracion_slot=60,
            tiempo_descanso=0,
        )

    def test_embrague_360_no_ofrece_1600(self):
        data = disponibilidad_con_duracion(
            taller=self.taller,
            fecha=date(2030, 1, 7),
            duracion_minutos=360,
        )
        horas = {s['hora'] for s in data.get('slots_disponibles') or []}
        self.assertTrue(data['proveedor_disponible'])
        self.assertEqual(data['duracion_servicio_solicitado']['maximo'], 360)
        self.assertNotIn('16:00', horas)
        self.assertIn('08:00', horas)
        self.assertIn('10:00', horas)

    def test_diagnostico_60_si_ofrece_1630(self):
        data = disponibilidad_con_duracion(
            taller=self.taller,
            fecha=date(2030, 1, 7),
            duracion_minutos=60,
        )
        horas = {s['hora'] for s in data.get('slots_disponibles') or []}
        self.assertIn('16:30', horas)
        self.assertEqual(data['duracion_servicio_solicitado']['maximo'], 60)

"""Tests de naturalidad (anti-muletillas) y seguimiento proactivo del agente IA."""
from __future__ import annotations

from django.test import TestCase

from mecanimovilapp.apps.agente_ia.models import LeadCalificacion, TallerAgenteConfig
from mecanimovilapp.apps.agente_ia.services.orquestador import _sanitizar_muletillas_robot
from mecanimovilapp.apps.agente_ia.services.seguimiento_proactivo import (
    documentar_lead_perdido,
    es_respuesta_perdida_competencia,
)
from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.usuarios.models import Taller, Usuario


class AgenteNaturalidadYSeguimientoTestCase(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(
            email='taller_test_seguimiento@mecanimovil.cl',
            password='Password123!',
            nombre='Taller Test',
            rol='proveedor',
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller MecaniTest',
            rut='11111111-1',
        )
        self.config = TallerAgenteConfig.objects.create(
            taller=self.taller,
            habilitado=True,
            nombre_agente='Carlos',
        )
        self.conversation = Conversation.objects.create(
            source_channel='WHATSAPP',
            external_user_id='+56911223344',
        )

    def test_sanitizar_muletillas_robot_inicio(self):
        textos = [
            "Entendido. Te comento que para la revisión de frenos podemos agendar el jueves.",
            "Perfecto, ya tengo tu teléfono 912345678. Te armo el borrador.",
            "Con mucho gusto te ayudo con la mantención de tu auto.",
        ]
        limpios = _sanitizar_muletillas_robot(textos)
        self.assertEqual(len(limpios), 3)
        self.assertFalse(limpios[0].startswith("Entendido"))
        self.assertTrue(limpios[0].startswith("Te comento"))
        self.assertFalse("ya tengo tu teléfono" in limpios[1].lower())
        self.assertFalse(limpios[2].startswith("Con mucho gusto"))

    def test_sanitizar_muletillas_robot_cierre(self):
        textos = [
            "El cambio de aceite incluye filtro de aceite y mano de obra. Quedo atento a tu respuesta.",
            "Podemos coordinar la visita a domicilio. No dudes en escribirme si tienes dudas.",
        ]
        limpios = _sanitizar_muletillas_robot(textos)
        self.assertEqual(len(limpios), 2)
        self.assertFalse("Quedo atento" in limpios[0])
        self.assertFalse("No dudes" in limpios[1])

    def test_es_respuesta_perdida_competencia(self):
        self.assertTrue(es_respuesta_perdida_competencia("Hola, ya lo llevé a otro taller"))
        self.assertTrue(es_respuesta_perdida_competencia("Muchas gracias, pero ya lo arreglé con otro mecánico"))
        self.assertTrue(es_respuesta_perdida_competencia("Lo solucioné en otro lado más barato"))
        self.assertFalse(es_respuesta_perdida_competencia("Hola, quiero cotizar cambio de pastillas"))
        self.assertFalse(es_respuesta_perdida_competencia("¿Tienen disponibilidad para mañana?"))

    def test_documentar_lead_perdido(self):
        documentar_lead_perdido(
            conversation_id=self.conversation.id,
            taller_id=self.taller.id,
            motivo='competencia',
        )
        lead = LeadCalificacion.objects.get(conversation_id=self.conversation.id)
        self.assertTrue(lead.perdido_por_competencia)
        self.assertEqual(lead.motivo_perdida, 'competencia')
        self.assertTrue(lead.senales.get('competencia'))

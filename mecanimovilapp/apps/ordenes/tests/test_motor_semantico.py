"""Tests capa semántica (local y proveedores gratuitos, sin APIs de pago)."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_necesidad import analizar_necesidad
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_semantico import (
    analizar_semantico_lexico_local,
    integrar_llm_en_resultado,
    normalizar_salida_semantica,
    parsear_respuesta_semantica,
    semantico_habilitado,
)
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()


class MotorSemanticoParseTests(SimpleTestCase):
    def test_parsea_json(self):
        data = parsear_respuesta_semantica(
            '{"interpretacion": "Frenos", "servicio_ids": [1]}'
        )
        self.assertEqual(data['interpretacion'], 'Frenos')

    def test_normaliza_ids(self):
        out = normalizar_salida_semantica(
            {'interpretacion': 'Ok', 'servicio_ids': [1, 99]},
            {1},
        )
        self.assertEqual(out['servicio_ids'], [1])


class MotorSemanticoLocalTests(SimpleTestCase):
    def test_lexico_local_detecta_frenos(self):
        s = MagicMock()
        s.id = 10
        s.nombre = 'Cambio de pastillas de frenos'
        s.descripcion = 'Pastillas y discos'
        out = analizar_semantico_lexico_local(
            texto='pedal de freno se va al piso',
            servicios=[s],
        )
        self.assertIsNotNone(out)
        self.assertEqual(out['proveedor'], 'lexico')
        self.assertIn(10, out['servicio_ids'])
        self.assertIn('freno', (out.get('interpretacion') or '').lower())


@override_settings(
    AGENDAMIENTO_IA_ASISTIDO=True,
    AGENDAMIENTO_IA_SEMANTICO_ENABLED=True,
    AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR='lexico',
)
class AnalizarNecesidadSemanticoLocalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='sem@test.com',
            email='sem@test.com',
            password='testpass123',
        )
        self.cliente = Cliente.objects.create(
            usuario=self.user,
            nombre='Sem',
            apellido='Test',
            email='sem@test.com',
        )
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Yaris', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2019,
            patente='SEM001',
        )
        self.servicio_freno = Servicio.objects.create(
            nombre='Cambio de pastillas de frenos',
            descripcion='Frenos delanteros',
            precio_base=60000,
        )
        self.servicio_freno.modelos_compatibles.add(self.modelo)

    def test_motor_analisis_lexico_sin_api(self):
        result = analizar_necesidad(
            texto='pedal de freno se va al piso',
            vehiculo_id=self.vehiculo.id,
        )
        self.assertTrue(semantico_habilitado())
        self.assertIn(result['motor_analisis'], ('lexico', 'semantico'))
        self.assertTrue(result['servicios_recomendados'])
        self.assertEqual(
            result['servicios_recomendados'][0]['servicio_id'],
            self.servicio_freno.id,
        )

    def test_integrar_prioriza_semantico(self):
        servicio = self.servicio_freno
        base = {'servicios_recomendados': [], 'interpretacion': 'vieja'}
        llm = {
            'servicio_ids': [servicio.id],
            'razones_por_servicio': {servicio.id: 'Pedal al piso'},
            'interpretacion': 'Revisión de frenos',
            'proveedor': 'lexico',
        }
        out = integrar_llm_en_resultado(base, llm, [servicio])
        self.assertEqual(out['motor_analisis'], 'lexico')
        self.assertEqual(out['servicios_recomendados'][0]['servicio_id'], servicio.id)


@override_settings(
    AGENDAMIENTO_IA_ASISTIDO=True,
    AGENDAMIENTO_IA_SEMANTICO_ENABLED=True,
    AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR='gemini',
    GEMINI_API_KEY='fake',
)
class AnalizarNecesidadGeminiFallbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='gem@test.com',
            email='gem@test.com',
            password='testpass123',
        )
        self.cliente = Cliente.objects.create(
            usuario=self.user,
            nombre='Gem',
            apellido='Test',
            email='gem@test.com',
        )
        self.marca = Marca.objects.create(nombre='Kia')
        self.modelo = Modelo.objects.create(nombre='Rio', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2020,
            patente='GEM001',
        )
        self.servicio = Servicio.objects.create(
            nombre='Cambio de batería',
            descripcion='Batería 60Ah',
            precio_base=50000,
        )
        self.servicio.modelos_compatibles.add(self.modelo)

    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_semantico._llamar_gemini'
    )
    def test_fallback_lexico_si_gemini_falla(self, mock_gemini):
        mock_gemini.return_value = None
        result = analizar_necesidad(
            texto='no arranca hace clic',
            vehiculo_id=self.vehiculo.id,
        )
        self.assertIn(result['motor_analisis'], ('lexico', 'lexico_fallback', 'semantico'))
        nombres = ' '.join(s['nombre'].lower() for s in result['servicios_recomendados'])
        self.assertIn('bater', nombres)

"""
Tests del asistente de agendamiento IA (consultas stateless).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_necesidad import (
    analizar_necesidad,
    calcular_temperatura,
)
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()


@override_settings(AGENDAMIENTO_IA_ASISTIDO=True)
class AnalizarNecesidadSinPersistenciaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='cliente_ia@test.com',
            email='cliente_ia@test.com',
            password='testpass123',
        )
        self.cliente = Cliente.objects.create(
            usuario=self.user,
            nombre='Test',
            apellido='Cliente',
            email='cliente_ia@test.com',
        )
        self.marca = Marca.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Corolla', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=self.marca,
            modelo=self.modelo,
            year=2020,
            patente='IA1234',
        )
        self.servicio = Servicio.objects.create(
            nombre='Cambio pastillas de freno',
            descripcion='Pastillas y discos frenos delanteros',
            precio_base=50000,
        )
        self.servicio.modelos_compatibles.add(self.modelo)

    def test_temperatura_sub_e_con_urgencia(self):
        t, label = calcular_temperatura('urgente no frena en la ruta', None)
        self.assertGreater(t, 0.5)
        self.assertIn(label, ('urgente', 'atencion'))

    def test_analizar_no_crea_solicitudes(self):
        antes = SolicitudServicioPublica.objects.count()
        result = analizar_necesidad(
            texto='ruido al frenar pedal blando',
            vehiculo_id=self.vehiculo.id,
        )
        despues = SolicitudServicioPublica.objects.count()
        self.assertEqual(antes, despues)
        self.assertIn('servicios_recomendados', result)
        self.assertIn('temperatura', result)

    def test_api_analizar_necesidad(self):
        api = APIClient()
        api.force_authenticate(user=self.user)
        url = reverse('ordenes:asistente-agendamiento-analizar-necesidad')
        antes = SolicitudServicioPublica.objects.count()
        resp = api.post(
            url,
            {
                'texto': 'pastillas freno desgastadas',
                'vehiculo_id': self.vehiculo.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(SolicitudServicioPublica.objects.count(), antes)
        self.assertIsNotNone(resp.data.get('servicios_recomendados'))


@override_settings(AGENDAMIENTO_IA_ASISTIDO=False)
class AsistenteFlagDeshabilitadoTests(TestCase):
    def test_403_si_flag_off(self):
        user = User.objects.create_user(
            username='off@test.com',
            email='off@test.com',
            password='testpass123',
        )
        Cliente.objects.create(
            usuario=user,
            nombre='Off',
            apellido='User',
            email='off@test.com',
        )
        api = APIClient()
        api.force_authenticate(user=user)
        url = reverse('ordenes:asistente-agendamiento-analizar-necesidad')
        resp = api.post(url, {'texto': 'hola'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

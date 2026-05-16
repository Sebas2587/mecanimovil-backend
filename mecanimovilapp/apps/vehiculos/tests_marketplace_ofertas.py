from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo, OfertaVehiculo, MarcaVehiculo, Modelo

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class OfertaVehiculoUnicaPorVendedorTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.seller_user = User.objects.create_user(
            username='seller_of', password='password123', email='seller_of@example.com'
        )
        self.seller_client = Cliente.objects.create(
            usuario=self.seller_user, nombre='Vendedor', apellido='Ofertas'
        )
        self.buyer_user = User.objects.create_user(
            username='buyer_of', password='password123', email='buyer_of@example.com'
        )
        Cliente.objects.create(usuario=self.buyer_user, nombre='Comprador', apellido='Ofertas')

        self.marca = MarcaVehiculo.objects.create(nombre='Honda')
        self.modelo = Modelo.objects.create(nombre='Civic', marca=self.marca)
        self.vehiculo_a = Vehiculo.objects.create(
            marca=self.marca,
            modelo=self.modelo,
            cliente=self.seller_client,
            patente='OFRT01',
        )
        self.vehiculo_b = Vehiculo.objects.create(
            marca=self.marca,
            modelo=self.modelo,
            cliente=self.seller_client,
            patente='OFRT02',
        )

    def _create_offer_payload(self, vehiculo):
        return {'vehiculo': vehiculo.id, 'monto': 3_000_000, 'mensaje': 'Oferta test'}

    def test_segunda_oferta_mismo_vendedor_rechazada(self):
        self.api.force_authenticate(user=self.buyer_user)
        r1 = self.api.post('/api/vehiculos/ofertas/', self._create_offer_payload(self.vehiculo_a))
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)

        r2 = self.api.post('/api/vehiculos/ofertas/', self._create_offer_payload(self.vehiculo_b))
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('oferta activa', str(r2.data).lower())

    def test_nueva_oferta_tras_rechazo(self):
        OfertaVehiculo.objects.create(
            vehiculo=self.vehiculo_a,
            comprador=self.buyer_user,
            monto=2_000_000,
            estado='rechazada',
        )
        self.api.force_authenticate(user=self.buyer_user)
        response = self.api.post('/api/vehiculos/ofertas/', self._create_offer_payload(self.vehiculo_b))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_puede_ofertar_endpoint(self):
        OfertaVehiculo.objects.create(
            vehiculo=self.vehiculo_a,
            comprador=self.buyer_user,
            monto=2_000_000,
            estado='pendiente',
        )
        self.api.force_authenticate(user=self.buyer_user)
        response = self.api.get(
            '/api/vehiculos/ofertas/puede_ofertar/',
            {'vehiculo_id': self.vehiculo_b.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['puede_ofertar'])
        self.assertEqual(response.data['code'], 'oferta_activa_mismo_vendedor')

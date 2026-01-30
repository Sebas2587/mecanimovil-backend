from django.test import TestCase
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.vehiculos.models import Vehiculo, OfertaVehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.usuarios.models import Cliente
from .models import TransferenciaVehiculo
from rest_framework.test import APIClient
from rest_framework import status
import uuid

User = get_user_model()

class TransferenciaVehiculoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        # Setup Seller
        self.seller_user = User.objects.create_user(username='seller', password='password123', email='seller@example.com')
        self.seller_client = Cliente.objects.create(usuario=self.seller_user, nombre='Vendedor', apellido='Test')
        
        # Setup Buyer
        self.buyer_user = User.objects.create_user(username='buyer', password='password123', email='buyer@example.com')
        
        # Setup Vehicle
        self.marca = MarcaVehiculo.objects.create(nombre='Toyota')
        self.modelo = Modelo.objects.create(nombre='Corolla', marca=self.marca)
        self.vehiculo = Vehiculo.objects.create(
            marca=self.marca, 
            modelo=self.modelo, 
            cliente=self.seller_client,
            patente='ABCD12'
        )
        
        # Setup Offer
        self.offer = OfertaVehiculo.objects.create(
            vehiculo=self.vehiculo,
            comprador=self.buyer_user,
            monto=5000000,
            estado='aceptada'
        )

    def test_generate_token_success(self):
        """Test que el dueño puede generar un token para una oferta aceptada"""
        self.client.force_authenticate(user=self.seller_user)
        response = self.client.post('/api/marketplace/transferencias/generate_transfer_token/', {'offer_id': self.offer.id})
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertIn('qr_data', response.data)
        
        # Verificar que se creó en DB
        transfer = TransferenciaVehiculo.objects.first()
        self.assertIsNotNone(transfer)
        self.assertEqual(transfer.token_transferencia, response.data['token'])

    def test_generate_token_not_owner(self):
        """Test que un no-dueño no puede generar el token"""
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.post('/api/marketplace/transferencias/generate_transfer_token/', {'offer_id': self.offer.id})
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_complete_transfer_success(self):
        """Test completo de transferencia"""
        # 1. Generar token (backend side)
        transfer = TransferenciaVehiculo.objects.create(
            vehiculo=self.vehiculo,
            vendedor=self.seller_user,
            comprador=self.buyer_user,
            oferta_asociada=self.offer,
            qr_data="test_data"
        )
        token = transfer.token_transferencia
        
        # 2. Ejecutar complete_transfer como comprador
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.post('/api/marketplace/transferencias/complete_transfer/', {'token': token})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 3. Verificaciones post-transferencia
        self.vehiculo.refresh_from_db()
        transfer.refresh_from_db()
        self.offer.refresh_from_db()
        
        # Nuevo dueño
        self.assertEqual(self.vehiculo.cliente.usuario, self.buyer_user)
        # Estado completado
        self.assertEqual(transfer.estado, 'COMPLETADO')
        # Oferta cerrada
        self.assertEqual(self.offer.estado, 'completada')

    def test_complete_transfer_wrong_user(self):
        """Test que otro usuario no puede usar el token"""
        transfer = TransferenciaVehiculo.objects.create(
            vehiculo=self.vehiculo,
            vendedor=self.seller_user,
            comprador=self.buyer_user,
            oferta_asociada=self.offer,
            qr_data="test_data"
        )
        token = transfer.token_transferencia
        
        other_user = User.objects.create_user(username='thief', password='password123')
        self.client.force_authenticate(user=other_user)
        
        response = self.client.post('/api/marketplace/transferencias/complete_transfer/', {'token': token})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

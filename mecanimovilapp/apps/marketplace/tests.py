from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from mecanimovilapp.apps.vehiculos.models import Vehiculo, OfertaVehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.usuarios.models import Cliente
from .models import TransferenciaVehiculo
from rest_framework.test import APIClient
from rest_framework import status
import uuid

User = get_user_model()

@override_settings(SECURE_SSL_REDIRECT=False)
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

    def test_generate_token_second_call_reuses_pending(self):
        """Segundo POST con misma oferta no duplica fila (OneToOne) y devuelve el mismo token."""
        self.client.force_authenticate(user=self.seller_user)
        r1 = self.client.post(
            '/api/marketplace/transferencias/generate_transfer_token/',
            {'offer_id': self.offer.id},
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        token1 = r1.data['token']

        r2 = self.client.post(
            '/api/marketplace/transferencias/generate_transfer_token/',
            {'offer_id': self.offer.id},
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data['token'], token1)
        self.assertEqual(TransferenciaVehiculo.objects.filter(oferta_asociada=self.offer).count(), 1)

    def test_generate_token_after_expiry_regenerates_same_row(self):
        """Si el token venció, se reutiliza la misma fila y no viola la restricción única."""
        self.client.force_authenticate(user=self.seller_user)
        r1 = self.client.post(
            '/api/marketplace/transferencias/generate_transfer_token/',
            {'offer_id': self.offer.id},
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        transfer = TransferenciaVehiculo.objects.get(oferta_asociada=self.offer)
        transfer.fecha_expiracion = timezone.now() - timezone.timedelta(minutes=1)
        transfer.save(update_fields=['fecha_expiracion'])

        r2 = self.client.post(
            '/api/marketplace/transferencias/generate_transfer_token/',
            {'offer_id': self.offer.id},
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertNotEqual(r2.data['token'], r1.data['token'])
        self.assertEqual(TransferenciaVehiculo.objects.filter(oferta_asociada=self.offer).count(), 1)

    def test_generate_token_fails_when_already_completed(self):
        """No se puede generar QR si la transferencia ya se completó."""
        TransferenciaVehiculo.objects.create(
            vehiculo=self.vehiculo,
            vendedor=self.seller_user,
            comprador=self.buyer_user,
            oferta_asociada=self.offer,
            qr_data='{}',
            estado='COMPLETADO',
        )
        self.client.force_authenticate(user=self.seller_user)
        response = self.client.post(
            '/api/marketplace/transferencias/generate_transfer_token/',
            {'offer_id': self.offer.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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

    def test_generate_token_by_vehicle_id(self):
        """P2P: el dueño genera QR desde la ficha del vehículo sin oferta."""
        self.client.force_authenticate(user=self.seller_user)
        response = self.client.post(
            '/api/marketplace/transferencias/generate_transfer_token/',
            {'vehicle_id': self.vehiculo.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertIn('transfer_id', response.data)
        transfer = TransferenciaVehiculo.objects.get(id=response.data['transfer_id'])
        self.assertIsNone(transfer.oferta_asociada_id)
        self.assertIsNone(transfer.comprador_id)
        self.assertEqual(transfer.estado, 'PENDIENTE')

    def test_complete_p2p_transfer_any_authenticated_buyer(self):
        """P2P: quien escanea el QR (distinto del vendedor) se convierte en dueño."""
        transfer = TransferenciaVehiculo.objects.create(
            vehiculo=self.vehiculo,
            vendedor=self.seller_user,
            comprador=None,
            oferta_asociada=None,
            qr_data='{}',
        )
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.post(
            '/api/marketplace/transferencias/complete_transfer/',
            {'token': transfer.token_transferencia},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.vehiculo.refresh_from_db()
        transfer.refresh_from_db()
        self.assertEqual(self.vehiculo.cliente.usuario, self.buyer_user)
        self.assertEqual(transfer.estado, 'COMPLETADO')
        self.assertEqual(transfer.comprador_id, self.buyer_user.id)

    def test_complete_p2p_rejects_seller_self_transfer(self):
        transfer = TransferenciaVehiculo.objects.create(
            vehiculo=self.vehiculo,
            vendedor=self.seller_user,
            comprador=None,
            oferta_asociada=None,
            qr_data='{}',
        )
        self.client.force_authenticate(user=self.seller_user)
        response = self.client.post(
            '/api/marketplace/transferencias/complete_transfer/',
            {'token': transfer.token_transferencia},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_transfer_status_polling(self):
        transfer = TransferenciaVehiculo.objects.create(
            vehiculo=self.vehiculo,
            vendedor=self.seller_user,
            comprador=None,
            oferta_asociada=None,
            qr_data='{}',
        )
        self.client.force_authenticate(user=self.seller_user)
        response = self.client.get(
            '/api/marketplace/transferencias/transfer_status/',
            {'transfer_id': transfer.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['estado'], 'PENDIENTE')
        self.assertEqual(response.data['vehicle_id'], self.vehiculo.id)

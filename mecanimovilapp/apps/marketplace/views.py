from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import TransferenciaVehiculo
from mecanimovilapp.apps.vehiculos.models import Vehiculo, OfertaVehiculo
from mecanimovilapp.apps.usuarios.models import Cliente
import logging
import json
import uuid
import secrets

logger = logging.getLogger(__name__)


def _vehicle_display_name(vehiculo):
    marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
    modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
    return f"{marca} {modelo}".strip() or 'Vehículo'


def _user_display_name(user):
    if not user:
        return ''
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username or user.email or 'Usuario'


def _serialize_token_response(transferencia, http_status=status.HTTP_200_OK):
    return Response(
        {
            'token': transferencia.token_transferencia,
            'expires_at': transferencia.fecha_expiracion,
            'qr_data': transferencia.qr_data,
            'transfer_id': transferencia.id,
            'vehicle_id': transferencia.vehiculo_id,
            'estado': transferencia.estado,
        },
        status=http_status,
    )


def _regenerate_pending_token(transferencia, qr_json):
    transferencia.token_transferencia = secrets.token_urlsafe(32)
    transferencia.fecha_expiracion = timezone.now() + timezone.timedelta(minutes=15)
    transferencia.qr_data = qr_json
    transferencia.estado = 'PENDIENTE'
    transferencia.save()
    return transferencia


class TransferenciaViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'])
    def generate_transfer_token(self, request):
        """
        Genera QR de transferencia.
        Preferido: vehicle_id (P2P desde ficha del vehículo).
        Legacy: offer_id (oferta marketplace aceptada).
        """
        vehicle_id = request.data.get('vehicle_id')
        offer_id = request.data.get('offer_id')

        if not vehicle_id and not offer_id:
            return Response(
                {'error': 'vehicle_id o offer_id es requerido'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if vehicle_id:
                return self._generate_for_vehicle(request, vehicle_id)
            return self._generate_for_offer(request, offer_id)
        except Vehiculo.DoesNotExist:
            return Response({'error': 'Vehículo no encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except OfertaVehiculo.DoesNotExist:
            return Response({'error': 'Oferta no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error generando token de transferencia: {e}")
            return Response(
                {'error': 'Error interno del servidor'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _generate_for_vehicle(self, request, vehicle_id):
        vehiculo = Vehiculo.objects.select_related('cliente__usuario', 'marca', 'modelo').get(id=vehicle_id)

        if not vehiculo.cliente or vehiculo.cliente.usuario_id != request.user.id:
            return Response(
                {'error': 'No eres el dueño de este vehículo'},
                status=status.HTTP_403_FORBIDDEN,
            )

        qr_payload = {
            't_id': str(uuid.uuid4()),
            'v_id': vehiculo.id,
            'type': 'transfer_vehicle',
        }
        qr_json = json.dumps(qr_payload)

        with transaction.atomic():
            transferencia = (
                TransferenciaVehiculo.objects.select_for_update()
                .filter(vehiculo=vehiculo, vendedor=request.user, oferta_asociada__isnull=True)
                .exclude(estado='COMPLETADO')
                .order_by('-fecha_creacion')
                .first()
            )

            if transferencia is None:
                transferencia = TransferenciaVehiculo.objects.create(
                    vehiculo=vehiculo,
                    vendedor=request.user,
                    comprador=None,
                    oferta_asociada=None,
                    qr_data=qr_json,
                )
                return _serialize_token_response(transferencia, status.HTTP_201_CREATED)

            if transferencia.estado == 'PENDIENTE' and not transferencia.is_expired:
                return _serialize_token_response(transferencia, status.HTTP_200_OK)

            _regenerate_pending_token(transferencia, qr_json)
            return _serialize_token_response(transferencia, status.HTTP_200_OK)

    def _generate_for_offer(self, request, offer_id):
        oferta = OfertaVehiculo.objects.select_related(
            'vehiculo', 'vehiculo__cliente__usuario'
        ).get(id=offer_id)

        if oferta.vehiculo.cliente.usuario != request.user:
            return Response(
                {'error': 'No eres el dueño de este vehículo'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if oferta.estado != 'aceptada':
            return Response(
                {'error': f'La oferta debe estar aceptada. Estado actual: {oferta.estado}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qr_payload = {
            't_id': str(uuid.uuid4()),
            'o_id': oferta.id,
            'v_id': oferta.vehiculo.id,
            'type': 'transfer_vehicle',
        }
        qr_json = json.dumps(qr_payload)

        with transaction.atomic():
            transferencia = (
                TransferenciaVehiculo.objects.select_for_update()
                .filter(oferta_asociada=oferta)
                .first()
            )
            if transferencia is None:
                try:
                    transferencia = TransferenciaVehiculo.objects.create(
                        vehiculo=oferta.vehiculo,
                        vendedor=request.user,
                        comprador=oferta.comprador,
                        oferta_asociada=oferta,
                        qr_data=qr_json,
                    )
                except IntegrityError:
                    transferencia = (
                        TransferenciaVehiculo.objects.select_for_update()
                        .get(oferta_asociada=oferta)
                    )
                else:
                    return _serialize_token_response(transferencia, status.HTTP_201_CREATED)

            if transferencia.estado == 'COMPLETADO':
                return Response(
                    {'error': 'La transferencia para esta oferta ya fue completada.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if transferencia.estado == 'PENDIENTE' and not transferencia.is_expired:
                return _serialize_token_response(transferencia, status.HTTP_200_OK)

            _regenerate_pending_token(transferencia, qr_json)
            return _serialize_token_response(transferencia, status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def transfer_status(self, request):
        """Polling del vendedor: ¿ya escaneó el comprador?"""
        transfer_id = request.query_params.get('transfer_id')
        if not transfer_id:
            return Response(
                {'error': 'transfer_id es requerido'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            transferencia = TransferenciaVehiculo.objects.select_related(
                'vehiculo', 'vehiculo__marca', 'vehiculo__modelo', 'comprador', 'vendedor'
            ).get(id=transfer_id)
        except TransferenciaVehiculo.DoesNotExist:
            return Response({'error': 'Transferencia no encontrada'}, status=status.HTTP_404_NOT_FOUND)

        if transferencia.vendedor_id != request.user.id and transferencia.comprador_id != request.user.id:
            return Response({'error': 'No autorizado'}, status=status.HTTP_403_FORBIDDEN)

        if transferencia.estado == 'PENDIENTE' and transferencia.is_expired:
            transferencia.estado = 'EXPIRADO'
            transferencia.save(update_fields=['estado', 'fecha_actualizacion'])

        return Response({
            'transfer_id': transferencia.id,
            'estado': transferencia.estado,
            'vehicle_id': transferencia.vehiculo_id,
            'vehicle_name': _vehicle_display_name(transferencia.vehiculo),
            'vehicle_year': getattr(transferencia.vehiculo, 'year', '') or '',
            'new_owner': _user_display_name(transferencia.comprador),
            'expires_at': transferencia.fecha_expiracion,
        })

    @action(detail=False, methods=['post'])
    def complete_transfer(self, request):
        """
        Completa la transferencia escaneando el token/QR.
        P2P: cualquier usuario autenticado distinto del vendedor puede reclamar.
        Legacy: si hay comprador preasignado, solo ese usuario.
        """
        token = request.data.get('token')

        if not token:
            return Response({'error': 'Token es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            transferencia = TransferenciaVehiculo.objects.select_related(
                'vehiculo', 'vehiculo__marca', 'vehiculo__modelo',
                'oferta_asociada', 'comprador', 'vendedor',
            ).get(token_transferencia=token)

            if transferencia.is_expired:
                transferencia.estado = 'EXPIRADO'
                transferencia.save(update_fields=['estado', 'fecha_actualizacion'])
                return Response(
                    {'error': 'El token de transferencia ha expirado'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if transferencia.estado != 'PENDIENTE':
                return Response(
                    {'error': f'Esta transferencia ya está {transferencia.estado}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if transferencia.vendedor_id == request.user.id:
                return Response(
                    {'error': 'No puedes transferirte el vehículo a ti mismo'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if transferencia.comprador_id and transferencia.comprador_id != request.user.id:
                return Response(
                    {'error': 'No eres el comprador autorizado para esta transferencia'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            with transaction.atomic():
                cliente_comprador, _ = Cliente.objects.get_or_create(
                    usuario=request.user,
                    defaults={
                        'nombre': request.user.first_name,
                        'apellido': request.user.last_name,
                        'email': request.user.email,
                    },
                )

                vehiculo = transferencia.vehiculo
                vehiculo.cliente = cliente_comprador
                if hasattr(vehiculo, 'is_published'):
                    vehiculo.is_published = False
                if hasattr(vehiculo, 'precio_venta'):
                    vehiculo.precio_venta = None
                vehiculo.save()

                transferencia.comprador = request.user
                transferencia.estado = 'COMPLETADO'
                transferencia.save()

                oferta = transferencia.oferta_asociada
                if oferta is not None:
                    oferta.estado = 'completada'
                    oferta.save(update_fields=['estado'])

                logger.info(
                    "VEHICULO TRANSFERIDO: VehicleID=%s de UserID=%s a UserID=%s",
                    vehiculo.id,
                    transferencia.vendedor_id,
                    request.user.id,
                )

            return Response({
                'status': 'success',
                'message': 'Vehículo transferido exitosamente',
                'vehicle_id': vehiculo.id,
                'vehicle_name': _vehicle_display_name(vehiculo),
                'vehicle_year': getattr(vehiculo, 'year', '') or '',
                'vehicle_cilindrada': getattr(vehiculo, 'cilindraje', None) or '',
                'new_owner': request.user.username,
                'new_owner_name': _user_display_name(request.user),
                'new_owner_email': request.user.email,
                'seller_name': _user_display_name(transferencia.vendedor),
            })

        except TransferenciaVehiculo.DoesNotExist:
            return Response({'error': 'Token inválido'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error procesando transferencia: {e}")
            return Response(
                {'error': 'Error procesando la transferencia'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

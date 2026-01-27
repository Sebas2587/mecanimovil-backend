import json
import logging
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from .models import MecanicoDomicilio, Taller, ConnectionStatus

User = get_user_model()
logger = logging.getLogger(__name__)

class ConnectionConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        """
        Maneja la conexión del WebSocket
        """
        # Obtener el proveedor autenticado
        self.proveedor = await self.get_proveedor()
        
        if not self.proveedor:
            await self.close()
            return
        
        # Obtener información del proveedor de forma async-safe
        proveedor_info = await self.get_proveedor_info()
        
        if not proveedor_info or not proveedor_info['id']:
            logger.error("❌ No se pudo obtener información del proveedor")
            await self.close()
            return
        
        # Marcar como conectado
        await self.marcar_conectado()
        
        # Añadir a grupos
        await self.channel_layer.group_add(
            f"proveedor_{proveedor_info['id']}",
            self.channel_name
        )
        await self.channel_layer.group_add(
            "clientes",
            self.channel_name
        )
        
        # Aceptar la conexión
        await self.accept()
        
        # Inicializar contador de heartbeats para optimización de DB writes
        self.heartbeat_counter = 0
        
        logger.info(f"🔗 WebSocket conectado: {proveedor_info['nombre']}")
        
        # Notificar a todos los clientes sobre el cambio de estado
        await self.channel_layer.group_send(
            "clientes",
            {
                'type': 'connection_status_update',
                'proveedor_id': proveedor_info['id'],
                'usuario_id': proveedor_info.get('usuario_id'),  # ID del Usuario para comparar con otra_persona.id
                'tipo_proveedor': self.tipo_proveedor,
                'esta_conectado': True,
                'nombre_proveedor': proveedor_info['nombre']
            }
        )
        
        # Programar verificación de heartbeat
        await self.programar_verificacion_heartbeat()
    
    async def disconnect(self, close_code):
        """
        Maneja la desconexión del WebSocket
        """
        if hasattr(self, 'proveedor') and self.proveedor:
            try:
                # Obtener información del proveedor de forma async-safe
                proveedor_info = await self.get_proveedor_info()
                
                if proveedor_info and proveedor_info['id']:
                    # Marcar como desconectado
                    await self.marcar_desconectado()
                    
                    # Remover de los grupos
                    await self.channel_layer.group_discard(
                        f"proveedor_{proveedor_info['id']}",
                        self.channel_name
                    )
                    await self.channel_layer.group_discard(
                        "clientes",
                        self.channel_name
                    )
                    
                    logger.info(f"🔌 WebSocket desconectado: {proveedor_info['nombre']}")
                    
                    # Notificar a todos los clientes sobre el cambio de estado
                    await self.channel_layer.group_send(
                        "clientes",
                        {
                            'type': 'connection_status_update',
                            'proveedor_id': proveedor_info['id'],
                            'usuario_id': proveedor_info.get('usuario_id'),  # ID del Usuario para comparar con otra_persona.id
                            'tipo_proveedor': self.tipo_proveedor,
                            'esta_conectado': False,
                            'nombre_proveedor': proveedor_info['nombre']
                        }
                    )
            except Exception as e:
                logger.error(f"❌ Error en disconnect: {e}", exc_info=True)
    
    async def receive(self, text_data):
        """
        Maneja mensajes recibidos del WebSocket
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'heartbeat':
                    await self.actualizar_heartbeat()
            elif message_type == 'status_update':
                new_status = data.get('status', 'online')
                estado_info = await self.actualizar_estado(new_status)
                if estado_info:
                    await self.notificar_cambio_estado(estado_info)
            else:
                logger.warning(f"Tipo de mensaje desconocido: {message_type}")
            
        except json.JSONDecodeError:
            logger.error("❌ Error decodificando JSON del WebSocket")
        except Exception as e:
            logger.error(f"❌ Error procesando mensaje WebSocket: {e}")
    
    async def connection_status_update(self, event):
        """
        Envía actualizaciones de estado a los clientes
        """
        await self.send(text_data=json.dumps({
            'type': 'connection_status_update',
            'proveedor_id': event['proveedor_id'],
            'usuario_id': event.get('usuario_id'),  # ID del Usuario para comparar con otra_persona.id
            'tipo_proveedor': event['tipo_proveedor'],
            'esta_conectado': event.get('esta_conectado', event.get('is_online', False)),
            'nombre_proveedor': event.get('nombre_proveedor', 'Proveedor'),
            'status': event.get('status', 'offline'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def provider_location_update(self, event):
        """
        Envía notificaciones de cambio de ubicación del proveedor a los clientes
        """
        await self.send(text_data=json.dumps({
            'type': 'provider_location_update',
            'proveedor_id': event['proveedor_id'],
            'tipo_proveedor': event['tipo_proveedor'],
            'nombre_proveedor': event['nombre_proveedor'],
            'nueva_direccion': event['nueva_direccion'],
            'nueva_ubicacion': event['nueva_ubicacion'],
            'timestamp': event['timestamp']
        }))
    
    async def nueva_solicitud(self, event):
        """
        Notifica al proveedor sobre una nueva solicitud disponible
        """
        await self.send(text_data=json.dumps({
            'type': 'nueva_solicitud',
            'solicitud_id': event['solicitud_id'],
            'vehiculo': event['vehiculo'],
            'descripcion': event['descripcion'],
            'urgencia': event['urgencia'],
            'fecha_expiracion': event['fecha_expiracion'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def oferta_aceptada(self, event):
        """
        Notifica al proveedor que su oferta fue aceptada
        """
        await self.send(text_data=json.dumps({
            'type': 'oferta_aceptada',
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'solicitud_tradicional_id': event.get('solicitud_tradicional_id'),
            'carrito_id': event.get('carrito_id'),
            'mensaje': event.get('mensaje', '¡Tu oferta fue aceptada!'),
            'estado_oferta': event.get('estado_oferta', 'aceptada'),
            'monto_total': event.get('monto_total'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def pago_en_proceso(self, event):
        """
        Notifica al proveedor que el cliente está procesando el pago
        """
        await self.send(text_data=json.dumps({
            'type': 'pago_en_proceso',
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'mensaje': event.get('mensaje', 'El cliente está procesando el pago.'),
            'estado_oferta': event.get('estado_oferta', 'pendiente_pago'),
            'monto_total': event.get('monto_total'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def pago_completado(self, event):
        """
        Notifica al proveedor que el pago fue completado exitosamente
        """
        await self.send(text_data=json.dumps({
            'type': 'pago_completado',
            'solicitud_id': event['solicitud_id'],
            'solicitud_servicio_id': event.get('solicitud_servicio_id'),
            'oferta_id': event['oferta_id'],
            'mensaje': event.get('mensaje', '¡Pago completado! Servicio confirmado.'),
            'estado_oferta': event.get('estado_oferta', 'pagada'),
            'monto_total': event.get('monto_total'),
            'fecha_servicio': event.get('fecha_servicio'),
            'hora_servicio': event.get('hora_servicio'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def oferta_rechazada(self, event):
        """
        Notifica al proveedor que su oferta fue rechazada
        """
        await self.send(text_data=json.dumps({
            'type': 'oferta_rechazada',
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def solicitud_cancelada(self, event):
        """
        Notifica al proveedor que una solicitud fue cancelada
        """
        await self.send(text_data=json.dumps({
            'type': 'solicitud_cancelada',
            'solicitud_id': event['solicitud_id'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def nuevo_mensaje_chat(self, event):
        """
        Notifica al proveedor sobre un nuevo mensaje en el chat
        """
        await self.send(text_data=json.dumps({
            'type': 'nuevo_mensaje_chat',
            'mensaje_id': event['mensaje_id'],
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'enviado_por': event['enviado_por'],
            'mensaje': event['mensaje'],
            'es_proveedor': event['es_proveedor'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def servicio_iniciado(self, event):
        """
        Notifica al cliente que el proveedor ha iniciado el servicio
        """
        await self.send(text_data=json.dumps({
            'type': 'servicio_iniciado',
            'solicitud_id': event['solicitud_id'],
            'oferta_id': event['oferta_id'],
            'proveedor_nombre': event.get('proveedor_nombre'),
            'mensaje': event.get('mensaje', 'El proveedor ha iniciado el servicio'),
            'timestamp': timezone.now().isoformat()
        }))
    
    async def programar_verificacion_heartbeat(self):
        """
        Programa la verificación de heartbeat para detectar desconexiones
        Optimizado para reducir writes a BD: verifica cada 60s, guarda cada 3min
        """
        # Verificar cada 60 segundos (antes era 30s)
        # OPTIMIZACIÓN: Deshabilitado temporalmente para reducir consumo
        # await asyncio.sleep(60)
        return # Salir inmediatamente para no programar nada
        
        if hasattr(self, 'proveedor') and self.proveedor:
            # Incrementar contador de heartbeats
            self.heartbeat_counter += 1
            
            # Solo guardar a BD cada 3 ciclos (cada 3 minutos)
            # Esto reduce DB writes de ~120/hora a ~20/hora por conexión
            should_save_to_db = (self.heartbeat_counter % 3 == 0)
            
            if should_save_to_db:
                # Verificar si el último heartbeat fue hace más de 120 segundos (2 ciclos)
                connection_status = await self.verificar_ultimo_heartbeat()
                
                if connection_status and not connection_status.esta_conectado:
                    # Obtener información del proveedor de forma async-safe
                    proveedor_info = await self.get_proveedor_info()
                    if proveedor_info and proveedor_info['id']:
                        logger.info(f"🔌 Proveedor {proveedor_info['nombre']} marcado como desconectado por timeout")
                        
                        # Notificar a clientes
                        await self.channel_layer.group_send(
                            "clientes",
                            {
                                'type': 'connection_status_update',
                                'proveedor_id': proveedor_info['id'],
                                'usuario_id': proveedor_info.get('usuario_id'),  # ID del Usuario para comparar con otra_persona.id
                                'tipo_proveedor': self.tipo_proveedor,
                                'esta_conectado': False,
                                'nombre_proveedor': proveedor_info['nombre'],
                                'timestamp': timezone.now().isoformat()
                            }
                        )
            
            # Continuar verificando cada 60 segundos
            await self.programar_verificacion_heartbeat()
    
    @database_sync_to_async
    def get_proveedor(self):
        """
        Obtiene el proveedor asociado al usuario autenticado
        """
        try:
            # Obtener el usuario del scope
            user = self.scope.get('user')
            if not user or not user.is_authenticated:
                return None
            
            # Buscar si es un mecánico a domicilio
            try:
                mecanico = MecanicoDomicilio.objects.get(usuario=user)
                self.tipo_proveedor = 'mecanico'
                return mecanico
            except MecanicoDomicilio.DoesNotExist:
                pass
            
            # Buscar si es un taller
            try:
                taller = Taller.objects.get(usuario=user)
                self.tipo_proveedor = 'taller'
                return taller
            except Taller.DoesNotExist:
                pass
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo proveedor: {e}")
            return None
    
    @database_sync_to_async
    def get_proveedor_info(self):
        """
        Obtiene información del proveedor de forma async-safe
        """
        try:
            if not self.proveedor:
                return {'id': None, 'nombre': 'Proveedor', 'usuario_id': None}
            
            proveedor_id = self.proveedor.pk if hasattr(self.proveedor, 'pk') else None
            
            nombre = 'Proveedor'
            if hasattr(self.proveedor, 'nombre'):
                nombre = self.proveedor.nombre
            elif hasattr(self.proveedor, 'razon_social'):
                nombre = self.proveedor.razon_social
            
            usuario_id = None
            if hasattr(self.proveedor, 'usuario'):
                try:
                    usuario = self.proveedor.usuario
                    if usuario:
                        usuario_id = usuario.pk if hasattr(usuario, 'pk') else usuario.id
                except Exception as e:
                    logger.warning(f"Error obteniendo usuario_id: {e}")
            
            return {
                'id': proveedor_id,
                'nombre': nombre,
                'usuario_id': usuario_id
            }
        except Exception as e:
            logger.error(f"Error obteniendo información del proveedor: {e}", exc_info=True)
            return {'id': None, 'nombre': 'Proveedor', 'usuario_id': None}
    
    @database_sync_to_async
    def marcar_conectado(self):
        """
        Marca al proveedor como conectado
        """
        try:
            # Crear filtro según el tipo de proveedor
            if self.tipo_proveedor == 'mecanico':
                filter_kwargs = {'proveedor': self.proveedor}
            else:  # taller
                filter_kwargs = {'taller': self.proveedor}
            
            connection_status, created = ConnectionStatus.objects.get_or_create(
                **filter_kwargs,
                defaults={
                    'status': 'online',
                    'is_online': True,
                    'esta_conectado': True,
                    'last_heartbeat': timezone.now(),
                    'ultima_conexion': timezone.now()
                }
            )
            
            if not created:
                connection_status.update_status('online')
            
            logger.info(f"🔗 Proveedor {self.proveedor.nombre} marcado como conectado")
            
        except Exception as e:
            logger.error(f"❌ Error marcando como conectado: {e}")
    
    @database_sync_to_async
    def marcar_desconectado(self):
        """
        Marca al proveedor como desconectado
        """
        try:
            # Crear filtro según el tipo de proveedor
            if self.tipo_proveedor == 'mecanico':
                filter_kwargs = {'proveedor': self.proveedor}
            else:  # taller
                filter_kwargs = {'taller': self.proveedor}
            
            connection_status = ConnectionStatus.objects.filter(**filter_kwargs).first()
            
            if connection_status:
                connection_status.update_status('offline')
                logger.info(f"🔌 Proveedor {self.proveedor.nombre} marcado como desconectado")
            
        except Exception as e:
            logger.error(f"❌ Error marcando como desconectado: {e}")
    
    @database_sync_to_async
    def actualizar_heartbeat(self):
        """
        Actualiza el heartbeat del proveedor
        """
        try:
            # Crear filtro según el tipo de proveedor
            if self.tipo_proveedor == 'mecanico':
                filter_kwargs = {'proveedor': self.proveedor}
            else:  # taller
                filter_kwargs = {'taller': self.proveedor}
            
            connection_status = ConnectionStatus.objects.filter(**filter_kwargs).first()
            
            if connection_status:
                connection_status.update_heartbeat()
                
        except Exception as e:
            logger.error(f"❌ Error actualizando heartbeat: {e}")
    
    @database_sync_to_async
    def actualizar_estado(self, new_status):
        """
        Actualiza el estado del proveedor
        """
        try:
            # Crear filtro según el tipo de proveedor
            if self.tipo_proveedor == 'mecanico':
                filter_kwargs = {'proveedor': self.proveedor}
            else:  # taller
                filter_kwargs = {'taller': self.proveedor}
            
            connection_status = ConnectionStatus.objects.filter(**filter_kwargs).first()
            
            if connection_status:
                connection_status.update_status(new_status)
                
                # Obtener información del proveedor de forma segura
                proveedor_id = self.proveedor.pk if hasattr(self.proveedor, 'pk') else None
                nombre_proveedor = getattr(self.proveedor, 'nombre', 'Proveedor')
                
                # Retornar información para notificar después (no usar asyncio.create_task aquí)
                return {
                    'proveedor_id': proveedor_id,
                    'nombre_proveedor': nombre_proveedor,
                    'status': new_status
                }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error actualizando estado: {e}")
            return None
    
    async def notificar_cambio_estado(self, estado_info):
        """
        Notifica a clientes sobre el cambio de estado (método async separado)
        """
        if estado_info:
            # Obtener usuario_id del proveedor si no está en estado_info
            usuario_id = estado_info.get('usuario_id')
            if not usuario_id and hasattr(self, 'proveedor') and self.proveedor:
                try:
                    if hasattr(self.proveedor, 'usuario') and self.proveedor.usuario:
                        usuario_id = self.proveedor.usuario.id
                except:
                    pass
        
        await self.channel_layer.group_send(
            "clientes",
            {
                'type': 'connection_status_update',
                'proveedor_id': estado_info['proveedor_id'],
                'usuario_id': usuario_id,  # ID del Usuario para comparar con otra_persona.id
                'tipo_proveedor': self.tipo_proveedor,
                'esta_conectado': estado_info['status'] in ['online', 'busy'],
                'nombre_proveedor': estado_info['nombre_proveedor'],
                'status': estado_info['status'],
                'timestamp': timezone.now().isoformat()
            }
        )
    
    @database_sync_to_async
    def verificar_ultimo_heartbeat(self):
        """
        Verifica el último heartbeat del proveedor
        """
        try:
            # Crear filtro según el tipo de proveedor
            if self.tipo_proveedor == 'mecanico':
                filter_kwargs = {'proveedor': self.proveedor}
            else:  # taller
                filter_kwargs = {'taller': self.proveedor}
            
            connection_status = ConnectionStatus.objects.filter(**filter_kwargs).first()
            
            if connection_status and connection_status.last_heartbeat:
                # Verificar si el último heartbeat fue hace más de 60 segundos
                cutoff_time = timezone.now() - timezone.timedelta(seconds=60)
                if connection_status.last_heartbeat < cutoff_time:
                    connection_status.update_status('offline')
                    return connection_status
            
            return connection_status
            
        except Exception as e:
            logger.error(f"❌ Error verificando heartbeat: {e}")
            return None


class MechanicStatusConsumer(AsyncWebsocketConsumer):
    """
    Consumer para manejar el estado de conexión de los proveedores
    con autenticación JWT y manejo de estados mejorado
    """
    
    async def connect(self):
        """
        Maneja la conexión del WebSocket con autenticación JWT
        """
        try:
            # Extraer token de los parámetros de consulta o headers
            query_string = self.scope.get('query_string', b'').decode()
            token = None
            
            # Buscar token en query string
            for param in query_string.split('&'):
                if param.startswith('token='):
                    token = param.split('=')[1]
                    break
            
            # Si no hay token en query string, buscar en headers
            if not token:
                headers = dict(self.scope.get('headers', []))
                auth_header = headers.get(b'authorization', b'').decode()
                if auth_header.startswith('Token '):
                    token = auth_header.split(' ')[1]
                elif auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
            
            if not token:
                logger.error("❌ No se proporcionó token de autenticación")
                await self.close()
                return
            
            # Autenticar token JWT
            self.proveedor = await self.authenticate_token(token)
            
            if not self.proveedor:
                logger.error("❌ Autenticación fallida")
                await self.close()
                return
        except Exception as e:
            logger.error(f"❌ Error en connect (autenticación): {e}", exc_info=True)
            try:
                await self.close()
            except:
                pass
            return
        
        try:
            # Obtener información del proveedor de forma async-safe ANTES de cualquier operación
            proveedor_info = await self.get_proveedor_info()
            
            if not proveedor_info or not proveedor_info['id']:
                logger.error("❌ No se pudo obtener información del proveedor")
                await self.close()
                return
            
            # Actualizar estado a 'online'
            await self.update_provider_status('online')
            
            # Añadir al grupo de mecánicos
            await self.channel_layer.group_add(
                "mechanic_status",
                self.channel_name
            )
            
            # Añadir al grupo específico del proveedor (para estados)
            await self.channel_layer.group_add(
                f"mechanic_{proveedor_info['id']}",
                self.channel_name
            )
            
            # Añadir al grupo proveedor_{id} para recibir eventos de solicitudes
            # (ConnectionConsumer también usa este grupo)
            if proveedor_info['usuario_id']:
                await self.channel_layer.group_add(
                    f"proveedor_{proveedor_info['usuario_id']}",
                    self.channel_name
                )
            
            # Aceptar la conexión
            await self.accept()
            
            # Enviar confirmación de conexión
            await self.send(text_data=json.dumps({
                'type': 'connection_confirmed',
                'message': 'Conexión establecida correctamente',
                'proveedor_id': proveedor_info['id'],
                'nombre_proveedor': proveedor_info['nombre']
            }))
            
            logger.info(f"🔗 MechanicStatusConsumer conectado: {proveedor_info['nombre']}")
            
            # Notificar a clientes sobre el cambio de estado
            await self.broadcast_status_update('online', proveedor_info)
        except Exception as e:
            logger.error(f"❌ Error en connect (después de autenticación): {e}", exc_info=True)
            try:
                await self.close()
            except:
                pass
    
    async def disconnect(self, close_code):
        """
        Maneja la desconexión del WebSocket
        """
        if hasattr(self, 'proveedor') and self.proveedor:
            try:
                # Obtener información del proveedor de forma async-safe PRIMERO
                proveedor_info = await self.get_proveedor_info()
                
                if proveedor_info and proveedor_info['id']:
                    # Actualizar estado a 'offline'
                    await self.update_provider_status('offline')
                    
                    # Remover de grupos usando la información obtenida
                    await self.channel_layer.group_discard(
                        "mechanic_status",
                        self.channel_name
                    )
                    await self.channel_layer.group_discard(
                        f"mechanic_{proveedor_info['id']}",
                        self.channel_name
                    )
                    # Remover del grupo proveedor_{usuario_id} de forma async-safe
                    if proveedor_info['usuario_id']:
                        await self.channel_layer.group_discard(
                            f"proveedor_{proveedor_info['usuario_id']}",
                            self.channel_name
                        )
                    
                    logger.info(f"🔌 MechanicStatusConsumer desconectado: {proveedor_info['nombre']}")
                    
                    # Notificar a clientes sobre el cambio de estado
                    await self.broadcast_status_update('offline', proveedor_info)
            except Exception as e:
                logger.error(f"❌ Error en disconnect: {e}", exc_info=True)
    
    async def receive(self, text_data):
        """
        Maneja mensajes recibidos del WebSocket
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'heartbeat':
                await self.update_heartbeat()
            elif message_type == 'status_update':
                new_status = data.get('status', 'online')
                await self.update_provider_status(new_status)
            else:
                logger.warning(f"Tipo de mensaje desconocido: {message_type}")
                
        except json.JSONDecodeError:
            logger.error("❌ Error decodificando JSON del WebSocket")
        except Exception as e:
            logger.error(f"❌ Error procesando mensaje WebSocket: {e}")
    
    async def broadcast_status_update(self, status, proveedor_info=None):
        """
        Difunde actualización de estado a todos los clientes
        """
        # Obtener información del proveedor si no se proporciona
        if not proveedor_info:
            proveedor_info = await self.get_proveedor_info()
        
        await self.channel_layer.group_send(
            "clientes",
            {
                'type': 'mechanic_status_update',
                'proveedor_id': proveedor_info['id'],
                'usuario_id': proveedor_info.get('usuario_id'),  # ID del Usuario para comparar con otra_persona.id
                'tipo_proveedor': 'mecanico',
                'status': status,
                'is_online': status in ['online', 'busy'],
                'esta_conectado': status in ['online', 'busy'],
                'nombre_proveedor': proveedor_info['nombre'],
                'timestamp': timezone.now().isoformat()
            }
        )
    
    async def mechanic_status_update(self, event):
        """
        Envía actualizaciones de estado a los clientes
        """
        await self.send(text_data=json.dumps({
            'type': 'mechanic_status_update',
            'proveedor_id': event['proveedor_id'],
            'tipo_proveedor': event['tipo_proveedor'],
            'status': event['status'],
            'is_online': event['is_online'],
            'nombre_proveedor': event['nombre_proveedor'],
            'timestamp': event['timestamp']
        }))
    
    async def nueva_solicitud(self, event):
        """
        Notifica al proveedor sobre una nueva solicitud disponible
        """
        await self.send(text_data=json.dumps({
            'type': 'nueva_solicitud',
            'solicitud_id': event['solicitud_id'],
            'vehiculo': event['vehiculo'],
            'descripcion': event['descripcion'],
            'urgencia': event['urgencia'],
            'fecha_expiracion': event['fecha_expiracion'],
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def oferta_aceptada(self, event):
        """
        Notifica al proveedor que su oferta fue aceptada
        """
        await self.send(text_data=json.dumps({
            'type': 'oferta_aceptada',
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'solicitud_tradicional_id': event.get('solicitud_tradicional_id'),
            'carrito_id': event.get('carrito_id'),
            'mensaje': event.get('mensaje', '¡Tu oferta fue aceptada!'),
            'estado_oferta': event.get('estado_oferta', 'aceptada'),
            'monto_total': event.get('monto_total'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def pago_en_proceso(self, event):
        """
        Notifica al proveedor que el cliente está procesando el pago
        """
        await self.send(text_data=json.dumps({
            'type': 'pago_en_proceso',
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'mensaje': event.get('mensaje', 'El cliente está procesando el pago.'),
            'estado_oferta': event.get('estado_oferta', 'pendiente_pago'),
            'monto_total': event.get('monto_total'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def pago_completado(self, event):
        """
        Notifica al proveedor que el pago fue completado exitosamente
        """
        await self.send(text_data=json.dumps({
            'type': 'pago_completado',
            'solicitud_id': event['solicitud_id'],
            'solicitud_servicio_id': event.get('solicitud_servicio_id'),
            'oferta_id': event['oferta_id'],
            'mensaje': event.get('mensaje', '¡Pago completado! Servicio confirmado.'),
            'estado_oferta': event.get('estado_oferta', 'pagada'),
            'monto_total': event.get('monto_total'),
            'fecha_servicio': event.get('fecha_servicio'),
            'hora_servicio': event.get('hora_servicio'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def oferta_rechazada(self, event):
        """
        Notifica al proveedor que su oferta fue rechazada
        """
        await self.send(text_data=json.dumps({
            'type': 'oferta_rechazada',
            'oferta_id': event.get('oferta_id'),
            'solicitud_id': event.get('solicitud_id'),
            'timestamp': timezone.now().isoformat()
        }))
    
    async def solicitud_cancelada(self, event):
        """
        Notifica al proveedor que una solicitud fue cancelada
        """
        await self.send(text_data=json.dumps({
            'type': 'solicitud_cancelada',
            'solicitud_id': event['solicitud_id'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def nuevo_mensaje_chat(self, event):
        """
        Notifica al proveedor sobre un nuevo mensaje en el chat
        """
        await self.send(text_data=json.dumps({
            'type': 'nuevo_mensaje_chat',
            'mensaje_id': event['mensaje_id'],
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'enviado_por': event['enviado_por'],
            'mensaje': event['mensaje'],
            'es_proveedor': event['es_proveedor'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def servicio_iniciado(self, event):
        """
        Notifica al cliente que el proveedor ha iniciado el servicio
        """
        await self.send(text_data=json.dumps({
            'type': 'servicio_iniciado',
            'solicitud_id': event['solicitud_id'],
            'oferta_id': event['oferta_id'],
            'proveedor_nombre': event.get('proveedor_nombre'),
            'mensaje': event.get('mensaje', 'El proveedor ha iniciado el servicio'),
            'timestamp': timezone.now().isoformat()
        }))
    
    @database_sync_to_async
    def get_proveedor_usuario_id(self):
        """
        Obtiene el ID del usuario asociado al proveedor de forma async-safe
        """
        try:
            if hasattr(self.proveedor, 'usuario') and self.proveedor.usuario:
                return self.proveedor.usuario.id
            return None
        except Exception as e:
            logger.error(f"Error obteniendo usuario_id del proveedor: {e}")
            return None
    
    @database_sync_to_async
    def get_proveedor_info(self):
        """
        Obtiene información del proveedor de forma async-safe
        IMPORTANTE: Este método debe ser llamado desde un contexto async
        """
        try:
            if not self.proveedor:
                return {'id': None, 'nombre': 'Proveedor', 'usuario_id': None}
            
            # Obtener ID directamente (no requiere consulta adicional)
            proveedor_id = self.proveedor.pk if hasattr(self.proveedor, 'pk') else None
            
            # Obtener nombre de forma segura
            nombre = 'Proveedor'
            if hasattr(self.proveedor, 'nombre'):
                nombre = self.proveedor.nombre
            elif hasattr(self.proveedor, 'razon_social'):
                nombre = self.proveedor.razon_social
            
            # Obtener usuario_id de forma segura
            usuario_id = None
            if hasattr(self.proveedor, 'usuario'):
                try:
                    # Acceder al usuario de forma segura
                    usuario = self.proveedor.usuario
                    if usuario:
                        usuario_id = usuario.pk if hasattr(usuario, 'pk') else usuario.id
                except Exception as e:
                    logger.warning(f"Error obteniendo usuario_id: {e}")
            
            return {
                'id': proveedor_id,
                'nombre': nombre,
                'usuario_id': usuario_id
            }
        except Exception as e:
            logger.error(f"Error obteniendo información del proveedor: {e}", exc_info=True)
            return {
                'id': None,
                'nombre': 'Proveedor',
                'usuario_id': None
            }
    
    @database_sync_to_async
    def authenticate_token(self, token):
        """
        Autentica el token (JWT o Django REST Framework) y obtiene el proveedor
        """
        try:
            # Primero intentar con token de Django REST Framework
            try:
                from rest_framework.authtoken.models import Token
                token_obj = Token.objects.get(key=token)
                user = token_obj.user
            except:
                # Si falla, intentar con JWT
                try:
                    access_token = AccessToken(token)
                    user_id = access_token['user_id']
                    user = User.objects.get(id=user_id)
                except:
                    logger.error("❌ Token inválido (ni DRF ni JWT)")
                    return None
            
            # Buscar si es un mecánico a domicilio
            try:
                mecanico = MecanicoDomicilio.objects.get(usuario=user)
                return mecanico
            except MecanicoDomicilio.DoesNotExist:
                pass
            
            # Buscar si es un taller
            try:
                taller = Taller.objects.get(usuario=user)
                return taller
            except Taller.DoesNotExist:
                pass
            
            logger.error(f"❌ Usuario {user.username} no es un proveedor")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error autenticando token: {e}")
            return None
    
    @database_sync_to_async
    def update_provider_status(self, status):
        """
        Actualiza el estado del proveedor
        """
        try:
            # Crear filtro según el tipo de proveedor
            if isinstance(self.proveedor, MecanicoDomicilio):
                filter_kwargs = {'proveedor': self.proveedor}
            else:  # Taller
                filter_kwargs = {'taller': self.proveedor}
            
            connection_status, created = ConnectionStatus.objects.get_or_create(
                **filter_kwargs,
                defaults={
                    'status': status,
                    'is_online': status in ['online', 'busy'],
                    'esta_conectado': status in ['online', 'busy'],
                    'last_heartbeat': timezone.now(),
                    'ultima_conexion': timezone.now()
                }
            )
            
            if not created:
                connection_status.update_status(status)
            
            # Obtener nombre de forma segura
            nombre_proveedor = getattr(self.proveedor, 'nombre', 'Proveedor')
            logger.info(f"🔄 Proveedor {nombre_proveedor} estado actualizado a: {status}")
            
        except Exception as e:
            logger.error(f"❌ Error actualizando estado del proveedor: {e}")
    
    @database_sync_to_async
    def update_heartbeat(self):
        """
        Actualiza solo el heartbeat del proveedor
        """
        try:
            # Crear filtro según el tipo de proveedor
            if isinstance(self.proveedor, MecanicoDomicilio):
                filter_kwargs = {'proveedor': self.proveedor}
            else:  # Taller
                filter_kwargs = {'taller': self.proveedor}
            
            connection_status = ConnectionStatus.objects.filter(**filter_kwargs).first()
            
            if connection_status:
                connection_status.update_heartbeat()
                
        except Exception as e:
            logger.error(f"❌ Error actualizando heartbeat: {e}")


class ClientStatusConsumer(AsyncWebsocketConsumer):
    """
    Consumer para clientes que quieren monitorear el estado de los proveedores
    y recibir notificaciones de chat
    """
    
    async def connect(self):
        """
        Maneja la conexión del WebSocket para clientes
        """
        # Autenticar al cliente usando token de query params
        query_string = self.scope.get('query_string', b'').decode()
        token = None
        
        # Buscar token en query string
        for param in query_string.split('&'):
            if param.startswith('token='):
                token = param.split('=')[1]
                break
        
        if token:
            # Autenticar el token
            self.user = await self.authenticate_token(token)
            if self.user:
                logger.info(f"👤 Cliente autenticado: {self.user.username} (ID: {self.user.id})")
                
                # Añadir al grupo específico del cliente
                await self.channel_layer.group_add(
                    f"cliente_{self.user.id}",
                    self.channel_name
                )
                
                # También añadir al grupo general de clientes
                await self.channel_layer.group_add(
                    "clientes",
                    self.channel_name
                )
                
                # Aceptar la conexión
                await self.accept()
                
                logger.info(f"✅ Cliente {self.user.username} conectado al WebSocket")
                
                # Enviar estados actuales de todos los proveedores
                await self.send_current_statuses()
            else:
                logger.warning("❌ Token inválido, rechazando conexión")
                await self.close()
        else:
            # Si no hay token, permitir conexión pero solo al grupo general
            self.user = None
            await self.channel_layer.group_add(
                "clientes",
                self.channel_name
            )
            
            await self.accept()
            logger.info("👤 Cliente conectado al WebSocket (sin autenticación)")
            await self.send_current_statuses()
    
    async def disconnect(self, close_code):
        """
        Maneja la desconexión del WebSocket
        """
        # Remover del grupo general de clientes
        await self.channel_layer.group_discard(
            "clientes",
            self.channel_name
        )
        
        # Remover del grupo específico del cliente si está autenticado
        if hasattr(self, 'user') and self.user:
            await self.channel_layer.group_discard(
                f"cliente_{self.user.id}",
                self.channel_name
            )
            logger.info(f"👤 Cliente {self.user.username} desconectado del WebSocket")
        else:
            logger.info("👤 Cliente desconectado del WebSocket")
    
    async def receive(self, text_data):
        """
        Maneja mensajes recibidos del WebSocket
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'subscribe_to_mechanics':
                mechanic_ids = data.get('mechanic_ids', [])
                await self.subscribe_to_mechanics(mechanic_ids)
            else:
                logger.warning(f"Tipo de mensaje desconocido: {message_type}")
                
        except json.JSONDecodeError:
            logger.error("❌ Error decodificando JSON del WebSocket")
        except Exception as e:
            logger.error(f"❌ Error procesando mensaje WebSocket: {e}")
    
    async def subscribe_to_mechanics(self, mechanic_ids):
        """
        Suscribe al cliente a actualizaciones de mecánicos específicos
        """
        for mechanic_id in mechanic_ids:
            await self.channel_layer.group_add(
                f"mechanic_{mechanic_id}",
                self.channel_name
            )
        
        await self.send(text_data=json.dumps({
            'type': 'subscription_confirmed',
            'message': f'Suscrito a {len(mechanic_ids)} mecánicos',
            'mechanic_ids': mechanic_ids
        }))
    
    async def send_current_statuses(self):
        """
        Envía los estados actuales de todos los proveedores
        """
        try:
            statuses = await self.get_current_statuses()
            await self.send(text_data=json.dumps({
                'type': 'current_statuses',
                'statuses': statuses
            }))
        except Exception as e:
            logger.error(f"❌ Error enviando estados actuales: {e}")
    
    @database_sync_to_async
    def get_current_statuses(self):
        """
        Obtiene los estados actuales de todos los proveedores
        """
        try:
            connection_statuses = ConnectionStatus.objects.filter(
                esta_conectado=True
            ).select_related('proveedor', 'taller')
            
            statuses = []
            for status in connection_statuses:
                statuses.append({
                    'proveedor_id': status.proveedor.id if status.proveedor else status.taller.id,
                    'tipo_proveedor': 'mecanico' if status.proveedor else 'taller',
                    'nombre_proveedor': status.nombre_proveedor,
                    'status': status.status,
                    'is_online': status.is_online,
                    'ultima_conexion': status.ultima_conexion.isoformat() if status.ultima_conexion else None
                })
            
            return statuses
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo estados actuales: {e}")
            return []
    
    async def mechanic_status_update(self, event):
        """
        Envía actualizaciones de estado a los clientes
        """
        await self.send(text_data=json.dumps({
            'type': 'mechanic_status_update',
            'proveedor_id': event['proveedor_id'],
            'tipo_proveedor': event['tipo_proveedor'],
            'status': event['status'],
            'is_online': event['is_online'],
            'nombre_proveedor': event['nombre_proveedor'],
            'timestamp': event['timestamp']
        }))
    
    async def nueva_oferta(self, event):
        """
        Notifica al cliente sobre una nueva oferta recibida
        """
        await self.send(text_data=json.dumps({
            'type': 'nueva_oferta',
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'proveedor_nombre': event['proveedor_nombre'],
            'precio': event['precio'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def solicitud_adjudicada(self, event):
        """
        Notifica al cliente que su solicitud fue adjudicada
        """
        await self.send(text_data=json.dumps({
            'type': 'solicitud_adjudicada',
            'solicitud_id': event['solicitud_id'],
            'oferta_id': event['oferta_id'],
            'solicitud_tradicional_id': event.get('solicitud_tradicional_id'),
            'timestamp': timezone.now().isoformat()
        }))
    
    async def alerta_pago_proximo(self, event):
        """
        Notifica al cliente que se está acercando la fecha límite de pago (6h antes)
        """
        await self.send(text_data=json.dumps({
            'type': 'alerta_pago_proximo',
            'solicitud_id': event['solicitud_id'],
            'oferta_id': event.get('oferta_id'),
            'mensaje': event.get('mensaje', 'Se está acercando la fecha límite para pagar esta solicitud.'),
            'tiempo_restante_horas': event.get('tiempo_restante_horas'),
            'tiempo_restante_minutos': event.get('tiempo_restante_minutos'),
            'fecha_limite_pago': event.get('fecha_limite_pago'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def pago_expirado(self, event):
        """
        Notifica al cliente que el pago expiró sin completarse
        """
        await self.send(text_data=json.dumps({
            'type': 'pago_expirado',
            'solicitud_id': event['solicitud_id'],
            'oferta_id': event.get('oferta_id'),
            'mensaje': event.get('mensaje', 'El plazo para pagar ha expirado.'),
            'fecha_limite_pago': event.get('fecha_limite_pago'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def nuevo_mensaje_chat(self, event):
        """
        Notifica al cliente sobre un nuevo mensaje en el chat
        """
        await self.send(text_data=json.dumps({
            'type': 'nuevo_mensaje_chat',
            'mensaje_id': event['mensaje_id'],
            'oferta_id': event['oferta_id'],
            'solicitud_id': event['solicitud_id'],
            'enviado_por': event['enviado_por'],
            'mensaje': event['mensaje'],
            'es_proveedor': event['es_proveedor'],
            'timestamp': timezone.now().isoformat()
        }))
    
    async def salud_vehiculo_actualizada(self, event):
        """
        Notifica al cliente sobre actualización de salud del vehículo
        """
        await self.send(text_data=json.dumps({
            'type': 'salud_vehiculo_actualizada',
            'vehicle_id': event['vehicle_id'],
            'checklist_id': event['checklist_id'],
            'vehiculo_info': event.get('vehiculo_info', 'Vehículo'),
            'componentes_actualizados': event.get('componentes_actualizados', 0),
            'mensaje': event.get('mensaje', 'Las métricas de salud de tu vehículo han sido actualizadas'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    @database_sync_to_async
    def authenticate_token(self, token):
        """
        Autentica el token y obtiene el usuario cliente
        """
        try:
            # Intentar con token de Django REST Framework
            try:
                from rest_framework.authtoken.models import Token
                token_obj = Token.objects.get(key=token)
                user = token_obj.user
                logger.info(f"✅ Token DRF autenticado para usuario: {user.username}")
                return user
            except:
                # Si falla, intentar con JWT
                try:
                    access_token = AccessToken(token)
                    user_id = access_token['user_id']
                    user = User.objects.get(id=user_id)
                    logger.info(f"✅ Token JWT autenticado para usuario: {user.username}")
                    return user
                except:
                    logger.error("❌ Token inválido (ni DRF ni JWT)")
                    return None
            
        except Exception as e:
            logger.error(f"❌ Error autenticando token: {e}")
            return None 
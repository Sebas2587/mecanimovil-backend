# Guía de Implementación de Push Notifications con Expo

## ¿Cómo funcionan las Push Notifications con Expo?

Las push notifications con Expo funcionan mediante un flujo de 3 pasos:

### 1. **Frontend (App Móvil)** - Obtener Token
- La app solicita permisos de notificaciones
- Expo genera un **Push Token** único para cada dispositivo
- Este token se envía al backend y se asocia con el usuario

### 2. **Backend (Django/Celery)** - Enviar Notificación
- El backend detecta eventos (cambio de estado, recordatorio de pago, etc.)
- Usando el token del usuario, envía la notificación a **Expo Push Notification Service (EPNS)**
- Expo se encarga de enviar la notificación a los dispositivos físicos

### 3. **Expo Push Notification Service (EPNS)** - Distribución
- Expo actúa como intermediario entre tu backend y los dispositivos
- Para iOS: Expo usa **Apple Push Notification Service (APNs)**
- Para Android: Expo usa **Firebase Cloud Messaging (FCM)**
- No necesitas configurar APNs/FCM manualmente

## Arquitectura del Sistema

```
┌─────────────────┐
│   Frontend App  │
│  (React Native) │
└────────┬────────┘
         │ 1. Obtiene Push Token
         │ 2. Envía Token al Backend
         ↓
┌─────────────────┐
│   Django API    │
│   (Render.com)  │
└────────┬────────┘
         │ Almacena tokens en BD
         │ Detecta eventos (Celery)
         ↓
┌─────────────────┐
│  Celery Worker  │
│  (Render.com)   │
└────────┬────────┘
         │ 3. Envía notificación
         │    vía HTTP a EPNS
         ↓
┌─────────────────┐
│   Expo Push     │
│  Notification   │
│    Service      │
└────────┬────────┘
         │ 4. Distribuye a dispositivo
         ↓
┌─────────────────┐
│   Dispositivo   │
│  (iOS/Android)  │
└─────────────────┘
```

## Implementación Paso a Paso

### Parte 1: Frontend (App de Usuarios)

#### 1.1. Actualizar `notificationService.js`

Ya tienes el método `obtenerPushToken()`. Necesitas:

```javascript
// Enviar token al backend al iniciar sesión
async registrarTokenEnBackend(token, userId) {
  try {
    const response = await post('/usuarios/registrar-push-token/', {
      push_token: token,
      user_id: userId
    });
    return response;
  } catch (error) {
    console.error('Error registrando push token:', error);
  }
}
```

#### 1.2. Registrar token en AuthContext

Cuando el usuario inicia sesión, obtener y registrar el token:

```javascript
// En el AuthContext o después de login exitoso
useEffect(() => {
  const registrarToken = async () => {
    const hasPermission = await NotificationService.requestPermissions();
    if (hasPermission) {
      const token = await NotificationService.obtenerPushToken();
      if (token && user) {
        await NotificationService.registrarTokenEnBackend(token, user.id);
      }
    }
  };
  
  if (user) {
    registrarToken();
  }
}, [user]);
```

#### 1.3. Escuchar notificaciones recibidas

```javascript
// En App.js o componente raíz
useEffect(() => {
  // Escuchar notificaciones cuando la app está en foreground
  const subscription = Notifications.addNotificationReceivedListener(
    notification => {
      console.log('📱 Notificación recibida:', notification);
      // Manejar la notificación según su tipo
      const { type, solicitud_id } = notification.request.content.data;
      if (type === 'recordatorio_pago') {
        // Navegar a pantalla de pago
        navigation.navigate('DetalleSolicitud', { id: solicitud_id });
      }
    }
  );

  // Escuchar cuando el usuario toca la notificación (app en background)
  const responseSubscription = Notifications.addNotificationResponseReceivedListener(
    response => {
      const { type, solicitud_id } = response.notification.request.content.data;
      if (type === 'recordatorio_pago') {
        navigation.navigate('DetalleSolicitud', { id: solicitud_id });
      }
    }
  );

  return () => {
    subscription.remove();
    responseSubscription.remove();
  };
}, []);
```

### Parte 2: Backend (Django)

#### 2.1. Modelo para almacenar tokens

```python
# mecanimovilapp/apps/usuarios/models.py
class PushToken(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='push_tokens')
    token = models.CharField(max_length=255, unique=True)
    dispositivo = models.CharField(max_length=100, blank=True, null=True)
    plataforma = models.CharField(max_length=20, choices=[('ios', 'iOS'), ('android', 'Android')])
    activo = models.BooleanField(default=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'usuarios_push_tokens'
        indexes = [
            models.Index(fields=['usuario', 'activo']),
        ]
```

#### 2.2. API para registrar tokens

```python
# mecanimovilapp/apps/usuarios/views.py
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registrar_push_token(request):
    """Registrar o actualizar push token del usuario"""
    token = request.data.get('push_token')
    if not token:
        return Response({'error': 'push_token es requerido'}, status=400)
    
    PushToken.objects.update_or_create(
        token=token,
        defaults={
            'usuario': request.user,
            'activo': True,
            'dispositivo': request.data.get('dispositivo'),
            'plataforma': request.data.get('plataforma', 'unknown')
        }
    )
    
    return Response({'mensaje': 'Token registrado correctamente'})
```

#### 2.3. Tarea Celery para enviar notificaciones

```python
# mecanimovilapp/apps/ordenes/tasks.py
from celery import shared_task
import requests
from django.conf import settings
from mecanimovilapp.apps.usuarios.models import PushToken

@shared_task
def enviar_push_notificacion_pago_pendiente(solicitud_id, user_id, mensaje):
    """
    Enviar push notification de recordatorio de pago
    """
    try:
        # Obtener tokens activos del usuario
        tokens = PushToken.objects.filter(
            usuario_id=user_id,
            activo=True
        ).values_list('token', flat=True)
        
        if not tokens:
            logger.warning(f"No hay tokens push para usuario {user_id}")
            return
        
        # Preparar mensaje para Expo
        mensajes = [
            {
                'to': token,
                'sound': 'default',
                'title': '💳 Recordatorio de Pago',
                'body': mensaje,
                'data': {
                    'type': 'recordatorio_pago',
                    'solicitud_id': str(solicitud_id)
                },
                'priority': 'high'
            }
            for token in tokens
        ]
        
        # Enviar a Expo Push Notification Service
        response = requests.post(
            'https://exp.host/--/api/v2/push/send',
            json=mensajes,
            headers={
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate',
                'Content-Type': 'application/json',
            }
        )
        
        if response.status_code == 200:
            logger.info(f"Notificaciones push enviadas para solicitud {solicitud_id}")
        else:
            logger.error(f"Error enviando push: {response.text}")
            
    except Exception as e:
        logger.error(f"Error en tarea push notification: {e}", exc_info=True)
```

#### 2.4. Trigger cuando cambia el estado de solicitud

```python
# mecanimovilapp/apps/ordenes/models.py (en SolicitudServicioPublica)
def save(self, *args, **kwargs):
    # Detectar cambio de estado
    if self.pk:
        old_instance = SolicitudServicioPublica.objects.get(pk=self.pk)
        estado_anterior = old_instance.estado
        estado_nuevo = self.estado
        
        # Si cambió a 'adjudicada', enviar recordatorio de pago
        if estado_anterior != 'adjudicada' and estado_nuevo == 'adjudicada':
            # Programar recordatorio 6 horas antes de la fecha límite
            from mecanimovilapp.apps.ordenes.tasks import enviar_recordatorio_pago
            
            if self.cliente and self.fecha_preferida:
                fecha_limite = self.fecha_preferida
                # Programar recordatorio 6 horas antes
                hora_recordatorio = fecha_limite - timedelta(hours=6)
                
                # Si la hora del recordatorio aún no pasó
                if hora_recordatorio > timezone.now():
                    enviar_recordatorio_pago.apply_async(
                        args=[self.id, self.cliente.user.id],
                        eta=hora_recordatorio
                    )
    
    super().save(*args, **kwargs)
```

#### 2.5. Tarea programada con Celery Beat (recordatorios periódicos)

```python
# mecanimovilapp/apps/ordenes/tasks.py
@shared_task
def verificar_pagos_pendientes():
    """
    Tarea periódica que verifica solicitudes con pagos pendientes
    y envía recordatorios
    """
    from datetime import timedelta
    from django.utils import timezone
    from .models import SolicitudServicioPublica
    
    ahora = timezone.now()
    ventana_6_horas = ahora + timedelta(hours=6)
    
    # Buscar solicitudes adjudicadas sin pago que venzan en 6 horas
    solicitudes_pendientes = SolicitudServicioPublica.objects.filter(
        estado='adjudicada',
        pago_realizado=False,
        fecha_preferida__gte=ahora,
        fecha_preferida__lte=ventana_6_horas
    )
    
    for solicitud in solicitudes_pendientes:
        if solicitud.cliente and solicitud.cliente.user:
            mensaje = f"Recordatorio: Tu solicitud {solicitud.id} requiere pago antes de {solicitud.fecha_preferida.strftime('%d/%m/%Y %H:%M')}"
            
            enviar_push_notificacion_pago_pendiente.delay(
                solicitud.id,
                solicitud.cliente.user.id,
                mensaje
            )
```

Actualizar `celery.py`:

```python
app.conf.beat_schedule = {
    'recalcular-salud-vehiculos': {
        'task': 'mecanimovilapp.apps.vehiculos.tasks.recalcular_salud_vehiculos_batch',
        'schedule': crontab(hour='*/6', minute=0),
        'options': {'queue': 'heavy'},
    },
    'verificar-pagos-pendientes': {
        'task': 'mecanimovilapp.apps.ordenes.tasks.verificar_pagos_pendientes',
        'schedule': crontab(minute='*/30'),  # Cada 30 minutos
        'options': {'queue': 'default'},
    },
}
```

## Flujo Completo de Ejemplo: Recordatorio de Pago

1. **Usuario acepta oferta** → Estado cambia a `adjudicada`
2. **Backend detecta cambio** → Programa recordatorio 6 horas antes
3. **Celery Beat verifica** (cada 30 min) → Encuentra solicitudes próximas a vencer
4. **Celery Worker envía push** → Llama a Expo Push Notification Service
5. **Usuario recibe notificación** → Toca la notificación → Navega a pantalla de pago

## Configuración Requerida

### Backend
- ✅ Celery ya está corriendo
- ✅ Redis ya está configurado
- ✅ Necesitas instalar: `requests` (para llamar a EPNS)
- ⚠️ Crear modelo `PushToken`
- ⚠️ Crear API endpoint para registrar tokens
- ⚠️ Crear tareas Celery para enviar notificaciones

### Frontend
- ✅ `expo-notifications` ya instalado
- ✅ `notificationService.js` ya configurado
- ⚠️ Registrar token al iniciar sesión
- ⚠️ Escuchar notificaciones recibidas
- ⚠️ Navegar cuando se toca la notificación

## Consideraciones Importantes

1. **Expo Go vs Builds de Producción**
   - Push tokens **NO funcionan** en Expo Go (solo builds nativos)
   - En producción deben usarse builds de EAS (Expo Application Services)

2. **Múltiples Tokens por Usuario**
   - Un usuario puede tener varios dispositivos
   - Almacenar todos los tokens y enviar a todos

3. **Tokens Expirados**
   - Expo puede marcar tokens como inválidos
   - Manejar errores 400/404 y desactivar tokens

4. **Rate Limiting**
   - Expo tiene límites: ~3500 notificaciones/segundo
   - Si tienes muchos usuarios, enviar en batches

5. **Costo**
   - Expo Push Notifications es **gratuito** sin límite de notificaciones
   - No hay costo adicional por usarlo

## Testing

### Desarrollo (Expo Go)
- Las notificaciones push **NO funcionan** en Expo Go
- Usar notificaciones locales para testing básico

### Producción (Builds Nativos)
- Crear build de desarrollo: `eas build --profile development --platform ios`
- Instalar en dispositivo físico
- Las push notifications funcionarán correctamente

## Recursos

- [Expo Notifications Docs](https://docs.expo.dev/versions/latest/sdk/notifications/)
- [Expo Push Notification Tool](https://expo.dev/notifications) (para testing manual)
- [Expo Push Notification Service API](https://docs.expo.dev/push-notifications/sending-notifications/)

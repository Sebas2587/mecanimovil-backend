# 🔐 Sistema de Protección de Datos de Clientes - MecaniMóvil

## 📋 Descripción General

El sistema de protección de datos de clientes de MecaniMóvil ha sido diseñado para prevenir que los técnicos/mecánicos contacten directamente a los clientes para realizar trabajos "por fuera" de la plataforma, protegiendo así tanto el modelo de negocio como la seguridad de los clientes.

## 🎯 Objetivos del Sistema

1. **Protección del Modelo de Negocio**: Evitar que los proveedores bypassen la plataforma
2. **Seguridad del Cliente**: Proteger información personal sensible
3. **Transparencia**: Mantener un registro auditable de todos los accesos
4. **Graduación de Acceso**: Información progresiva según el estado de la orden
5. **Detección Proactiva**: Identificar comportamientos sospechosos automáticamente

## 🔧 Componentes del Sistema

### 1. Protección Progresiva de Datos

#### **Niveles de Acceso**

| Nivel | Estado de Orden | Información Disponible |
|-------|----------------|------------------------|
| **Restringido** | Cancelado, Rechazado, Completado (>24h) | Solo servicios básicos |
| **Parcial** | Pendiente de Aceptación | Iniciales del nombre, teléfono parcial, sector aproximado |
| **Completo** | Aceptado, En Proceso, Checklist | Información completa del cliente |

#### **Información por Nivel**

**Nivel Parcial (Antes de Aceptar):**
```json
{
  "cliente": {
    "nombre_ofuscado": "J. P.",
    "telefono_ofuscado": "***-***-1234"
  },
  "ubicacion": "Sector: Las Condes"
}
```

**Nivel Completo (Después de Aceptar):**
```json
{
  "cliente": {
    "nombre": "Juan Pérez",
    "telefono": "+56912341234",
    "email": "juan@email.com"
  },
  "ubicacion": "Av. Las Condes 1234, Oficina 567"
}
```

### 2. Sistema de Auditoría

#### **Modelo AuditAccesoCliente**

```python
class AuditAccesoCliente(models.Model):
    # Información básica del acceso
    solicitud_servicio = ForeignKey(SolicitudServicio)
    usuario_proveedor = ForeignKey(Usuario)
    fecha_acceso = DateTimeField(auto_now_add=True)
    
    # Tipo y nivel de acceso
    tipo_acceso = CharField(choices=TIPO_ACCESO_CHOICES)
    nivel_informacion = CharField(choices=NIVEL_INFORMACION_CHOICES)
    
    # Contexto técnico
    ip_address = GenericIPAddressField()
    user_agent = TextField()
    estado_orden_acceso = CharField()
    
    # Datos específicos accedidos
    datos_accedidos = JSONField()
    justificacion = CharField()
    
    # Flags de seguridad
    acceso_autorizado = BooleanField()
    requiere_revision = BooleanField()
```

#### **Tipos de Acceso Auditados**

- **vista_listado**: Visualización de lista de órdenes
- **vista_detalle**: Acceso a detalle específico de orden
- **contacto_directo**: Intento de llamada o contacto directo
- **exportacion**: Exportación de datos del sistema

### 3. Serializers Seguros

#### **Backend - Serialización Protegida**

```python
class SolicitudServicioProveedorSeguroSerializer(ModelSerializer):
    cliente_detail = SerializerMethodField()
    ubicacion_servicio_segura = SerializerMethodField()
    informacion_disponible = SerializerMethodField()
    tiempo_respuesta_requerido = SerializerMethodField()
    
    def get_cliente_detail(self, obj):
        nivel_acceso = self._determinar_nivel_acceso(obj)
        
        if nivel_acceso == 'completo':
            return ClienteCompletoSerializer(obj.cliente).data
        else:
            return ClienteProtegidoSerializer(obj.cliente).data
```

#### **Frontend - Manejo Seguro**

```typescript
// Funciones de utilidad para información protegida
export const obtenerNombreSeguro = (cliente: ClienteProtegido | ClienteCompleto): string => {
  if (esClienteCompleto(cliente)) {
    return `${cliente.nombre} ${cliente.apellido || ''}`.trim();
  }
  return cliente.nombre_ofuscado; // "J. P."
};

export const puedeContactarCliente = (orden: Orden): boolean => {
  return orden.informacion_disponible.puede_contactar;
};
```

### 4. Componentes de Frontend Seguros

#### **OrdenCard con Protección**

- **Indicadores Visuales**: Iconos de seguridad para información protegida
- **Mensajes Contextuales**: Explicación de restricciones al usuario
- **Botones Condicionales**: Contacto solo cuando está autorizado
- **Alertas de Restricción**: Información clara sobre limitaciones

```tsx
{!clienteEsCompleto && (
  <View style={styles.protectedBadge}>
    <MaterialIcons name="security" size={12} color="#ffc107" />
  </View>
)}

{mensajeRestriccion && (
  <View style={styles.restriccionInfo}>
    <Text>{mensajeRestriccion}</Text>
  </View>
)}
```

### 5. Detección Automática de Comportamientos Sospechosos

#### **Comando de Monitoreo**

```bash
# Ejecutar análisis manual
python manage.py detectar_accesos_sospechosos --hours 24 --verbose

# Ejecutar con reporte por email
python manage.py detectar_accesos_sospechosos --send-email

# Configurar en cron para ejecución automática
0 */6 * * * cd /path/to/mecanimovil-backend && python manage.py detectar_accesos_sospechosos --send-email
```

#### **Patrones Detectados**

1. **Accesos No Autorizados** (Gravedad: Alta)
   - Intentos de acceso a información restringida
   - Accesos fuera de estados permitidos

2. **Usuarios con Accesos Excesivos** (Gravedad: Media)
   - Más de 50 accesos en 24 horas
   - Comportamiento inusual de navegación

3. **Accesos Fuera de Horario** (Gravedad: Baja)
   - Accesos entre 22:00 y 06:00
   - Puede indicar automatización o comportamiento anómalo

4. **Múltiples IPs por Usuario** (Gravedad: Media)
   - Más de 3 IPs diferentes en 24 horas
   - Posible cuenta compartida o comprometida

5. **Contacto Directo No Autorizado** (Gravedad: Alta)
   - Intentos de llamada sin permisos
   - Violación directa de políticas

6. **Accesos a Órdenes Cerradas** (Gravedad: Alta)
   - Acceso completo a órdenes finalizadas
   - Posible intento de contacto post-servicio

## 🚀 Implementación y Configuración

### **1. Configuración del Backend**

```python
# settings.py
ADMINS = [
    ('Admin Security', 'security@mecanimovil.com'),
    ('CTO', 'cto@mecanimovil.com'),
]

DEFAULT_FROM_EMAIL = 'noreply@mecanimovil.com'

# Configuración de email para alertas
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
```

### **2. Configuración de Auditoría Automática**

Las vistas del backend automáticamente registran accesos:

```python
# En ProveedorOrdenesViewSet
def retrieve(self, request, *args, **kwargs):
    instance = self.get_object()
    nivel_acceso = self._determinar_nivel_acceso_orden(instance)
    
    # Registrar auditoría automáticamente
    AuditAccesoCliente.registrar_acceso(
        solicitud_servicio=instance,
        usuario_proveedor=request.user,
        tipo_acceso='vista_detalle',
        nivel_informacion=nivel_acceso,
        request=request
    )
```

### **3. Configuración del Frontend**

```typescript
// services/ordenesProveedor.ts
// El servicio automáticamente usa las funciones de utilidad seguras
const nombreCliente = obtenerNombreSeguro(orden.cliente_detail);
const puedeContactar = puedeContactarCliente(orden);
```

## 📊 Panel de Administración

### **Acceso al Panel de Auditoría**

1. **Admin Django**: `/admin/ordenes/auditaccesocliente/`
2. **Filtros Disponibles**:
   - Tipo de acceso
   - Nivel de información
   - Acceso autorizado
   - Requiere revisión
   - Estado de orden
   - Fecha de acceso

### **Acciones Administrativas**

- **Marcar como Revisado**: Quitar flag de revisión manual
- **Marcar como Sospechoso**: Flagear para investigación
- **Exportar Datos**: Generar reportes de auditoría

## ⚡ Automatización y Monitoreo

### **Configuración de Cron**

```bash
# /etc/crontab o crontab -e
# Verificar cada 6 horas
0 */6 * * * cd /path/to/mecanimovil-backend && python manage.py detectar_accesos_sospechosos --send-email

# Verificación diaria con reporte detallado
0 9 * * * cd /path/to/mecanimovil-backend && python manage.py detectar_accesos_sospechosos --hours 24 --send-email --verbose
```

### **Alertas por Email**

El sistema envía automáticamente reportes cuando detecta:
- Patrones de alta gravedad
- Usuarios con comportamiento anómalo
- Intentos de acceso no autorizado

Ejemplo de reporte:
```
🚨 REPORTE DE SEGURIDAD - ACCESOS SOSPECHOSOS
📅 Período analizado: Últimas 24 horas
🕐 Generado: 2025-01-05 14:30:00

🔴 ALERTAS DE ALTA GRAVEDAD:
   • Intentos de contacto directo no autorizados
   • Accesos completos a órdenes cerradas

🟡 ALERTAS DE MEDIA GRAVEDAD:
   • Usuarios con número excesivo de accesos
     - tecnico1: 75 accesos
     - mecanico2: 65 accesos

📊 Total de patrones detectados: 3
⚠️  Recomendación: Revisar manualmente los accesos marcados como sospechosos.
```

## 🔒 Medidas de Seguridad Adicionales

### **1. Restricciones Temporales**
- Información completa disponible solo durante órdenes activas
- Acceso restringido 24 horas después del cierre de orden
- Cache inteligente para evitar accesos repetitivos innecesarios

### **2. Validación de Estados**
```python
def _determinar_nivel_acceso(self, orden):
    # Estados seguros para acceso completo
    if orden.estado in ['aceptada_por_proveedor', 'en_proceso']:
        return 'completo'
    
    # Estados de información limitada
    elif orden.estado == 'pendiente_aceptacion_proveedor':
        return 'parcial'
    
    # Estados restringidos
    else:
        return 'restringido'
```

### **3. Registro de IP y User-Agent**
- Tracking completo de dispositivos y ubicaciones
- Detección de accesos desde múltiples dispositivos
- Identificación de patrones de automatización

## 📈 Métricas y KPIs de Seguridad

### **Métricas Monitoreadas**

1. **Tasa de Accesos No Autorizados**
   - Target: < 1% del total de accesos
   - Alerta: > 5% en 24 horas

2. **Tiempo de Acceso a Información Completa**
   - Desde aceptación de orden hasta primer acceso completo
   - Target: Inmediato tras aceptación

3. **Usuarios con Comportamiento Anómalo**
   - Usuarios con > 50 accesos diarios
   - Usuarios con > 3 IPs diferentes

4. **Efectividad de Restricciones**
   - % de órdenes donde no se accedió a info completa antes de aceptar
   - Target: > 95%

## 🛡️ Buenas Prácticas para Desarrolladores

### **1. Al Desarrollar Nuevas Funcionalidades**

```python
# SIEMPRE registrar auditoría al acceder a datos de clientes
def nueva_vista_cliente(request, orden_id):
    orden = get_object_or_404(SolicitudServicio, id=orden_id)
    
    # Registrar acceso
    AuditAccesoCliente.registrar_acceso(
        solicitud_servicio=orden,
        usuario_proveedor=request.user,
        tipo_acceso='nueva_funcionalidad',
        nivel_informacion='parcial',  # o 'completo' según corresponda
        request=request
    )
```

### **2. Al Agregar Nuevos Campos de Cliente**

```typescript
// Frontend - Usar siempre funciones de utilidad
const informacionSegura = {
  nombre: obtenerNombreSeguro(cliente),
  telefono: obtenerTelefonoSeguro(cliente),
  puedeContactar: puedeContactarCliente(orden)
};
```

### **3. Testing de Seguridad**

```python
# tests/test_security.py
def test_acceso_parcial_orden_pendiente():
    """Verificar que información parcial se devuelve para órdenes pendientes"""
    orden = crear_orden_pendiente()
    response = self.client.get(f'/api/ordenes/{orden.id}/')
    
    assert 'nombre_ofuscado' in response.data['cliente_detail']
    assert 'telefono_ofuscado' in response.data['cliente_detail']
    assert response.data['informacion_disponible']['nivel_acceso'] == 'parcial'
```

## 🚨 Respuesta a Incidentes

### **Pasos al Detectar Actividad Sospechosa**

1. **Investigación Inmediata**
   - Revisar logs de auditoría en admin Django
   - Identificar usuario y patrones de acceso
   - Verificar si hay órdenes comprometidas

2. **Acciones de Contención**
   - Suspender temporalmente cuenta del proveedor
   - Notificar a clientes afectados si es necesario
   - Cambiar contraseñas si cuenta está comprometida

3. **Documentación**
   - Registrar incidente en sistema de tickets
   - Documentar acciones tomadas
   - Crear reporte post-incidente

4. **Prevención Futura**
   - Actualizar reglas de detección
   - Mejorar entrenamiento de proveedores
   - Implementar controles adicionales si es necesario

## 📞 Contactos de Seguridad

- **Responsable de Seguridad**: security@mecanimovil.com
- **CTO**: cto@mecanimovil.com
- **Soporte Técnico**: soporte@mecanimovil.com

---

**Este sistema de protección de datos de clientes asegura que MecaniMóvil mantenga la confianza de sus usuarios mientras protege su modelo de negocio contra comportamientos desleales de proveedores.** 
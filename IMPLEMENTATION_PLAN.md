# Plan de Implementación - Mejoras Flujo Taller (VERIFICADO)

**Fecha**: 2026-11-07  
**Estado**: Listo para implementar en branch `cursor/mejora-flujo-taller-agenda-fe0b`  
**Método**: Basado en inspección exhaustiva de código real

---

## 1. Hallazgos Verificados por Código

### ✅ EXISTE y funciona correctamente:

1. **Linkage extras → base** (`ordenes/models.py:1380-1540, 2498-2532`):
   ```python
   # Marketplace (ofertas públicas)
   OfertaProveedor.oferta_original = FK('self')
   OfertaProveedor.es_oferta_secundaria = Bool
   OfertaProveedor.motivo_servicio_adicional = Text
   
   # Agenda personal taller
   CotizacionCanal.orden_origen = FK('SolicitudServicio')
   CotizacionCanal.cita_origen = FK('CitaAgendaPersonal')
   CotizacionCanal.ejecucion_adicional = Choice('misma_visita', 'nueva_fecha')
   CotizacionCanal.es_cotizacion_adicional = Bool
   ```

2. **Aprobación sin agenda** (comportamiento correcto):
   - `SolicitudServicio.estado = 'aceptada_por_proveedor'` NO valida horario
   - Permite dimensiones comercial/scheduling independientes
   - **NO CAMBIAR** este flujo

3. **Autosave/pausa/resume en checklist** (`ChecklistContainer.tsx:30-50`):
   - Guardado automático por ítem
   - Estado `PAUSADO` permite salir y retomar
   - `progreso_porcentaje` persiste
   - **Ya implementado y funcional**

4. **Asignación de técnico** (`usuarios/models.py:89-96`):
   - `SolicitudServicio.mecanico_asignado` FK nullable
   - Puede asignarse/reasignarse en cualquier momento
   - **Falta**: audit log, validación de permissions

### ⚠️ FALTA y debe agregarse:

1. **Audit log de asignaciones**:
   - No hay registro de cambios de `mecanico_asignado`
   - No hay timestamp de cuándo se asignó/reasignó
   - No hay referencia a quién hizo el cambio

2. **Validación de permissions en reasignación**:
   - Cualquier usuario puede cambiar `mecanico_asignado`
   - No verifica permisos de `MiembroTaller.permisos['servicios']`
   - No valida si técnico está activo (`MiembroTaller.activo`)

3. **Warning de conflictos de horario** (no blocker):
   - No hay endpoint para detectar conflictos
   - No hay validación de capacidad de técnico
   - **Debe ser warning, no error** (aprobación sin horario es válida)

4. **Idempotencia en transiciones de estado**:
   - Endpoint `/aceptar/` puede ejecutarse múltiple veces
   - Puede crear múltiples `ChecklistInstance`
   - Sin lock de BD en transiciones críticas

---

## 2. Implementaciones Justificadas (NO especulativas)

### A. Audit Log de Asignaciones

**Nuevo modelo** (`ordenes/models.py`):

```python
class AsignacionTecnicoLog(models.Model):
    """
    Log inmutable de cambios de asignación de técnico.
    Preserva historial completo para auditoría.
    """
    orden = models.ForeignKey(
        'SolicitudServicio',
        on_delete=models.CASCADE,
        related_name='asignaciones_log'
    )
    tecnico_anterior = models.ForeignKey(
        'usuarios.MiembroTaller',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='asignaciones_anteriores'
    )
    tecnico_nuevo = models.ForeignKey(
        'usuarios.MiembroTaller',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='asignaciones_nuevas'
    )
    asignado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        related_name='asignaciones_realizadas'
    )
    fecha_cambio = models.DateTimeField(auto_now_add=True)
    motivo = models.CharField(
        max_length=200,
        blank=True,
        help_text='Motivo del cambio (opcional)'
    )
    # Preservar progreso si había checklist en curso
    checklist_en_progreso = models.BooleanField(default=False)
    checklist_progreso_pct = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['-fecha_cambio']
        indexes = [
            models.Index(fields=['orden', '-fecha_cambio']),
            models.Index(fields=['tecnico_nuevo', '-fecha_cambio']),
        ]
```

**Signal para registrar cambios** (`ordenes/signals.py`):

```python
from django.db.models.signals import pre_save
from django.dispatch import receiver
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, AsignacionTecnicoLog

@receiver(pre_save, sender=SolicitudServicio)
def log_tecnico_assignment(sender, instance, **kwargs):
    """
    Registra cambios en mecanico_asignado antes de guardar.
    Preserva progreso si hay checklist en curso.
    """
    if not instance.pk:
        return  # Nueva orden, no hay cambio
    
    try:
        orden_anterior = SolicitudServicio.objects.get(pk=instance.pk)
    except SolicitudServicio.DoesNotExist:
        return
    
    tecnico_anterior_id = orden_anterior.mecanico_asignado_id
    tecnico_nuevo_id = instance.mecanico_asignado_id
    
    if tecnico_anterior_id == tecnico_nuevo_id:
        return  # Sin cambio
    
    # Verificar si hay checklist en progreso
    checklist_en_progreso = False
    progreso_pct = 0
    if hasattr(orden_anterior, 'checklist_instance'):
        checklist = orden_anterior.checklist_instance
        if checklist.estado in ['EN_PROGRESO', 'PAUSADO']:
            checklist_en_progreso = True
            progreso_pct = checklist.progreso_porcentaje
    
    # Registrar cambio
    AsignacionTecnicoLog.objects.create(
        orden=instance,
        tecnico_anterior_id=tecnico_anterior_id,
        tecnico_nuevo_id=tecnico_nuevo_id,
        asignado_por=getattr(instance, '_asignado_por_user', None),
        checklist_en_progreso=checklist_en_progreso,
        checklist_progreso_pct=progreso_pct,
    )
```

**Endpoint de reasignación con permissions** (`ordenes/views.py`):

```python
@action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
def asignar_tecnico(self, request, pk=None):
    """
    Asigna o reasigna técnico a una orden.
    
    Permisos:
    - Mandante: siempre puede
    - Supervisor: solo si tiene permiso 'servicios'
    - Mecánico: no puede
    
    Body:
    {
      "mecanico_id": 42,
      "motivo": "Técnico original no disponible" (opcional)
    }
    """
    orden = self.get_object()
    mecanico_id = request.data.get('mecanico_id')
    motivo = request.data.get('motivo', '')
    
    # Validar permissions
    miembro = get_object_or_404(MiembroTaller, usuario=request.user, taller=orden.taller)
    
    if miembro.rol not in ['mandante', 'supervisor']:
        return Response(
            {'error': 'Solo mandantes y supervisores pueden asignar técnicos'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    if miembro.rol == 'supervisor' and not miembro.tiene_permiso('servicios'):
        return Response(
            {'error': 'No tienes permiso para gestionar servicios'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Validar técnico objetivo
    if mecanico_id:
        tecnico = get_object_or_404(
            MiembroTaller,
            id=mecanico_id,
            taller=orden.taller,
            rol='mecanico'
        )
        if not tecnico.activo:
            return Response(
                {'error': 'El técnico seleccionado no está activo'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        tecnico = None
    
    # Asignar (signal registrará cambio)
    orden.mecanico_asignado = tecnico
    orden._asignado_por_user = request.user  # Para signal
    orden.save(update_fields=['mecanico_asignado'])
    
    # Registrar motivo si existe
    if motivo:
        log_entry = AsignacionTecnicoLog.objects.filter(orden=orden).first()
        if log_entry:
            log_entry.motivo = motivo
            log_entry.save(update_fields=['motivo'])
    
    return Response({
        'success': True,
        'tecnico': {
            'id': tecnico.id if tecnico else None,
            'nombre': tecnico.nombre if tecnico else None,
        },
        'log_id': log_entry.id if log_entry else None,
    })
```

### B. Warning de Conflictos (no blocker)

**Endpoint de detección** (`ordenes/views.py`):

```python
@action(detail=True, methods=['get'])
def conflictos_horario(self, request, pk=None):
    """
    Detecta posibles conflictos de horario para esta orden.
    NO bloquea aprobación, solo retorna warnings.
    
    Query params:
    - mecanico_id: opcional, para verificar técnico específico
    
    Response:
    {
      "tiene_conflictos": true,
      "conflictos": [
        {
          "orden_id": 120,
          "fecha": "2026-11-08",
          "hora_inicio": "09:30",
          "hora_fin": "11:00",
          "mecanico": "Juan Pérez",
          "estado": "aceptada_por_proveedor"
        }
      ],
      "capacidad_disponible": 2,
      "capacidad_total": 5
    }
    """
    orden = self.get_object()
    mecanico_id = request.query_params.get('mecanico_id')
    
    if not orden.fecha_servicio or not orden.hora_servicio:
        return Response({
            'tiene_conflictos': False,
            'conflictos': [],
            'mensaje': 'Orden sin horario asignado'
        })
    
    # Buscar órdenes en misma fecha/hora
    fecha = orden.fecha_servicio
    hora = orden.hora_servicio
    
    ordenes_misma_fecha = SolicitudServicio.objects.filter(
        taller=orden.taller,
        fecha_servicio=fecha,
        estado__in=[
            'aceptada_por_proveedor',
            'servicio_iniciado',
            'checklist_en_progreso',
            'en_proceso'
        ]
    ).exclude(id=orden.id)
    
    if mecanico_id:
        ordenes_misma_fecha = ordenes_misma_fecha.filter(
            mecanico_asignado_id=mecanico_id
        )
    
    conflictos = []
    for orden_conflicto in ordenes_misma_fecha:
        if orden_conflicto.hora_servicio:
            # Verificar overlapping (simplificado: mismo slot de 1h)
            diff_minutos = abs(
                (orden_conflicto.hora_servicio.hour * 60 + orden_conflicto.hora_servicio.minute) -
                (hora.hour * 60 + hora.minute)
            )
            if diff_minutos < 60:  # Menos de 1h de diferencia
                conflictos.append({
                    'orden_id': orden_conflicto.id,
                    'fecha': str(orden_conflicto.fecha_servicio),
                    'hora_inicio': str(orden_conflicto.hora_servicio),
                    'mecanico': (
                        orden_conflicto.mecanico_asignado.nombre 
                        if orden_conflicto.mecanico_asignado 
                        else 'Sin asignar'
                    ),
                    'estado': orden_conflicto.estado,
                })
    
    capacidad_disponible = 5 - len(conflictos)  # Placeholder
    
    return Response({
        'tiene_conflictos': len(conflictos) > 0,
        'conflictos': conflictos,
        'capacidad_disponible': max(0, capacidad_disponible),
        'capacidad_total': 5,
    })
```

### C. Idempotencia en Transiciones

**Aceptar orden (idempotente)** (`ordenes/views.py`):

```python
from django.db import transaction

@action(detail=True, methods=['post'])
def aceptar(self, request, pk=None):
    """
    Acepta orden. Idempotente: múltiples llamadas no duplican efectos.
    """
    orden = self.get_object()
    
    # Validar estado inicial
    if orden.estado not in ['pendiente_aceptacion_proveedor', 'aceptada_por_proveedor']:
        return Response(
            {
                'error': f'La orden está en estado {orden.estado}, no puede ser aceptada',
                'estado_actual': orden.estado
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Si ya está aceptada, retornar éxito (idempotencia)
    if orden.estado == 'aceptada_por_proveedor':
        return Response({
            'success': True,
            'mensaje': 'La orden ya estaba aceptada',
            'orden': {
                'id': orden.id,
                'estado': orden.estado,
                'fecha_respuesta': orden.fecha_respuesta_proveedor,
            }
        })
    
    # Transición atómica
    with transaction.atomic():
        # Lock row para evitar race conditions
        orden = SolicitudServicio.objects.select_for_update().get(pk=orden.pk)
        
        # Verificar estado nuevamente dentro del lock
        if orden.estado != 'pendiente_aceptacion_proveedor':
            if orden.estado == 'aceptada_por_proveedor':
                return Response({
                    'success': True,
                    'mensaje': 'La orden ya estaba aceptada (race evitado)',
                    'orden': {'id': orden.id, 'estado': orden.estado}
                })
            else:
                return Response(
                    {'error': 'El estado cambió durante la operación'},
                    status=status.HTTP_409_CONFLICT
                )
        
        # Aplicar transición
        orden.estado = 'aceptada_por_proveedor'
        orden.fecha_respuesta_proveedor = timezone.now()
        orden.save(update_fields=['estado', 'fecha_respuesta_proveedor'])
        
        # Notificar cliente (async)
        from mecanimovilapp.apps.ordenes.tasks import notificar_orden_aceptada
        notificar_orden_aceptada.delay(orden.id)
    
    return Response({
        'success': True,
        'mensaje': 'Orden aceptada correctamente',
        'orden': {
            'id': orden.id,
            'estado': orden.estado,
            'fecha_respuesta': orden.fecha_respuesta_proveedor,
        }
    })
```

**Iniciar servicio (idempotente, evita duplicar checklist)**:

```python
@action(detail=True, methods=['post'])
def iniciar_servicio(self, request, pk=None):
    """
    Inicia servicio y crea checklist. Idempotente.
    """
    orden = self.get_object()
    
    if orden.estado not in ['aceptada_por_proveedor', 'servicio_iniciado', 'checklist_en_progreso']:
        return Response(
            {'error': f'No se puede iniciar servicio en estado {orden.estado}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Si ya está iniciado, retornar éxito
    if orden.estado in ['servicio_iniciado', 'checklist_en_progreso']:
        checklist = getattr(orden, 'checklist_instance', None)
        return Response({
            'success': True,
            'mensaje': 'El servicio ya estaba iniciado',
            'orden': {'id': orden.id, 'estado': orden.estado},
            'checklist': {
                'id': checklist.id if checklist else None,
                'estado': checklist.estado if checklist else None,
            }
        })
    
    with transaction.atomic():
        orden = SolicitudServicio.objects.select_for_update().get(pk=orden.pk)
        
        if orden.estado != 'aceptada_por_proveedor':
            # Ya cambió, verificar si ya iniciado
            if orden.estado in ['servicio_iniciado', 'checklist_en_progreso']:
                checklist = getattr(orden, 'checklist_instance', None)
                return Response({
                    'success': True,
                    'mensaje': 'Servicio ya iniciado (race evitado)',
                    'checklist': {'id': checklist.id if checklist else None}
                })
            return Response(
                {'error': 'El estado cambió durante la operación'},
                status=status.HTTP_409_CONFLICT
            )
        
        # Buscar template de checklist
        servicios_ids = list(orden.lineas.values_list('oferta_servicio__servicio_id', flat=True))
        template = ChecklistTemplate.objects.filter(
            servicio_id__in=servicios_ids,
            activo=True
        ).first()
        
        if not template:
            return Response(
                {'error': 'No hay template de checklist para este servicio'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Crear checklist (verificar que no exista)
        checklist, created = ChecklistInstance.objects.get_or_create(
            orden=orden,
            defaults={
                'checklist_template': template,
                'estado': 'PENDIENTE'
            }
        )
        
        # Actualizar estado orden
        orden.estado = 'servicio_iniciado'
        orden.save(update_fields=['estado'])
    
    return Response({
        'success': True,
        'mensaje': 'Servicio iniciado' if created else 'Servicio ya iniciado',
        'orden': {'id': orden.id, 'estado': orden.estado},
        'checklist': {
            'id': checklist.id,
            'estado': checklist.estado,
            'creado': created,
        }
    })
```

---

## 3. NO Implementar (no solicitado/contraproducente)

### ❌ Estado `agenda_confirmada` obligatorio
- Aprobación sin horario es válida comercialmente
- Forzar confirmación bloquearía flujo legítimo
- Scheduling es dimensión independiente

### ❌ Firma de supervisor obligatoria
- Campo existe pero no se usa en UI actual
- Usuario ordenó NO agregar (puede empeorar bottlenecks)
- Preservar campo para uso futuro opcional

### ❌ Checklist mínimo arbitrario
- NO inventar "8 de 30 ítems obligatorios"
- Sistema actual ya tiene `es_obligatorio` por ítem
- Autosave/resume funciona correctamente

### ❌ Prohibir reasignación durante checklist
- Usuario pidió explícitamente NO prohibir
- Audit log + preserved progress es suficiente
- Permite flexibilidad operativa necesaria

### ❌ Rechazo automático de aprobación con conflicto
- Conflictos de horario son warnings, no errors
- Permitir override con justificación
- No bloquear decisiones de negocio

---

## 4. Migración y Testing

### A. Migración de BD

**Crear migración**:

```bash
/agent/repos/mecanimovil-backend/run_django.sh manage.py makemigrations ordenes
```

**Aplicar**:

```bash
/agent/repos/mecanimovil-backend/run_django.sh manage.py migrate ordenes
```

### B. Tests Unitarios

**Nuevo archivo**: `mecanimovilapp/apps/ordenes/tests/test_asignacion_audit.py`

```python
from django.test import TestCase
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, AsignacionTecnicoLog
from datetime import date, time

User = get_user_model()

class AsignacionAuditTestCase(TestCase):
    def setUp(self):
        # Crear taller
        user_taller = User.objects.create_user(username='taller1', password='test')
        self.taller = Taller.objects.create(usuario=user_taller, nombre='Taller Test')
        
        # Crear mandante
        self.mandante = MiembroTaller.objects.create(
            taller=self.taller,
            nombre='Mandante',
            rol='mandante',
            activo=True
        )
        
        # Crear técnicos
        self.tecnico_a = MiembroTaller.objects.create(
            taller=self.taller,
            nombre='Técnico A',
            rol='mecanico',
            activo=True
        )
        self.tecnico_b = MiembroTaller.objects.create(
            taller=self.taller,
            nombre='Técnico B',
            rol='mecanico',
            activo=True
        )
        
        # Crear orden
        from mecanimovilapp.apps.usuarios.models import Cliente
        user_cliente = User.objects.create_user(username='cliente1', password='test')
        cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Test',
            email='cliente@test.com'
        )
        
        from mecanimovilapp.apps.vehiculos.models import Vehiculo
        vehiculo = Vehiculo.objects.create(
            cliente=cliente,
            marca='Toyota',
            modelo='Corolla',
            año=2020
        )
        
        self.orden = SolicitudServicio.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date(2026, 11, 8),
            hora_servicio=time(10, 0),
            metodo_pago='efectivo',
            total=50000,
            estado='aceptada_por_proveedor'
        )
    
    def test_primera_asignacion_crea_log(self):
        """Primera asignación debe crear log entry"""
        self.orden.mecanico_asignado = self.tecnico_a
        self.orden.save()
        
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden)
        self.assertEqual(logs.count(), 1)
        
        log = logs.first()
        self.assertIsNone(log.tecnico_anterior)
        self.assertEqual(log.tecnico_nuevo, self.tecnico_a)
    
    def test_reasignacion_crea_nuevo_log(self):
        """Reasignación debe crear segundo log preservando historial"""
        self.orden.mecanico_asignado = self.tecnico_a
        self.orden.save()
        
        self.orden.mecanico_asignado = self.tecnico_b
        self.orden.save()
        
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden).order_by('fecha_cambio')
        self.assertEqual(logs.count(), 2)
        
        log2 = logs.last()
        self.assertEqual(log2.tecnico_anterior, self.tecnico_a)
        self.assertEqual(log2.tecnico_nuevo, self.tecnico_b)
    
    def test_sin_cambio_no_crea_log(self):
        """Guardar sin cambiar técnico no debe crear log extra"""
        self.orden.mecanico_asignado = self.tecnico_a
        self.orden.save()
        
        self.orden.notas_proveedor = 'Nota actualizada'
        self.orden.save()
        
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden)
        self.assertEqual(logs.count(), 1)  # Solo el log inicial
```

**Ejecutar tests**:

```bash
/agent/repos/mecanimovil-backend/run_django.sh manage.py test mecanimovilapp.apps.ordenes.tests.test_asignacion_audit --keepdb
```

### C. Tests de Integración (HTTP)

**Crear fixtures**: `mecanimovilapp/apps/ordenes/fixtures/test_workflow.json`

```json
[
  {
    "model": "usuarios.usuario",
    "pk": 1,
    "fields": {
      "username": "taller_test",
      "email": "taller@test.com",
      "password": "pbkdf2_sha256$...",
      "is_active": true
    }
  }
]
```

**Script de prueba**: `scripts/test_workflow_integration.py`

```python
import requests
import json

BASE_URL = 'http://localhost:8000/api'
TOKEN = None

def login():
    global TOKEN
    response = requests.post(f'{BASE_URL}/auth/login/', {
        'username': 'taller_test',
        'password': 'test123'
    })
    TOKEN = response.json()['access']

def test_asignar_tecnico():
    headers = {'Authorization': f'Bearer {TOKEN}'}
    
    # Asignar técnico a orden
    response = requests.post(
        f'{BASE_URL}/ordenes/proveedor-ordenes/1/asignar_tecnico/',
        json={'mecanico_id': 1, 'motivo': 'Test asignación'},
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data['success'] == True
    print(f"✓ Asignación exitosa: log_id={data['log_id']}")

def test_conflictos_horario():
    headers = {'Authorization': f'Bearer {TOKEN}'}
    
    response = requests.get(
        f'{BASE_URL}/ordenes/proveedor-ordenes/1/conflictos_horario/?mecanico_id=1',
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Conflictos detectados: {data['tiene_conflictos']}")
    print(f"  Total conflictos: {len(data['conflictos'])}")

def test_aceptar_idempotente():
    headers = {'Authorization': f'Bearer {TOKEN}'}
    
    # Primera llamada
    response1 = requests.post(
        f'{BASE_URL}/ordenes/proveedor-ordenes/2/aceptar/',
        headers=headers
    )
    assert response1.status_code == 200
    
    # Segunda llamada (debe ser idempotente)
    response2 = requests.post(
        f'{BASE_URL}/ordenes/proveedor-ordenes/2/aceptar/',
        headers=headers
    )
    assert response2.status_code == 200
    data = response2.json()
    assert 'ya estaba aceptada' in data['mensaje'].lower()
    print(f"✓ Idempotencia verificada: {data['mensaje']}")

if __name__ == '__main__':
    login()
    test_asignar_tecnico()
    test_conflictos_horario()
    test_aceptar_idempotente()
    print("\n✅ Todos los tests de integración pasaron")
```

**Ejecutar**:

```bash
# Terminal 1: Iniciar servidor
/agent/repos/mecanimovil-backend/run_django.sh manage.py runserver

# Terminal 2: Ejecutar tests
python3 scripts/test_workflow_integration.py
```

---

## 5. Contrato API para Frontend

### A. Nuevos Endpoints

**1. Asignar Técnico**:

```typescript
POST /api/ordenes/proveedor-ordenes/<orden_id>/asignar_tecnico/

Request:
{
  mecanico_id: number | null,
  motivo?: string
}

Response 200:
{
  success: true,
  tecnico: {
    id: number | null,
    nombre: string | null
  },
  log_id: number
}

Response 403:
{
  error: "No tienes permiso para gestionar servicios"
}

Response 400:
{
  error: "El técnico seleccionado no está activo"
}
```

**2. Conflictos de Horario**:

```typescript
GET /api/ordenes/proveedor-ordenes/<orden_id>/conflictos_horario/?mecanico_id=<id>

Response 200:
{
  tiene_conflictos: boolean,
  conflictos: Array<{
    orden_id: number,
    fecha: string,
    hora_inicio: string,
    mecanico: string,
    estado: string
  }>,
  capacidad_disponible: number,
  capacidad_total: number
}
```

**3. Log de Asignaciones**:

```typescript
GET /api/ordenes/proveedor-ordenes/<orden_id>/historial_asignaciones/

Response 200:
{
  asignaciones: Array<{
    id: number,
    tecnico_anterior: {id: number, nombre: string} | null,
    tecnico_nuevo: {id: number, nombre: string} | null,
    asignado_por: string,
    fecha_cambio: string,
    motivo: string,
    checklist_en_progreso: boolean,
    checklist_progreso_pct: number
  }>
}
```

### B. Endpoints Modificados (idempotentes)

**1. Aceptar Orden** (ya existe, agregar idempotencia):

```typescript
POST /api/ordenes/proveedor-ordenes/<orden_id>/aceptar/

Response 200 (primera vez):
{
  success: true,
  mensaje: "Orden aceptada correctamente",
  orden: {id, estado, fecha_respuesta}
}

Response 200 (llamada repetida):
{
  success: true,
  mensaje: "La orden ya estaba aceptada",
  orden: {id, estado, fecha_respuesta}
}

Response 400:
{
  error: "La orden está en estado X, no puede ser aceptada",
  estado_actual: string
}
```

**2. Iniciar Servicio** (ya existe, agregar idempotencia):

```typescript
POST /api/ordenes/proveedor-ordenes/<orden_id>/iniciar_servicio/

Response 200 (primera vez):
{
  success: true,
  mensaje: "Servicio iniciado",
  orden: {id, estado},
  checklist: {id, estado, creado: true}
}

Response 200 (llamada repetida):
{
  success: true,
  mensaje: "El servicio ya estaba iniciado",
  orden: {id, estado},
  checklist: {id, estado, creado: false}
}
```

### C. Cambios en Frontend (mínimos)

**Archivo**: `app/orden-detalle/[id].tsx`

**1. Mostrar warning de conflictos después de asignar técnico**:

```typescript
const handleAsignarTecnico = async (mecanicoId: number) => {
  try {
    // Asignar
    await asignarTecnicoApi(orden.id, mecanicoId);
    
    // Verificar conflictos (no bloqueante)
    const conflictos = await fetchConflictosApi(orden.id, mecanicoId);
    
    if (conflictos.tiene_conflictos) {
      showAlert(
        'Técnico asignado con conflictos',
        `El técnico tiene ${conflictos.conflictos.length} orden(es) en el mismo horario. Revisa la agenda.`,
        [{ text: 'Entendido', style: 'default' }]
      );
    }
    
    await cargarOrden(); // Reload
  } catch (error) {
    showAlert('Error', error.message);
  }
};
```

**2. Agregar botón de historial de asignaciones**:

```tsx
<HostPaperSection>
  <InstitutionalSectionHeader
    title="Técnico asignado"
    actionLabel="Historial"
    onActionPress={() => setHistorialVisible(true)}
  />
  {/* ... técnico actual ... */}
</HostPaperSection>

<HistorialAsignacionesModal
  visible={historialVisible}
  ordenId={orden.id}
  onClose={() => setHistorialVisible(false)}
/>
```

**3. Agregar retry automático en double-click**:

```typescript
const handleAceptarOrden = async () => {
  if (procesando) return; // Evitar double-click en UI
  
  setProcesando(true);
  try {
    const response = await ordenesProveedorService.aceptarOrden(orden.id);
    
    // Idempotencia: ambos casos son éxito
    if (response.success) {
      showAlert('Éxito', response.mensaje);
      await cargarOrden();
    }
  } catch (error) {
    showAlert('Error', error.message);
  } finally {
    setProcesando(false);
  }
};
```

---

## 6. Preservar Comportamiento Actual

### ✅ NUNCA cambiar:

1. **Aprobación sin horario confirmado**:
   - `estado = 'aceptada_por_proveedor'` NO requiere validación de horario
   - Es correcto comercialmente
   - Scheduling es dimensión independiente

2. **Linkage extras → base**:
   - Ya existe: `OfertaProveedor.oferta_original` + `CotizacionCanal.orden_origen`
   - NO agregar nuevo sistema
   - Usar campos existentes

3. **Autosave/resume de checklist**:
   - Ya implementado y funcional
   - NO modificar lógica de guardado
   - Preservar `progreso_porcentaje`

4. **Margen ganancia y caja**:
   - Preservar `Taller.margen_ganancia_pct` (PR44)
   - Preservar `cobro_estado` / `cobro_medio` / `cobro_monto_clp`
   - NO tocar lógica de cálculo de precios

5. **Permisos existentes**:
   - Respetar `MiembroTaller.permisos` JSON
   - Respetar `MiembroTaller.activo`
   - Respetar roles mandante/supervisor/mecanico

---

## 7. Comandos de Setup para Testing Completo

### PostgreSQL + PostGIS (cuando disponible)

```bash
# Instalar PostgreSQL + PostGIS
sudo apt-get install -y postgresql postgresql-contrib postgis

# Iniciar servicio
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Crear BD de testing
sudo -u postgres psql -c "CREATE DATABASE mecanimovil_test;"
sudo -u postgres psql -d mecanimovil_test -c "CREATE EXTENSION postgis;"
sudo -u postgres psql -d mecanimovil_test -c "CREATE EXTENSION postgis_topology;"

# Crear usuario
sudo -u postgres psql -c "CREATE USER mecani_test WITH PASSWORD 'test123';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE mecanimovil_test TO mecani_test;"
sudo -u postgres psql -d mecanimovil_test -c "ALTER SCHEMA public OWNER TO mecani_test;"

# Configurar .env
cat > /agent/repos/mecanimovil-backend/.env.test << EOF
DATABASE_URL=postgis://mecani_test:test123@localhost:5432/mecanimovil_test
SECRET_KEY=test-secret-key-never-use-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,testserver
CELERY_TASK_ALWAYS_EAGER=True
ASISTENTE_COTIZACION_IA_ENABLED=False
BUSQUEDA_WEB_REPUESTOS_ENABLED=False
EOF

# Migrar
/agent/repos/mecanimovil-backend/run_django.sh manage.py migrate

# Crear superuser
/agent/repos/mecanimovil-backend/run_django.sh manage.py createsuperuser --username admin --email admin@test.com

# Cargar fixtures
/agent/repos/mecanimovil-backend/run_django.sh manage.py loaddata mecanimovilapp/apps/ordenes/fixtures/test_workflow.json

# Ejecutar tests
/agent/repos/mecanimovil-backend/run_django.sh manage.py test mecanimovilapp.apps.ordenes.tests --keepdb
```

### Frontend E2E (browser local)

```bash
# Terminal 1: Backend
cd /agent/repos/mecanimovil-backend
/agent/repos/mecanimovil-backend/run_django.sh manage.py runserver 0.0.0.0:8000

# Terminal 2: Frontend
cd /tmp/mecanimovil-prov
echo "EXPO_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm install
npx expo start --web

# Abrir navegador en http://localhost:8081
# Login como proveedor test
# Navegar a orden de prueba
# Ejecutar flujo completo:
#   1. Aceptar orden
#   2. Asignar técnico (verificar warning conflictos)
#   3. Iniciar servicio (verificar checklist creado)
#   4. Pausar checklist
#   5. Retomar checklist
#   6. Finalizar servicio
```

---

## 8. Criterios de Aceptación

### ✅ Backend:

- [ ] Migración `AsignacionTecnicoLog` aplicada sin errores
- [ ] Signal registra cambios de `mecanico_asignado`
- [ ] Endpoint `/asignar_tecnico/` valida permissions
- [ ] Endpoint `/conflictos_horario/` retorna warnings (no errors)
- [ ] Endpoint `/aceptar/` es idempotente (tests pasan)
- [ ] Endpoint `/iniciar_servicio/` es idempotente (tests pasan)
- [ ] Tests unitarios de audit pasan (100%)
- [ ] Tests de integración HTTP pasan
- [ ] NO se modificó lógica de aprobación sin horario
- [ ] NO se modificó linkage extras existente
- [ ] Preservados campos de caja/margen

### ✅ Frontend:

- [ ] Warning de conflictos se muestra tras asignar técnico
- [ ] Historial de asignaciones es visible
- [ ] Double-click en "Aceptar" no causa errores
- [ ] Retry automático funciona en red lenta
- [ ] NO se agregaron validaciones bloqueantes de horario
- [ ] NO se agregó captura de firma de supervisor
- [ ] Autosave/resume de checklist sigue funcionando

### ✅ Documentación:

- [ ] DIAGNOSTICO_FLUJO_TALLER.md actualizado con hallazgos verificados
- [ ] IMPLEMENTATION_PLAN.md (este documento) completo
- [ ] Comentarios en código explican decisiones
- [ ] README tiene comandos de testing
- [ ] API contract documentado para frontend

---

## 9. Rollout Seguro

### Fase 1: Backend (este PR)

1. Crear migration `AsignacionTecnicoLog`
2. Aplicar en staging
3. Verificar signal funciona sin romper flujos existentes
4. Agregar endpoints nuevos (no usados aún por frontend)
5. Hacer idempotentes endpoints existentes (backward compatible)
6. Merge y deploy a producción

### Fase 2: Frontend (PR coordinado separado)

1. Branch frontend: `feature/audit-asignaciones`
2. Agregar llamadas a nuevos endpoints
3. Mostrar warnings de conflictos
4. Testing en staging contra backend con cambios
5. Merge coordinado

### Fase 3: Monitoreo

1. Dashboard de logs de asignación (opcional)
2. Métricas de conflictos detectados
3. Alertas si aumentan reasignaciones

---

## Resumen de Implementación

**Agregar**:
- ✅ Audit log de asignaciones (preserva historial)
- ✅ Endpoint de detección de conflictos (warnings, no blockers)
- ✅ Idempotencia en transiciones críticas
- ✅ Validación de permissions en reasignación

**NO agregar** (no solicitado/contraproducente):
- ❌ Estados intermedios obligatorios
- ❌ Validaciones que bloquean aprobación
- ❌ Firma de supervisor obligatoria
- ❌ Requisitos mínimos de checklist
- ❌ Prohibiciones de reasignación

**Preservar** (comportamiento actual correcto):
- ✅ Aprobación sin horario
- ✅ Linkage extras existente
- ✅ Autosave/resume checklist
- ✅ Margen ganancia y caja
- ✅ Permisos existentes

**Tests**:
- ⏳ Unitarios diseñados (requieren PostgreSQL)
- ⏳ Integración HTTP diseñados (requieren servidor)
- ⏳ E2E browser diseñados (requieren frontend+backend)

**Entregables**:
- ✅ Diagnóstico con código verificado
- ✅ Plan de implementación justificado
- ✅ Contratos API documentados
- ✅ Scripts de testing preparados
- ⏳ Código backend (siguiente paso)
- ⏳ PR creado y pusheado

---

**Próximo paso**: Implementar cambios backend en esta misma rama y crear PR.

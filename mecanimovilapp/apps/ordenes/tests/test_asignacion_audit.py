"""
Tests for AsignacionTecnicoLog audit trail.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, AsignacionTecnicoLog
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from datetime import date, time

User = get_user_model()


class AsignacionAuditTestCase(TestCase):
    """Test audit logging of technician assignments."""
    
    def setUp(self):
        """Create test fixtures."""
        # Taller
        user_taller = User.objects.create_user(
            username='taller1',
            password='test',
            email='taller@test.com'
        )
        self.taller = Taller.objects.create(
            usuario=user_taller,
            nombre='Taller Test',
            rut='12345678-9',
            telefono='+56912345678'
        )
        
        # Mandante
        user_mandante = User.objects.create_user(
            username='mandante1',
            password='test',
            email='mandante@test.com'
        )
        self.mandante = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_mandante,
            nombre='Mandante Test',
            rol='mandante',
            activo=True,
            permisos={}
        )
        
        # Técnicos
        user_tec_a = User.objects.create_user(
            username='tecnicoa',
            password='test',
            email='tecnicoa@test.com'
        )
        self.tecnico_a = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_tec_a,
            nombre='Técnico A',
            rol='mecanico',
            activo=True,
            permisos={}
        )
        
        user_tec_b = User.objects.create_user(
            username='tecnicob',
            password='test',
            email='tecnicob@test.com'
        )
        self.tecnico_b = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_tec_b,
            nombre='Técnico B',
            rol='mecanico',
            activo=True,
            permisos={}
        )
        
        # Cliente
        user_cliente = User.objects.create_user(
            username='cliente1',
            password='test',
            email='cliente@test.com'
        )
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Test',
            email='cliente@test.com',
            telefono='+56987654321'
        )
        
        # Marca, Modelo y Vehículo
        marca_toyota, _ = MarcaVehiculo.objects.get_or_create(nombre='Toyota')
        modelo_corolla, _ = Modelo.objects.get_or_create(
            marca=marca_toyota,
            nombre='Corolla'
        )
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca_toyota,
            modelo=modelo_corolla,
            year=2020,
            patente='AB1234'
        )
        
        # Orden
        self.orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date(2026, 11, 8),
            hora_servicio=time(10, 0),
            metodo_pago='efectivo',
            total=Decimal('50000.00'),
            estado='aceptada_por_proveedor'
        )
    
    def test_primera_asignacion_crea_log(self):
        """Primera asignación debe crear log entry con tecnico_anterior=None."""
        # No debe haber logs antes de asignar
        self.assertEqual(AsignacionTecnicoLog.objects.filter(orden=self.orden).count(), 0)
        
        # Asignar técnico
        self.orden.mecanico_asignado = self.tecnico_a
        self.orden._asignado_por_user = self.mandante.usuario
        self.orden.save()
        
        # Debe haberse creado log
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden)
        self.assertEqual(logs.count(), 1)
        
        log = logs.first()
        self.assertIsNone(log.tecnico_anterior)
        self.assertEqual(log.tecnico_nuevo, self.tecnico_a)
        self.assertEqual(log.asignado_por, self.mandante.usuario)
        self.assertFalse(log.checklist_en_progreso)
        self.assertEqual(log.checklist_progreso_pct, 0)
    
    def test_reasignacion_crea_nuevo_log(self):
        """Reasignación debe crear segundo log preservando historial."""
        # Primera asignación
        self.orden.mecanico_asignado = self.tecnico_a
        self.orden._asignado_por_user = self.mandante.usuario
        self.orden.save()
        
        # Reasignar
        self.orden.mecanico_asignado = self.tecnico_b
        self.orden._asignado_por_user = self.mandante.usuario
        self.orden.save()
        
        # Deben haber 2 logs
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden).order_by('fecha_cambio')
        self.assertEqual(logs.count(), 2)
        
        log1 = logs[0]
        self.assertIsNone(log1.tecnico_anterior)
        self.assertEqual(log1.tecnico_nuevo, self.tecnico_a)
        
        log2 = logs[1]
        self.assertEqual(log2.tecnico_anterior, self.tecnico_a)
        self.assertEqual(log2.tecnico_nuevo, self.tecnico_b)
    
    def test_sin_cambio_no_crea_log(self):
        """Guardar sin cambiar técnico no debe crear log extra."""
        # Primera asignación
        self.orden.mecanico_asignado = self.tecnico_a
        self.orden.save()
        
        # Modificar otro campo sin cambiar técnico
        self.orden.notas_proveedor = 'Nota actualizada'
        self.orden.save()
        
        # Solo debe haber 1 log
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden)
        self.assertEqual(logs.count(), 1)
    
    def test_desasignacion_registrada(self):
        """Desasignar técnico (set to None) debe crear log."""
        # Asignar
        self.orden.mecanico_asignado = self.tecnico_a
        self.orden.save()
        
        # Desasignar
        self.orden.mecanico_asignado = None
        self.orden.save()
        
        # Deben haber 2 logs
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden).order_by('fecha_cambio')
        self.assertEqual(logs.count(), 2)
        
        log2 = logs[1]
        self.assertEqual(log2.tecnico_anterior, self.tecnico_a)
        self.assertIsNone(log2.tecnico_nuevo)
    
    def test_asignacion_sin_actor_funciona(self):
        """Asignación sin _asignado_por_user debe funcionar con asignado_por=None."""
        self.orden.mecanico_asignado = self.tecnico_a
        # NO setear _asignado_por_user
        self.orden.save()
        
        log = AsignacionTecnicoLog.objects.get(orden=self.orden)
        self.assertIsNone(log.asignado_por)
        self.assertEqual(log.tecnico_nuevo, self.tecnico_a)

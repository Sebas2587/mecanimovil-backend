"""
Tests for AsignacionTecnicoLog audit trail.
Verifies atomic guarantees, rollback behavior, and accurate old/new capture.
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.test.utils import CaptureQueriesContext
from decimal import Decimal
from datetime import date, time
from django.db import transaction, connection

from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, AsignacionTecnicoLog
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo

User = get_user_model()


class AsignacionAuditTestCase(TestCase):
    """Test audit logging with atomic guarantees."""
    
    def setUp(self):
        """Create fixtures."""
        user_taller = User.objects.create_user(username='taller_audit', password='test', email='t@test.com')
        self.taller = Taller.objects.create(
            usuario=user_taller,
            nombre='Taller Audit',
            rut='55555555-5',
            telefono='+56999999999',
            estado_verificacion='aprobado'
        )
        
        self.user_mandante = User.objects.create_user(username='mandante_audit', password='test', email='m@test.com')
        self.mandante = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=self.user_mandante,
            nombre='Mandante',
            rol='mandante',
            activo=True
        )
        
        user_mec = User.objects.create_user(username='mec_audit', password='test', email='mec@test.com')
        self.mecanico = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_mec,
            nombre='Mecánico',
            rol='mecanico',
            activo=True
        )
        
        user_cliente = User.objects.create_user(username='cli_audit', password='test', email='cli@test.com')
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Audit',
            email='cli@test.com',
            telefono='+56900000001'
        )
        
        marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Volkswagen')
        modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Golf')
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca,
            modelo=modelo,
            year=2021,
            patente='KL1234'
        )
        
        self.orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date.today(),
            hora_servicio=time(11, 0),
            metodo_pago='efectivo',
            total=Decimal('60000.00'),
            estado='aceptada_por_proveedor'
        )
    
    def test_asignar_crea_log(self):
        """Primera asignación crea log con old=None."""
        self.orden._old_mecanico_asignado_id = self.orden.mecanico_asignado_id
        self.orden._asignado_por_user = self.user_mandante
        self.orden.mecanico_asignado = self.mecanico
        
        # Capture and execute on_commit callbacks
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden)
        self.assertEqual(logs.count(), 1)
        
        log = logs.first()
        self.assertIsNone(log.tecnico_anterior)
        self.assertEqual(log.tecnico_nuevo, self.mecanico)
        self.assertEqual(log.asignado_por, self.user_mandante)
    
    def test_reasignacion_crea_nuevo_log(self):
        """Reasignar crea segundo log con correct old->new."""
        # Primera asignación
        self.orden._old_mecanico_asignado_id = None
        self.orden.mecanico_asignado = self.mecanico
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        # Segundo técnico
        user_mec2 = User.objects.create_user(username='mec2_audit', password='test', email='mec2@test.com')
        mec2 = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=user_mec2,
            nombre='Mecánico 2',
            rol='mecanico',
            activo=True
        )
        
        # Reasignar
        self.orden.refresh_from_db()
        self.orden._old_mecanico_asignado_id = self.orden.mecanico_asignado_id
        self.orden.mecanico_asignado = mec2
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden).order_by('fecha_cambio')
        self.assertEqual(logs.count(), 2)
        
        log2 = logs.last()
        self.assertEqual(log2.tecnico_anterior, self.mecanico)
        self.assertEqual(log2.tecnico_nuevo, mec2)
    
    def test_sin_cambio_no_crea_log(self):
        """Save sin cambio no crea log."""
        # Asignar
        self.orden._old_mecanico_asignado_id = None
        self.orden.mecanico_asignado = self.mecanico
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        # Save sin cambio (con _old igual a current)
        self.orden.refresh_from_db()
        self.orden._old_mecanico_asignado_id = self.orden.mecanico_asignado_id
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden)
        self.assertEqual(logs.count(), 1)
    
    def test_desasignar_crea_log(self):
        """Desasignar (None) registra cambio."""
        # Asignar
        self.orden._old_mecanico_asignado_id = None
        self.orden.mecanico_asignado = self.mecanico
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        # Desasignar
        self.orden.refresh_from_db()
        self.orden._old_mecanico_asignado_id = self.orden.mecanico_asignado_id
        self.orden.mecanico_asignado = None
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        logs = AsignacionTecnicoLog.objects.filter(orden=self.orden).order_by('fecha_cambio')
        self.assertEqual(logs.count(), 2)
        
        log2 = logs.last()
        self.assertEqual(log2.tecnico_anterior, self.mecanico)
        self.assertIsNone(log2.tecnico_nuevo)
    
    def test_asignacion_sin_actor(self):
        """Audit sin actor (automático)."""
        self.orden._old_mecanico_asignado_id = None
        self.orden.mecanico_asignado = self.mecanico
        # No _asignado_por_user
        with self.captureOnCommitCallbacks(execute=True):
            self.orden.save()
        
        log = AsignacionTecnicoLog.objects.get(orden=self.orden)
        self.assertIsNone(log.asignado_por)


class AuditRollbackTestCase(TransactionTestCase):
    """Test audit behavior on transaction rollback."""
    
    def test_rollback_no_audit_orphan(self):
        """Rollback debe prevenir audit orphan."""
        user = User.objects.create_user(username='rollback_user', password='test', email='rb@test.com')
        taller = Taller.objects.create(
            usuario=user,
            nombre='Taller Rollback',
            rut='66666666-6',
            telefono='+56900000002',
            estado_verificacion='aprobado'
        )
        
        user_mec = User.objects.create_user(username='mec_rb', password='test', email='mecrb@test.com')
        mecanico = MiembroTaller.objects.create(
            taller=taller,
            usuario=user_mec,
            nombre='Mecánico RB',
            rol='mecanico',
            activo=True
        )
        
        user_cli = User.objects.create_user(username='cli_rb', password='test', email='clirb@test.com')
        cliente = Cliente.objects.create(
            usuario=user_cli,
            nombre='Cliente',
            apellido='RB',
            email='clirb@test.com',
            telefono='+56900000003'
        )
        
        marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Ford')
        modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Fiesta')
        vehiculo = Vehiculo.objects.create(
            cliente=cliente,
            marca=marca,
            modelo=modelo,
            year=2020,
            patente='RB5678'
        )
        
        orden = SolicitudServicio.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            tipo_servicio='taller',
            taller=taller,
            fecha_servicio=date.today(),
            hora_servicio=time(12, 0),
            metodo_pago='efectivo',
            total=Decimal('40000.00'),
            estado='aceptada_por_proveedor'
        )
        
        orden_id = orden.pk
        
        # Intento de asignación con rollback
        try:
            with transaction.atomic():
                orden._old_mecanico_asignado_id = None
                orden.mecanico_asignado = mecanico
                orden.save()
                
                # Forzar rollback
                raise Exception("Simulated failure")
        except:
            pass
        
        # Verificar que NO se creó audit log (on_commit no ejecutó)
        logs = AsignacionTecnicoLog.objects.filter(orden_id=orden_id)
        self.assertEqual(logs.count(), 0, "Audit log no debe persistir después de rollback")
        
        # Verificar que orden no cambió
        orden.refresh_from_db()
        self.assertIsNone(orden.mecanico_asignado)

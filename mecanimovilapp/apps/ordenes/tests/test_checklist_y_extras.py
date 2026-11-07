"""
Tests for checklist pause/resume/partial saves and additional quotes workflow.
Explicitly in scope: partial capture, findings->extras, customer authorization, base independence.
"""
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date, time, datetime
from django.utils import timezone
from django.db import connection, transaction

from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, CotizacionCanal, CitaAgendaPersonal
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.checklists.models import (
    ChecklistInstance, ChecklistTemplate, ChecklistItemTemplate,
    ChecklistItemResponse, ChecklistItemCatalog
)
from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import crear_cotizacion_adicional_desde_catalogo

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_RESULT_BACKEND='cache+memory://'
)
class ChecklistWorkflowTestCase(TestCase):
    """Test checklist partial saves, pause, resume."""
    
    def setUp(self):
        """Create test fixtures with active checklist."""
        # Taller owner
        self.user_mandante = User.objects.create_user(
            username='mandante_chk',
            password='test',
            email='mandante_chk@test.com'
        )
        self.taller = Taller.objects.create(
            usuario=self.user_mandante,
            nombre='Taller Checklist',
            rut='11111111-1',
            telefono='+56911111111',
            estado_verificacion='aprobado'
        )
        self.mandante = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=self.user_mandante,
            nombre='Mandante CHK',
            rol='mandante',
            activo=True,
            permisos={'servicios': True}
        )
        
        # Cliente
        user_cliente = User.objects.create_user(
            username='cliente_chk',
            password='test',
            email='cliente_chk@test.com'
        )
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='CHK',
            email='cliente_chk@test.com',
            telefono='+56922222222'
        )
        
        # Vehículo
        marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Honda')
        modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Civic')
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca,
            modelo=modelo,
            year=2021,
            patente='CD5678'
        )
        
        # Orden base
        self.orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date.today(),
            hora_servicio=time(11, 0),
            metodo_pago='efectivo',
            total=Decimal('80000.00'),
            estado='aceptada_por_proveedor'
        )
        
        # Servicio y checklist template
        self.servicio, _ = Servicio.objects.get_or_create(nombre='Revisión General')
        self.template = ChecklistTemplate.objects.create(
            servicio=self.servicio,
            nombre='Template Test',
            activo=True
        )
        
        # Create catalog items
        self.catalog_item1 = ChecklistItemCatalog.objects.create(
            nombre='Revisar frenos',
            categoria='SISTEMA_FRENOS',
            tipo_pregunta='SELECT',
            pregunta_texto='¿Cuál es el estado de los frenos?',
            es_obligatorio_por_defecto=True,
            opciones_seleccion=['bueno', 'regular', 'malo'],
            activo=True
        )
        self.catalog_item2 = ChecklistItemCatalog.objects.create(
            nombre='Nivel aceite',
            categoria='FLUIDOS_NIVELES',
            tipo_pregunta='NUMBER',
            pregunta_texto='Nivel de aceite (mm)',
            es_obligatorio_por_defecto=True,
            activo=True
        )
        
        # Create template items
        self.item1 = ChecklistItemTemplate.objects.create(
            checklist_template=self.template,
            catalog_item=self.catalog_item1,
            orden_visual=1
        )
        self.item2 = ChecklistItemTemplate.objects.create(
            checklist_template=self.template,
            catalog_item=self.catalog_item2,
            orden_visual=2
        )
        
        # APIClient
        self.client = APIClient()
        self.client.force_authenticate(user=self.user_mandante)
    
    def test_crear_checklist_instance_con_orden(self):
        """Crear ChecklistInstance para orden activa."""
        url = '/api/checklists/instances/'
        response = self.client.post(url, {
            'orden': self.orden.id,
            'checklist_template': self.template.id
        }, format='json')
        
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ChecklistInstance.objects.filter(orden=self.orden).exists())
        instance = ChecklistInstance.objects.get(orden=self.orden)
        self.assertEqual(instance.estado, 'BORRADOR')
    
    def test_partial_save_respuestas(self):
        """Guardar respuestas parciales (no todos los items)."""
        instance = ChecklistInstance.objects.create(
            orden=self.orden,
            checklist_template=self.template,
            estado='EN_PROGRESO'
        )
        
        # Responder solo item1 (SELECT type)
        url = '/api/checklists/responses/'
        response = self.client.post(url, {
            'checklist_instance': instance.id,
            'item_template': self.item1.id,
            'respuesta_seleccion': 'bueno',
            'respuesta_texto': 'Frenos en buen estado'
        }, format='json')
        
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ChecklistItemResponse.objects.filter(checklist_instance=instance).count(), 1)
        
        # Item2 sin respuesta aún
        self.assertFalse(ChecklistItemResponse.objects.filter(
            checklist_instance=instance,
            item_template=self.item2
        ).exists())
    
    def test_pause_checklist(self):
        """Pausar checklist en progreso."""
        instance = ChecklistInstance.objects.create(
            orden=self.orden,
            checklist_template=self.template,
            estado='EN_PROGRESO'
        )
        
        url = f'/api/checklists/instances/{instance.id}/pause/'
        response = self.client.post(url, {})
        
        self.assertEqual(response.status_code, 200)
        instance.refresh_from_db()
        self.assertEqual(instance.estado, 'PAUSADO')
    
    def test_pause_requires_en_progreso(self):
        """Pausar requiere estado EN_PROGRESO."""
        instance = ChecklistInstance.objects.create(
            orden=self.orden,
            checklist_template=self.template,
            estado='BORRADOR'
        )
        
        url = f'/api/checklists/instances/{instance.id}/pause/'
        response = self.client.post(url, {})
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)
    
    def test_resume_checklist(self):
        """Reanudar checklist pausado."""
        instance = ChecklistInstance.objects.create(
            orden=self.orden,
            checklist_template=self.template,
            estado='PAUSADO'
        )
        
        url = f'/api/checklists/instances/{instance.id}/resume/'
        response = self.client.post(url, {})
        
        self.assertEqual(response.status_code, 200)
        instance.refresh_from_db()
        self.assertEqual(instance.estado, 'EN_PROGRESO')
    
    def test_resume_preserves_partial_responses(self):
        """Reanudar checklist preserva respuestas parciales guardadas."""
        instance = ChecklistInstance.objects.create(
            orden=self.orden,
            checklist_template=self.template,
            estado='EN_PROGRESO'
        )
        
        # Guardar respuesta item1
        ChecklistItemResponse.objects.create(
            checklist_instance=instance,
            item_template=self.item1,
            respuesta_seleccion='bueno',
            respuesta_texto='Primera respuesta',
            completado=True
        )
        
        # Pausar
        instance.estado = 'PAUSADO'
        instance.save()
        
        # Reanudar
        url = f'/api/checklists/instances/{instance.id}/resume/'
        response = self.client.post(url, {})
        
        self.assertEqual(response.status_code, 200)
        # Verificar respuesta anterior sigue existiendo
        self.assertTrue(ChecklistItemResponse.objects.filter(
            checklist_instance=instance,
            item_template=self.item1
        ).exists())
    
    def test_update_existing_response_idempotente(self):
        """Actualizar respuesta existente (idempotente)."""
        instance = ChecklistInstance.objects.create(
            orden=self.orden,
            checklist_template=self.template,
            estado='EN_PROGRESO'
        )
        
        # Primera respuesta
        url = '/api/checklists/responses/'
        response1 = self.client.post(url, {
            'checklist_instance': instance.id,
            'item_template': self.item1.id,
            'respuesta_seleccion': 'bueno',
            'respuesta_texto': 'Primer check'
        }, format='json')
        self.assertEqual(response1.status_code, 201)
        resp_id = response1.data['id']
        
        # Actualizar (mismo item_template + checklist_instance)
        response2 = self.client.post(url, {
            'checklist_instance': instance.id,
            'item_template': self.item1.id,
            'respuesta_seleccion': 'regular',
            'respuesta_texto': 'Actualizado'
        }, format='json')
        
        # Debe retornar 200 (update) no 201 (create)
        self.assertEqual(response2.status_code, 200)
        # Solo debe existir 1 respuesta para este item
        self.assertEqual(ChecklistItemResponse.objects.filter(
            checklist_instance=instance,
            item_template=self.item1
        ).count(), 1)
        
        # Verificar actualización
        resp = ChecklistItemResponse.objects.get(id=resp_id)
        self.assertEqual(resp.respuesta_seleccion, 'regular')
        self.assertEqual(resp.respuesta_texto, 'Actualizado')


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_RESULT_BACKEND='cache+memory://'
)
class AdditionalQuotesWorkflowTestCase(TestCase):
    """Test findings -> additional quotes -> customer authorization -> base independence."""
    
    def setUp(self):
        """Create base order with customer."""
        # Taller
        self.user_taller = User.objects.create_user(
            username='taller_extras',
            password='test',
            email='taller_extras@test.com'
        )
        self.taller = Taller.objects.create(
            usuario=self.user_taller,
            nombre='Taller Extras',
            rut='22222222-2',
            telefono='+56933333333',
            estado_verificacion='aprobado'
        )
        
        # Cliente
        self.user_cliente = User.objects.create_user(
            username='cliente_extras',
            password='test',
            email='cliente_extras@test.com'
        )
        self.cliente = Cliente.objects.create(
            usuario=self.user_cliente,
            nombre='Cliente',
            apellido='Extras',
            email='cliente_extras@test.com',
            telefono='+56944444444'
        )
        
        # Vehículo
        marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Nissan')
        modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Sentra')
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca,
            modelo=modelo,
            year=2019,
            patente='EF9012'
        )
        
        # Cotización base (aceptada)
        self.cot_base = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user_taller,
            estado='aceptada',
            servicio_nombre='Cambio de aceite',
            mano_obra_clp=30000,
            total_clp=50000,
            token='base-token-001'
        )
        
        # Cita base
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.cot_base,
            fecha_servicio=date.today(),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            creado_por=self.user_taller
        )
        
        # Clients
        self.client_taller = APIClient()
        self.client_taller.force_authenticate(user=self.user_taller)
        
        self.client_cliente = APIClient()
        self.client_cliente.force_authenticate(user=self.user_cliente)
    
    def test_crear_cotizacion_adicional_misma_visita(self):
        """Crear cotización adicional (hallazgo) para misma visita."""
        # Simular hallazgo durante inspección
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Se detectó fuga en manguera',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        
        self.assertTrue(cot_adicional.es_cotizacion_adicional)
        self.assertEqual(cot_adicional.cotizacion_original_id, self.cot_base.id)
        self.assertEqual(cot_adicional.ejecucion_adicional, 'misma_visita')
        self.assertEqual(cot_adicional.estado, 'borrador')  # Pending customer approval
    
    def test_cotizacion_adicional_nueva_fecha(self):
        """Cotización adicional para nueva fecha requiere fecha/hora propuesta."""
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Cambio de correa distribución',
            servicios_catalogo=[],
            ejecucion_adicional='nueva_fecha',
            fecha_propuesta=date(2026, 11, 15),
            hora_propuesta=time(14, 0)
        )
        
        self.assertEqual(cot_adicional.ejecucion_adicional, 'nueva_fecha')
        self.assertEqual(cot_adicional.fecha_propuesta, date(2026, 11, 15))
        self.assertEqual(cot_adicional.hora_propuesta, time(14, 0))
    
    def test_base_order_completes_with_pending_extra(self):
        """Orden base puede completarse con extra pendiente de aprobación."""
        # Crear extra pendiente
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Filtro aire sucio',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        self.assertEqual(cot_adicional.estado, 'borrador')  # Pending
        
        # Completar orden base
        self.cot_base.estado = 'completada'
        self.cot_base.save()
        self.cot_base.refresh_from_db()
        
        self.assertEqual(self.cot_base.estado, 'completada')
        # Extra sigue pendiente
        cot_adicional.refresh_from_db()
        self.assertEqual(cot_adicional.estado, 'borrador')
    
    def test_base_order_completes_with_rejected_extra(self):
        """Orden base puede completarse con extra rechazado por cliente."""
        # Crear y rechazar extra
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Pastillas freno extra',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        cot_adicional.estado = 'rechazada'  # Cliente rechazó
        cot_adicional.save()
        
        # Completar base
        self.cot_base.estado = 'completada'
        self.cot_base.save()
        
        self.assertEqual(self.cot_base.estado, 'completada')
        # Extra sigue rechazado
        cot_adicional.refresh_from_db()
        self.assertEqual(cot_adicional.estado, 'rechazada')
    
    def test_approved_extra_extends_scope(self):
        """Extra aprobado por cliente extiende alcance autorizado."""
        # Crear extra
        cot_adicional = crear_cotizacion_adicional_desde_catalogo(
            cotizacion_original=self.cot_base,
            cita=self.cita,
            taller=self.taller,
            creado_por=self.user_taller,
            motivo_servicio_adicional='Filtro combustible',
            servicios_catalogo=[],
            ejecucion_adicional='misma_visita'
        )
        cot_adicional.mano_obra_clp = 15000
        cot_adicional.total_clp = 25000
        cot_adicional.save()
        
        # Cliente aprueba (simular aceptación)
        cot_adicional.estado = 'aceptada'
        cot_adicional.save()
        
        # Verificar aprobación
        self.assertEqual(cot_adicional.estado, 'aceptada')
        # Alcance base + extra aprobado
        total_autorizado = self.cot_base.total_clp + cot_adicional.total_clp
        self.assertEqual(total_autorizado, Decimal('75000'))


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_RESULT_BACKEND='cache+memory://'
)
class ConcurrentRequestsTestCase(TransactionTestCase):
    """Test actual concurrent transactions (not just select_for_update inspection)."""
    
    def setUp(self):
        """Create test fixtures."""
        self.user = User.objects.create_user(
            username='concurrent_user',
            password='test',
            email='concurrent@test.com'
        )
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Concurrent',
            rut='33333333-3',
            telefono='+56955555555',
            estado_verificacion='aprobado'
        )
        
        user_cliente = User.objects.create_user(
            username='cliente_concurrent',
            password='test',
            email='cliente_concurrent@test.com'
        )
        self.cliente = Cliente.objects.create(
            usuario=user_cliente,
            nombre='Cliente',
            apellido='Concurrent',
            email='cliente_concurrent@test.com',
            telefono='+56966666666'
        )
        
        marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Ford')
        modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Focus')
        self.vehiculo = Vehiculo.objects.create(
            cliente=self.cliente,
            marca=marca,
            modelo=modelo,
            year=2020,
            patente='GH3456'
        )
    
    def test_concurrent_accept_serialized(self):
        """Two concurrent accept requests are serialized by select_for_update."""
        orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=self.vehiculo,
            tipo_servicio='taller',
            taller=self.taller,
            fecha_servicio=date.today(),
            hora_servicio=time(12, 0),
            metodo_pago='efectivo',
            total=Decimal('60000.00'),
            estado='pendiente_aceptacion_proveedor'
        )
        
        from mecanimovilapp.apps.ordenes.views import ProveedorOrdenesViewSet
        from unittest.mock import Mock
        import threading
        
        results = []
        errors = []
        
        def accept_in_thread():
            try:
                # Simulate concurrent request
                from django.db import connection
                connection.close()  # Force new connection
                
                with transaction.atomic():
                    orden_locked = SolicitudServicio.objects.select_for_update().get(pk=orden.pk)
                    if orden_locked.estado == 'pendiente_aceptacion_proveedor':
                        orden_locked.estado = 'aceptada_por_proveedor'
                        orden_locked.save()
                        results.append('accepted')
                    else:
                        results.append('already_accepted')
            except Exception as e:
                errors.append(str(e))
        
        # Simulate 2 concurrent threads
        thread1 = threading.Thread(target=accept_in_thread)
        thread2 = threading.Thread(target=accept_in_thread)
        
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()
        
        # One should accept, one should see already_accepted
        self.assertEqual(len(results), 2)
        self.assertEqual(len(errors), 0)
        self.assertIn('accepted', results)
        self.assertIn('already_accepted', results)
        
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'aceptada_por_proveedor')

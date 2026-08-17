"""Tests: cotización adicional ligada a un servicio principal en ejecución."""
from datetime import date, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CitaAgendaPersonalDetalle,
    CotizacionCanal,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
    cita_permite_cotizacion_adicional,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import formatear_teaser_cotizacion
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    aceptar_cotizacion_publica,
    serializar_cotizacion_publica,
)
from mecanimovilapp.apps.ordenes.services.resumen_economico_cita import (
    construir_resumen_economico_cita,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class CotizacionAdicionalFlujoTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_adicional', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Embrague',
            telefono='900000001',
            estado_verificacion='aprobado',
        )
        self.cot_principal = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            modalidad='domicilio',
            cliente_nombre='Cliente Test',
            cliente_telefono='+56911111111',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_patente='AB1234',
            servicio_nombre='Cambio de kit de embrague',
            mano_obra_clp=180000,
            costo_repuestos_clp=220000,
            total_clp=400000,
            token='tok-principal-test',
        )
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.cot_principal,
            fecha_servicio=date(2030, 8, 12),
            hora_servicio=time(10, 0),
            duracion_minutos=180,
            tipo_servicio='domicilio',
            estado='activa',
            horario_por_confirmar=False,
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=self.cita,
            cliente_nombre='Cliente Test',
            cliente_telefono='+56911111111',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_patente='AB1234',
            servicio_nombre='Cambio de kit de embrague',
            precio_referencia=400000,
        )

    def _crear_adicional(self, estado='enviada', **kwargs):
        defaults = {
            'es_libre': True,
            'taller': self.taller,
            'creado_por': self.user,
            'estado': estado,
            'modalidad': 'domicilio',
            'cliente_nombre': 'Cliente Test',
            'vehiculo_marca': 'Fiat',
            'vehiculo_modelo': 'Bravo',
            'vehiculo_patente': 'AB1234',
            'servicio_nombre': 'Cambio de soporte de motor',
            'motivo_servicio_adicional': 'Soporte de motor lado caja en mal estado',
            'es_cotizacion_adicional': True,
            'cotizacion_original': self.cot_principal,
            'cita_origen': self.cita,
            'mano_obra_clp': 45000,
            'costo_repuestos_clp': 35000,
            'total_clp': 80000,
            'duracion_minutos_estimada': 40,
            'token': 'tok-adicional-test',
            'enviada_en': timezone.now() if estado == 'enviada' else None,
        }
        defaults.update(kwargs)
        return CotizacionCanal.objects.create(**defaults)

    def test_cita_no_permite_adicional_sin_checklist(self):
        self.assertFalse(cita_permite_cotizacion_adicional(self.cita))

    def test_cita_permite_adicional_con_checklist_en_curso(self):
        from types import SimpleNamespace

        self.cita.checklist_instance = SimpleNamespace(estado='EN_PROGRESO')
        self.assertTrue(cita_permite_cotizacion_adicional(self.cita))

    def test_cita_no_permite_segundo_adicional_pendiente(self):
        from types import SimpleNamespace

        self.cita.checklist_instance = SimpleNamespace(estado='EN_PROGRESO')
        self._crear_adicional(estado='enviada', token='tok-pendiente')
        # Refresh related manager on the in-memory cita
        self.cita = CitaAgendaPersonal.objects.get(pk=self.cita.pk)
        self.cita.checklist_instance = SimpleNamespace(estado='EN_PROGRESO')
        self.assertFalse(cita_permite_cotizacion_adicional(self.cita))

    def test_serializar_publico_expone_trabajo_adicional(self):
        adicional = self._crear_adicional()
        data = serializar_cotizacion_publica(adicional)
        self.assertTrue(data['es_trabajo_adicional'])
        self.assertEqual(data['motivo_servicio_adicional'], 'Soporte de motor lado caja en mal estado')
        self.assertEqual(data['servicio_principal']['nombre'], 'Cambio de kit de embrague')
        self.assertTrue(data['pago_directo_taller'])
        self.assertEqual(data['ejecucion_adicional'], 'misma_visita')
        self.assertIsNone(data['fecha_propuesta'])
        self.assertNotIn('cita_origen_id', data)

    def test_serializar_publico_principal_no_marca_adicional(self):
        data = serializar_cotizacion_publica(self.cot_principal)
        self.assertFalse(data['es_trabajo_adicional'])
        self.assertIsNone(data['servicio_principal'])

    def test_aceptar_adicional_no_crea_cita_nueva(self):
        adicional = self._crear_adicional()
        citas_antes = CitaAgendaPersonal.objects.filter(taller=self.taller).count()
        cot, cita = aceptar_cotizacion_publica(adicional)
        self.assertEqual(cot.estado, 'aceptada')
        self.assertEqual(cita.id, self.cita.id)
        self.assertEqual(
            CitaAgendaPersonal.objects.filter(taller=self.taller).count(),
            citas_antes,
        )
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.duracion_minutos, 220)
        self.cita.detalle.refresh_from_db()
        self.assertEqual(int(self.cita.detalle.precio_referencia), 480000)

    def test_aceptar_principal_sigue_creando_cita(self):
        principal = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='enviada',
            modalidad='taller',
            cliente_nombre='Otro',
            servicio_nombre='Alineación',
            total_clp=50000,
            token='tok-otra-principal',
            enviada_en=timezone.now(),
        )
        cot, cita = aceptar_cotizacion_publica(principal)
        self.assertEqual(cot.estado, 'aceptada')
        self.assertIsNotNone(cita)
        self.assertEqual(cita.cotizacion_canal_origen_id, principal.id)
        self.assertTrue(cita.horario_por_confirmar)
        self.assertNotEqual(cita.id, self.cita.id)

    def test_teaser_adicional_menciona_servicio_principal(self):
        adicional = self._crear_adicional(url_publica='https://example.com/cotizacion/x')
        teaser = formatear_teaser_cotizacion(adicional)
        self.assertIn('trabajo adicional', teaser.lower())
        self.assertIn('Cambio de kit de embrague', teaser)

    def test_resumen_economico_suma_adicional_aceptada(self):
        self._crear_adicional(estado='aceptada', token='tok-adicional-aceptada')
        resumen = construir_resumen_economico_cita(self.cita)
        self.assertEqual(resumen['total_clp'], 400000)
        self.assertEqual(resumen['total_visita_clp'], 480000)
        self.assertEqual(len(resumen['servicios_secundarios']), 1)
        self.assertEqual(resumen['servicios_secundarios'][0]['estado'], 'aceptada')

    def test_resumen_no_suma_adicional_enviada(self):
        self._crear_adicional(estado='enviada')
        resumen = construir_resumen_economico_cita(self.cita)
        self.assertEqual(resumen['total_visita_clp'], 400000)

    @patch('mecanimovilapp.apps.ordenes.services.cotizacion_publica.iniciar_agendamiento_task', create=True)
    def test_on_respondida_no_agenda_adicional(self, _mock_task):
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import on_cotizacion_respondida

        adicional = self._crear_adicional()
        adicional.estado = 'aceptada'
        adicional.save(update_fields=['estado'])
        with patch(
            'mecanimovilapp.apps.agente_ia.tasks.iniciar_agendamiento_task'
        ) as mock_agenda:
            on_cotizacion_respondida(adicional, 'aceptar', cita_id=self.cita.id)
            mock_agenda.delay.assert_not_called()

    def test_api_publica_aceptar_adicional(self):
        adicional = self._crear_adicional()
        client = APIClient()
        res = client.post('/api/ordenes/cotizaciones-publicas/tok-adicional-test/aceptar/')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.data['es_trabajo_adicional'])
        self.assertFalse(res.data.get('horario_por_confirmar'))
        self.assertNotIn('cita_id', res.data)
        self.assertEqual(
            CitaAgendaPersonal.objects.filter(cotizacion_canal_origen=adicional).count(),
            0,
        )
        adicional.refresh_from_db()
        self.assertEqual(adicional.estado, 'aceptada')
        self.assertEqual(adicional.cita_origen_id, self.cita.id)

    def test_no_anidar_adicional(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
            crear_cotizacion_adicional_desde_catalogo,
        )

        adicional = self._crear_adicional(estado='aceptada', token='tok-ya-adicional')
        with self.assertRaises(ValueError):
            crear_cotizacion_adicional_desde_catalogo(
                cotizacion_original=adicional,
                cita=self.cita,
                taller=self.taller,
                creado_por=self.user,
                motivo_servicio_adicional='Otro hallazgo',
                servicios_catalogo=[{'oferta_id': 1, 'cantidad': 1}],
            )

    def test_aceptar_adicional_nueva_fecha_crea_cita_hija(self):
        adicional = self._crear_adicional(
            token='tok-adicional-fecha',
            ejecucion_adicional='nueva_fecha',
            fecha_propuesta=date(2030, 8, 20),
            hora_propuesta=time(16, 30),
        )
        citas_antes = CitaAgendaPersonal.objects.filter(taller=self.taller).count()
        duracion_padre = self.cita.duracion_minutos
        cot, cita = aceptar_cotizacion_publica(adicional)
        self.assertEqual(cot.estado, 'aceptada')
        self.assertNotEqual(cita.id, self.cita.id)
        self.assertEqual(cita.cotizacion_canal_origen_id, adicional.id)
        self.assertEqual(cita.fecha_servicio, date(2030, 8, 20))
        self.assertEqual(cita.hora_servicio, time(16, 30))
        self.assertFalse(cita.horario_por_confirmar)
        self.assertEqual(
            CitaAgendaPersonal.objects.filter(taller=self.taller).count(),
            citas_antes + 1,
        )
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.duracion_minutos, duracion_padre)
        self.cita.detalle.refresh_from_db()
        self.assertEqual(int(self.cita.detalle.precio_referencia), 400000)

    def test_resumen_no_suma_adicional_nueva_fecha_aceptada(self):
        self._crear_adicional(
            estado='aceptada',
            token='tok-adicional-fecha-aceptada',
            ejecucion_adicional='nueva_fecha',
            fecha_propuesta=date(2030, 8, 21),
            hora_propuesta=time(9, 0),
        )
        resumen = construir_resumen_economico_cita(self.cita)
        self.assertEqual(resumen['total_visita_clp'], 400000)
        self.assertEqual(resumen['servicios_secundarios'][0]['ejecucion_adicional'], 'nueva_fecha')

    def test_teaser_nueva_fecha_menciona_slot(self):
        adicional = self._crear_adicional(
            url_publica='https://example.com/cotizacion/x',
            ejecucion_adicional='nueva_fecha',
            fecha_propuesta=date(2030, 8, 20),
            hora_propuesta=time(16, 30),
        )
        teaser = formatear_teaser_cotizacion(adicional)
        self.assertIn('20/08/2030', teaser)
        self.assertIn('16:30', teaser)

    def test_enviar_nueva_fecha_sin_hora_falla(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
            validar_adicional_listo_para_enviar,
        )

        adicional = self._crear_adicional(
            estado='borrador',
            token='tok-borrador-fecha',
            ejecucion_adicional='nueva_fecha',
            fecha_propuesta=None,
            hora_propuesta=None,
            enviada_en=None,
        )
        with self.assertRaises(ValueError):
            validar_adicional_listo_para_enviar(adicional)

    def test_serializar_publico_nueva_fecha(self):
        adicional = self._crear_adicional(
            ejecucion_adicional='nueva_fecha',
            fecha_propuesta=date(2030, 8, 20),
            hora_propuesta=time(16, 30),
        )
        data = serializar_cotizacion_publica(adicional)
        self.assertEqual(data['ejecucion_adicional'], 'nueva_fecha')
        self.assertEqual(data['fecha_propuesta'], '2030-08-20')
        self.assertEqual(data['hora_propuesta'], '16:30')

    def test_cita_es_dia_de_servicio_solo_hoy(self):
        from mecanimovilapp.apps.ordenes.services.cita_agenda_personal import (
            cita_es_dia_de_servicio,
        )

        self.cita.fecha_servicio = date(2030, 8, 12)
        self.assertFalse(cita_es_dia_de_servicio(self.cita))
        self.cita.fecha_servicio = timezone.localdate()
        self.assertTrue(cita_es_dia_de_servicio(self.cita))

    def test_iniciar_servicio_fuera_de_fecha_409(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        res = client.post(f'/api/ordenes/citas-agenda-personal/{self.cita.id}/iniciar-servicio/')
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.data.get('codigo'), 'fuera_de_fecha')

    def test_reabrir_enviada_conserva_token(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            reabrir_cotizacion_enviada,
        )

        cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='enviada',
            modalidad='domicilio',
            servicio_nombre='Alineación',
            mano_obra_clp=50000,
            total_clp=50000,
            token='tok-reabrir-stable',
            enviada_en=timezone.now(),
        )
        reabrir_cotizacion_enviada(cot)
        cot.refresh_from_db()
        self.assertEqual(cot.estado, 'borrador')
        self.assertEqual(cot.token, 'tok-reabrir-stable')
        self.assertTrue((cot.metadata or {}).get('reabierta_por_taller'))

    def test_actualizar_aceptada_sin_iniciar_total_igual(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            actualizar_cotizacion_aceptada_sin_iniciar,
        )

        cot, modo = actualizar_cotizacion_aceptada_sin_iniciar(
            self.cot_principal,
            {
                'servicio_nombre': 'Cambio de kit de embrague (ajustado)',
                'mano_obra_clp': 180000,
                'repuestos': [
                    {
                        'nombre': 'Kit embrague',
                        'cantidad': 1,
                        'precio_unitario_clp': 220000,
                    }
                ],
            },
        )
        self.assertEqual(modo, 'actualizada')
        self.assertEqual(cot.estado, 'aceptada')
        self.assertEqual(int(cot.total_clp), 400000)
        self.cita.detalle.refresh_from_db()
        self.assertEqual(int(self.cita.detalle.precio_referencia), 400000)

    def test_actualizar_aceptada_sin_iniciar_total_sube_a_enviada(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            actualizar_cotizacion_aceptada_sin_iniciar,
        )

        cot, modo = actualizar_cotizacion_aceptada_sin_iniciar(
            self.cot_principal,
            {
                'servicio_nombre': 'Cambio de kit de embrague + disco',
                'mano_obra_clp': 250000,
                'repuestos': [
                    {
                        'nombre': 'Kit embrague',
                        'cantidad': 1,
                        'precio_unitario_clp': 220000,
                    }
                ],
            },
        )
        self.assertEqual(modo, 'requiere_confirmacion')
        self.assertEqual(cot.estado, 'enviada')
        self.assertEqual(int(cot.total_clp), 470000)
        self.cita.detalle.refresh_from_db()
        self.assertEqual(int(self.cita.detalle.precio_referencia), 400000)

    def test_actualizada_por_taller_por_metadata_y_timestamp(self):
        self.cot_principal.estado = 'enviada'
        self.cot_principal.enviada_en = timezone.now() - timedelta(hours=2)
        self.cot_principal.metadata = {'reabierta_por_taller': True}
        self.cot_principal.save()
        data = serializar_cotizacion_publica(self.cot_principal)
        self.assertTrue(data['actualizada_por_taller'])

        self.cot_principal.metadata = {}
        self.cot_principal.actualizado_en = timezone.now()
        self.cot_principal.save(update_fields=['metadata', 'actualizado_en'])
        data2 = serializar_cotizacion_publica(self.cot_principal)
        self.assertTrue(data2['actualizada_por_taller'])


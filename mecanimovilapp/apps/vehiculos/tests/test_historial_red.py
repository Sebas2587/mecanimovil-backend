"""Historial clínico de patente en la red: privacidad de montos y patente válida."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle
from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.vehiculos.services.historial_red import (
    _clave_servicio,
    _percentile,
    consultar_historial_red,
    patente_consulta_valida,
    texto_historial_red_para_prompt,
)

User = get_user_model()


class PatenteConsultaValidaTests(SimpleTestCase):
    def test_vacia_o_basura(self):
        self.assertFalse(patente_consulta_valida(''))
        self.assertFalse(patente_consulta_valida('   '))
        self.assertFalse(patente_consulta_valida('!!!'))
        self.assertFalse(patente_consulta_valida('AB'))
        self.assertFalse(patente_consulta_valida('ABCDEFGHI'))

    def test_chilena_compacta_o_con_guion(self):
        self.assertTrue(patente_consulta_valida('KGGR22'))
        self.assertTrue(patente_consulta_valida('KG-GR22'))
        self.assertTrue(patente_consulta_valida(' kg gr 22 '))


class TextoHistorialRedPromptTests(SimpleTestCase):
    def test_monto_solo_taller_propio_y_no_suma_pedido(self):
        texto = texto_historial_red_para_prompt(
            [
                {
                    'fecha': '2024-03-01',
                    'taller_nombre': 'Taller Sur',
                    'taller_es_propio': False,
                    'servicio_nombre': 'Cambio de bomba de embrague',
                    'kilometraje': 80000,
                    'monto_clp': 237000,
                },
                {
                    'fecha': '2025-01-10',
                    'taller_nombre': 'Taller Norte',
                    'taller_es_propio': True,
                    'servicio_nombre': 'Diagnóstico de frenos',
                    'kilometraje': 92000,
                    'monto_clp': 45000,
                },
            ]
        )
        self.assertIn('NO agregues estos servicios al pedido', texto)
        self.assertIn('Diagnóstico de frenos', texto)
        self.assertIn('$45.000', texto)
        self.assertIn('Cambio de bomba de embrague', texto)
        self.assertNotIn('237', texto)
        self.assertNotIn('en la red', texto)

    def test_rango_anonimo_en_ajeno_sin_boleta(self):
        texto = texto_historial_red_para_prompt(
            [
                {
                    'fecha': '2024-03-01',
                    'taller_nombre': 'Taller Sur',
                    'taller_es_propio': False,
                    'servicio_nombre': 'Cambio de bomba de embrague',
                    'kilometraje': 80000,
                    'monto_clp': 237000,
                    'rango_mercado_clp': {'min': 180000, 'max': 260000, 'muestras': 8},
                },
            ]
        )
        self.assertIn('en la red $180.000–$260.000', texto)
        self.assertNotIn('237', texto)


class RangoMercadoHelpersTests(SimpleTestCase):
    def test_servicio_con_coma_no_tiene_clave(self):
        self.assertIsNone(_clave_servicio('Frenos, aceite'))
        self.assertTrue(_clave_servicio('Cambio de bomba de embrague'))

    def test_percentile_p25_p75(self):
        vals = [180000, 220000, 260000]
        self.assertEqual(_percentile(vals, 0.25), 200000)
        self.assertEqual(_percentile(vals, 0.75), 240000)
        self.assertEqual(_percentile([200000, 200000, 200000], 0.25), 200000)


class HistorialRedPrivacidadTests(TestCase):
    def setUp(self):
        self.user_norte = User.objects.create_user(username='taller_norte', password='test123')
        self.taller_norte = Taller.objects.create(
            usuario=self.user_norte,
            nombre='Taller Norte',
            telefono='900000011',
            estado_verificacion='aprobado',
        )
        self.user_sur = User.objects.create_user(username='taller_sur', password='test123')
        self.taller_sur = Taller.objects.create(
            usuario=self.user_sur,
            nombre='Taller Sur',
            telefono='900000012',
            estado_verificacion='aprobado',
        )
        self.user_este = User.objects.create_user(username='taller_este', password='test123')
        self.taller_este = Taller.objects.create(
            usuario=self.user_este,
            nombre='Taller Este',
            telefono='900000014',
            estado_verificacion='aprobado',
        )

    def _cita(self, *, taller, user, estado, patente, servicio, precio, fecha, cerrada=False):
        kwargs = {
            'taller': taller,
            'fecha_servicio': fecha,
            'hora_servicio': time(10, 0),
            'duracion_minutos': 60,
            'tipo_servicio': 'taller',
            'estado': estado,
            'creado_por': user,
        }
        if cerrada:
            kwargs['cerrada_en'] = timezone.now()
        cita = CitaAgendaPersonal.objects.create(**kwargs)
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre='Cliente',
            vehiculo_marca='Changan',
            vehiculo_modelo='Hunter',
            vehiculo_patente=patente,
            servicio_nombre=servicio,
            precio_referencia=precio,
        )
        return cita

    def test_propio_con_monto_ajeno_sin_monto(self):
        self._cita(
            taller=self.taller_norte,
            user=self.user_norte,
            estado='cerrada',
            patente='KGGR22',
            servicio='Diagnóstico de frenos',
            precio=45000,
            fecha=date(2025, 1, 10),
            cerrada=True,
        )
        self._cita(
            taller=self.taller_sur,
            user=self.user_sur,
            estado='cerrada',
            patente='KG-GR22',
            servicio='Cambio de bomba de embrague',
            precio=237000,
            fecha=date(2024, 3, 1),
            cerrada=True,
        )
        payload = consultar_historial_red(patente='KGGR22', taller_id=self.taller_norte.id)
        self.assertNotIn('error', payload)
        self.assertEqual(len(payload['eventos']), 2)
        propio = next(e for e in payload['eventos'] if e['taller_es_propio'])
        ajeno = next(e for e in payload['eventos'] if not e['taller_es_propio'])
        self.assertEqual(propio['monto_clp'], 45000)
        self.assertEqual(propio['servicio_nombre'], 'Diagnóstico de frenos')
        self.assertEqual(ajeno['monto_clp'], None)
        self.assertIsNone(ajeno.get('rango_mercado_clp'))
        self.assertEqual(propio.get('rango_mercado_clp'), None)
        self.assertEqual(ajeno['taller_nombre'], 'Taller Sur')
        self.assertIn('bomba', ajeno['servicio_nombre'].lower())

    def test_cita_activa_ajena_no_aparece(self):
        self._cita(
            taller=self.taller_sur,
            user=self.user_sur,
            estado='activa',
            patente='KGGR22',
            servicio='Trabajo en curso ajeno',
            precio=99000,
            fecha=date(2026, 8, 20),
        )
        payload = consultar_historial_red(patente='KGGR22', taller_id=self.taller_norte.id)
        self.assertEqual(payload['eventos'], [])

    def test_patente_invalida_no_consulta(self):
        payload = consultar_historial_red(patente='??', taller_id=self.taller_norte.id)
        self.assertEqual(payload['error'], 'patente_invalida')
        self.assertEqual(payload['eventos'], [])

    def test_rango_con_tres_muestras_y_dos_talleres(self):
        self._cita(
            taller=self.taller_sur,
            user=self.user_sur,
            estado='cerrada',
            patente='KGGR22',
            servicio='Cambio de bomba de embrague',
            precio=180000,
            fecha=date(2024, 3, 1),
            cerrada=True,
        )
        self._cita(
            taller=self.taller_sur,
            user=self.user_sur,
            estado='cerrada',
            patente='AA1111',
            servicio='Cambio de bomba de embrague',
            precio=220000,
            fecha=date(2024, 6, 1),
            cerrada=True,
        )
        self._cita(
            taller=self.taller_este,
            user=self.user_este,
            estado='cerrada',
            patente='BB2222',
            servicio='Cambio de bomba de embrague',
            precio=260000,
            fecha=date(2025, 1, 1),
            cerrada=True,
        )
        payload = consultar_historial_red(patente='KGGR22', taller_id=self.taller_norte.id)
        ajeno = payload['eventos'][0]
        self.assertFalse(ajeno['taller_es_propio'])
        self.assertIsNone(ajeno['monto_clp'])
        rango = ajeno['rango_mercado_clp']
        self.assertIsNotNone(rango)
        self.assertEqual(rango['muestras'], 3)
        self.assertLess(rango['min'], rango['max'])
        self.assertEqual(rango['min'], 200000)
        self.assertEqual(rango['max'], 240000)

    def test_rango_omitido_si_un_solo_taller(self):
        for patente, precio, fecha in (
            ('KGGR22', 180000, date(2024, 3, 1)),
            ('AA1111', 220000, date(2024, 6, 1)),
            ('BB2222', 260000, date(2025, 1, 1)),
        ):
            self._cita(
                taller=self.taller_sur,
                user=self.user_sur,
                estado='cerrada',
                patente=patente,
                servicio='Cambio de bomba de embrague',
                precio=precio,
                fecha=fecha,
                cerrada=True,
            )
        payload = consultar_historial_red(patente='KGGR22', taller_id=self.taller_norte.id)
        ajeno = payload['eventos'][0]
        self.assertIsNone(ajeno['monto_clp'])
        self.assertIsNone(ajeno['rango_mercado_clp'])

    def test_rango_omitido_si_p25_igual_p75(self):
        self._cita(
            taller=self.taller_sur,
            user=self.user_sur,
            estado='cerrada',
            patente='KGGR22',
            servicio='Cambio de bomba de embrague',
            precio=200000,
            fecha=date(2024, 3, 1),
            cerrada=True,
        )
        self._cita(
            taller=self.taller_sur,
            user=self.user_sur,
            estado='cerrada',
            patente='AA1111',
            servicio='Cambio de bomba de embrague',
            precio=200000,
            fecha=date(2024, 6, 1),
            cerrada=True,
        )
        self._cita(
            taller=self.taller_este,
            user=self.user_este,
            estado='cerrada',
            patente='BB2222',
            servicio='Cambio de bomba de embrague',
            precio=200000,
            fecha=date(2025, 1, 1),
            cerrada=True,
        )
        payload = consultar_historial_red(patente='KGGR22', taller_id=self.taller_norte.id)
        self.assertIsNone(payload['eventos'][0]['rango_mercado_clp'])

    def test_evento_propio_monto_exacto_sin_rango(self):
        self._cita(
            taller=self.taller_norte,
            user=self.user_norte,
            estado='cerrada',
            patente='KGGR22',
            servicio='Diagnóstico de frenos',
            precio=45000,
            fecha=date(2025, 1, 10),
            cerrada=True,
        )
        self._cita(
            taller=self.taller_sur,
            user=self.user_sur,
            estado='cerrada',
            patente='AA1111',
            servicio='Diagnóstico de frenos',
            precio=180000,
            fecha=date(2024, 3, 1),
            cerrada=True,
        )
        self._cita(
            taller=self.taller_este,
            user=self.user_este,
            estado='cerrada',
            patente='BB2222',
            servicio='Diagnóstico de frenos',
            precio=260000,
            fecha=date(2025, 2, 1),
            cerrada=True,
        )
        payload = consultar_historial_red(patente='KGGR22', taller_id=self.taller_norte.id)
        propio = next(e for e in payload['eventos'] if e['taller_es_propio'])
        self.assertEqual(propio['monto_clp'], 45000)
        self.assertIsNone(propio['rango_mercado_clp'])


class HistorialRedAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='prov_hist', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller API Hist',
            telefono='900000013',
            estado_verificacion='aprobado',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_sin_patente_400(self):
        resp = self.client.get('/api/vehiculos/historial-red/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data.get('code'), 'patente_invalida')

    def test_patente_basura_400(self):
        resp = self.client.get('/api/vehiculos/historial-red/?patente=!!!')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data.get('code'), 'patente_invalida')

    def test_anonimo_401(self):
        anon = APIClient()
        resp = anon.get('/api/vehiculos/historial-red/?patente=KGGR22')
        self.assertIn(resp.status_code, (401, 403))

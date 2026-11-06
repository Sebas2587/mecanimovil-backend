"""Caja del taller: abonos, reversos, legacy y totales de la misma respuesta."""
import threading
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import (
    AnclaCaja,
    CitaAgendaPersonal,
    CitaAgendaPersonalDetalle,
    CobroTaller,
    CotizacionCanal,
    OfertaProveedor,
    SolicitudServicio,
    SolicitudServicioPublica,
)
from mecanimovilapp.apps.ordenes.serializers import SolicitudServicioProveedorSerializer
from mecanimovilapp.apps.ordenes.serializers_cotizacion_canal import CotizacionCanalSerializer
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    economia_repuesto,
)
from mecanimovilapp.apps.ordenes.services.caja_taller import (
    CajaError,
    fecha_local_de,
    identidades_anclas,
    intentar_contabilizar_pago_mp,
    monto_exigible,
    registrar_manual,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import _repuestos_publicos
from mecanimovilapp.apps.ordenes.services.pago_oferta_cliente import (
    aplicar_confirmacion_pago_servicio,
)
from mecanimovilapp.apps.pagos.models import Pago
from mecanimovilapp.apps.usuarios.models import Cliente, MiembroTaller, Taller
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()
ZONA = ZoneInfo('America/Santiago')


class CajaTallerAPITest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='caja_dueno', password='x')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Caja',
            telefono='900000010',
            estado_verificacion='aprobado',
        )
        self.mecanico_user = User.objects.create_user(username='caja_mec', password='x')
        self.mecanico = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=self.mecanico_user,
            rol='mecanico',
            nombre='Mecánico Caja',
            modalidad_tecnico='ambas',
            activo=True,
        )
        self.otro = User.objects.create_user(username='caja_otro', password='x')
        self.taller_otro = Taller.objects.create(
            usuario=self.otro,
            nombre='Otro Taller',
            telefono='900000011',
            estado_verificacion='aprobado',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            cliente_nombre='Cliente Caja',
            servicio_nombre='Servicio',
            mano_obra_clp=100,
            costo_repuestos_clp=0,
            total_clp=100,
            token='tok-caja-100',
        )
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.cot,
            miembro_taller=self.mecanico,
            fecha_servicio=date(2026, 3, 2),
            hora_servicio=time(10, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=self.cita,
            cliente_nombre='Cliente Caja',
            servicio_nombre='Servicio',
            precio_referencia=Decimal('100'),
        )

    def _post(self, client, **kwargs):
        cuerpo = {
            'ancla_tipo': 'cita',
            'ancla_id': str(self.cita.id),
            'tipo': 'entrada',
            'componente': 'total',
            'monto_clp': 30,
            'fecha_efectiva': '2026-03-02',
        }
        cuerpo.update(kwargs)
        key = cuerpo.pop('idempotency_key', 'abono-30')
        return client.post(
            '/api/ordenes/caja/cobros/',
            cuerpo,
            format='json',
            HTTP_IDEMPOTENCY_KEY=key,
        )

    def test_abono_y_reembolso_en_dias_distintos(self):
        alta = self._post(self.client)
        self.assertEqual(alta.status_code, 201, alta.data)
        reverso = self._post(
            self.client,
            tipo='reembolso',
            monto_clp=10,
            fecha_efectiva='2026-03-03',
            movimiento_origen_id=alta.data['id'],
            idempotency_key='reembolso-10',
        )
        self.assertEqual(reverso.status_code, 201, reverso.data)
        self.assertEqual(CobroTaller.objects.count(), 2)

        dia = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-02', 'hasta': '2026-03-02',
        })
        self.assertEqual(dia.status_code, 200)
        self.assertEqual(dia.data['resumen']['cobros_brutos_clp'], 30)
        self.assertEqual(dia.data['resumen']['neto_clp'], 30)
        self.assertNotIn(100, (
            dia.data['resumen']['cobros_brutos_clp'],
            dia.data['resumen']['neto_clp'],
        ))

        siguiente = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-03', 'hasta': '2026-03-03',
        })
        self.assertEqual(siguiente.data['resumen']['cobros_brutos_clp'], 0)
        self.assertEqual(siguiente.data['resumen']['reembolsos_clp'], 10)
        self.assertEqual(siguiente.data['resumen']['neto_clp'], -10)

        ambos = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-02', 'hasta': '2026-03-03', 'granularidad': 'dia',
        })
        resumen = ambos.data['resumen']
        self.assertEqual(resumen['cobros_brutos_clp'], 30)
        self.assertEqual(resumen['reembolsos_clp'], 10)
        self.assertEqual(resumen['neto_clp'], 20)
        self.assertEqual(
            sum(b['neto_clp'] for b in ambos.data['serie']),
            resumen['neto_clp'],
        )
        self.assertEqual(
            sum(
                m['monto_clp'] if m['tipo'] == 'entrada' else -m['monto_clp']
                for m in ambos.data['movimientos']['results']
                if m['estado'] == 'confirmado' and m['contabiliza_clp']
            ),
            resumen['neto_clp'],
        )
        caso = ambos.data['casos']['results'][0]
        self.assertEqual(caso['monto_exigible_clp'], 100)
        self.assertEqual(caso['neto_acumulado_clp'], 20)
        self.assertEqual(caso['saldo_clp'], 80)
        self.assertEqual(caso['estado_pago'], 'parcial')

    def test_reintento_igual_y_cuerpo_distinto(self):
        primero = self._post(self.client, idempotency_key='misma')
        segundo = self._post(self.client, idempotency_key='misma')
        self.assertEqual(segundo.status_code, 200)
        self.assertEqual(primero.data['id'], segundo.data['id'])
        self.assertEqual(CobroTaller.objects.count(), 1)
        conflicto = self._post(self.client, idempotency_key='misma', monto_clp=31)
        self.assertEqual(conflicto.status_code, 409)
        self.assertEqual(conflicto.data['code'], 'idempotencia_conflicto')
        self.assertEqual(CobroTaller.objects.get().monto_clp, 30)

    def test_reverso_no_borra_ni_supera(self):
        alta = self._post(self.client)
        enorme = self._post(
            self.client,
            tipo='reembolso',
            monto_clp=31,
            fecha_efectiva='2026-03-04',
            movimiento_origen_id=alta.data['id'],
            idempotency_key='reembolso-grande',
        )
        self.assertEqual(enorme.status_code, 409)
        self.assertEqual(enorme.data['code'], 'reverso_excede_original')
        self.assertEqual(CobroTaller.objects.count(), 1)

    def test_periodo_367_dias_y_monto_con_centavos(self):
        largo = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-01-01', 'hasta': '2027-01-02',
        })
        self.assertEqual(largo.status_code, 400)
        self.assertEqual(largo.data['code'], 'periodo_excede_366')
        centavos = self._post(self.client, monto_clp='30.50', idempotency_key='centavos')
        self.assertEqual(centavos.status_code, 400)
        self.assertEqual(centavos.data['code'], 'monto_no_entero')

    def test_aceptar_o_completar_no_inserta(self):
        self.cita.estado = 'cerrada'
        self.cita.cerrada_en = timezone.now()
        self.cita.save()
        self.cot.estado = 'aceptada'
        self.cot.save()
        self.assertEqual(CobroTaller.objects.count(), 0)

    def test_saldo_desconocido_no_es_cero(self):
        self.cot.estado = 'enviada'
        self.cot.save()
        alta = self._post(self.client, idempotency_key='sin-exigible')
        self.assertEqual(alta.status_code, 201, alta.data)
        data = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-02', 'hasta': '2026-03-02',
        }).data
        caso = data['casos']['results'][0]
        self.assertFalse(caso['exigible_conocido'])
        self.assertIsNone(caso['monto_exigible_clp'])
        self.assertIsNone(caso['saldo_clp'])
        self.assertFalse(caso['saldo_conocido'])

    def test_sobrepago_exige_confirmacion(self):
        self.assertEqual(self._post(self.client, monto_clp=100, idempotency_key='todo').status_code, 201)
        extra = self._post(self.client, monto_clp=1, idempotency_key='extra')
        self.assertEqual(extra.status_code, 409)
        self.assertEqual(extra.data['code'], 'sobrepago')
        forzado = self._post(
            self.client,
            monto_clp=1,
            idempotency_key='extra-ok',
            confirmar_sobrepago=True,
        )
        self.assertEqual(forzado.status_code, 201)

    def test_permiso_mecanico_sin_claves_y_taller_ajeno(self):
        self._post(self.client)
        self.client.post(
            '/api/ordenes/caja/costos/',
            {
                'ancla_tipo': 'cita',
                'ancla_id': str(self.cita.id),
                'componente': 'repuestos',
                'tipo': 'registrado',
                'monto_clp': 40,
            },
            format='json',
        )
        mec = APIClient()
        mec.force_authenticate(user=self.mecanico_user)
        visto = mec.get('/api/ordenes/caja/', {
            'desde': '2026-03-01', 'hasta': '2026-03-31',
        })
        self.assertEqual(visto.status_code, 200)
        texto = str(visto.data)
        self.assertNotIn('costo_registrado_clp', texto)
        self.assertNotIn('margen_real_clp', texto)
        self.assertNotIn('margen_contratado_clp', texto)
        self.assertNotIn('resultado_caja_clp', texto)
        self.assertEqual(visto.data['resumen']['neto_clp'], 30)
        prohibido = mec.post(
            '/api/ordenes/caja/cobros/',
            {
                'ancla_tipo': 'cita',
                'ancla_id': str(self.cita.id),
                'tipo': 'entrada',
                'monto_clp': 1,
                'fecha_efectiva': '2026-03-02',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='mec',
        )
        self.assertEqual(prohibido.status_code, 403)

        ajeno = APIClient()
        ajeno.force_authenticate(user=self.otro)
        lectura = ajeno.get('/api/ordenes/caja/', {
            'desde': '2026-03-01',
            'hasta': '2026-03-31',
            'ancla_tipo': 'cita',
            'ancla_id': str(self.cita.id),
        })
        self.assertEqual(lectura.status_code, 404)
        escritura = self._post(ajeno, idempotency_key='ajeno')
        self.assertEqual(escritura.status_code, 404)

    def test_fecha_imposible_responde_400_y_no_inserta(self):
        antes = CobroTaller.objects.count()
        for fecha in ('2026-02-30', '2026-02-30T15:04:00'):
            respuesta = self._post(
                self.client,
                fecha_efectiva=fecha,
                idempotency_key=f'fecha-imposible-{fecha}',
            )
            self.assertEqual(respuesta.status_code, 400, respuesta.data)
            self.assertEqual(respuesta.data['code'], 'fecha_invalida')
            self.assertLess(respuesta.status_code, 500)
        self.assertEqual(CobroTaller.objects.count(), antes)
        lectura = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-02-30', 'hasta': '2026-02-30',
        })
        self.assertEqual(lectura.status_code, 400)
        self.assertEqual(lectura.data['code'], 'periodo_invalido')

    def test_identidad_legible_sin_inventar_ni_salir_del_taller(self):
        self.cita.numero_publico = 'TC-000007'
        self.cita.save(update_fields=['numero_publico'])
        self.cot.numero_publico = 'TC-000001'
        self.cot.vehiculo_patente = 'NOUSAR'
        self.cot.save(update_fields=['numero_publico', 'vehiculo_patente'])
        detalle = self.cita.detalle
        detalle.cliente_nombre = 'Ana Soto'
        detalle.vehiculo_patente = 'ABCD12'
        detalle.cliente_telefono = '+56911112222'
        detalle.save()
        alta = self._post(self.client)
        self.assertEqual(alta.status_code, 201, alta.data)
        self.assertEqual(alta.data['cliente_nombre'], 'Ana Soto')
        self.assertEqual(alta.data['vehiculo_patente'], 'ABCD12')
        self.assertEqual(alta.data['folio'], 'TC-000007')

        cot_misma = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            cliente_nombre='Desde Cotizacion',
            vehiculo_patente='BBCD12',
            numero_publico='TC-000008',
            servicio_nombre='Sin detalle',
            mano_obra_clp=20,
            total_clp=20,
            token='tok-caja-identidad',
        )
        cita_cot = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=cot_misma,
            fecha_servicio=date(2026, 3, 4),
            hora_servicio=time(11, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        self._post(
            self.client,
            ancla_tipo='cita',
            ancla_id=str(cita_cot.id),
            monto_clp=20,
            fecha_efectiva='2026-03-04',
            idempotency_key='abono-cot',
        )
        cot_ajena = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller_otro,
            creado_por=self.otro,
            estado='aceptada',
            cliente_nombre='Secreto Ajeno',
            vehiculo_patente='ZZZZ99',
            numero_publico='AJ-000009',
            servicio_nombre='Ajena',
            mano_obra_clp=10,
            total_clp=10,
            token='tok-caja-ajena',
        )
        cita_ajena = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=cot_ajena,
            miembro_taller=self.mecanico,
            fecha_servicio=date(2026, 3, 5),
            hora_servicio=time(12, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        self._post(
            self.client,
            ancla_tipo='cita',
            ancla_id=str(cita_ajena.id),
            monto_clp=10,
            fecha_efectiva='2026-03-05',
            idempotency_key='abono-ajena',
        )
        otro_user = User.objects.create_user(username='caja_mec_2', password='x')
        otro_miembro = MiembroTaller.objects.create(
            taller=self.taller,
            usuario=otro_user,
            rol='mecanico',
            nombre='Otro Mecánico',
            modalidad_tecnico='ambas',
            activo=True,
        )
        cita_oculta = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            miembro_taller=otro_miembro,
            fecha_servicio=date(2026, 3, 6),
            hora_servicio=time(13, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita_oculta,
            cliente_nombre='Nombre Oculto',
            vehiculo_patente='OCUL99',
            servicio_nombre='Oculto',
        )
        self._post(
            self.client,
            ancla_tipo='cita',
            ancla_id=str(cita_oculta.id),
            monto_clp=5,
            fecha_efectiva='2026-03-06',
            idempotency_key='abono-oculto',
        )

        data = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-01', 'hasta': '2026-03-31', 'page_size': 50,
        }).data
        por_ancla = {fila['ancla_id']: fila for fila in data['casos']['results']}
        propia = por_ancla[str(self.cita.id)]
        self.assertEqual(propia['cliente_nombre'], 'Ana Soto')
        self.assertEqual(propia['vehiculo_patente'], 'ABCD12')
        self.assertEqual(propia['folio'], 'TC-000007')
        desde_cot = por_ancla[str(cita_cot.id)]
        self.assertEqual(desde_cot['cliente_nombre'], 'Desde Cotizacion')
        self.assertEqual(desde_cot['vehiculo_patente'], 'BBCD12')
        self.assertEqual(desde_cot['folio'], 'TC-000008')
        ajena = por_ancla[str(cita_ajena.id)]
        self.assertIsNone(ajena['cliente_nombre'])
        self.assertIsNone(ajena['vehiculo_patente'])
        self.assertIsNone(ajena['folio'])
        texto = str(data)
        self.assertNotIn('+56911112222', texto)
        self.assertNotIn('Secreto Ajeno', texto)
        self.assertNotIn('AJ-000009', texto)
        self.assertNotIn('ZZZZ99', texto)

        mec = APIClient()
        mec.force_authenticate(user=self.mecanico_user)
        visto = mec.get('/api/ordenes/caja/', {
            'desde': '2026-03-01', 'hasta': '2026-03-31', 'page_size': 50,
        })
        self.assertEqual(visto.status_code, 200)
        ids = {fila['ancla_id'] for fila in visto.data['casos']['results']}
        self.assertIn(str(self.cita.id), ids)
        self.assertIn(str(cita_ajena.id), ids)
        self.assertNotIn(str(cita_oculta.id), ids)
        self.assertNotIn('Nombre Oculto', str(visto.data))
        self.assertNotIn('costo_registrado_clp', str(visto.data))
        self.assertNotIn('+56911112222', str(visto.data))
        anon = APIClient()
        self.assertNotEqual(
            anon.get('/api/ordenes/caja/', {
                'desde': '2026-03-01', 'hasta': '2026-03-31',
            }).status_code,
            200,
        )

    def test_dedup_misma_visita_y_nueva_fecha(self):
        CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            es_cotizacion_adicional=True,
            ejecucion_adicional='misma_visita',
            cita_origen=self.cita,
            cotizacion_original=self.cot,
            mano_obra_clp=40,
            total_clp=40,
            servicio_nombre='Misma visita',
            token='tok-caja-40',
        )
        hija_cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            es_cotizacion_adicional=True,
            ejecucion_adicional='nueva_fecha',
            cita_origen=self.cita,
            cotizacion_original=self.cot,
            mano_obra_clp=70,
            total_clp=70,
            servicio_nombre='Nueva fecha',
            token='tok-caja-70',
        )
        hija = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=hija_cot,
            fecha_servicio=date(2026, 4, 1),
            hora_servicio=time(9, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        self.assertEqual(monto_exigible(self.taller, 'cita', self.cita.id), (140, True))
        self.assertEqual(monto_exigible(self.taller, 'cita', hija.id), (70, True))

    def test_fecha_limite_de_horario_de_verano(self):
        antes = datetime(2024, 9, 7, 23, 30, tzinfo=ZONA)
        despues = datetime(2024, 9, 8, 12, 0, tzinfo=ZONA)
        self.assertEqual(fecha_local_de(antes), date(2024, 9, 7))
        self.assertEqual(fecha_local_de(despues), date(2024, 9, 8))
        self._post(
            self.client,
            fecha_efectiva=antes.isoformat(),
            idempotency_key='dst-antes',
            monto_clp=5,
        )
        self._post(
            self.client,
            fecha_efectiva=despues.isoformat(),
            idempotency_key='dst-despues',
            monto_clp=7,
        )
        solo = self.client.get('/api/ordenes/caja/', {
            'desde': '2024-09-07', 'hasta': '2024-09-07',
        })
        self.assertEqual(solo.data['resumen']['cobros_brutos_clp'], 5)
        self.assertEqual(len(solo.data['movimientos']['results']), 1)

    def test_margen_real_resta_la_caja_no_la_obligacion(self):
        self._post(self.client, monto_clp=30, idempotency_key='margen-abono')
        alta = CobroTaller.objects.get(tipo='entrada')
        self._post(
            self.client,
            tipo='reembolso',
            monto_clp=10,
            fecha_efectiva='2026-03-03',
            movimiento_origen_id=str(alta.id),
            idempotency_key='margen-reembolso',
        )
        costo = self.client.post(
            '/api/ordenes/caja/costos/',
            {
                'ancla_tipo': 'cita',
                'ancla_id': str(self.cita.id),
                'componente': 'servicio',
                'tipo': 'registrado',
                'monto_clp': 40,
            },
            format='json',
        )
        self.assertEqual(costo.status_code, 201, costo.data)
        data = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-01', 'hasta': '2026-03-31',
        }).data
        caso = data['casos']['results'][0]
        self.assertEqual(caso['neto_acumulado_clp'], 20)
        self.assertEqual(caso['margen_real_clp'], -20)
        self.assertEqual(caso['resultado_caja_clp'], -20)
        self.assertEqual(caso['margen_contratado_clp'], 60)
        self.assertNotEqual(caso['margen_real_clp'], caso['margen_contratado_clp'])

    def test_reverso_de_otra_ancla_responde_409(self):
        alta = self._post(self.client, idempotency_key='ancla-a')
        otra_cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            servicio_nombre='Otra',
            mano_obra_clp=100,
            total_clp=100,
            token='tok-caja-otra',
        )
        otra = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=otra_cot,
            fecha_servicio=date(2026, 3, 4),
            hora_servicio=time(11, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        cruce = self._post(
            self.client,
            ancla_id=str(otra.id),
            tipo='reembolso',
            monto_clp=10,
            movimiento_origen_id=alta.data['id'],
            idempotency_key='cruce-ancla',
        )
        self.assertEqual(cruce.status_code, 409)
        self.assertEqual(cruce.data['code'], 'reverso_ancla_distinta')
        self.assertEqual(CobroTaller.objects.filter(tipo='reembolso').count(), 0)

    def test_discrepancia_de_total_no_fija_el_exigible_viejo(self):
        self.cot.mano_obra_clp = 70
        self.cot.total_clp = 100
        self.cot.save(update_fields=['mano_obra_clp', 'total_clp'])
        meta_antes = dict(self.cot.metadata or {})
        visto = CotizacionCanalSerializer(self.cot).data
        self.assertEqual(visto['total_clp'], 70)
        self.assertEqual(visto['total_persistido_clp'], 100)
        self.assertFalse(visto['total_alineado'])
        self.assertIsNone(visto['obligacion_clp'])
        self.assertEqual(visto['obligacion_fuente'], 'discrepancia')
        self.cot.refresh_from_db()
        self.assertEqual(dict(self.cot.metadata or {}), meta_antes)
        self.assertEqual(int(self.cot.total_clp), 100)
        monto, conocido = monto_exigible(self.taller, 'cita', self.cita.id)
        self.assertIsNone(monto)
        self.assertFalse(conocido)
        alta = self._post(self.client, monto_clp=30, idempotency_key='sin-tope-viejo')
        self.assertEqual(alta.status_code, 201, alta.data)
        caso = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-02', 'hasta': '2026-03-02',
        }).data['casos']['results'][0]
        self.assertIsNone(caso['saldo_clp'])
        self.assertEqual(caso['exigible_fuente'], 'discrepancia')

    def test_caja_con_muchos_casos_no_explota_queries(self):
        """La caja debe manejar múltiples casos sin N+1 descontrolado.
        
        Verifica que con varios cobros en diferentes casos:
        1. Query count se mantiene bajo control (crece logarítmicamente, no linealmente)
        2. Todos los casos aparecen correctamente
        3. None permanece None (no inventado)
        4. El neto suma correctamente
        """
        from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonalDetalle
        
        # Set 1: pocos casos (baseline)
        citas_pequeno = []
        for i in range(3):
            cita = CitaAgendaPersonal.objects.create(
                taller=self.taller,
                miembro_taller=self.mecanico,
                fecha_servicio=date(2026, 3, 2),
                hora_servicio=time(10, 0),
                tipo_servicio='taller',
                creado_por=self.user,
            )
            CitaAgendaPersonalDetalle.objects.create(
                cita=cita,
                cliente_nombre=f'Cliente Small {i}',
                vehiculo_patente=f'SML{i}00',
                servicio_nombre='Servicio Test',
            )
            registrar_manual(
                taller=self.taller,
                usuario=self.user,
                ancla_tipo='cita',
                ancla_id=str(cita.id),
                tipo='entrada',
                monto_clp=5000,
                fecha_valor='2026-03-02',
                idempotency_key=f'test-small-{i}',
            )
            citas_pequeno.append(str(cita.id))
        
        with CaptureQueriesContext(connection) as ctx_pequeno:
            resp_pequeno = self.client.get('/api/ordenes/caja/', {
                'desde': '2026-03-01', 'hasta': '2026-03-05', 'granularidad': 'dia',
            })
        
        self.assertEqual(resp_pequeno.status_code, 200)
        queries_pequeno = len(ctx_pequeno.captured_queries)
        casos_pequeno = len(resp_pequeno.data['casos']['results'])
        
        # Set 2: muchos casos (10x más)
        citas_grande = []
        for i in range(30):
            cita = CitaAgendaPersonal.objects.create(
                taller=self.taller,
                miembro_taller=self.mecanico,
                fecha_servicio=date(2026, 3, 2),
                hora_servicio=time(10, 0),
                tipo_servicio='taller',
                creado_por=self.user,
            )
            CitaAgendaPersonalDetalle.objects.create(
                cita=cita,
                cliente_nombre=f'Cliente Big {i}',
                vehiculo_patente=f'BIG{i:02d}0',
                servicio_nombre='Servicio Test',
            )
            registrar_manual(
                taller=self.taller,
                usuario=self.user,
                ancla_tipo='cita',
                ancla_id=str(cita.id),
                tipo='entrada',
                monto_clp=1000,
                fecha_valor='2026-03-02',
                idempotency_key=f'test-big-{i}',
            )
            citas_grande.append(str(cita.id))
        
        with CaptureQueriesContext(connection) as ctx_grande:
            resp_grande = self.client.get('/api/ordenes/caja/', {
                'desde': '2026-03-01', 'hasta': '2026-03-05', 'granularidad': 'dia',
            })
        
        self.assertEqual(resp_grande.status_code, 200)
        queries_grande = len(ctx_grande.captured_queries)
        casos_grande = len(resp_grande.data['casos']['results'])
        
        # Verificar que query count no escala linealmente con casos
        # Con batching: queries deben ser similares (diff < 10) independiente de # casos
        # Sin batching: queries_grande sería ~10x queries_pequeno (N+1 pattern)
        self.assertLess(
            queries_grande - queries_pequeno, 15,
            f'Query explosion: {queries_pequeno} queries para {casos_pequeno} casos, '
            f'pero {queries_grande} queries para {casos_grande} casos. '
            f'Debe crecer logarítmicamente, no linealmente (N+1).'
        )
        
        # Verificar que el neto suma correctamente
        resumen = resp_grande.data['resumen']
        self.assertEqual(resumen['neto_clp'], 45000)  # 3*5000 + 30*1000
        
        # Verificar invariantes en algunos casos
        casos = resp_grande.data['casos']['results']
        casos_sin_exigible = [c for c in casos if c['ancla_id'] in citas_grande[:5]]
        for caso in casos_sin_exigible:
            # Sin cotización: exigible debe ser None
            self.assertIsNone(caso['monto_exigible_clp'])
            self.assertFalse(caso['exigible_conocido'])
            # Pero neto debe estar presente
            self.assertIsNotNone(caso['neto_acumulado_clp'])

    def test_caja_invariantes_sin_inventar_ceros(self):
        """Verifica que la caja no inventa montos $0 cuando el valor es desconocido.
        
        Invariante de producto: None debe permanecer None, nunca convertirse a 0.
        """
        # Crear una cita CON cobro pero sin cotización (exigible desconocido)
        cita_sin_exigible = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            miembro_taller=self.mecanico,
            fecha_servicio=date(2026, 3, 3),
            hora_servicio=time(14, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        
        # Registrar UN cobro para que la cita aparezca en casos
        registrar_manual(
            taller=self.taller,
            usuario=self.user,
            ancla_tipo='cita',
            ancla_id=str(cita_sin_exigible.id),
            tipo='entrada',
            monto_clp=12345,
            fecha_valor='2026-03-03',
            idempotency_key='test-invariantes-cobro',
        )
        
        resp = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-03-01', 'hasta': '2026-03-05', 'granularidad': 'dia',
        })
        
        self.assertEqual(resp.status_code, 200)
        casos = resp.data['casos']['results']
        
        # Buscar el caso de la cita sin cotización
        caso_sin_exigible = next(
            (c for c in casos if c['ancla_id'] == str(cita_sin_exigible.id)),
            None
        )
        
        # Debe aparecer porque tiene cobros en el periodo
        self.assertIsNotNone(caso_sin_exigible, 'Caso con cobro debe aparecer en la lista')
        
        # Exigible desconocido debe ser None, no 0
        self.assertIsNone(
            caso_sin_exigible['monto_exigible_clp'],
            'Exigible desconocido debe ser None (no inventar $0)'
        )
        self.assertFalse(caso_sin_exigible['exigible_conocido'])
        
        # Neto debe ser el cobro registrado, no None
        self.assertEqual(
            caso_sin_exigible['neto_acumulado_clp'], 12345,
            'Neto debe ser el cobro confirmado'
        )


class LegacyPagoSinLibroTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='legacy_dueno', password='x')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Legacy',
            telefono='900000012',
            estado_verificacion='aprobado',
        )
        cliente_user = User.objects.create_user(username='legacy_cli', password='x')
        self.cliente = Cliente.objects.create(
            usuario=cliente_user,
            nombre='Cliente',
            apellido='Legacy',
            email='legacy_cli@test.com',
        )
        marca = Marca.objects.create(nombre='LegacyMarca')
        modelo = Modelo.objects.create(nombre='LegacyModelo', marca=marca)
        vehiculo = Vehiculo.objects.create(
            cliente=self.cliente, marca=marca, modelo=modelo, year=2020, patente='LEG001',
        )
        self.solicitud_pub = SolicitudServicioPublica.objects.create(
            cliente=self.cliente,
            vehiculo=vehiculo,
            descripcion_problema='Test',
            fecha_preferida=date(2026, 5, 1),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6 -33.4)',
            direccion_servicio_texto='Test',
            estado='publicada',
        )
        self.oferta = OfertaProveedor.objects.create(
            solicitud=self.solicitud_pub,
            proveedor=self.user,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal('100'),
            tiempo_estimado_total=timedelta(hours=2),
            descripcion_oferta='Oferta de prueba',
            fecha_disponible=date(2026, 5, 3),
            hora_disponible=time(10, 0),
            estado='pagada',
            estado_pago_servicio='pagado',
            estado_pago_repuestos='no_aplica',
        )
        self.orden = SolicitudServicio.objects.create(
            cliente=self.cliente,
            vehiculo=vehiculo,
            taller=self.taller,
            tipo_servicio='taller',
            fecha_servicio=date(2026, 5, 2),
            hora_servicio=time(11, 0),
            metodo_pago='mercadopago',
            total=Decimal('100'),
            estado='confirmado',
            oferta_proveedor=self.oferta,
        )

    def test_flag_pagado_no_suma_ni_se_vuelve_deuda(self):
        aplicar_confirmacion_pago_servicio(self.oferta, self.solicitud_pub)
        self.oferta.save()
        self.assertEqual(CobroTaller.objects.count(), 0)
        data = SolicitudServicioProveedorSerializer(self.orden).data
        self.assertEqual(data['estado_pago_servicio'], 'pagado')
        self.assertEqual(data['estado_cobro_ui'], 'pagado_segun_oferta')
        self.assertFalse(data['pago_contabilizable'])
        self.assertIsNone(data['pago_provenance']['saldo_clp'])
        self.assertIsNone(data['pago_provenance']['neto_acumulado_clp'])
        self.assertNotEqual(data['estado_cobro_ui'], 'por_cobrar')

    def test_reintento_mp_no_duplica_y_conserva_la_entrada(self):
        from mecanimovilapp.apps.ordenes.services.caja_taller import contabilizar_desde_pago

        pago = Pago.objects.create(
            usuario=self.user,
            transaction_amount=Decimal('100'),
            currency_id='CLP',
            description='Oferta',
            status='approved',
            payer_email='c@test.com',
            external_reference=f'oferta_{self.oferta.id}_total',
            payment_id_mp=777001,
            date_approved_mp=timezone.now(),
        )
        contabilizar_desde_pago(pago, self.oferta, 'total')
        contabilizar_desde_pago(pago, self.oferta, 'total')
        self.assertEqual(CobroTaller.objects.filter(tipo='entrada').count(), 1)
        pago.status = 'refunded'
        pago.metadata = {'transaction_amount_refunded': '10'}
        pago.date_last_updated_mp = timezone.now() + timedelta(days=1)
        pago.save()
        contabilizar_desde_pago(pago, self.oferta, 'total')
        self.assertEqual(CobroTaller.objects.filter(tipo='entrada').count(), 1)
        reverso = CobroTaller.objects.get(tipo='reembolso')
        self.assertEqual(reverso.monto_clp, 10)
        self.assertEqual(reverso.movimiento_origen.tipo, 'entrada')
        self.assertEqual(reverso.movimiento_origen.monto_clp, 100)

    def test_reembolso_mp_domina_el_flag(self):
        Pago.objects.create(
            usuario=self.user,
            transaction_amount=Decimal('100'),
            description='Oferta',
            status='refunded',
            payer_email='c@test.com',
            external_reference=f'oferta_{self.oferta.id}_total',
            payment_id_mp=424242,
        )
        data = SolicitudServicioProveedorSerializer(self.orden).data
        self.assertEqual(data['estado_pago_servicio'], 'pagado')
        self.assertEqual(data['estado_cobro_ui'], 'reembolsado')
        self.assertEqual(data['pago_provenance']['dominio'], 'mercadopago_reverso')
        self.oferta.refresh_from_db()
        self.assertEqual(self.oferta.estado_pago_servicio, 'pagado')

    def test_fila_pendiente_no_convierte_el_flag_en_deuda(self):
        CobroTaller.objects.create(
            taller=self.taller,
            ancla_tipo='oferta',
            ancla_id=str(self.oferta.id),
            origen='manual',
            ref_externa='manual:pendiente-legacy',
            tipo='entrada',
            estado='pendiente',
            monto_clp=100,
            contabiliza_clp=True,
            fecha_efectiva=timezone.now(),
            fecha_local=date(2026, 5, 2),
        )
        data = SolicitudServicioProveedorSerializer(self.orden).data
        self.assertEqual(data['estado_cobro_ui'], 'pagado_segun_oferta')
        self.assertIsNone(data['pago_provenance']['saldo_clp'])
        self.assertIsNone(data['pago_provenance']['neto_acumulado_clp'])
        self.assertEqual(data['pago_provenance']['aviso_libro'], 'sin_efecto_contable')
        self.assertEqual(data['pago_provenance']['pendientes_no_sumados_clp'], 100)
        self.assertNotEqual(data['estado_cobro_ui'], 'por_cobrar')

    def test_moneda_distinta_no_inventa_deuda(self):
        CobroTaller.objects.create(
            taller=self.taller,
            ancla_tipo='oferta',
            ancla_id=str(self.oferta.id),
            origen='mercadopago',
            ref_externa='mp:9:moneda',
            tipo='entrada',
            estado='confirmado',
            monto_clp=0,
            moneda='USD',
            contabiliza_clp=False,
            monto_origen=Decimal('10.00'),
            fecha_efectiva=timezone.now(),
            fecha_local=date(2026, 5, 2),
        )
        data = SolicitudServicioProveedorSerializer(self.orden).data
        self.assertEqual(data['estado_cobro_ui'], 'pagado_segun_oferta')
        self.assertIsNone(data['pago_provenance']['saldo_clp'])
        self.assertEqual(data['pago_provenance']['aviso_libro'], 'sin_efecto_contable')

    def test_reembolso_acumulado_mp_es_incremental_y_idempotente(self):
        from mecanimovilapp.apps.ordenes.services.caja_taller import contabilizar_desde_pago

        pago = self._pago_mp(880001, 'approved')
        contabilizar_desde_pago(pago, self.oferta, 'total')
        for acumulado in ('10', '30', '100', '30'):
            pago.status = 'refunded'
            pago.metadata = {'transaction_amount_refunded': acumulado}
            pago.date_last_updated_mp = timezone.now()
            pago.save()
            contabilizar_desde_pago(pago, self.oferta, 'total')
        reversos = list(CobroTaller.objects.filter(tipo='reembolso').order_by('creado_en'))
        self.assertEqual(sum(r.monto_clp for r in reversos), 100)
        self.assertLessEqual(sum(r.monto_clp for r in reversos), 100)
        self.assertNotEqual(sum(r.monto_clp for r in reversos), 140)

    def test_reembolso_acumulado_fuera_de_orden_no_resta(self):
        from mecanimovilapp.apps.ordenes.services.caja_taller import contabilizar_desde_pago

        pago = self._pago_mp(880002, 'approved')
        contabilizar_desde_pago(pago, self.oferta, 'total')
        for acumulado in ('30', '10', '30'):
            pago.metadata = {'transaction_amount_refunded': acumulado}
            pago.status = 'refunded'
            pago.save()
            contabilizar_desde_pago(pago, self.oferta, 'total')
        self.assertEqual(
            sum(CobroTaller.objects.filter(tipo='reembolso').values_list('monto_clp', flat=True)),
            30,
        )
        self.assertEqual(CobroTaller.objects.filter(tipo='reembolso').count(), 1)

    def test_contracargo_despues_del_reembolso_parcial_cierra_sin_duplicar(self):
        from mecanimovilapp.apps.ordenes.services.caja_taller import contabilizar_desde_pago

        pago = self._pago_mp(880010, 'approved')
        contabilizar_desde_pago(pago, self.oferta, 'total')
        pago.status = 'refunded'
        pago.metadata = {'transaction_amount_refunded': '30'}
        pago.save()
        contabilizar_desde_pago(pago, self.oferta, 'total')
        pago.status = 'charged_back'
        pago.save()
        intentar_contabilizar_pago_mp(
            pago,
            self.oferta,
            'total',
            {'status': 'charged_back', 'transaction_amount_refunded': '30'},
        )
        intentar_contabilizar_pago_mp(
            Pago.objects.get(pk=pago.pk),
            self.oferta,
            'total',
            {'status': 'charged_back', 'transaction_amount_refunded': '30'},
        )
        self._assert_reversa_cerrada(30, 70)
        for acumulado in ('10', '30'):
            pago.status = 'refunded'
            pago.save(update_fields=['status'])
            intentar_contabilizar_pago_mp(
                Pago.objects.get(pk=pago.pk),
                self.oferta,
                'total',
                {'status': 'refunded', 'transaction_amount_refunded': acumulado},
            )
        pago.refresh_from_db()
        self.assertTrue(pago.metadata.get('contracargo_observado'))
        self.assertEqual(pago.metadata.get('transaction_amount_refunded'), '30')
        self._assert_reversa_cerrada(30, 70)

    def test_fallo_de_contracargo_conserva_la_evidencia_y_cierra_al_reintentar(self):
        from mecanimovilapp.apps.ordenes.services import caja_taller as caja_mod
        from mecanimovilapp.apps.ordenes.services.caja_taller import contabilizar_desde_pago

        pago = self._pago_mp(880011, 'approved')
        contabilizar_desde_pago(pago, self.oferta, 'total')
        pago.status = 'refunded'
        pago.metadata = {'transaction_amount_refunded': '30'}
        pago.save()
        contabilizar_desde_pago(pago, self.oferta, 'total')
        pago.status = 'charged_back'
        pago.save()
        real = caja_mod.registrar_movimiento

        def _cae(**kwargs):
            if kwargs.get('tipo') == 'contracargo':
                raise RuntimeError('caja caida')
            return real(**kwargs)

        with patch.object(caja_mod, 'registrar_movimiento', side_effect=_cae):
            intentar_contabilizar_pago_mp(
                pago,
                self.oferta,
                'total',
                {'status': 'charged_back', 'transaction_amount_refunded': '30'},
            )
        pago.refresh_from_db()
        self.assertTrue(pago.metadata.get('contracargo_observado'))
        self.assertEqual(pago.metadata.get('transaction_amount_refunded'), '30')
        self.assertEqual(self._suma_reversos(), 30)
        fresco = Pago.objects.get(pk=pago.pk)
        fresco.status = 'refunded'
        fresco.save(update_fields=['status'])
        intentar_contabilizar_pago_mp(
            fresco,
            self.oferta,
            'total',
            {'status': 'refunded', 'transaction_amount_refunded': '10'},
        )
        guardado = Pago.objects.get(pk=pago.pk)
        self.assertTrue(guardado.metadata.get('contracargo_observado'))
        self.assertEqual(guardado.metadata.get('transaction_amount_refunded'), '30')
        contabilizar_desde_pago(guardado, self.oferta, 'total')
        self._assert_reversa_cerrada(30, 70)

    def _suma_reversos(self):
        return sum(
            CobroTaller.objects.filter(tipo__in=['reembolso', 'contracargo'])
            .values_list('monto_clp', flat=True)
        )

    def _assert_reversa_cerrada(self, reembolso, contracargo):
        self.assertEqual(
            sum(CobroTaller.objects.filter(tipo='reembolso').values_list('monto_clp', flat=True)),
            reembolso,
        )
        self.assertEqual(
            sum(CobroTaller.objects.filter(tipo='contracargo').values_list('monto_clp', flat=True)),
            contracargo,
        )
        self.assertEqual(self._suma_reversos(), 100)
        self.assertEqual(CobroTaller.objects.filter(tipo='contracargo').count(), 1)
        self.assertEqual(CobroTaller.objects.filter(tipo='entrada').get().monto_clp, 100)

    def test_webhook_atrasado_no_saca_la_entrada_de_la_caja(self):
        from mecanimovilapp.apps.ordenes.services.caja_taller import contabilizar_desde_pago

        pago = self._pago_mp(880003, 'approved')
        contabilizar_desde_pago(pago, self.oferta, 'total')
        pago.status = 'in_mediation'
        pago.save()
        contabilizar_desde_pago(pago, self.oferta, 'total')
        entrada = CobroTaller.objects.get(tipo='entrada')
        self.assertEqual(entrada.estado, 'confirmado')
        self.assertTrue(entrada.metadata.get('eventos_ignorados'))
        self.assertEqual(entrada.monto_clp, 100)

    def test_fallo_de_reembolso_parcial_se_reconstruye_al_reintentar(self):
        from mecanimovilapp.apps.ordenes.services.caja_taller import contabilizar_desde_pago

        pago = self._pago_mp(880004, 'approved')
        contabilizar_desde_pago(pago, self.oferta, 'total')

        from mecanimovilapp.apps.ordenes.services import caja_taller as caja_mod

        real = caja_mod.registrar_movimiento

        def _cae(**kwargs):
            if kwargs.get('tipo') != 'entrada':
                raise RuntimeError('caja caida')
            return real(**kwargs)

        with patch.object(caja_mod, 'registrar_movimiento', side_effect=_cae):
            intentar_contabilizar_pago_mp(
                pago, self.oferta, 'total', {'transaction_amount_refunded': '10'},
            )
        pago.refresh_from_db()
        self.assertEqual(pago.metadata.get('transaction_amount_refunded'), '10')
        self.assertEqual(CobroTaller.objects.filter(tipo='reembolso').count(), 0)
        guardado = Pago.objects.get(pk=pago.pk)
        contabilizar_desde_pago(guardado, self.oferta, 'total')
        contabilizar_desde_pago(Pago.objects.get(pk=pago.pk), self.oferta, 'total')
        reversos = CobroTaller.objects.filter(tipo='reembolso')
        self.assertEqual(reversos.count(), 1)
        self.assertEqual(reversos.get().monto_clp, 10)

    def test_solicitud_y_oferta_comparten_libro(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        primero = client.post(
            '/api/ordenes/caja/cobros/',
            {
                'ancla_tipo': 'solicitud',
                'ancla_id': str(self.orden.id),
                'tipo': 'entrada',
                'componente': 'total',
                'monto_clp': 60,
                'fecha_efectiva': '2026-05-02',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='sol-60',
        )
        self.assertEqual(primero.status_code, 201, primero.data)
        self.assertEqual(primero.data['ancla_tipo'], 'oferta')
        self.assertEqual(primero.data['ancla_id'], str(self.oferta.id))
        segundo = client.post(
            '/api/ordenes/caja/cobros/',
            {
                'ancla_tipo': 'oferta',
                'ancla_id': str(self.oferta.id),
                'tipo': 'entrada',
                'componente': 'total',
                'monto_clp': 50,
                'fecha_efectiva': '2026-05-02',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='ofe-50',
        )
        self.assertEqual(segundo.status_code, 409)
        self.assertEqual(segundo.data['code'], 'sobrepago')
        data = SolicitudServicioProveedorSerializer(self.orden).data
        self.assertEqual(data['pago_provenance']['neto_acumulado_clp'], 60)
        self.assertEqual(data['pago_provenance']['saldo_clp'], 40)

    def _pago_mp(self, payment_id, status):
        return Pago.objects.create(
            usuario=self.user,
            transaction_amount=Decimal('100'),
            currency_id='CLP',
            description='Oferta',
            status=status,
            payer_email='c@test.com',
            external_reference=f'oferta_{self.oferta.id}_total',
            payment_id_mp=payment_id,
            date_approved_mp=timezone.now(),
        )


class ContabilizarPagoNoBloqueaTest(TestCase):
    def test_error_de_caja_no_se_propaga(self):
        class Roto:
            id = 'pago'
            payment_id_mp = 9
            status = 'approved'

            @property
            def metadata(self):
                raise RuntimeError('caja rota')

            @metadata.setter
            def metadata(self, value):
                raise RuntimeError('caja rota')

        intentar_contabilizar_pago_mp(Roto(), object(), 'total', {'transaction_amount_refunded': 1})
        self.assertEqual(CobroTaller.objects.count(), 0)


class TotalesMismaRespuestaTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='totales_dueno', password='x')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Totales',
            telefono='900000013',
            estado_verificacion='aprobado',
        )

    def test_get_no_escribe_y_total_sale_de_las_lineas(self):
        cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            servicio_nombre='Mantención',
            mano_obra_clp=999,
            costo_repuestos_clp=1,
            total_clp=248304,
            repuestos=[{
                'id': 'filtro',
                'nombre': 'Filtro',
                'cantidad': 2,
                'precio_unitario_clp': 8000,
            }],
            metadata={'servicios_lineas': [{'id': 'mo-1', 'nombre': 'Faena', 'monto_clp': 10000}]},
            token='tok-totales',
        )
        data = CotizacionCanalSerializer(cot).data
        self.assertEqual(data['total_clp'], 2 * 8000 + 10000)
        self.assertEqual(data['total_persistido_clp'], 248304)
        self.assertEqual(data['precios_iva'], 'incluido')
        self.assertFalse(data['total_alineado'])
        cot.refresh_from_db()
        self.assertEqual(int(cot.total_clp), 248304)
        self.assertEqual(int(cot.mano_obra_clp), 999)

    def test_linea_sin_precio_no_suma_enganoso(self):
        cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            servicio_nombre='Parcial',
            total_clp=5000,
            repuestos=[
                {'id': 'a', 'nombre': 'Con precio', 'cantidad': 1, 'precio_unitario_clp': 5000},
                {'id': 'b', 'nombre': 'Sin precio', 'cantidad': 1, 'precio_unitario_clp': None},
            ],
            token='tok-parcial',
        )
        data = CotizacionCanalSerializer(cot).data
        self.assertIsNone(data['total_clp'])
        self.assertFalse(data['totales_completos'])
        self.assertIn('Sin precio', data['totales_faltantes'])
        self.assertEqual(data['total_conocido_parcial_clp'], 5000)

    def test_precio_cobrado_no_es_costo_real_y_publico_no_lo_ve(self):
        fila = economia_repuesto({
            'precio_unitario_clp': 8000,
            'cantidad': 1,
        })
        self.assertIsNone(fila['costo_registrado_clp'])
        self.assertIsNone(fila['margen_real_clp'])
        self.assertIsNone(fila['costo_unitario_clp'])
        pubs = _repuestos_publicos([{
            'nombre': 'Filtro',
            'precio_unitario_clp': 8000,
            'costo_registrado_clp': 5000,
            'margen_real_clp': 3000,
            'margen_estimado_clp': 1000,
            'costo_estimado_clp': 7000,
        }])
        self.assertNotIn('costo_registrado_clp', pubs[0])
        self.assertNotIn('margen_real_clp', pubs[0])
        self.assertNotIn('margen_estimado_clp', pubs[0])


class IdentidadCajaLoteTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ident_dueno', password='x')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Ident',
            telefono='900000014',
            estado_verificacion='aprobado',
        )
        self.otro = User.objects.create_user(username='ident_otro', password='x')
        self.taller_otro = Taller.objects.create(
            usuario=self.otro,
            nombre='Taller Ident Otro',
            telefono='900000015',
            estado_verificacion='aprobado',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _cita(self, n, *, folio=''):
        cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            cliente_nombre=f'Cliente {n}',
            servicio_nombre='Servicio',
            mano_obra_clp=10,
            total_clp=10,
            token=f'tok-ident-{n}',
        )
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=cot,
            numero_publico=folio,
            fecha_servicio=date(2026, 7, 1),
            hora_servicio=time(10, n % 50),
            tipo_servicio='taller',
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre=f'Cliente {n}',
            vehiculo_patente=f'ID{n:04d}',
            servicio_nombre='Servicio',
        )
        registrar_manual(
            taller=self.taller,
            usuario=self.user,
            ancla_tipo='cita',
            ancla_id=str(cita.id),
            tipo='entrada',
            monto_clp=10,
            fecha_valor='2026-07-01',
            idempotency_key=f'ident-{n}',
        )
        return cita

    def _solicitud_publica(self, cliente, vehiculo, token):
        return SolicitudServicioPublica.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            descripcion_problema=token,
            fecha_preferida=date(2026, 7, 2),
            fecha_expiracion=timezone.now() + timedelta(days=7),
            ubicacion_servicio='POINT(-70.6 -33.4)',
            direccion_servicio_texto='Test',
            estado='publicada',
        )

    def _oferta(self, solicitud, proveedor, precio='40'):
        return OfertaProveedor.objects.create(
            solicitud=solicitud,
            proveedor=proveedor,
            tipo_proveedor='taller',
            precio_total_ofrecido=Decimal(precio),
            tiempo_estimado_total=timedelta(hours=1),
            descripcion_oferta='Oferta',
            fecha_disponible=date(2026, 7, 3),
            hora_disponible=time(10, 0),
            estado='aceptada',
        )

    def test_lote_de_identidad_no_crece_y_no_escribe_folio(self):
        citas = [self._cita(n, folio=f'TC-{n:06d}') for n in range(8)]
        pares = [('cita', str(cita.id)) for cita in citas]
        with self.assertNumQueries(1):
            una = identidades_anclas(self.taller, pares[:1])
        with self.assertNumQueries(1):
            todas = identidades_anclas(self.taller, pares)
        self.assertEqual(una[('cita', str(citas[0].id))]['folio'], 'TC-000000')
        self.assertEqual(len(todas), 8)

        cliente_user = User.objects.create_user(username='ident_cli', password='x')
        cliente = Cliente.objects.create(
            usuario=cliente_user,
            nombre='Nora',
            apellido='Campos',
            email='ident_cli@test.com',
            telefono='+56900001111',
        )
        marca = Marca.objects.create(nombre='IdentMarca')
        modelo = Modelo.objects.create(nombre='IdentModelo', marca=marca)
        vehiculo = Vehiculo.objects.create(
            cliente=cliente, marca=marca, modelo=modelo, year=2019, patente='IDNT01',
        )
        publica = self._solicitud_publica(cliente, vehiculo, 'propia')
        oferta = self._oferta(publica, self.user)
        orden = SolicitudServicio.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            taller=self.taller,
            tipo_servicio='taller',
            fecha_servicio=date(2026, 7, 4),
            hora_servicio=time(9, 0),
            metodo_pago='efectivo',
            total=Decimal('40'),
            estado='confirmado',
            oferta_proveedor=oferta,
        )
        SolicitudServicio.objects.filter(pk=orden.pk).update(numero_publico='')
        orden.refresh_from_db()
        self.assertEqual(orden.numero_publico, '')
        publica_vacia = self._solicitud_publica(cliente, vehiculo, 'sin-orden')
        oferta_sin_orden = self._oferta(publica_vacia, self.user, '15')
        ajeno_user = User.objects.create_user(username='ident_cli_2', password='x')
        ajeno = Cliente.objects.create(
            usuario=ajeno_user,
            nombre='Secreto',
            apellido='Ajeno',
            email='ident_ajeno@test.com',
        )
        vehiculo_ajeno = Vehiculo.objects.create(
            cliente=ajeno, marca=marca, modelo=modelo, year=2018, patente='AJEN01',
        )
        publica_ajena = self._solicitud_publica(ajeno, vehiculo_ajeno, 'ajena')
        oferta_ajena = self._oferta(publica_ajena, self.otro, '15')
        mixtos = pares + [
            ('solicitud', str(orden.id)),
            ('oferta', str(oferta.id)),
            ('oferta', str(oferta_sin_orden.id)),
            ('oferta', str(oferta_ajena.id)),
        ]
        with self.assertNumQueries(4):
            encontradas = identidades_anclas(self.taller, mixtos)
        with self.assertNumQueries(4):
            identidades_anclas(self.taller, mixtos * 3)
        with self.assertNumQueries(0):
            self.assertEqual(identidades_anclas(self.taller, []), {})
        self.assertEqual(
            encontradas[('oferta', str(oferta.id))],
            {
                'cliente_nombre': 'Nora Campos',
                'vehiculo_patente': 'IDNT01',
                'folio': None,
            },
        )
        self.assertEqual(
            encontradas[('oferta', str(oferta_sin_orden.id))]['cliente_nombre'],
            'Nora Campos',
        )
        self.assertIsNone(encontradas[('oferta', str(oferta_sin_orden.id))]['folio'])
        self.assertNotIn(('oferta', str(oferta_ajena.id)), encontradas)
        self.assertNotIn('Secreto Ajeno', str(encontradas))
        self.assertNotIn('+56900001111', str(encontradas))
        orden.refresh_from_db()
        self.assertEqual(orden.numero_publico, '')

        registrar_manual(
            taller=self.taller,
            usuario=self.user,
            ancla_tipo='oferta',
            ancla_id=str(oferta.id),
            tipo='entrada',
            monto_clp=15,
            fecha_valor='2026-07-04',
            idempotency_key='ident-oferta',
            confirmar_sobrepago=True,
        )
        visto = self.client.get('/api/ordenes/caja/', {
            'desde': '2026-07-04', 'hasta': '2026-07-04',
        }).data
        caso = visto['casos']['results'][0]
        self.assertEqual(caso['ancla_tipo'], 'oferta')
        self.assertEqual(caso['cliente_nombre'], 'Nora Campos')
        self.assertEqual(caso['vehiculo_patente'], 'IDNT01')
        self.assertIsNone(caso['folio'])
        self.assertIsNone(visto['movimientos']['results'][0]['folio'])
        self.assertNotIn('+56900001111', str(visto))
        orden.refresh_from_db()
        self.assertEqual(orden.numero_publico, '')

        with CaptureQueriesContext(connection) as ctx:
            pagina = self.client.get('/api/ordenes/caja/', {
                'desde': '2026-07-01', 'hasta': '2026-07-01',
                'page': 1, 'page_size': 2, 'casos_page': 1,
            })
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(len(pagina.data['casos']['results']), 2)
        identidad = [
            q['sql'] for q in ctx.captured_queries
            if 'citaagendapersonaldetalle' in q['sql'].lower() and ' in (' in q['sql'].lower()
        ]
        self.assertEqual(len(identidad), 1)

    def test_pagina_siguiente_no_repite_la_identidad_de_toda_la_lista(self):
        citas = [self._cita(n + 20, folio='') for n in range(4)]
        with CaptureQueriesContext(connection) as ctx:
            pagina = self.client.get('/api/ordenes/caja/', {
                'desde': '2026-07-01', 'hasta': '2026-07-01',
                'page': 2, 'page_size': 2, 'casos_page': 2,
            })
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual({fila['folio'] for fila in pagina.data['casos']['results']}, {None})
        self.assertEqual(
            {fila['cliente_nombre'] for fila in pagina.data['movimientos']['results']},
            {fila['cliente_nombre'] for fila in pagina.data['casos']['results']},
        )
        identidad = [
            q['sql'] for q in ctx.captured_queries
            if 'citaagendapersonaldetalle' in q['sql'].lower() and ' in (' in q['sql'].lower()
        ]
        self.assertEqual(len(identidad), 1)
        self.assertEqual(len(citas), 4)


class CajaMigracionTest(TransactionTestCase):
    def test_migracion_baja_y_sube(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('ordenes', '0049_vista_taller_oculta')])
        executor.loader.build_graph()
        tablas = set(connection.introspection.table_names())
        self.assertNotIn('ordenes_cobrotaller', tablas)
        executor = MigrationExecutor(connection)
        executor.migrate([('ordenes', '0051_ancla_caja')])
        executor.loader.build_graph()
        tablas = set(connection.introspection.table_names())
        self.assertIn('ordenes_cobrotaller', tablas)
        self.assertIn('ordenes_costotaller', tablas)
        self.assertIn('ordenes_anclacaja', tablas)
        executor = MigrationExecutor(connection)
        executor.migrate([('ordenes', '0050_cobro_taller')])
        executor.loader.build_graph()
        tablas = set(connection.introspection.table_names())
        self.assertNotIn('ordenes_anclacaja', tablas)
        self.assertIn('ordenes_cobrotaller', tablas)
        executor = MigrationExecutor(connection)
        executor.migrate([('ordenes', '0051_ancla_caja')])


def _en_hilo(barrera, salida, fn):
    from django.db import connections

    connections.close_all()
    try:
        barrera.wait(timeout=15)
        salida.append(fn())
    except CajaError as exc:
        salida.append(exc.code)
    except Exception as exc:
        salida.append(f'error:{type(exc).__name__}:{exc}')
    finally:
        connections.close_all()


class CajaConcurrenciaPostgresTest(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('La carrera se prueba en PostgreSQL')
        self.user = User.objects.create_user(username='caja_race', password='x')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Race',
            telefono='900000099',
            estado_verificacion='aprobado',
        )
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='aceptada',
            servicio_nombre='Race',
            mano_obra_clp=100,
            total_clp=100,
            token='tok-race',
        )
        self.cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.cot,
            fecha_servicio=date(2026, 6, 1),
            hora_servicio=time(10, 0),
            tipo_servicio='taller',
            creado_por=self.user,
        )

    def _correr(self, trabajos):
        from django.db import connections

        connections.close_all()
        barrera = threading.Barrier(len(trabajos))
        salida = []
        hilos = [
            threading.Thread(target=_en_hilo, args=(barrera, salida, fn))
            for fn in trabajos
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(20)
            self.assertFalse(hilo.is_alive())
        return salida

    def test_dos_primeros_abonos_no_superan_el_exigible(self):
        self.assertEqual(AnclaCaja.objects.count(), 0)

        def abono(clave):
            mov, _creado = registrar_manual(
                taller=self.taller,
                usuario=self.user,
                ancla_tipo='cita',
                ancla_id=str(self.cita.id),
                tipo='entrada',
                monto_clp=80,
                fecha_valor='2026-06-01',
                idempotency_key=clave,
            )
            return ('ok', mov.monto_clp)

        salida = self._correr([lambda: abono('race-a'), lambda: abono('race-b')])
        self.assertIn('sobrepago', salida)
        self.assertEqual(sum(1 for item in salida if item == 'sobrepago'), 1)
        self.assertEqual(
            sum(m.monto_clp for m in CobroTaller.objects.filter(tipo='entrada')),
            80,
        )
        self.assertEqual(AnclaCaja.objects.count(), 1)

    def test_dos_reembolsos_concurrentes_no_superan_la_entrada(self):
        mov, _creado = registrar_manual(
            taller=self.taller,
            usuario=self.user,
            ancla_tipo='cita',
            ancla_id=str(self.cita.id),
            tipo='entrada',
            monto_clp=100,
            fecha_valor='2026-06-01',
            idempotency_key='race-base',
        )

        def reverso(clave):
            registrar_manual(
                taller=self.taller,
                usuario=self.user,
                ancla_tipo='cita',
                ancla_id=str(self.cita.id),
                tipo='reembolso',
                monto_clp=60,
                fecha_valor='2026-06-02',
                idempotency_key=clave,
                movimiento_origen_id=str(mov.id),
            )
            return 'ok'

        salida = self._correr([lambda: reverso('rev-a'), lambda: reverso('rev-b')])
        self.assertIn('reverso_excede_original', salida)
        self.assertEqual(
            sum(m.monto_clp for m in CobroTaller.objects.filter(tipo='reembolso')),
            60,
        )

    def test_dos_contracargos_concurrentes_no_duplican_el_resto(self):
        from mecanimovilapp.apps.ordenes.services.caja_taller import (
            _aplicar_reembolso_acumulado,
            registrar_movimiento,
        )

        ahora = timezone.now()
        entrada, _creado = registrar_movimiento(
            taller=self.taller,
            ancla_tipo='oferta',
            ancla_id='oferta-race',
            origen='mercadopago',
            ref_externa='mp:race-cb',
            tipo='entrada',
            estado='confirmado',
            monto_clp=100,
            fecha_efectiva=ahora,
            fecha_local=date(2026, 6, 1),
            cuerpo={'payment_id': 'race-cb', 'tipo': 'entrada', 'monto_clp': 100},
        )
        registrar_movimiento(
            taller=self.taller,
            ancla_tipo='oferta',
            ancla_id='oferta-race',
            origen='mercadopago',
            ref_externa='mp-refund:race-cb:acum:30',
            tipo='reembolso',
            estado='confirmado',
            monto_clp=30,
            fecha_efectiva=ahora,
            fecha_local=date(2026, 6, 1),
            movimiento_origen=entrada,
            cuerpo={'payment_id': 'race-cb', 'acumulado_clp': 30, 'incremento_clp': 30},
        )

        def golpe():
            _aplicar_reembolso_acumulado(
                taller=self.taller,
                entrada=entrada,
                payment_id='race-cb',
                objetivo=100,
                tipo_salida='contracargo',
                momento=ahora,
                componente='total',
                pago=None,
                metadata={'status_mp': 'charged_back'},
            )
            return 'ok'

        salida = self._correr([golpe, golpe])
        self.assertEqual(salida, ['ok', 'ok'], salida)
        self.assertEqual(
            sum(CobroTaller.objects.filter(tipo='contracargo').values_list('monto_clp', flat=True)),
            70,
        )
        self.assertEqual(CobroTaller.objects.filter(tipo='contracargo').count(), 1)
        self.assertEqual(
            sum(
                CobroTaller.objects.filter(tipo__in=['reembolso', 'contracargo'])
                .values_list('monto_clp', flat=True)
            ),
            100,
        )


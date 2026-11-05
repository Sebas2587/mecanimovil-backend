"""Caja del taller: abonos, reversos, legacy y totales de la misma respuesta."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import (
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
    fecha_local_de,
    intentar_contabilizar_pago_mp,
    monto_exigible,
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


class CajaMigracionTest(TransactionTestCase):
    def test_migracion_baja_y_sube(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('ordenes', '0049_vista_taller_oculta')])
        executor.loader.build_graph()
        tablas = set(connection.introspection.table_names())
        self.assertNotIn('ordenes_cobrotaller', tablas)
        executor = MigrationExecutor(connection)
        executor.migrate([('ordenes', '0050_cobro_taller')])
        executor.loader.build_graph()
        tablas = set(connection.introspection.table_names())
        self.assertIn('ordenes_cobrotaller', tablas)
        self.assertIn('ordenes_costotaller', tablas)

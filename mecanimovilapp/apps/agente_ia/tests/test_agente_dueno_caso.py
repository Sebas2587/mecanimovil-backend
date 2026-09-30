"""El agente del dueño contesta con un caso y escribe solo después del sí."""
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import (
    AgenteDuenoAvisoCliente,
    AgenteDuenoHilo,
    AgenteDuenoMensaje,
)
from mecanimovilapp.apps.agente_ia.services.agente_dueno import responder_agente_dueno
from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CitaAgendaPersonalDetalle,
    SolicitudServicio,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import Cliente, HorarioProveedor, Taller
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo, Vehiculo

User = get_user_model()


class AgenteDuenoCasoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='dueno_caso', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Caso',
            telefono='900000010',
            estado_verificacion='aprobado',
        )
        self.hoy = timezone.localdate()

    def _cita(
        self,
        *,
        cliente,
        hora,
        marca='',
        modelo='',
        patente='',
        confirmar=True,
        fecha=None,
        telefono='+56911111111',
        oferta=None,
        precio=None,
        servicio='Cambio de pastillas',
    ):
        cita = CitaAgendaPersonal.objects.create(
            taller=self.taller,
            fecha_servicio=fecha or self.hoy,
            hora_servicio=hora,
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            horario_por_confirmar=not confirmar,
            creado_por=self.user,
        )
        CitaAgendaPersonalDetalle.objects.create(
            cita=cita,
            cliente_nombre=cliente,
            cliente_telefono=telefono,
            vehiculo_marca=marca,
            vehiculo_modelo=modelo,
            vehiculo_patente=patente,
            servicio_nombre=servicio,
            oferta_servicio=oferta,
            precio_referencia=precio,
        )
        return cita

    def _decir(self, texto, hilo_id=None):
        return responder_agente_dueno(self.taller, texto, [], hilo_id, self.user)

    def test_vehiculo_de_la_cita_no_es_la_marca_del_servicio(self):
        self._cita(
            cliente='Ana',
            hora=time(14, 30),
            marca='Toyota',
            modelo='Yaris',
            patente='ABCD12',
        )
        respuesta = self._decir('¿Qué vehículo es el de las 14:30?')
        self.assertTrue(respuesta['ok'])
        self.assertIn('Toyota Yaris', respuesta['resumen'])
        self.assertIn('ABCD12', respuesta['resumen'])

    def test_cita_sin_auto_separa_la_configuracion_del_servicio(self):
        marca = Marca.objects.create(nombre='Chevrolet Caso')
        modelo = Modelo.objects.create(nombre='Sail Caso', marca=marca)
        servicio = Servicio.objects.create(nombre='Aceite Caso')
        oferta = OfertaServicio.objects.create(
            servicio=servicio,
            tipo_proveedor='taller',
            taller=self.taller,
            marca_vehiculo_seleccionada=marca,
            modelo_vehiculo_seleccionado=modelo,
            disponible=True,
            precio_sin_repuestos=Decimal('40000'),
            precio_con_repuestos=Decimal('50000'),
            precio_publicado_cliente=Decimal('50000'),
            costo_mano_de_obra_sin_iva=Decimal('30000'),
            costo_repuestos_sin_iva=Decimal('8000'),
        )
        self._cita(cliente='Ana', hora=time(16, 0), oferta=oferta, servicio='Aceite')
        respuesta = self._decir('¿Qué vehículo es el de las 16:00?')
        resumen = respuesta['resumen'].lower()
        self.assertIn('no tiene marca', resumen)
        self.assertIn('chevrolet caso', resumen)
        self.assertIn('configurado', resumen)
        self.assertNotIn('el auto es chevrolet', resumen)

    def test_cuenta_servicios_y_ofertas_por_separado(self):
        aceite = Servicio.objects.create(nombre='Aceite Taller')
        frenos = Servicio.objects.create(nombre='Frenos Taller')
        for servicio, marca_nombre in (
            (aceite, 'Toyota Oferta'),
            (aceite, 'Suzuki Oferta'),
            (frenos, 'Kia Oferta'),
        ):
            marca = Marca.objects.create(nombre=marca_nombre)
            OfertaServicio.objects.create(
                servicio=servicio,
                tipo_proveedor='taller',
                taller=self.taller,
                marca_vehiculo_seleccionada=marca,
                disponible=True,
                tipo_servicio='sin_repuestos' if servicio == frenos else 'con_repuestos',
                precio_sin_repuestos=Decimal('20000'),
                precio_con_repuestos=Decimal('30000'),
                precio_publicado_cliente=Decimal('30000'),
            )
        respuesta = self._decir('¿Cuántos servicios tengo?')
        self.assertIn('2 servicios', respuesta['resumen'])
        self.assertIn('3 ofertas', respuesta['resumen'])
        self.assertNotIn('3 servicios', respuesta['resumen'])
        self.assertTrue(any('Toyota Oferta' in fila['detalle'] for fila in respuesta['filas']))

    def test_hoy_incluye_cita_personal_y_orden_de_la_app(self):
        self._cita(cliente='Ana', hora=time(11, 0), marca='Toyota', modelo='Yaris', patente='ABCD12')
        cliente_user = User.objects.create_user(username='cli_caso', email='cli_caso@test.com', password='x')
        cliente = Cliente.objects.create(usuario=cliente_user, nombre='Bruno', email='cli_caso@test.com')
        marca = Marca.objects.create(nombre='Fiat Caso')
        modelo = Modelo.objects.create(nombre='Uno Caso', marca=marca)
        vehiculo = Vehiculo.objects.create(cliente=cliente, marca=marca, modelo=modelo, year=2018, patente='BRUNO1')
        SolicitudServicio.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            taller=self.taller,
            tipo_servicio='taller',
            fecha_servicio=self.hoy,
            hora_servicio=time(10, 0),
            metodo_pago='transferencia',
            total=Decimal('45000'),
            estado='aceptada_por_proveedor',
        )
        respuesta = self._decir('¿Qué tengo hoy?')
        texto = respuesta['resumen'] + ' '.join(fila['titulo'] for fila in respuesta['filas'])
        self.assertIn('Ana', texto)
        self.assertIn('Bruno', texto)
        self.assertEqual(len(respuesta['filas']), 2)

    def test_agendar_espera_el_si_y_despues_escribe_la_agenda(self):
        manana = self.hoy + timedelta(days=1)
        HorarioProveedor.objects.create(
            taller=self.taller,
            dia_semana=manana.weekday(),
            activo=True,
            hora_inicio=time(8, 0),
            hora_fin=time(18, 0),
        )
        cita = self._cita(
            cliente='Rosa',
            hora=time(8, 0),
            confirmar=False,
            marca='Toyota',
            modelo='Yaris',
            patente='ROSA12',
        )
        propuesta = self._decir('Agenda la cita de Rosa mañana a las 8')
        cita.refresh_from_db()
        self.assertTrue(cita.horario_por_confirmar)
        self.assertEqual(propuesta['confirmacion']['tipo'], 'accion')
        self.assertIn('08:00', propuesta['resumen'])
        self.assertIn('ROSA12', propuesta['resumen'])
        hecho = self._decir('sí', propuesta['hilo_id'])
        cita.refresh_from_db()
        self.assertFalse(cita.horario_por_confirmar)
        self.assertEqual(cita.fecha_servicio, manana)
        self.assertEqual(cita.hora_servicio.hour, 8)
        self.assertIn('agenda', hecho['resumen'].lower())
        self.assertIsNone(hecho['confirmacion'])

    def test_mensaje_se_anota_en_el_caso_y_el_caso_sigue(self):
        self._cita(cliente='Ana', hora=time(14, 30), telefono='+56912345678', marca='Toyota', modelo='Yaris')
        propuesta = self._decir('Dile a Ana que mañana está listo')
        self.assertEqual(propuesta['confirmacion']['tipo'], 'whatsapp')
        self.assertIn('mañana está listo', propuesta['resumen'])
        self.assertEqual(AgenteDuenoAvisoCliente.objects.count(), 0)
        hecho = self._decir('sí', propuesta['hilo_id'])
        aviso = AgenteDuenoAvisoCliente.objects.get()
        self.assertIn('mañana está listo', aviso.texto)
        self.assertEqual(aviso.telefono, '+56912345678')
        self.assertEqual(hecho['abrir_whatsapp']['telefono'], '+56912345678')
        hilo = AgenteDuenoHilo.objects.get(id=propuesta['hilo_id'])
        self.assertEqual(hilo.caso_anclado.get('cliente'), 'Ana')

    def test_reabrir_el_hilo_muestra_las_mismas_tarjetas(self):
        self._cita(cliente='Ana', hora=time(14, 30), marca='Toyota', modelo='Yaris', patente='ABCD12')
        respuesta = self._decir('¿Qué vehículo es el de las 14:30?')
        mensaje = AgenteDuenoMensaje.objects.filter(hilo_id=respuesta['hilo_id'], rol='agente').get()
        self.assertEqual(mensaje.vista['filas'][0]['id'], respuesta['filas'][0]['id'])
        self.assertIn('ABCD12', mensaje.vista['resumen'])

    def test_una_correccion_vale_en_el_hilo_siguiente(self):
        self._cita(cliente='Pedro', hora=time(9, 0), marca='Kia', modelo='Rio', patente='PEDR01')
        primero = self._decir('¿Qué tengo hoy?')
        self._decir('ese no es el cliente', primero['hilo_id'])
        siguiente = self._decir('¿Qué tengo hoy?')
        texto = siguiente['resumen'] + ' '.join(
            f"{fila['titulo']} {fila['detalle']}" for fila in siguiente['filas']
        )
        self.assertNotIn('Pedro', texto)

    def test_dos_casos_a_la_misma_hora_no_escribe(self):
        self._cita(cliente='Ana', hora=time(14, 30), marca='Toyota', modelo='Yaris', patente='AAAA11')
        self._cita(cliente='Luis', hora=time(14, 30), marca='Kia', modelo='Rio', patente='BBBB22')
        respuesta = self._decir('¿Qué vehículo es el de las 14:30?')
        self.assertEqual(len(respuesta['filas']), 2)
        self.assertIsNone(respuesta['confirmacion'])
        hilo = AgenteDuenoHilo.objects.get(id=respuesta['hilo_id'])
        self.assertEqual(hilo.accion_pendiente, {})

    def test_cobro_espera_el_si(self):
        cita = self._cita(
            cliente='Ana',
            hora=time(14, 30),
            precio=Decimal('50000'),
            marca='Toyota',
            modelo='Yaris',
        )
        propuesta = self._decir('Anota el cobro de Ana en efectivo')
        cita.refresh_from_db()
        self.assertEqual(cita.cobro_estado, 'pendiente')
        self.assertIn('50.000', propuesta['resumen'])
        self._decir('sí', propuesta['hilo_id'])
        cita.refresh_from_db()
        self.assertEqual(cita.cobro_estado, 'anotado')
        self.assertEqual(cita.cobro_medio, 'efectivo')
        self.assertEqual(int(cita.cobro_monto_clp), 50000)

    def test_frase_abierta_no_escribe_el_caso(self):
        cita = self._cita(cliente='Ana', hora=time(14, 30), precio=Decimal('50000'))
        with patch(
            'mecanimovilapp.apps.agente_ia.services.orquestador._llamar_gemini_agente',
            return_value=(None, 'sin modelo'),
        ):
            respuesta = self._decir('hola, qué tal el día')
        self.assertFalse(respuesta['ok'])
        cita.refresh_from_db()
        self.assertEqual(cita.cobro_estado, 'pendiente')

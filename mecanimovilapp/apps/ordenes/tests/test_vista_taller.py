"""Limpiar la lista no borra la cotización ni el historial que leen los agentes."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from mecanimovilapp.apps.ordenes.models import CotizacionCanal, VistaTallerOculta
from mecanimovilapp.apps.ordenes.services.vista_taller import (
    cotizacion_se_puede_ocultar,
    excluir_ocultos,
    limpiar_vista,
    ocultar_cotizacion,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class VistaTallerOcultaTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='limpia_taller', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Limpieza',
            telefono='900000088',
            estado_verificacion='aprobado',
        )

    def _cotizacion(self, **kwargs):
        datos = {
            'taller': self.taller,
            'es_libre': True,
            'estado': 'rechazada',
            'cliente_nombre': 'Ana',
            'servicio_nombre': 'Embrague',
            'vehiculo_marca': 'Suzuki',
            'vehiculo_modelo': 'Swift',
            'mano_obra_clp': 80000,
        }
        datos.update(kwargs)
        return CotizacionCanal.objects.create(**datos)

    def test_rechazada_sale_de_la_lista_y_la_fila_sigue(self):
        cotizacion = self._cotizacion()
        ocultos = ocultar_cotizacion(self.taller, cotizacion)
        self.assertEqual(ocultos, 1)
        self.assertTrue(CotizacionCanal.objects.filter(pk=cotizacion.id).exists())
        visibles = excluir_ocultos(CotizacionCanal.objects.filter(taller=self.taller), self.taller.id, 'cotizacion')
        self.assertFalse(visibles.filter(pk=cotizacion.id).exists())
        self.assertEqual(VistaTallerOculta.objects.count(), 1)

    def test_enviada_no_se_puede_quitar(self):
        cotizacion = self._cotizacion(estado='enviada')
        self.assertFalse(cotizacion_se_puede_ocultar(cotizacion))
        with self.assertRaises(ValueError):
            ocultar_cotizacion(self.taller, cotizacion)

    def test_limpiar_no_borra_el_historial_del_agente(self):
        self._cotizacion(
            estado='aceptada',
            vehiculo_marca='Suzuki',
            vehiculo_modelo='Swift',
            servicio_nombre='Cambio de embrague',
        )
        terminada = self._cotizacion(estado='rechazada', servicio_nombre='Radiador')
        antes = CotizacionCanal.objects.count()
        limpiar_vista(self.taller, 'cotizaciones_rechazadas')
        self.assertEqual(CotizacionCanal.objects.count(), antes)
        self.assertTrue(CotizacionCanal.objects.filter(pk=terminada.id).exists())
        historial = CotizacionCanal.objects.filter(
            taller=self.taller,
            estado__in=('enviada', 'aceptada'),
        )
        self.assertEqual(historial.count(), 1)
        self.assertEqual(historial.get().servicio_nombre, 'Cambio de embrague')

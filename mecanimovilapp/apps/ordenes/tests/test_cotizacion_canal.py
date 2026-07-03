"""Tests cotización canal IA."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
    normalizar_cotizacion_ia,
    normalizar_repuesto,
    recalcular_totales,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
    _parse_button_id,
    formatear_resumen_cotizacion,
)


class NormalizarCotizacionTestCase(SimpleTestCase):
    def test_normaliza_repuesto_desde_ia(self):
        rep = normalizar_repuesto(
            {'repuesto': 'Filtro aceite', 'precio_estimado_clp': '$15.000 - $25.000 CLP', 'cantidad': 1},
            0,
        )
        self.assertEqual(rep['nombre'], 'Filtro aceite')
        self.assertGreater(rep['precio_unitario_clp'], 0)

    def test_recalcular_totales(self):
        rep, mo, total = recalcular_totales(
            [{'cantidad': 2, 'precio_unitario_clp': 10000}],
            5000,
        )
        self.assertEqual(rep, 20000)
        self.assertEqual(mo, 5000)
        self.assertEqual(total, 25000)

    def test_normalizar_cotizacion_completa(self):
        ctx = {'tipo_motor_efectivo': 'GASOLINA', 'tipo_motor_efectivo_label': 'Bencinero (gasolina)'}
        data = {
            'servicio_nombre': 'Cambio bujías',
            'mano_obra_clp': 40000,
            'repuestos': [{'nombre': 'Bujía', 'cantidad': 4, 'precio_unitario_clp': 8000}],
        }
        out = normalizar_cotizacion_ia(data, ctx)
        self.assertEqual(out['servicio_nombre'], 'Cambio bujías')
        self.assertEqual(out['total_clp'], 40000 + 4 * 8000)


class CotizacionCanalUtilTestCase(SimpleTestCase):
    def test_parse_button_aceptar(self):
        self.assertEqual(_parse_button_id('cotizacion_aceptar_42'), ('aceptar', 42))

    def test_parse_button_rechazar(self):
        self.assertEqual(_parse_button_id('cotizacion_rechazar_7'), ('rechazar', 7))

    def test_parse_button_invalido(self):
        self.assertIsNone(_parse_button_id('otro_id'))

    def test_formatear_resumen_incluye_total(self):
        class FakeCot:
            servicio_nombre = 'Diagnóstico'
            vehiculo_marca = 'FIAT'
            vehiculo_modelo = 'Bravo'
            vehiculo_anio = 2010
            vehiculo_patente = 'AB1234'
            tipo_motor_label = 'Bencinero (gasolina)'
            descripcion_problema = 'Fallo encendido'
            repuestos = [{'nombre': 'Bobina', 'cantidad': 1, 'precio_unitario_clp': 50000}]
            costo_repuestos_clp = 50000
            mano_obra_clp = 45000
            total_clp = 95000
            duracion_minutos_estimada = 90

        texto = formatear_resumen_cotizacion(FakeCot())
        self.assertIn('Diagnóstico', texto)
        self.assertIn('$95.000', texto)

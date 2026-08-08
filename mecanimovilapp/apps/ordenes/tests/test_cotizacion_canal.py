"""Tests cotización canal IA."""
from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.contexto import armar_contexto_cotizacion
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

    def test_normaliza_repuesto_marketplace_y_marca(self):
        rep = normalizar_repuesto(
            {
                'nombre': 'Pastillas freno',
                'fuente_repuesto': 'mercadolibre',
                'marca_repuesto': 'Bosch',
                'tienda_ml': 'Autopartes Sur',
                'precio_unitario_clp': 45000,
            },
            0,
        )
        self.assertEqual(rep['nombre'], 'Pastillas freno')
        self.assertEqual(rep['fuente_marketplace'], 'mercadolibre')
        self.assertEqual(rep['marca_repuesto'], 'Bosch')
        self.assertEqual(rep['tienda_ml'], 'Autopartes Sur')
        self.assertTrue(rep['precio_iva_incluido'])

    def test_enriquecer_infiere_marca_desde_nombre(self):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        out = enriquecer_repuestos_cotizacion(
            [{'id': 'rep-0', 'nombre': 'Volante bimasa Vimasa', 'cantidad': 1, 'precio_unitario_clp': 180000}],
            marca_vehiculo='Fiat',
            modelo_vehiculo='Bravo',
            usar_ml=False,
        )
        self.assertEqual(out[0].get('marca_repuesto'), 'Vimasa')
        self.assertIsNone(out[0].get('tienda_ml'))
        self.assertNotEqual(out[0].get('fuente_marketplace'), 'mercadolibre')

    def test_enriquecer_ml_mock_llena_tienda(self):
        from unittest.mock import patch

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            enriquecer_repuestos_cotizacion,
        )

        fake = {
            'marca_repuesto': 'Bosch',
            'tienda_ml': 'AutopartesSurCL',
            'fuente_marketplace': 'mercadolibre',
        }
        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos._buscar_ml_repuesto',
            return_value=fake,
        ):
            out = enriquecer_repuestos_cotizacion(
                [{'id': 'rep-0', 'nombre': 'Pastillas freno', 'cantidad': 1, 'precio_unitario_clp': 45000}],
                usar_ml=True,
            )
        self.assertEqual(out[0].get('marca_repuesto'), 'Bosch')
        self.assertEqual(out[0].get('tienda_ml'), 'AutopartesSurCL')
        self.assertEqual(out[0].get('fuente_marketplace'), 'mercadolibre')

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
            modalidad = 'taller'
            vehiculo_marca = 'FIAT'
            vehiculo_modelo = 'Bravo'
            vehiculo_anio = 2010
            vehiculo_patente = 'AB1234'
            vehiculo_cilindraje = '1368'
            tipo_motor_label = 'Bencinero (gasolina)'
            descripcion_problema = 'Fallo encendido'
            repuestos = [{'nombre': 'Bobina', 'cantidad': 1, 'precio_unitario_clp': 50000}]
            costo_repuestos_clp = 50000
            mano_obra_clp = 45000
            total_clp = 95000
            duracion_minutos_estimada = 90
            advertencias = ['Precios referenciales']

        texto = formatear_resumen_cotizacion(FakeCot())
        self.assertIn('Diagnóstico', texto)
        self.assertIn('$95.000', texto)
        self.assertIn('Marca: FIAT', texto)
        self.assertIn('Cilindraje: 1368', texto)
        self.assertIn('Mano de obra:', texto)
        self.assertIn('Condiciones:', texto)


class ContextoCotizacionTestCase(SimpleTestCase):
    def test_incluye_vehiculo_servicio_y_descripcion(self):
        ctx = armar_contexto_cotizacion(
            servicio_nombre='cambio de aceite',
            descripcion_problema='Aceite sintético 5W40',
            modalidad='taller',
            vehiculo={
                'marca': 'FIAT',
                'modelo': 'BRAVO SPORT TJET',
                'anio': 2010,
                'patente': 'ABCD12',
                'cilindraje': '1368',
            },
        )
        self.assertEqual(ctx['marca'], 'FIAT')
        self.assertEqual(ctx['modelo'], 'BRAVO SPORT TJET')
        self.assertEqual(ctx['servicio_nombre'], 'cambio de aceite')
        self.assertEqual(ctx['descripcion_problema'], 'Aceite sintético 5W40')
        self.assertEqual(ctx['tipo_motor_efectivo'], 'GASOLINA')


class PlantillaVehiculoTestCase(SimpleTestCase):
    def test_coincide_marca_modelo_cilindraje(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        snap = {
            'vehiculo_marca': 'FIAT',
            'vehiculo_modelo': 'BRAVO SPORT TJET',
            'vehiculo_cilindraje': '1368',
        }
        self.assertTrue(
            plantilla_coincide_vehiculo(
                snap,
                marca='Fiat',
                modelo='Bravo Sport T-Jet',
                cilindraje='1.368 cc',
            ),
        )

    def test_rechaza_cilindraje_distinto(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        snap = {
            'vehiculo_marca': 'FIAT',
            'vehiculo_modelo': 'BRAVO',
            'vehiculo_cilindraje': '1368',
        }
        self.assertFalse(
            plantilla_coincide_vehiculo(
                snap,
                marca='FIAT',
                modelo='BRAVO',
                cilindraje='1600',
            ),
        )

    def test_rechaza_sin_vehiculo_en_snapshot(self):
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import plantilla_coincide_vehiculo

        self.assertFalse(
            plantilla_coincide_vehiculo(
                {'servicio_nombre': 'Cambio aceite'},
                marca='FIAT',
                modelo='BRAVO',
            ),
        )

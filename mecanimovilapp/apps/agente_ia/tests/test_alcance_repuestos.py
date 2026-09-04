from django.test import SimpleTestCase, override_settings

from mecanimovilapp.apps.agente_ia.services.contexto_repuestos import (
    ALCANCE_CON,
    ALCANCE_SOLO_MO,
    aplicar_alcance_repuestos,
    bloque_prompt_repuestos,
    inferir_alcance_repuestos,
)
from mecanimovilapp.apps.agente_ia.services.pregunta_calidad import (
    parsear_respuesta_calidad,
    pregunta_calidad_necesaria,
)
from mecanimovilapp.apps.agente_ia.services.resumen_alcance import (
    construir_resumen_alcance,
    debe_enviar_resumen,
    urgencia_explicita,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import metadata_cotizacion_mensaje


class AlcanceRepuestosTest(SimpleTestCase):
    def test_yo_pongo_repuestos_es_solo_mano_obra(self):
        self.assertEqual(inferir_alcance_repuestos('yo pongo los repuestos'), ALCANCE_SOLO_MO)
        datos = aplicar_alcance_repuestos({}, {}, 'ya tengo la pieza')
        self.assertEqual(datos['alcance_repuestos'], ALCANCE_SOLO_MO)
        self.assertFalse(datos['repuestos_incluidos_ultimo_servicio'])

    def test_pieza_nombrada_es_con_repuestos(self):
        self.assertEqual(inferir_alcance_repuestos('cambio de pastillas delanteras'), ALCANCE_CON)

    def test_preferencia_conocida_no_pregunta(self):
        datos = {
            'vehiculo': {'marca': 'Hyundai', 'modelo': 'Accent'},
            'piezas_mencionadas': ['pastillas de freno'],
            'alcance_repuestos': 'con_repuestos',
        }

        class _Cfg:
            preguntar_calidad_repuestos = True

        with override_settings(
            AGENTE_IA_ALCANCE_REPUESTOS_ENABLED=True,
            AGENTE_IA_BOTONES_CALIDAD_ENABLED=True,
        ):
            self.assertFalse(
                pregunta_calidad_necesaria(
                    datos=datos,
                    config=_Cfg(),
                    ctx_repuestos={'calidad_preferida': 'alternativo', 'muestras': 3},
                )
            )

    def test_parseo_botones_y_numerado(self):
        self.assertEqual(parsear_respuesta_calidad('calidad_oem'), 'oem')
        self.assertEqual(parsear_respuesta_calidad('1'), 'original')
        self.assertEqual(parsear_respuesta_calidad('alternativo'), 'alternativo')

    def test_bloque_prompt_unico(self):
        txt = bloque_prompt_repuestos({'calidad_preferida': 'oem', 'nivel': 'memoria', 'muestras': 4})
        self.assertIn('equivalente OEM', txt)
        self.assertIn('NO preguntes', txt)


class ResumenAlcanceTest(SimpleTestCase):
    def test_sin_montos(self):
        burbujas = construir_resumen_alcance({
            'servicios': ['Cambio de pastillas'],
            'piezas_mencionadas': ['Pastilla delantera'],
            'calidad_preferida': 'oem',
        })
        blob = ' '.join(burbujas)
        self.assertNotRegex(blob, r'\$\s*\d')
        self.assertLessEqual(len(burbujas), 3)

    def test_escape_urgencia(self):
        self.assertTrue(urgencia_explicita('mándame el precio ya'))

        class _Ses:
            datos_capturados = {
                'servicios': ['Cambio de aceite'],
                'resumen_alcance_enviado': False,
            }

        with override_settings(AGENTE_IA_ALCANCE_REPUESTOS_ENABLED=True):
            self.assertFalse(
                debe_enviar_resumen(_Ses(), {'listo_para_cotizar': True}, 'mándame el precio ya')
            )


class CotizacionInteractiveRegressionTest(SimpleTestCase):
    def test_metadata_cotizacion_sigue_sin_interactive(self):
        class _Cot:
            id = 1
            servicio_nombre = 'Cambio de aceite'
            descripcion_problema = ''
            modalidad = 'taller'
            tipo_documento = 'cotizacion'
            vehiculo_marca = 'Hyundai'
            vehiculo_modelo = 'Accent'
            vehiculo_anio = '2016'
            vehiculo_cilindraje = ''
            vehiculo_patente = 'ABCD12'
            tipo_motor_label = ''
            mano_obra_clp = 40000
            costo_repuestos_clp = 0
            total_clp = 40000
            duracion_minutos_estimada = 60
            url_publica = 'https://ejemplo.cl/cotizacion/x'
            metadata = {}
            advertencias = []
            repuestos = []
            taller = None

        meta = metadata_cotizacion_mensaje(_Cot())
        self.assertFalse(meta.get('interactive'))
        self.assertEqual(meta.get('tipo'), 'cotizacion_canal')

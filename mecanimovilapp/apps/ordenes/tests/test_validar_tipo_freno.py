"""Tests para validación de tipo de freno (pastillas vs balatas)."""
from __future__ import annotations

from django.test import SimpleTestCase


class ValidarTipoFrenoTestCase(SimpleTestCase):
    """Tests para la distinción entre pastillas (disco) y balatas (tambor)."""

    def test_balatas_no_es_pastillas(self):
        """Las balatas (zapatas de tambor) no deben ser tratadas como pastillas (disco)."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _es_balatas_freno,
            _es_pastillas_freno,
        )

        # Balatas/zapatas son frenos de tambor
        self.assertTrue(_es_balatas_freno('balatas traseras'))
        self.assertTrue(_es_balatas_freno('balatas delanteras'))
        self.assertTrue(_es_balatas_freno('zapatas de freno'))
        self.assertTrue(_es_balatas_freno('zapatas traseras'))

        # Balatas NO son pastillas
        self.assertFalse(_es_pastillas_freno('balatas traseras'))
        self.assertFalse(_es_pastillas_freno('balatas delanteras'))
        self.assertFalse(_es_pastillas_freno('zapatas de freno'))

        # Pastillas son frenos de disco
        self.assertTrue(_es_pastillas_freno('pastillas de freno'))
        self.assertTrue(_es_pastillas_freno('pastillas delanteras'))
        self.assertTrue(_es_pastillas_freno('pastillas traseras'))

        # Pastillas NO son balatas
        self.assertFalse(_es_balatas_freno('pastillas de freno'))
        self.assertFalse(_es_balatas_freno('pastillas delanteras'))

    def test_validar_tipo_familia_freno_pastillas_vs_balatas(self):
        """Debe rechazar cuando se piden balatas pero el producto es pastillas."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_tipo_familia_freno,
        )

        # Caso reportado: se piden balatas traseras pero el enlace apunta a pastillas
        es_valido, motivo = _validar_tipo_familia_freno(
            'balatas traseras',
            'Pastillas de freno Peugeot Boxer'
        )
        self.assertFalse(es_valido)
        self.assertIn('pastillas', motivo.lower())
        self.assertIn('balatas', motivo.lower())

        # Caso inverso: se piden pastillas pero el enlace apunta a balatas
        es_valido, motivo = _validar_tipo_familia_freno(
            'pastillas delanteras',
            'Balatas de freno Peugeot Boxer'
        )
        self.assertFalse(es_valido)
        self.assertIn('balatas', motivo.lower())

    def test_validar_tipo_familia_freno_posicion_correcta(self):
        """Debe validar cuando el tipo y posición coinciden."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_tipo_familia_freno,
        )

        # Pastillas delanteras -> Pastillas delanteras: OK
        es_valido, motivo = _validar_tipo_familia_freno(
            'pastillas delanteras',
            'Pastillas de freno delanteras Peugeot Boxer'
        )
        self.assertTrue(es_valido)
        self.assertEqual(motivo, '')

        # Balatas traseras -> Balatas traseras: OK
        es_valido, motivo = _validar_tipo_familia_freno(
            'balatas traseras',
            'Balatas de freno traseras Peugeot Boxer'
        )
        self.assertTrue(es_valido)
        self.assertEqual(motivo, '')

        # Pastillas traseras -> Pastillas traseras: OK
        es_valido, motivo = _validar_tipo_familia_freno(
            'pastillas traseras',
            'Pastillas freno traseras Fiat Bravo'
        )
        self.assertTrue(es_valido)
        self.assertEqual(motivo, '')

    def test_validar_tipo_familia_freno_posicion_incorrecta(self):
        """Debe rechazar cuando se piden delanteras pero el producto es trasero."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_tipo_familia_freno,
        )

        # Pastillas delanteras -> Pastillas traseras: Rechazar
        es_valido, motivo = _validar_tipo_familia_freno(
            'pastillas delanteras',
            'Pastillas de freno traseras Peugeot Boxer'
        )
        self.assertFalse(es_valido)
        self.assertIn('trasero', motivo.lower())
        self.assertIn('delantero', motivo.lower())

        # Balatas traseras -> Balatas delanteras: Rechazar
        es_valido, motivo = _validar_tipo_familia_freno(
            'balatas traseras',
            'Balatas de freno delanteras Peugeot Boxer'
        )
        self.assertFalse(es_valido)
        self.assertIn('delantero', motivo.lower())
        self.assertIn('trasero', motivo.lower())

    def test_validar_tipo_familia_freno_posicion_ambigua(self):
        """Debe rechazar cuando se especifica posición pero el producto no la menciona."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _validar_tipo_familia_freno,
        )

        # Se piden pastillas delanteras pero el producto solo dice "Pastillas de freno": Rechazar
        es_valido, motivo = _validar_tipo_familia_freno(
            'pastillas delanteras',
            'Pastillas de freno Peugeot Boxer'
        )
        self.assertFalse(es_valido)
        self.assertIn('ambiguo', motivo.lower())
        self.assertIn('delantero', motivo.lower())

    def test_posicion_freno_extraccion(self):
        """Debe extraer correctamente la posición del freno."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _posicion_freno,
        )

        # Delantero
        self.assertEqual(_posicion_freno('pastillas delanteras'), 'delantero')
        self.assertEqual(_posicion_freno('balatas delanteras fiat bravo'), 'delantero')
        self.assertEqual(_posicion_freno('frenos delanteros'), 'delantero')

        # Trasero
        self.assertEqual(_posicion_freno('pastillas traseras'), 'trasero')
        self.assertEqual(_posicion_freno('balatas traseras peugeot boxer'), 'trasero')
        self.assertEqual(_posicion_freno('frenos traseros'), 'trasero')

        # Sin posición
        self.assertIsNone(_posicion_freno('pastillas de freno'))
        self.assertIsNone(_posicion_freno('balatas'))
        self.assertIsNone(_posicion_freno('kit de frenos'))

    def test_motivo_calidad_pastilla_rechaza_tipo_incompatible(self):
        """_motivo_calidad_pastilla debe rechazar cuando el tipo de freno no coincide."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _motivo_calidad_pastilla,
        )

        # Caso reportado: se piden balatas traseras pero la ficha es de pastillas
        candidato = {
            'title': 'Pastillas de freno Peugeot Boxer',
            'url': 'https://tienda.cl/pastillas-peugeot-boxer',
            'content': 'Pastillas de freno disco Peugeot Boxer',
            'precio_snippet': 35000,
            'ficha_leida': True,
        }

        motivo = _motivo_calidad_pastilla(
            candidato,
            nombre='balatas traseras',
            modelo='Boxer',
            tipo_motor='Diesel',
            banda_min=25000,
            banda_max=50000,
            anio=2015,
            cilindraje='2.2',
        )

        # Debe retornar solo el código string, no tuple
        self.assertEqual(motivo, 'tipo_freno_incompatible')
        self.assertIsInstance(motivo, str)

    def test_motivo_calidad_pastilla_acepta_tipo_correcto(self):
        """_motivo_calidad_pastilla debe aceptar cuando el tipo de freno coincide."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _motivo_calidad_pastilla,
        )

        # Pastillas -> Pastillas: OK
        candidato = {
            'title': 'Pastillas de freno delanteras Fiat Bravo 1.4',
            'url': 'https://tienda.cl/pastillas-fiat-bravo',
            'content': 'Pastillas de freno disco delanteras Fiat Bravo',
            'precio_snippet': 35000,
            'ficha_leida': True,
        }

        motivo = _motivo_calidad_pastilla(
            candidato,
            nombre='pastillas delanteras',
            modelo='Bravo',
            tipo_motor='T-Jet',
            banda_min=25000,
            banda_max=50000,
            anio=2012,
            cilindraje='1.4',
        )

        # No debe retornar 'tipo_freno_incompatible'
        self.assertNotEqual(motivo, 'tipo_freno_incompatible')

    def test_validar_repuesto_rechaza_tipo_incompatible(self):
        """validar_repuesto debe marcar como incompatible cuando el tipo no coincide."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
            validar_repuesto,
        )

        # Repuesto que pide balatas traseras pero tiene enlace a pastillas
        rep = {
            'nombre': 'balatas traseras',
            'cantidad': 1,
            'precio_unitario_clp': 35000,
            'precio_min_clp': 25000,
            'precio_max_clp': 50000,
            'fuentes_detalle': [
                {
                    'fuente': 'web',
                    'tienda': 'Repuestos Chile',
                    'dominio': 'repuestoschile.cl',
                    'precio_clp': 35000,
                    'url': 'https://repuestoschile.cl/pastillas-peugeot-boxer',
                    'nombre': 'Pastillas de freno Peugeot Boxer',
                }
            ],
        }

        resultado = validar_repuesto(
            rep,
            marca='Peugeot',
            modelo='Boxer',
            anio=2015,
            tipo_motor='Diesel',
            cilindraje='2.2',
        )

        # Debe estar en estado 'sin_referencia_valida' porque la ficha es incompatible
        self.assertEqual(resultado['validacion_estado'], 'sin_referencia_valida')
        self.assertIn('validacion_motivo', resultado)
        # El motivo debe contener el mensaje específico sobre el mismatch
        motivo = resultado['validacion_motivo']
        self.assertIn('pastillas', motivo.lower())
        self.assertIn('balatas', motivo.lower())

    def test_validar_repuesto_acepta_tipo_compatible(self):
        """validar_repuesto debe aceptar cuando el tipo coincide."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
            validar_repuesto,
        )

        # Repuesto que pide pastillas delanteras y el enlace es de pastillas delanteras
        rep = {
            'nombre': 'pastillas delanteras',
            'cantidad': 1,
            'precio_unitario_clp': 35000,
            'precio_min_clp': 25000,
            'precio_max_clp': 50000,
            'fuentes_detalle': [
                {
                    'fuente': 'web',
                    'tienda': 'Repuestos Chile',
                    'dominio': 'repuestoschile.cl',
                    'precio_clp': 35000,
                    'url': 'https://repuestoschile.cl/pastillas-fiat-bravo-delanteras',
                    'nombre': 'Pastillas de freno delanteras Fiat Bravo 1.4',
                }
            ],
        }

        resultado = validar_repuesto(
            rep,
            marca='Fiat',
            modelo='Bravo',
            anio=2012,
            tipo_motor='T-Jet',
            cilindraje='1.4',
        )

        # Debe estar en estado 'ok' porque la ficha coincide
        self.assertEqual(resultado['validacion_estado'], 'ok')
        self.assertTrue(resultado['precio_verificado_clp'] > 0)

    def test_validar_repuesto_rechaza_titulo_generico(self):
        """Debe rechazar cuando el producto tiene título genérico sin especificar familia."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
            validar_repuesto,
        )

        # Se piden balatas traseras pero el producto dice solo "frenos traseros"
        rep = {
            'nombre': 'balatas traseras',
            'cantidad': 1,
            'precio_unitario_clp': 32000,
            'precio_min_clp': 25000,
            'precio_max_clp': 50000,
            'fuentes_detalle': [
                {
                    'fuente': 'web',
                    'tienda': 'Auto Repuestos',
                    'dominio': 'autorepuestos.cl',
                    'precio_clp': 32000,
                    'url': 'https://autorepuestos.cl/frenos-peugeot-boxer',
                    'nombre': 'Frenos traseros Peugeot Boxer',
                }
            ],
        }

        resultado = validar_repuesto(
            rep,
            marca='Peugeot',
            modelo='Boxer',
            anio=2015,
            tipo_motor='Diesel',
            cilindraje='2.2',
        )

        # Debe estar en estado 'sin_referencia_valida' porque es ambiguo
        self.assertEqual(resultado['validacion_estado'], 'sin_referencia_valida')
        motivo = resultado['validacion_motivo']
        self.assertIn('ambiguo', motivo.lower())

    def test_consultas_balatas_no_contiene_pastillas(self):
        """_consultas_balatas debe buscar balatas/zapatas, nunca pastillas."""
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            _consultas_balatas,
        )

        # Caso: balatas traseras
        consultas = _consultas_balatas(
            'balatas traseras',
            marca='Peugeot',
            modelo='Boxer',
            cilindraje='2.2',
            tipo_motor='Diesel',
        )

        self.assertTrue(len(consultas) > 0)
        for consulta in consultas:
            consulta_lower = consulta.lower()
            # Debe contener balatas o zapatas
            self.assertTrue('balata' in consulta_lower or 'zapata' in consulta_lower,
                          f"Query '{consulta}' should contain 'balatas' or 'zapatas'")
            # Nunca debe contener pastillas
            self.assertNotIn('pastilla', consulta_lower,
                           f"Query '{consulta}' should NOT contain 'pastillas'")

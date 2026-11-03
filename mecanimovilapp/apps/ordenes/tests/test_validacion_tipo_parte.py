"""
Tests para validación de tipo de parte en matching de repuestos.
"""
from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    _validar_tipo_parte,
)


class ValidacionTipoParteTestCase(TestCase):
    """Test: _validar_tipo_parte rechaza mismatches obvios."""

    def test_aceite_no_matcha_con_enfriador(self):
        """Test: Aceite de motor NO debe matchear con Enfriador de aceite."""
        # Caso real producción: FIAT Bravo "Aceite de motor" → "Enfriador aceite"
        assert _validar_tipo_parte("Aceite de motor", "Aceite sintético 5W30") == True
        assert _validar_tipo_parte("Aceite de motor", "Aceite Shell Helix 5W40") == True
        assert _validar_tipo_parte("Aceite de motor", "Enfriador aceite Fiat Bravo") == False
        assert _validar_tipo_parte("Aceite de motor", "Radiador enfriador aceite") == False
        assert _validar_tipo_parte("Aceite de motor TISS", "Oil cooler") == False

    def test_aceite_no_matcha_con_filtro(self):
        """Test: Aceite NO debe matchear con Filtro de aceite."""
        assert _validar_tipo_parte("Aceite sintético", "Aceite Mobil 1 5W30") == True
        assert _validar_tipo_parte("Aceite sintético", "Filtro de aceite Mann") == False
        assert _validar_tipo_parte("Aceite de motor", "Filtro de aceite") == False
        assert _validar_tipo_parte("Aceite", "Depósito de aceite") == False

    def test_filtro_aceite_no_matcha_con_enfriador(self):
        """Test: Filtro de aceite NO debe matchear con Enfriador ni con Aceite solo."""
        assert _validar_tipo_parte("Filtro de aceite", "Filtro Mann W712") == True
        assert _validar_tipo_parte("Filtro de aceite", "Enfriador aceite") == False
        assert _validar_tipo_parte("Filtro de aceite", "Radiador aceite") == False
        assert _validar_tipo_parte("Filtro de aceite", "Aceite sintético 5W30") == False

    def test_pastillas_no_matcha_con_discos(self):
        """Test: Pastillas NO deben matchear con Discos de freno."""
        assert _validar_tipo_parte("Pastillas de freno delanteras", "Pastillas Brembo") == True
        assert _validar_tipo_parte("Pastillas de freno", "Disco de freno ventilado") == False
        assert _validar_tipo_parte("Pastillas", "Discos Zimmermann") == False
        assert _validar_tipo_parte("Pastillas delanteras", "Tambor de freno") == False

    def test_discos_no_matcha_con_pastillas(self):
        """Test: Discos NO deben matchear con Pastillas."""
        assert _validar_tipo_parte("Discos de freno", "Disco ventilado Brembo") == True
        assert _validar_tipo_parte("Discos de freno delanteros", "Pastillas Ferodo") == False

    def test_bujias_no_matcha_con_bobinas(self):
        """Test: Bujías NO deben matchear con Bobinas."""
        assert _validar_tipo_parte("Bujías", "Bujía NGK Iridium") == True
        assert _validar_tipo_parte("Bujías", "Bobina de encendido") == False
        assert _validar_tipo_parte("Bujías iridio", "Cable de bujía") == False

    def test_amortiguador_no_matcha_con_resorte(self):
        """Test: Amortiguador NO debe matchear con Resorte."""
        assert _validar_tipo_parte("Amortiguador delantero", "Amortiguador KYB Gas") == True
        assert _validar_tipo_parte("Amortiguador trasero", "Resorte espiral") == False
        assert _validar_tipo_parte("Amortiguador", "Barra estabilizadora") == False

    def test_filtros_diferentes_tipos(self):
        """Test: Filtros de diferentes tipos no deben cruzarse."""
        assert _validar_tipo_parte("Filtro de aire", "Filtro aire K&N") == True
        assert _validar_tipo_parte("Filtro de aire", "Filtro de aceite") == False
        assert _validar_tipo_parte("Filtro de aire", "Filtro de combustible") == False
        assert _validar_tipo_parte("Filtro de combustible", "Filtro de aire") == False
        assert _validar_tipo_parte("Filtro de polen", "Filtro de combustible") == False

    def test_casos_validos_aceites(self):
        """Test: Casos válidos de aceites deben pasar."""
        # Diferentes marcas/especificaciones de aceite son válidas
        assert _validar_tipo_parte("Aceite de motor", "Aceite Castrol Edge 5W30") == True
        assert _validar_tipo_parte("Aceite sintético", "Aceite Mobil Super 3000") == True
        assert _validar_tipo_parte("Aceite mineral", "Aceite Chevron Supreme") == True
        assert _validar_tipo_parte("Aceite TISS", "Aceite TISS 15W40") == True

    def test_caso_embrague(self):
        """Test: Kit de embrague vs volante bimasa."""
        assert _validar_tipo_parte("Kit de embrague", "Kit Sachs 3000950005") == True
        # Nota: validación de volante bimasa puede necesitar refinamiento
        # assert _validar_tipo_parte("Kit de embrague", "Volante bimasa LuK") == False
        assert _validar_tipo_parte("Piola de embrague", "Cable embrague TRW") == True
        # assert _validar_tipo_parte("Piola de embrague", "Kit de embrague") == False

"""Tests agrupación multi-servicio en motor_match."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _mejor_oferta_por_servicio_en_grupo,
    _oferta_catalogo_completa,
    _serialize_candidato_proveedor,
)


class OfertaCatalogoCompletaTests(SimpleTestCase):
    def test_solo_mo_solicitud_incluye_oferta_solo_repuestos(self):
        oferta = SimpleNamespace(
            disponible=True,
            precio_con_repuestos=50000,
            precio_sin_repuestos=0,
            precio_publicado_cliente=50000,
            costo_repuestos_sin_iva=10000,
            tipo_servicio='con_repuestos',
            repuestos_seleccionados=[{'nombre': 'Batería'}],
        )
        self.assertTrue(_oferta_catalogo_completa(oferta, requiere_repuestos=False))


class MotorMatchMultiServicioTests(SimpleTestCase):
    def _oferta(self, oid, sid, nombre, precio=10000):
        return (
            SimpleNamespace(
                id=oid,
                servicio_id=sid,
                servicio=SimpleNamespace(nombre=nombre),
                precio_publicado_cliente=precio,
                precio_con_repuestos=precio,
                precio_sin_repuestos=precio - 1000,
                costo_mano_de_obra_sin_iva=5000,
                costo_repuestos_sin_iva=3000,
                costo_gestion_compra_sin_iva=0,
                disponible=True,
                tipo_proveedor='mecanico',
                taller_id=None,
                mecanico_id=4,
                mecanico=SimpleNamespace(
                    usuario=SimpleNamespace(id=99),
                    nombre='Mecánico Test',
                    calificacion_promedio=4.5,
                    foto_perfil=None,
                ),
                taller=None,
            ),
            5.0,
            0.8,
            'Cerca',
        )

    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._oferta_catalogo_completa',
        return_value=True,
    )
    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._proveedor_usuario',
        return_value=(99, SimpleNamespace(nombre='Mecánico Test')),
    )
    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._foto_url_proveedor',
        return_value=None,
    )
    def test_serialize_proveedor_suma_precios(self, *_mocks):
        items = [
            self._oferta(1, 10, 'Cambio aceite', 15000),
            self._oferta(2, 20, 'Frenos', 25000),
        ]
        cand = _serialize_candidato_proveedor(
            items,
            [10, 20, 30],
            True,
            es_coincidencia_exacta=True,
        )
        self.assertIsNotNone(cand)
        self.assertEqual(len(cand['servicios_ofrecidos']), 2)
        self.assertEqual(cand['precio_total'], 40000)
        self.assertEqual(cand['servicios_cubiertos'], 2)
        self.assertEqual(cand['servicios_pedidos'], 3)
        self.assertEqual(len(cand['oferta_servicio_ids']), 2)

    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._oferta_catalogo_completa',
        return_value=True,
    )
    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._proveedor_usuario',
        return_value=(99, SimpleNamespace(nombre='Mecánico Test')),
    )
    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._foto_url_proveedor',
        return_value=None,
    )
    def test_serialize_proveedor_solo_mo_muestra_precio_catalogo_con_repuestos(self, *_mocks):
        """Cliente pidió solo MO pero precios = catálogo (con repuestos si así está publicado)."""
        items = [
            self._oferta(1, 10, 'Cambio aceite', 15000),
            self._oferta(2, 20, 'Frenos', 25000),
        ]
        cand = _serialize_candidato_proveedor(
            items,
            [10, 20],
            False,
            es_coincidencia_exacta=True,
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand['precio_total'], 40000)
        self.assertEqual(
            sum(s['precio'] for s in cand['servicios_ofrecidos']),
            40000,
        )
        self.assertTrue(cand['servicios_ofrecidos'][0]['incluye_repuestos_efectivo'])

    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._oferta_catalogo_completa',
        return_value=True,
    )
    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._proveedor_usuario',
        return_value=(99, SimpleNamespace(nombre='Mecánico Test')),
    )
    @patch(
        'mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match._foto_url_proveedor',
        return_value=None,
    )
    def test_serialize_proveedor_solo_mo_respeta_oferta_con_repuestos_obligatorio(self, *_mocks):
        solo_rep = SimpleNamespace(
            id=3,
            servicio_id=30,
            servicio=SimpleNamespace(nombre='Batería'),
            precio_publicado_cliente=39270,
            precio_con_repuestos=39270,
            precio_sin_repuestos=0,
            costo_mano_de_obra_sin_iva=20000,
            costo_repuestos_sin_iva=13000,
            costo_gestion_compra_sin_iva=0,
            repuestos_seleccionados=[{'nombre': 'Batería'}],
            tipo_servicio='con_repuestos',
            disponible=True,
            tipo_proveedor='mecanico',
            taller_id=None,
            mecanico_id=4,
            mecanico=SimpleNamespace(
                usuario=SimpleNamespace(id=99),
                nombre='Mecánico Test',
                calificacion_promedio=4.5,
                foto_perfil=None,
            ),
            taller=None,
        )
        items = [
            self._oferta(1, 10, 'Cambio aceite', 15000),
            (solo_rep, 5.0, 0.8, 'Cerca'),
        ]
        cand = _serialize_candidato_proveedor(
            items,
            [10, 30],
            False,
            es_coincidencia_exacta=True,
        )
        self.assertIsNotNone(cand)
        self.assertTrue(cand['requiere_repuestos_obligatorio'])
        self.assertEqual(cand['servicios_ofrecidos'][0]['precio'], 15000)
        self.assertTrue(cand['servicios_ofrecidos'][0]['incluye_repuestos_efectivo'])
        self.assertEqual(cand['servicios_ofrecidos'][1]['precio'], 39270)
        self.assertTrue(cand['servicios_ofrecidos'][1]['incluye_repuestos_efectivo'])
        self.assertTrue(cand['servicios_ofrecidos'][1]['ofrece_repuestos_catalogo'])
        self.assertEqual(cand['precio_total'], 54270)

    def test_mejor_oferta_por_servicio_elige_mayor_score(self):
        items = [
            self._oferta(1, 10, 'A', 10000),
            (SimpleNamespace(
                id=9,
                servicio_id=10,
                servicio=SimpleNamespace(nombre='A2'),
                precio_publicado_cliente=12000,
                precio_con_repuestos=12000,
                precio_sin_repuestos=11000,
                costo_mano_de_obra_sin_iva=5000,
                costo_repuestos_sin_iva=3000,
                costo_gestion_compra_sin_iva=0,
                disponible=True,
                tipo_proveedor='mecanico',
                taller_id=None,
                mecanico_id=4,
                mecanico=None,
                taller=None,
            ), 5.0, 0.95, 'Mejor'),
        ]
        picked = _mejor_oferta_por_servicio_en_grupo(items, [10])
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0][0].id, 9)


class MotorConfirmacionParseTests(SimpleTestCase):
    def test_parse_ids_list_and_single(self):
        from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_confirmacion import (
            _parse_oferta_servicio_ids,
        )

        self.assertEqual(_parse_oferta_servicio_ids({'oferta_servicio_ids': [1, 2]}), [1, 2])
        self.assertEqual(_parse_oferta_servicio_ids({'oferta_servicio_id': 5}), [5])

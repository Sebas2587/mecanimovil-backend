"""Tests: cotizar ítems faltantes con IA (precio + fuente) sobre un borrador."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes import (
    cotizar_items_faltantes,
    parsear_nombres_items,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    linea_necesita_busqueda_web,
)
from mecanimovilapp.apps.usuarios.models import Taller

User = get_user_model()


class CotizarItemsFaltantesServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_items_ia', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller Items IA',
            telefono='900000099',
            estado_verificacion='aprobado',
        )
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            vehiculo_anio=2010,
            servicio_nombre='Cambio de kit de embrague',
            mano_obra_clp=180000,
            costo_repuestos_clp=0,
            total_clp=180000,
            repuestos=[
                {
                    'id': 'rep-1',
                    'nombre': 'Kit de embrague',
                    'cantidad': 1,
                    'precio_unitario_clp': 220000,
                    'fuente_marketplace': 'historial',
                    'proveedor_nombre': 'Historial del taller',
                    'precio_estimado': False,
                },
            ],
        )

    def test_parsear_nombres_omite_placeholder_y_duplicados(self):
        out = parsear_nombres_items([
            '  Filtro de aceite  ',
            'repuesto',
            'filtro de aceite',
            '',
            'Pastillas de freno delanteras',
        ])
        self.assertEqual(out, ['Filtro de aceite', 'Pastillas de freno delanteras'])

    def test_linea_sin_precio_necesita_busqueda(self):
        self.assertTrue(linea_necesita_busqueda_web({
            'nombre': 'Filtro de aceite',
            'precio_unitario_clp': 0,
        }))
        self.assertFalse(linea_necesita_busqueda_web({
            'nombre': 'Kit de embrague',
            'precio_unitario_clp': 220000,
            'fuente_marketplace': 'historial',
        }))
        self.assertFalse(linea_necesita_busqueda_web({'nombre': 'Repuesto', 'precio_unitario_clp': 0}))

    def test_agrega_item_y_usa_precio_de_catalogo(self):
        def _fake_enrich(repuestos, **_kwargs):
            out = []
            for r in repuestos:
                nxt = dict(r)
                if 'filtro' in (nxt.get('nombre') or '').lower():
                    nxt['precio_unitario_clp'] = 12500
                    nxt['fuente_marketplace'] = 'catalogo'
                    nxt['proveedor_nombre'] = 'Catálogo del taller'
                    nxt['marca_repuesto'] = 'Mann'
                    nxt['precio_estimado'] = False
                out.append(nxt)
            return out

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes.enriquecer_repuestos_cotizacion',
            side_effect=_fake_enrich,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web.disparar_busqueda_web_cotizacion',
        ) as mock_disparo:
            resultado = cotizar_items_faltantes(self.cot, nombres=['Filtro de aceite'])

        self.assertEqual(resultado['agregados'], ['Filtro de aceite'])
        self.cot.refresh_from_db()
        nombres = [r['nombre'] for r in self.cot.repuestos]
        self.assertIn('Filtro de aceite', nombres)
        filtro = next(r for r in self.cot.repuestos if r['nombre'] == 'Filtro de aceite')
        self.assertEqual(filtro['precio_unitario_clp'], 12500)
        self.assertEqual(filtro['fuente_marketplace'], 'catalogo')
        self.assertEqual(filtro['proveedor_nombre'], 'Catálogo del taller')
        self.assertEqual(self.cot.costo_repuestos_clp, 232500)
        mock_disparo.assert_not_called()

    def test_no_duplica_item_existente_y_dispara_web_si_falta_precio(self):
        def _fake_enrich(repuestos, **_kwargs):
            return [dict(r) for r in repuestos]

        with patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes.enriquecer_repuestos_cotizacion',
            side_effect=_fake_enrich,
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web.marcar_busqueda_web_pendiente',
            side_effect=lambda meta: {**(meta or {}), 'busqueda_web_estado': 'pendiente'},
        ), patch(
            'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web.disparar_busqueda_web_cotizacion',
        ) as mock_disparo:
            resultado = cotizar_items_faltantes(
                self.cot,
                nombres=['Kit de embrague', 'Rodamiento piloto'],
            )

        self.assertEqual(resultado['agregados'], ['Rodamiento piloto'])
        self.assertTrue(resultado['busqueda_web'])
        mock_disparo.assert_called_once()
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.metadata.get('busqueda_web_estado'), 'pendiente')

    def test_rechaza_si_no_hay_nada_que_cotizar(self):
        with self.assertRaises(ValueError):
            cotizar_items_faltantes(self.cot, nombres=['repuesto'])

    def test_rechaza_si_no_es_editable(self):
        self.cot.estado = 'enviada'
        self.cot.save(update_fields=['estado'])
        with self.assertRaises(ValueError):
            cotizar_items_faltantes(self.cot, nombres=['Filtro de aceite'])

        self.cot.estado = 'cancelada'
        self.cot.save(update_fields=['estado'])
        with self.assertRaises(ValueError):
            cotizar_items_faltantes(self.cot, nombres=['Filtro de aceite'])


@override_settings(BUSQUEDA_WEB_REPUESTOS_ENABLED=False)
class CotizarItemsIaAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taller_items_api', password='test123')
        self.taller = Taller.objects.create(
            usuario=self.user,
            nombre='Taller API Items',
            telefono='900000098',
            estado_verificacion='aprobado',
        )
        self.cot = CotizacionCanal.objects.create(
            es_libre=True,
            taller=self.taller,
            creado_por=self.user,
            estado='borrador',
            modalidad='taller',
            vehiculo_marca='Fiat',
            vehiculo_modelo='Bravo',
            servicio_nombre='Mantención',
            mano_obra_clp=40000,
            total_clp=40000,
            repuestos=[],
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch(
        'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes.enriquecer_repuestos_cotizacion',
        side_effect=lambda reps, **_k: [
            {
                **r,
                'precio_unitario_clp': 8900,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'AutoPlanet',
                'url_producto': 'https://www.autoplanet.cl/p/1',
                'precio_referencia_mercado': True,
                'precio_estimado': True,
            }
            for r in reps
        ],
    )
    def test_endpoint_agrega_y_devuelve_fuente(self, _mock_enrich):
        resp = self.client.post(
            f'/api/ordenes/cotizaciones-canal/{self.cot.id}/cotizar-items/',
            {'nombres': ['Filtro de aceite']},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['agregados'], ['Filtro de aceite'])
        reps = data['cotizacion']['repuestos']
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]['precio_unitario_clp'], 8900)
        self.assertEqual(reps[0]['fuente_marketplace'], 'web')
        self.assertEqual(reps[0]['proveedor_nombre'], 'AutoPlanet')

    @patch(
        'mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes.enriquecer_repuestos_cotizacion',
        side_effect=lambda reps, **_k: [
            {
                **r,
                'precio_unitario_clp': 8900,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'AutoPlanet',
                'url_producto': 'https://www.autoplanet.cl/p/1',
                'precio_referencia_mercado': True,
                'precio_estimado': True,
            }
            for r in reps
        ],
    )
    def test_endpoint_reabre_enviada_y_agrega(self, _mock_enrich):
        self.cot.estado = 'enviada'
        self.cot.token = 'tok-enviada-items'
        self.cot.save(update_fields=['estado', 'token'])
        resp = self.client.post(
            f'/api/ordenes/cotizaciones-canal/{self.cot.id}/cotizar-items/',
            {'nombres': ['Filtro de aceite']},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['agregados'], ['Filtro de aceite'])
        self.cot.refresh_from_db()
        self.assertEqual(self.cot.estado, 'borrador')
        self.assertEqual(self.cot.token, 'tok-enviada-items')

    def test_endpoint_rechaza_aceptada_con_horario(self):
        from datetime import date, time

        from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

        self.cot.estado = 'aceptada'
        self.cot.save(update_fields=['estado'])
        CitaAgendaPersonal.objects.create(
            taller=self.taller,
            cotizacion_canal_origen=self.cot,
            fecha_servicio=date(2030, 8, 12),
            hora_servicio=time(10, 0),
            duracion_minutos=60,
            tipo_servicio='taller',
            estado='activa',
            horario_por_confirmar=False,
            creado_por=self.user,
        )
        resp = self.client.post(
            f'/api/ordenes/cotizaciones-canal/{self.cot.id}/cotizar-items/',
            {'nombres': ['Filtro de aceite']},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_enviada_reabre_y_agrega_item_manual(self):
        self.cot.estado = 'enviada'
        self.cot.token = 'tok-patch-enviada'
        self.cot.save(update_fields=['estado', 'token'])
        resp = self.client.patch(
            f'/api/ordenes/cotizaciones-canal/{self.cot.id}/',
            {
                'repuestos': [
                    {
                        'nombre': 'Filtro de aceite',
                        'cantidad': 1,
                        'precio_unitario_clp': 15000,
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['estado'], 'borrador')
        self.assertEqual(data['token'], 'tok-patch-enviada')
        self.assertTrue(data['permite_edicion_completa'])
        self.assertEqual(len(data['repuestos']), 1)
        self.assertEqual(data['repuestos'][0]['precio_unitario_clp'], 15000)
        self.assertEqual(int(data['total_clp']), 55000)


class FusionarRepuestosEdicionTests(TestCase):
    def test_conserva_enriquecimiento_web_si_el_patch_trae_precio_vacio(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            fusionar_repuestos_edicion,
        )

        actuales = [
            {
                'id': 'rep-1',
                'nombre': 'Filtro de aceite',
                'precio_unitario_clp': 8900,
                'fuente_marketplace': 'web',
                'proveedor_nombre': 'AutoPlanet',
                'url_producto': 'https://www.autoplanet.cl/p/1',
            },
        ]
        incoming = [
            {
                'id': 'rep-1',
                'nombre': 'Filtro de aceite Mann',
                'precio_unitario_clp': 0,
            },
        ]
        out = fusionar_repuestos_edicion(actuales, incoming)
        self.assertEqual(out[0]['nombre'], 'Filtro de aceite Mann')
        self.assertEqual(out[0]['precio_unitario_clp'], 8900)
        self.assertEqual(out[0]['fuente_marketplace'], 'web')
        self.assertEqual(out[0]['proveedor_nombre'], 'AutoPlanet')

    def test_no_bloquea_item_nuevo_del_patch(self):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            fusionar_repuestos_edicion,
        )

        actuales = [{'id': 'rep-1', 'nombre': 'Kit', 'precio_unitario_clp': 100}]
        incoming = [
            {'id': 'rep-1', 'nombre': 'Kit', 'precio_unitario_clp': 100},
            {'id': 'rep-2', 'nombre': 'Filtro', 'precio_unitario_clp': 0},
        ]
        out = fusionar_repuestos_edicion(actuales, incoming)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]['id'], 'rep-2')


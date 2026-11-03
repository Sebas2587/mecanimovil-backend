"""
Tests para verificar que buscar_oferta_exacta prioriza ofertas
específicas por marca/modelo sobre las genéricas.
"""
from django.test import TestCase

from mecanimovilapp.apps.ordenes.services.catalogo_pricing import buscar_oferta_exacta
from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import Taller, Usuario
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo


class BuscarOfertaEspecificaPorModeloTestCase(TestCase):
    """Test: buscar_oferta_exacta prioriza ofertas específicas por modelo."""

    def test_prioriza_modelo_especifico_sobre_generico(self):
        """Test: Si hay oferta específica para modelo y genérica, devuelve la específica."""
        user = Usuario.objects.create_user(username='testuser', email='test1@test.com', password='test123')
        taller = Taller.objects.create(
            nombre='Taller Test',
            usuario=user,
            telefono='900000001',
            estado_verificacion='aprobado',
        )
        marca = Marca.objects.create(nombre='Toyota')
        modelo = Modelo.objects.create(nombre='Corolla', marca=marca)
        servicio = Servicio.objects.create(nombre='Cambio de Aceite')

        # Crear oferta genérica (sin marca/modelo)
        oferta_generica = OfertaServicio.objects.create(
            taller=taller,
            servicio=servicio,
            tipo_proveedor='taller',
            marca_vehiculo_seleccionada=None,
            modelo_vehiculo_seleccionado=None,
            precio_sin_repuestos=25000,
            precio_con_repuestos=45000,
            disponible=True,
        )

        # Crear oferta específica para Toyota Corolla
        oferta_especifica = OfertaServicio.objects.create(
            taller=taller,
            servicio=servicio,
            tipo_proveedor='taller',
            marca_vehiculo_seleccionada=marca,
            modelo_vehiculo_seleccionado=modelo,
            precio_sin_repuestos=30000,
            precio_con_repuestos=50000,
            disponible=True,
        )

        # Buscar oferta para Toyota Corolla
        resultado = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre='Cambio de Aceite',
            marca='Toyota',
            modelo='Corolla',
        )

        # Debe devolver la específica, no la genérica
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.id, oferta_especifica.id)
        self.assertEqual(resultado.precio_sin_repuestos, 30000)

    def test_fallback_a_generico_cuando_no_hay_especifico(self):
        """Test: Si no hay oferta específica, devuelve la genérica."""
        user = Usuario.objects.create_user(username='testuser2', email='test2@test.com', password='test123')
        taller = Taller.objects.create(
            nombre='Taller Test 2',
            usuario=user,
            telefono='900000002',
            estado_verificacion='aprobado',
        )
        servicio = Servicio.objects.create(nombre='Cambio de Aceite 2')

        # Solo crear oferta genérica
        oferta_generica = OfertaServicio.objects.create(
            taller=taller,
            servicio=servicio,
            tipo_proveedor='taller',
            marca_vehiculo_seleccionada=None,
            modelo_vehiculo_seleccionado=None,
            precio_sin_repuestos=25000,
            precio_con_repuestos=45000,
            disponible=True,
        )

        # Buscar oferta para Toyota Corolla (que no existe)
        resultado = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre='Cambio de Aceite',
            marca='Toyota',
            modelo='Corolla',
        )

        # Debe devolver la genérica como fallback
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.id, oferta_generica.id)
        self.assertEqual(resultado.precio_sin_repuestos, 25000)

    def test_no_devuelve_oferta_de_otro_modelo(self):
        """Test: No devuelve oferta específica de OTRO modelo cuando hay cliente con datos."""
        user = Usuario.objects.create_user(username='testuser3', email='test3@test.com', password='test123')
        taller = Taller.objects.create(
            nombre='Taller Test 3',
            usuario=user,
            telefono='900000003',
            estado_verificacion='aprobado',
        )
        marca = Marca.objects.create(nombre='Toyota 2')
        modelo_corolla = Modelo.objects.create(nombre='Corolla 2', marca=marca)
        modelo_yaris = Modelo.objects.create(nombre='Yaris', marca=marca)
        servicio = Servicio.objects.create(nombre='Cambio de Aceite 3')

        # Crear oferta específica para Toyota Yaris
        oferta_yaris = OfertaServicio.objects.create(
            taller=taller,
            servicio=servicio,
            tipo_proveedor='taller',
            marca_vehiculo_seleccionada=marca,
            modelo_vehiculo_seleccionado=modelo_yaris,
            precio_sin_repuestos=28000,
            precio_con_repuestos=48000,
            disponible=True,
        )

        # Buscar oferta para Toyota Corolla (debe ser None o fallback genérico)
        resultado = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre='Cambio de Aceite',
            marca='Toyota',
            modelo='Corolla',
        )

        # No debe devolver la oferta de Yaris
        if resultado:
            self.assertNotEqual(resultado.id, oferta_yaris.id)

    def test_prioriza_marca_modelo_sobre_solo_marca(self):
        """Test: Oferta con marca+modelo tiene prioridad sobre solo marca."""
        user = Usuario.objects.create_user(username='testuser4', email='test4@test.com', password='test123')
        taller = Taller.objects.create(
            nombre='Taller Test 4',
            usuario=user,
            telefono='900000004',
            estado_verificacion='aprobado',
        )
        marca = Marca.objects.create(nombre='Toyota 3')
        modelo = Modelo.objects.create(nombre='Corolla 3', marca=marca)
        servicio = Servicio.objects.create(nombre='Cambio de Aceite 4')

        # Crear oferta para toda la marca Toyota
        oferta_marca = OfertaServicio.objects.create(
            taller=taller,
            servicio=servicio,
            tipo_proveedor='taller',
            marca_vehiculo_seleccionada=marca,
            modelo_vehiculo_seleccionado=None,
            precio_sin_repuestos=27000,
            precio_con_repuestos=47000,
            disponible=True,
        )

        # Crear oferta específica para Toyota Corolla
        oferta_modelo = OfertaServicio.objects.create(
            taller=taller,
            servicio=servicio,
            tipo_proveedor='taller',
            marca_vehiculo_seleccionada=marca,
            modelo_vehiculo_seleccionado=modelo,
            precio_sin_repuestos=30000,
            precio_con_repuestos=50000,
            disponible=True,
        )

        # Buscar oferta para Toyota Corolla
        resultado = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre='Cambio de Aceite',
            marca='Toyota',
            modelo='Corolla',
        )

        # Debe devolver la de marca+modelo, no solo marca
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.id, oferta_modelo.id)
        self.assertEqual(resultado.precio_sin_repuestos, 30000)

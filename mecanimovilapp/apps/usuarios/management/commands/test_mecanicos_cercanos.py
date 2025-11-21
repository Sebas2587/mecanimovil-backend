from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo


class Command(BaseCommand):
    help = 'Probar funcionalidad de mecánicos a domicilio cercanos'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== PROBANDO MECÁNICOS CERCANOS ==='))
        
        # Coordenadas de prueba (Santiago centro)
        user_lat = -33.4679
        user_lng = -70.6738
        user_location = Point(user_lng, user_lat, srid=4326)
        
        self.stdout.write(f'📍 Ubicación del usuario: {user_lat}, {user_lng}')
        
        # 1. Listar todos los mecánicos a domicilio
        self.stdout.write('\n1. MECÁNICOS A DOMICILIO EN BASE DE DATOS:')
        mecanicos = MecanicoDomicilio.objects.all()
        
        for m in mecanicos:
            self.stdout.write(f'   ID: {m.id} | {m.nombre}')
            self.stdout.write(f'   Ubicación: {m.ubicacion}')
            self.stdout.write(f'   Dirección: {m.direccion}')
            self.stdout.write(f'   Verificado: {m.verificado} | Activo: {m.activo}')
            
            if m.marcas_atendidas.exists():
                marcas = [marca.nombre for marca in m.marcas_atendidas.all()]
                self.stdout.write(f'   Marcas: {", ".join(marcas)}')
            self.stdout.write('')
        
        # 2. Consulta cercanos sin filtro de marca
        self.stdout.write('2. MECÁNICOS CERCANOS (sin filtro de marca):')
        mecanicosCercanos = MecanicoDomicilio.objects.filter(
            verificado=True,
            activo=True,
            ubicacion__isnull=False
        ).annotate(
            distance=Distance('ubicacion', user_location)
        ).filter(
            ubicacion__distance_lte=(user_location, D(km=10))
        ).order_by('distance')
        
        for m in mecanicosCercanos:
            self.stdout.write(f'   {m.nombre} - {m.distance.km:.2f}km')
            self.stdout.write(f'   Dirección: {m.direccion}')
            marcas = [marca.nombre for marca in m.marcas_atendidas.all()]
            self.stdout.write(f'   Marcas: {", ".join(marcas)}')
            self.stdout.write('')
        
        # 3. Probar con filtro por marca Ford (ID: 6)
        self.stdout.write('3. MECÁNICOS CERCANOS (filtro marca Ford - ID: 6):')
        mecanicosFord = MecanicoDomicilio.objects.filter(
            verificado=True,
            activo=True,
            ubicacion__isnull=False,
            marcas_atendidas__id=6
        ).annotate(
            distance=Distance('ubicacion', user_location)
        ).filter(
            ubicacion__distance_lte=(user_location, D(km=10))
        ).order_by('distance')
        
        for m in mecanicosFord:
            self.stdout.write(f'   {m.nombre} - {m.distance.km:.2f}km (especialista en Ford)')
            self.stdout.write(f'   Dirección: {m.direccion}')
            self.stdout.write('')
        
        # 4. Obtener vehículos de un cliente específico
        self.stdout.write('4. VEHÍCULOS DE CLIENTES:')
        try:
            # Buscar cliente con vehículos
            cliente = Cliente.objects.filter(vehiculos__isnull=False).first()
            if cliente:
                self.stdout.write(f'   Cliente: {cliente.nombre} {cliente.apellido}')
                vehiculos = Vehiculo.objects.filter(cliente_detail=cliente)
                for v in vehiculos:
                    self.stdout.write(f'   Vehículo: {v.marca_nombre} {v.modelo_nombre} (marca_id: {v.marca})')
                    
                    # Buscar mecánicos para esta marca específica
                    mecanicosMarca = MecanicoDomicilio.objects.filter(
                        verificado=True,
                        activo=True,
                        ubicacion__isnull=False,
                        marcas_atendidas__id=v.marca
                    ).annotate(
                        distance=Distance('ubicacion', user_location)
                    ).filter(
                        ubicacion__distance_lte=(user_location, D(km=10))
                    ).order_by('distance')
                    
                    self.stdout.write(f'   Mecánicos para {v.marca_nombre}:')
                    for m in mecanicosMarca:
                        self.stdout.write(f'     - {m.nombre} ({m.distance.km:.2f}km)')
            else:
                self.stdout.write('   No se encontraron clientes con vehículos')
        except Exception as e:
            self.stdout.write(f'   Error: {e}')
        
        self.stdout.write(self.style.SUCCESS('\n✅ Prueba completada')) 
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud, ReglaMantenimientoGenerica

class Command(BaseCommand):
    help = 'Inicializa el sistema Smart Health con componentes maestros y reglas base'

    def handle(self, *args, **options):
        self.stdout.write("🔧 Inicializando Smart Health System...")
        
        # 1. Definición del Catálogo Maestro
        catalog = [
            # Básico
            {'nombre': 'Aceite Motor', 'slug': 'oil', 'es_critico': True, 'icono': 'water'},
            {'nombre': 'Filtro de Aire', 'slug': 'air-filter', 'es_critico': False, 'icono': 'filter'},
            {'nombre': 'Filtro de Aceite', 'slug': 'oil-filter', 'es_critico': True, 'icono': 'filter'},
            {'nombre': 'Filtro de Cabina', 'slug': 'cabin-filter', 'es_critico': False, 'icono': 'snow'},
            
            # Encendido / Motor
            {'nombre': 'Bujías', 'slug': 'spark-plug', 'es_critico': True, 'icono': 'flash'},
            {'nombre': 'Correa de Distribución', 'slug': 'timing-belt', 'es_critico': True, 'icono': 'sync'},
            
            # Frenos
            {'nombre': 'Pastillas de Freno', 'slug': 'brakes', 'es_critico': True, 'icono': 'disc'},
            {'nombre': 'Discos de Freno', 'slug': 'brake-discs', 'es_critico': True, 'icono': 'disc'},
            {'nombre': 'Líquido de Frenos', 'slug': 'brake-fluid', 'es_critico': True, 'icono': 'water'},
            
            # Diesel
            {'nombre': 'DPF (Filtro Partículas)', 'slug': 'exhaust', 'es_critico': True, 'icono': 'cloud-done'},
            {'nombre': 'AdBlue', 'slug': 'adblue', 'es_critico': False, 'icono': 'water'},
            
            # General
            {'nombre': 'Batería', 'slug': 'battery', 'es_critico': True, 'icono': 'battery-charging'},
            {'nombre': 'Neumáticos', 'slug': 'tires', 'es_critico': True, 'icono': 'radio-button-on'},
            {'nombre': 'Amortiguadores', 'slug': 'shocks', 'es_critico': False, 'icono': 'move'},
            {'nombre': 'Refrigerante', 'slug': 'coolant', 'es_critico': True, 'icono': 'thermometer'},
        ]
        
        components_map = {}
        for item in catalog:
            comp, created = ComponenteSalud.objects.get_or_create(
                slug=item['slug'],
                defaults={'nombre': item['nombre'], 'es_critico': item['es_critico'], 'icono': item['icono']}
            )
            components_map[item['slug']] = comp
            if created:
                self.stdout.write(f"  - Componente creado: {item['nombre']}")
            else:
                self.stdout.write(f"  - Componente existente: {item['nombre']}")

        # 2. Reglas Genéricas (Nivel 2)
        # Formato: (slug_componente, tipo_motor, vida_util_km, beta)
        rules = [
            # GASOLINA
            ('oil', 'GASOLINA', 10000, 2.5),          # Aceite cada 10k
            ('oil-filter', 'GASOLINA', 10000, 3.0),   # Filtro Aceite cada 10k
            ('air-filter', 'GASOLINA', 20000, 2.0),   # Aire cada 20k
            ('spark-plug', 'GASOLINA', 40000, 3.0),   # Bujías cada 40k
            ('brakes', 'GASOLINA', 30000, 2.2),       # Pastillas cada 30k
            ('brake-discs', 'GASOLINA', 80000, 2.0),  # Discos cada 80k
            ('timing-belt', 'GASOLINA', 80000, 5.0),  # Correa cada 80k (falla abrupta -> beta alto)
            ('battery', 'GASOLINA', 50000, 3.0),      # Bateria ~2-3 años
            ('tires', 'GASOLINA', 45000, 2.0),        # Neumaticos 45k
            ('coolant', 'GASOLINA', 40000, 2.5),      # Refrigerante 40k
            ('brake-fluid', 'GASOLINA', 40000, 2.0),  # Liquido frenos 40k

            # DIESEL
            ('oil', 'DIESEL', 10000, 2.5),
            ('oil-filter', 'DIESEL', 10000, 3.0),
            ('air-filter', 'DIESEL', 15000, 2.0),     # Aire se ensucia mas rapido
            ('brakes', 'DIESEL', 30000, 2.2),
            ('exhaust', 'DIESEL', 80000, 3.0),        # DPF cada 80k
            ('adblue', 'DIESEL', 15000, 1.5),         # AdBlue
            ('timing-belt', 'DIESEL', 100000, 5.0),
            ('battery', 'DIESEL', 60000, 3.0),        # Bateria dura mas en diesel modernos? Igual.
            ('tires', 'DIESEL', 40000, 2.0),          # Mayor torque, mas desgaste?

            # ELECTRICO
            ('cabin-filter', 'ELECTRICO', 20000, 2.0),
            ('brakes', 'ELECTRICO', 50000, 2.2),      # Regenerativo gasta menos freno
            ('brake-fluid', 'ELECTRICO', 50000, 2.0),
            ('tires', 'ELECTRICO', 35000, 2.0),       # Mas peso y torque instantaneo -> mas desgaste
            ('battery', 'ELECTRICO', 150000, 2.0),    # Vida de batería HV (referencial para 12v?) Asumamos 12v aqui.
            # Bateria HV usualmente no es mantenible por usuario promedio. Bateria 12v si.
            
            # HIBRIDO
            ('oil', 'HIBRIDO', 15000, 2.5),           # Motor usa menos -> dura mas
            ('spark-plug', 'HIBRIDO', 60000, 3.0),
            ('brakes', 'HIBRIDO', 50000, 2.2),
            ('battery', 'HIBRIDO', 60000, 3.0),
        ]

        for slug, motor, eta, beta in rules:
            if slug not in components_map:
                continue
            
            comp = components_map[slug]
            ReglaMantenimientoGenerica.objects.update_or_create(
                componente=comp,
                tipo_motor=motor,
                defaults={
                    'vida_util_km': eta,
                    'beta': beta
                }
            )
            self.stdout.write(f"  - Regla Genérica: {comp.nombre} ({motor}) -> {eta}km")

        self.stdout.write(self.style.SUCCESS("✅ Sistema Smart Health inicializado correctamente"))

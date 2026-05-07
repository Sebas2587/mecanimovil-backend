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
        # Formato: (slug, tipo_motor, vida_util_km, beta, intervalo_meses, meses_critico)
        #
        # Criterios de vida útil (revisados):
        #   Pastillas freno: 15.000–20.000 km conducción mixta urbana/autopista.
        #     El prior de 30k era excesivamente optimista (escenario autopista puro).
        #   Discos freno: 40.000–60.000 km (antes 80k). Se adicionan 36 meses como
        #     intervalo de inspección mínima independientemente del km.
        #   Neumáticos: 40.000 km + 5 años máximo (el engine aplica el age_cap por goma).
        #   Correa distribución: 80.000–100.000 km + 7 años (age_cap independiente).
        #   Líquido frenos: componente higroscópico → 2 años / 40.000 km.
        rules = [
            # slug               motor      km      beta  meses  meses_crit
            # ── GASOLINA ──────────────────────────────────────────────────
            ('oil',          'GASOLINA', 10000,  2.5,  6,   12),
            ('oil-filter',   'GASOLINA', 10000,  3.0,  6,   12),
            ('air-filter',   'GASOLINA', 20000,  2.0, 12,   24),
            ('cabin-filter', 'GASOLINA', 20000,  2.0, 12,   24),
            ('spark-plug',   'GASOLINA', 40000,  3.0, 24,   48),
            ('brakes',       'GASOLINA', 18000,  2.5, 18,   30),  # 18k km / 18 meses
            ('brake-discs',  'GASOLINA', 50000,  2.0, 36,   60),  # 50k km / 3 años inspección
            ('timing-belt',  'GASOLINA', 80000,  5.0, 60,   84),  # 80k km / 5 años, crit 7 años
            ('battery',      'GASOLINA', 50000,  3.0, 36,   54),
            ('tires',        'GASOLINA', 40000,  2.0, 36,   60),  # age_cap independiente
            ('coolant',      'GASOLINA', 40000,  2.5, 24,   48),
            ('brake-fluid',  'GASOLINA', 40000,  2.0, 24,   36),  # higroscópico: 2 años
            ('shocks',       'GASOLINA', 80000,  2.0, 48,   96),

            # ── DIESEL ────────────────────────────────────────────────────
            ('oil',          'DIESEL',  10000,  2.5,  6,   12),
            ('oil-filter',   'DIESEL',  10000,  3.0,  6,   12),
            ('air-filter',   'DIESEL',  15000,  2.0, 12,   24),
            ('brakes',       'DIESEL',  18000,  2.5, 18,   30),
            ('brake-discs',  'DIESEL',  50000,  2.0, 36,   60),
            ('exhaust',      'DIESEL',  80000,  3.0, 48,   72),
            ('adblue',       'DIESEL',  15000,  1.5,  6,   12),
            ('timing-belt',  'DIESEL', 100000,  5.0, 72,   96),
            ('battery',      'DIESEL',  60000,  3.0, 36,   54),
            ('tires',        'DIESEL',  40000,  2.0, 36,   60),
            ('coolant',      'DIESEL',  40000,  2.5, 24,   48),
            ('brake-fluid',  'DIESEL',  40000,  2.0, 24,   36),

            # ── ELÉCTRICO ─────────────────────────────────────────────────
            ('cabin-filter', 'ELECTRICO', 20000, 2.0, 12,   24),
            ('brakes',       'ELECTRICO', 50000, 2.2, 36,   60),  # freno regenerativo
            ('brake-fluid',  'ELECTRICO', 50000, 2.0, 24,   36),
            ('tires',        'ELECTRICO', 35000, 2.0, 36,   60),  # más peso → más desgaste
            ('battery',      'ELECTRICO',150000, 2.0, 60,   96),

            # ── HÍBRIDO ───────────────────────────────────────────────────
            ('oil',          'HIBRIDO',  15000, 2.5, 12,   18),
            ('spark-plug',   'HIBRIDO',  60000, 3.0, 36,   60),
            ('brakes',       'HIBRIDO',  50000, 2.2, 36,   60),
            ('battery',      'HIBRIDO',  60000, 3.0, 36,   54),
            ('tires',        'HIBRIDO',  40000, 2.0, 36,   60),
            ('brake-fluid',  'HIBRIDO',  40000, 2.0, 24,   36),
        ]

        for slug, motor, eta, beta, intervalo_meses, meses_critico in rules:
            if slug not in components_map:
                continue

            comp = components_map[slug]
            ReglaMantenimientoGenerica.objects.update_or_create(
                componente=comp,
                tipo_motor=motor,
                defaults={
                    'vida_util_km':    eta,
                    'beta':            beta,
                    'intervalo_meses': intervalo_meses,
                    'meses_critico':   meses_critico,
                }
            )
            self.stdout.write(
                f"  - Regla Genérica: {comp.nombre} ({motor}) -> "
                f"{eta:,} km / {intervalo_meses} meses"
            )

        self.stdout.write(self.style.SUCCESS("✅ Sistema Smart Health inicializado correctamente"))

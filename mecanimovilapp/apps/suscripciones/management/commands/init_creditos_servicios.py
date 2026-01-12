"""
Comando de management para inicializar configuración de créditos por servicio.
Ejecutar: python manage.py init_creditos_servicios
"""
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.suscripciones.models import ConfiguracionCreditosServicio
from mecanimovilapp.apps.servicios.models import Servicio


class Command(BaseCommand):
    help = 'Inicializa la configuración de créditos por servicio con valores por defecto'

    def handle(self, *args, **options):
        self.stdout.write('Inicializando configuración de créditos por servicio...')
        
        # Mapeo de servicios comunes con sus créditos
        # Basado en complejidad: Baja=2, Media=3, Alta=4
        creditos_por_servicio = {
            # Servicios de baja complejidad (2 créditos)
            'cambio de aceite': 2,
            'cambio de filtro de aceite': 2,
            'cambio de filtro de aire': 2,
            'revisión general': 2,
            'alineación': 2,
            'balanceo': 2,
            
            # Servicios de complejidad media (3 créditos)
            'cambio de frenos': 3,
            'cambio de pastillas de freno': 3,
            'cambio de discos de freno': 3,
            'cambio de amortiguadores': 3,
            'cambio de bujías': 3,
            'cambio de correa de distribución': 3,
            'cambio de batería': 3,
            'reparación de sistema eléctrico': 3,
            
            # Servicios de alta complejidad (4 créditos)
            'cambio de embrague': 4,
            'reparación de motor': 4,
            'reparación de transmisión': 4,
            'cambio de caja de cambios': 4,
            'reparación de sistema de refrigeración': 4,
            'reparación de sistema de dirección': 4,
        }
        
        servicios_creados = 0
        servicios_actualizados = 0
        
        # Obtener todos los servicios
        servicios = Servicio.objects.all()
        
        for servicio in servicios:
            # Buscar coincidencia en el mapeo (case insensitive)
            nombre_lower = servicio.nombre.lower()
            creditos = None
            
            # Buscar coincidencia exacta o parcial
            for key, value in creditos_por_servicio.items():
                if key in nombre_lower or nombre_lower in key:
                    creditos = value
                    break
            
            # Si no hay coincidencia, usar valor por defecto (2 créditos)
            if creditos is None:
                creditos = 2
            
            # Crear o actualizar configuración
            config, created = ConfiguracionCreditosServicio.objects.get_or_create(
                servicio=servicio,
                defaults={
                    'creditos_requeridos': creditos,
                    'activo': True
                }
            )
            
            if created:
                servicios_creados += 1
                self.stdout.write(
                    f'✓ Configuración creada para "{servicio.nombre}": {creditos} créditos'
                )
            else:
                # Actualizar si ya existe pero con valor diferente
                if config.creditos_requeridos != creditos:
                    config.creditos_requeridos = creditos
                    config.activo = True
                    config.save()
                    servicios_actualizados += 1
                    self.stdout.write(
                        f'✓ Configuración actualizada para "{servicio.nombre}": {creditos} créditos'
                    )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Configuración de créditos por servicio completada:\n'
                f'  - Servicios configurados: {servicios_creados}\n'
                f'  - Servicios actualizados: {servicios_actualizados}\n'
                f'  - Total de servicios: {servicios.count()}'
            )
        )


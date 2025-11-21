from django.core.management.base import BaseCommand
from mecanimovilapp.apps.personalizacion.models import ConfiguracionPersonalizacion


class Command(BaseCommand):
    help = 'Configura las configuraciones iniciales del sistema de personalización'

    def handle(self, *args, **options):
        configuraciones_default = {
            'dias_expiracion_recomendaciones': '30',
            'max_recomendaciones_mantenimiento': '5',
            'max_recomendaciones_proveedores': '10',
            'max_recomendaciones_servicios_populares': '8',
            'umbral_score_minimo': '0.3',
            'peso_calificacion_proveedor': '0.4',
            'peso_historial_usuario': '0.3',
            'peso_popularidad_servicio': '0.3',
            'intervalo_actualizacion_perfiles': '24',  # horas
            'km_umbral_mantenimiento_urgente': '10000',
            'dias_umbral_mantenimiento_urgente': '180',
        }

        configuraciones_creadas = 0
        configuraciones_actualizadas = 0

        for clave, valor in configuraciones_default.items():
            config, created = ConfiguracionPersonalizacion.objects.get_or_create(
                clave=clave,
                defaults={
                    'valor': valor,
                    'descripcion': self._get_descripcion(clave)
                }
            )
            
            if created:
                configuraciones_creadas += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Configuración creada: {clave} = {valor}')
                )
            else:
                configuraciones_actualizadas += 1
                self.stdout.write(
                    self.style.WARNING(f'Configuración existente: {clave} = {config.valor}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Proceso completado. Creadas: {configuraciones_creadas}, '
                f'Existentes: {configuraciones_actualizadas}'
            )
        )

    def _get_descripcion(self, clave):
        descripciones = {
            'dias_expiracion_recomendaciones': 'Días después de los cuales las recomendaciones expiran',
            'max_recomendaciones_mantenimiento': 'Número máximo de recomendaciones de mantenimiento a mostrar',
            'max_recomendaciones_proveedores': 'Número máximo de proveedores recomendados a mostrar',
            'max_recomendaciones_servicios_populares': 'Número máximo de servicios populares a mostrar',
            'umbral_score_minimo': 'Score mínimo para que una recomendación sea considerada relevante',
            'peso_calificacion_proveedor': 'Peso de la calificación del proveedor en el score final',
            'peso_historial_usuario': 'Peso del historial del usuario en el score final',
            'peso_popularidad_servicio': 'Peso de la popularidad del servicio en el score final',
            'intervalo_actualizacion_perfiles': 'Intervalo en horas para actualizar perfiles de vehículos',
            'km_umbral_mantenimiento_urgente': 'Kilometraje umbral para considerar mantenimiento urgente',
            'dias_umbral_mantenimiento_urgente': 'Días umbral para considerar mantenimiento urgente',
        }
        return descripciones.get(clave, 'Configuración del sistema de personalización') 
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.checklists.models import ChecklistItemCatalog


class Command(BaseCommand):
    help = 'Poblar el catálogo de items de checklist con datos iniciales'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🚀 Iniciando población del catálogo de checklists...'))

        # Items del catálogo predefinidos
        items_catalogo = [
            {
                'nombre': 'Identificación del Técnico',
                'categoria': 'INFORMACION_GENERAL',
                'tipo_pregunta': 'TEXT',
                'pregunta_texto': 'Nombre completo del técnico responsable',
                'descripcion_ayuda': 'Ingrese el nombre completo del técnico que realizará el servicio',
                'placeholder': 'Ej: Juan Pérez García',
                'es_obligatorio_por_defecto': True,
                'uso_frecuente': True,
                'activo': True
            },
            {
                'nombre': 'Fecha y Hora de Inicio',
                'categoria': 'INFORMACION_GENERAL',
                'tipo_pregunta': 'DATETIME',
                'pregunta_texto': '¿Cuándo se inicia el servicio?',
                'descripcion_ayuda': 'Registre la fecha y hora exacta de inicio del servicio',
                'es_obligatorio_por_defecto': True,
                'uso_frecuente': True,
                'activo': True
            },
            {
                'nombre': 'Kilometraje Actual',
                'categoria': 'DATOS_VEHICULO',
                'tipo_pregunta': 'KILOMETER_INPUT',
                'pregunta_texto': '¿Cuál es el kilometraje actual del vehículo?',
                'descripcion_ayuda': 'Registre el kilometraje que muestra el odómetro del vehículo',
                'placeholder': 'Ej: 85,450',
                'valor_minimo': 0,
                'valor_maximo': 999999,
                'es_obligatorio_por_defecto': True,
                'uso_frecuente': True,
                'activo': True
            },
            {
                'nombre': 'Estado del Sistema Eléctrico',
                'categoria': 'SISTEMA_ELECTRICO',
                'tipo_pregunta': 'SELECT',
                'pregunta_texto': '¿Cuál es el estado general del sistema eléctrico?',
                'descripcion_ayuda': 'Evalúe el funcionamiento de luces, batería, alternador y demás componentes eléctricos',
                'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Malo', 'Crítico'],
                'es_obligatorio_por_defecto': False,
                'uso_frecuente': True,
                'activo': True
            },
            {
                'nombre': 'Firma del Técnico',
                'categoria': 'FIRMAS_CONFORMIDAD',
                'tipo_pregunta': 'SIGNATURE',
                'pregunta_texto': 'Firma del técnico responsable',
                'descripcion_ayuda': 'Firma digital del técnico que realizó la inspección',
                'es_obligatorio_por_defecto': True,
                'uso_frecuente': True,
                'activo': True
            },
        ]

        # Crear items del catálogo
        created_count = 0
        for item_data in items_catalogo:
            item, created = ChecklistItemCatalog.objects.get_or_create(
                nombre=item_data['nombre'],
                categoria=item_data['categoria'],
                defaults=item_data
            )
            if created:
                created_count += 1
                self.stdout.write(f"✅ Creado: {item.nombre}")
            else:
                self.stdout.write(f"⏭️  Ya existe: {item.nombre}")

        self.stdout.write(
            self.style.SUCCESS(
                f'\n🎉 ¡Población completada! '
                f'Se crearon {created_count} nuevos items del catálogo. '
                f'Total items en catálogo: {ChecklistItemCatalog.objects.count()}'
            )
        )

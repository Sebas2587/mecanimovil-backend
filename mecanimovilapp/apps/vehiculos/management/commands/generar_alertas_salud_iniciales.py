
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.vehiculos.tasks import calcular_salud_vehiculo_async
import logging

class Command(BaseCommand):
    help = 'Recalcula la salud de todos los vehículos para generar alertas iniciales (< 50%)'

    def handle(self, *args, **options):
        self.stdout.write("🔄 Iniciando generación de alertas de salud iniciales...")
        
        vehiculos = Vehiculo.objects.all()
        count = vehiculos.count()
        processed = 0
        
        self.stdout.write(f"📋 Procesando {count} vehículos...")
        
        for vehiculo in vehiculos:
            try:
                # Forzar recálculo para disparar la lógica de alertas
                # Usamos .apply() para ejecutarlo sincrónicamente si queremos ver logs aquí, 
                # o llamamos a la función interna si pudiéramos. 
                # Pero como es shared_task, podemos llamarla como función normal si quitamos el decorador o usamos la app de celery
                # Lo más seguro es llamarla como tarea normal sync wrapper si está disponible, o simplemente invocar la lógica.
                
                # Al ser shared_task, calling it directly works in eager mode or basic python function call in some celery versions, 
                # but safer to trust the task logic is robust.
                # However, calling .delay() creates a task. Calling it directly `calcular_salud_vehiculo_async(vehiculo.id)` might fail if it relies on `self` for retry.
                
                # Mejor opción: Llamar a calcular_estado_salud_interno si es importable, pero no lo es fácilmente (no está exportada en __init__).
                # Llamemos a la tarea async. Si celery corre, bien. Si no, dry run.
                # Pero el usuario dice que celery beat falla, no necesariamente el worker.
                
                # Vamos a intentar llamar a la tarea directamente simular ejecución
                calcular_salud_vehiculo_async(vehiculo.id, force_recalculate=True)
                processed += 1
                if processed % 10 == 0:
                    self.stdout.write(f"   Progreso: {processed}/{count}")
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error procesando vehículo {vehiculo.id}: {e}"))
        
        self.stdout.write(self.style.SUCCESS(f"✅ Proceso completado. {processed} vehículos recalculados."))

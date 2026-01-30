import os
import django
import sys

# Configurar Django
sys.path.append('/Users/sebastianm/Documents/apps/app-mecanimovil 11-05-2025/mecanimovil-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.usuarios.models import Resena, Review, Usuario

def migrate_reviews():
    resenas = Resena.objects.all()
    print(f"Encontradas {resenas.count()} reseñas legendarias.")
    
    migrated_count = 0
    skipped_count = 0
    
    for resena in resenas:
        # Verificar si ya existe en el nuevo sistema
        if Review.objects.filter(service_order=resena.solicitud).exists():
            print(f"Skipping resena ID {resena.id} - already exists in Review system.")
            skipped_count += 1
            continue
            
        try:
            provider_type = 'taller' if resena.taller else 'mecanico'
            provider_id = resena.taller.id if resena.taller else resena.mecanico.id
            
            Review.objects.create(
                client=resena.cliente.usuario,
                provider_type=provider_type,
                provider_id=provider_id,
                service_order=resena.solicitud,
                rating=resena.calificacion,
                comment=resena.comentario or "",
                created_at=resena.fecha_hora_resena
            )
            print(f"Migrated resena ID {resena.id} to new Review system.")
            migrated_count += 1
        except Exception as e:
            print(f"Error migrating resena ID {resena.id}: {e}")
            skipped_count += 1
            
    print(f"\nResumen: {migrated_count} migradas, {skipped_count} omitidas/errores.")

if __name__ == "__main__":
    migrate_reviews()

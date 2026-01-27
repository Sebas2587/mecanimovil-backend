import os
import django
import random

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.usuarios.models import Usuario

def update_provider_photos():
    try:
        # 1. Target Providers
        # These are the ones likely used in create_offers.py
        target_emails = ['taller1@example.com', 'taller2@example.com']
        
        # 2. Available Images in media/perfiles
        # Only use filenames that exist
        available_images = [
            'perfiles/profile.jpg',
            'perfiles/profile_edit.jpg',
            'perfiles/IMG_0001.JPG',
            'perfiles/IMG_0002.JPG',
            'perfiles/IMG_0005.JPG',
            'perfiles/IMG_0006.jpg'
        ]

        for email in target_emails:
            try:
                user = Usuario.objects.get(email=email)
                
                # Assign a random photo if not already set (or overwrite for testing)
                selected_image = random.choice(available_images)
                
                # We assign the relative path from media root
                user.foto_perfil = selected_image
                user.save()
                
                print(f"Updated {user.email} with photo: {selected_image}")
                
            except Usuario.DoesNotExist:
                print(f"User {email} not found - skipping.")

    except Exception as e:
        print(f"Error updating photos: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    update_provider_photos()

from django.db import migrations

class Migration(migrations.Migration):
    
    dependencies = [
        ('usuarios', '0002_direccionusuario'),
    ]

    operations = [
        # Esta migración se marca como aplicada manualmente
        # Los cambios reales se aplican con SQL directo en reconstruir_base_datos.sql
    ]

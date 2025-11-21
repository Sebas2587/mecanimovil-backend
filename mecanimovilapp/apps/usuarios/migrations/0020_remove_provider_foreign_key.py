# Generated manually to fix foreign key constraint issue

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0019_add_missing_provider_type_column'),
    ]

    operations = [
        migrations.RunSQL(
            # Eliminar la restricción de clave foránea problemática
            sql="ALTER TABLE usuarios_review DROP CONSTRAINT IF EXISTS usuarios_review_provider_id_cb50cfbb_fk_usuarios_;",
            reverse_sql="-- No reverse operation needed"
        ),
    ] 
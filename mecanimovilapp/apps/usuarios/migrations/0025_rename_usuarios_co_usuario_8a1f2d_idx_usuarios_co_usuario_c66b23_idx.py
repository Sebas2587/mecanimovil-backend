# En Render el índice origen no existe (0021 se aplicó o se fakeó
# sin crear usuarios_co_usuario_8a1f2d_idx). El RenameIndex crudo falla.
# Idempotente: renombra si está; si no, crea el nombre nuevo.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0024_dias_validez_cotizacion'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameIndex(
                    model_name='consentimientousuario',
                    new_name='usuarios_co_usuario_c66b23_idx',
                    old_name='usuarios_co_usuario_8a1f2d_idx',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER INDEX IF EXISTS usuarios_co_usuario_8a1f2d_idx '
                        'RENAME TO usuarios_co_usuario_c66b23_idx;'
                    ),
                    reverse_sql=(
                        'ALTER INDEX IF EXISTS usuarios_co_usuario_c66b23_idx '
                        'RENAME TO usuarios_co_usuario_8a1f2d_idx;'
                    ),
                ),
                migrations.RunSQL(
                    sql=(
                        'CREATE INDEX IF NOT EXISTS usuarios_co_usuario_c66b23_idx '
                        'ON usuarios_consentimientousuario '
                        '(usuario_id, tipo, fecha_aceptacion DESC);'
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]

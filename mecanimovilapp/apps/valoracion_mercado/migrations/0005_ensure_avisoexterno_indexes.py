"""Índices idempotentes de AvisoExternoVehiculo (evita RenameIndex frágiles en Render)."""

from django.db import migrations

CANONICAL_INDEXES = (
    'valoracion__marca_i_8a3f2d_idx',
    'valoracion__fecha_u_4b1c9e_idx',
)

GHOST_MIGRATION_NAMES = (
    '0005_rename_valoracion__marca_i_8a3f2d_idx_valoracion__marca_i_823b5d_idx_and_more',
)


def _drop_noncanonical_indexes(table_name, canonical, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.indexname
            FROM pg_indexes i
            JOIN pg_class c ON c.relname = i.indexname
            JOIN pg_index ix ON ix.indexrelid = c.oid
            WHERE i.schemaname = 'public'
              AND i.tablename = %s
              AND NOT ix.indisprimary
              AND i.indexname <> ALL(%s)
            """,
            [table_name, list(canonical)],
        )
        for (index_name,) in cursor.fetchall():
            cursor.execute(f'DROP INDEX IF EXISTS "{index_name}"')


def _ensure_aviso_indexes(apps, schema_editor):
    table = 'valoracion_mercado_avisoexternovehiculo'
    _drop_noncanonical_indexes(table, CANONICAL_INDEXES, schema_editor)
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS valoracion__marca_i_8a3f2d_idx
            ON valoracion_mercado_avisoexternovehiculo (marca_id, modelo_id, year, activo)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS valoracion__fecha_u_4b1c9e_idx
            ON valoracion_mercado_avisoexternovehiculo (fecha_ultima_vista)
            """
        )


def _cleanup_ghost_migration_records(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for name in GHOST_MIGRATION_NAMES:
            cursor.execute(
                'DELETE FROM django_migrations WHERE app = %s AND name = %s',
                ['valoracion_mercado', name],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('valoracion_mercado', '0004_mercadolibreoauthtoken_scope_textfield'),
    ]

    operations = [
        migrations.RunPython(_cleanup_ghost_migration_records, migrations.RunPython.noop),
        migrations.RunPython(_ensure_aviso_indexes, migrations.RunPython.noop),
    ]

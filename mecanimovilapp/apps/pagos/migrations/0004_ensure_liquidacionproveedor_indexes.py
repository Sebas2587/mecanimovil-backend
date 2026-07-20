"""Índices idempotentes de LiquidacionProveedor (evita RenameIndex frágiles en Render)."""

from django.db import migrations

CANONICAL_INDEXES = (
    'pagos_liquid_usuario_0a1b2c_idx',
    'pagos_liquid_estado__3d4e5f_idx',
)

# Migraciones auto-generadas con makemigrations que fallan o duplican en producción.
GHOST_MIGRATION_NAMES = (
    '0004_rename_pagos_liquid_usuario_0a1b2c_idx_pagos_liqui_usuario_06881e_idx_and_more',
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


def _ensure_liquidacion_indexes(apps, schema_editor):
    table = 'pagos_liquidacionproveedor'
    _drop_noncanonical_indexes(
        table,
        CANONICAL_INDEXES,
        schema_editor,
    )
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS pagos_liquid_usuario_0a1b2c_idx
            ON pagos_liquidacionproveedor (usuario_id, estado)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS pagos_liquid_estado__3d4e5f_idx
            ON pagos_liquidacionproveedor (estado, creado_en DESC)
            """
        )


def _cleanup_ghost_migration_records(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for name in GHOST_MIGRATION_NAMES:
            cursor.execute(
                'DELETE FROM django_migrations WHERE app = %s AND name = %s',
                ['pagos', name],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('pagos', '0003_liquidacionproveedor'),
    ]

    operations = [
        migrations.RunPython(_cleanup_ghost_migration_records, migrations.RunPython.noop),
        migrations.RunPython(_ensure_liquidacion_indexes, migrations.RunPython.noop),
    ]

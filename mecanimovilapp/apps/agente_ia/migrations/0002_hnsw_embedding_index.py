# HNSW index for vector similarity search (pgvector)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_extension WHERE extname = 'vector'
              ) AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'agente_ia_tallerconocimientochunk'
                  AND column_name = 'embedding'
              ) THEN
                CREATE INDEX IF NOT EXISTS agente_ia_chunk_embedding_hnsw
                ON agente_ia_tallerconocimientochunk
                USING hnsw (embedding vector_cosine_ops);
              END IF;
            END $$;
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS agente_ia_chunk_embedding_hnsw;
            """,
        ),
    ]

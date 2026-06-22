from django.db import migrations


def crear_mandantes(apps, schema_editor):
    """
    Por cada Taller con usuario y sin MiembroTaller(rol='mandante'), crea uno.
    Idempotente: re-ejecutar no duplica mandantes.
    """
    Taller = apps.get_model('usuarios', 'Taller')
    MiembroTaller = apps.get_model('usuarios', 'MiembroTaller')

    for taller in Taller.objects.all().iterator():
        if not getattr(taller, 'usuario_id', None):
            continue
        ya_existe = MiembroTaller.objects.filter(taller=taller, rol='mandante').exists()
        if ya_existe:
            continue

        nombre = (taller.nombre or '').strip()
        if not nombre and taller.usuario_id:
            usuario = taller.usuario
            nombre = f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username

        MiembroTaller.objects.create(
            taller=taller,
            usuario_id=taller.usuario_id,
            rol='mandante',
            nombre=nombre or 'Dueño',
            modalidad_tecnico=getattr(taller, 'modalidad_atencion', None) or 'en_taller',
            activo=True,
        )


def revertir_mandantes(apps, schema_editor):
    """
    Reverso seguro: no-op. No se eliminan mandantes para no perder datos del equipo
    que pudieran haberse editado tras la migración.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0015_miembrotaller_and_more'),
    ]

    operations = [
        migrations.RunPython(crear_mandantes, revertir_mandantes),
    ]

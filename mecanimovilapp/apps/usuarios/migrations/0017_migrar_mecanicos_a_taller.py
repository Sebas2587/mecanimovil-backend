"""
Migración de datos: unificación de proveedores.

Convierte cada `MecanicoDomicilio` existente en un `Taller` con
`modalidad_atencion='a_domicilio'`, repunta todas las relaciones dependientes
(ofertas, solicitudes, documentos, horarios, reseñas, áreas de servicio, etc.)
del mecánico al nuevo taller, crea el `MiembroTaller(rol='mandante')` y elimina
el registro legacy de mecánico.

Idempotente: tras la primera ejecución no quedan mecánicos por convertir, por lo
que re-ejecutar es un no-op. Transaccional (PostgreSQL envuelve la migración).
"""

from django.db import migrations


# Tablas con (columna_mecanico, columna_taller) que deben repuntarse al taller.
REPOINT_TABLES = [
    ('servicios_ofertaservicio', 'mecanico_id', 'taller_id'),
    ('ordenes_solicitudservicio', 'mecanico_id', 'taller_id'),
    ('ordenes_citaagendapersonal', 'mecanico_id', 'taller_id'),
    ('usuarios_documentoonboarding', 'mecanico_id', 'taller_id'),
    ('usuarios_horarioproveedor', 'mecanico_id', 'taller_id'),
    ('usuarios_resena', 'mecanico_id', 'taller_id'),
    ('usuarios_configuracionsemanalproveedor', 'mecanico_id', 'taller_id'),
    ('usuarios_mechanicservicearea', 'mechanic_id', 'taller_id'),
]


def migrar_mecanicos_a_taller(apps, schema_editor):
    Taller = apps.get_model('usuarios', 'Taller')
    MecanicoDomicilio = apps.get_model('usuarios', 'MecanicoDomicilio')
    MiembroTaller = apps.get_model('usuarios', 'MiembroTaller')
    connection = schema_editor.connection

    for mecanico in MecanicoDomicilio.objects.all().iterator():
        usuario_id = getattr(mecanico, 'usuario_id', None)

        # Mecánico huérfano (sin usuario): se elimina (no es un proveedor válido).
        if not usuario_id:
            mecanico.delete()
            continue

        existing_taller = Taller.objects.filter(usuario_id=usuario_id).first()

        # Caso fusión: el usuario ya tiene un taller. El mecánico legacy se elimina
        # (su data incompleta se limpia por cascade). El taller existente prevalece.
        if existing_taller:
            mecanico.delete()
            continue

        # Crear el taller espejo con modalidad a domicilio.
        nombre = (mecanico.nombre or '').strip()
        if not nombre:
            usuario = mecanico.usuario
            nombre = f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username

        taller = Taller.objects.create(
            usuario_id=usuario_id,
            nombre=nombre or 'Taller',
            telefono=mecanico.telefono,
            ubicacion=mecanico.ubicacion,
            foto_perfil=mecanico.foto_perfil,
            calificacion_promedio=mecanico.calificacion_promedio,
            numero_de_calificaciones=mecanico.numero_de_calificaciones,
            activo=mecanico.activo,
            estado_verificacion=mecanico.estado_verificacion,
            # save() custom no corre en migraciones: fijar verificado explícitamente.
            verificado=(mecanico.estado_verificacion == 'aprobado'),
            onboarding_completado=mecanico.onboarding_completado,
            onboarding_iniciado=mecanico.onboarding_iniciado,
            fecha_verificacion=mecanico.fecha_verificacion,
            verificado_por_id=getattr(mecanico, 'verificado_por_id', None),
            descripcion=mecanico.descripcion,
            rut=mecanico.rut,
            dni=mecanico.dni,
            experiencia_anos=mecanico.experiencia_anos,
            ultima_conexion=mecanico.ultima_conexion,
            esta_conectado=mecanico.esta_conectado,
            tipo_cobertura_marca=mecanico.tipo_cobertura_marca,
            radio_cobertura=mecanico.radio_cobertura,
            modalidad_atencion='a_domicilio',
        )

        # Copiar especialidades y marcas (M2M) antes de eliminar el mecánico.
        taller.especialidades.set(mecanico.especialidades.all())
        taller.marcas_atendidas.set(mecanico.marcas_atendidas.all())

        # Repuntar relaciones dependientes del mecánico al nuevo taller.
        with connection.cursor() as cursor:
            for table, col_mecanico, col_taller in REPOINT_TABLES:
                cursor.execute(
                    f"UPDATE {table} SET {col_taller} = %s, {col_mecanico} = NULL "
                    f"WHERE {col_mecanico} = %s",
                    [taller.id, mecanico.id],
                )

        # Crear mandante (dueño) para el taller.
        if not MiembroTaller.objects.filter(taller=taller, rol='mandante').exists():
            MiembroTaller.objects.create(
                taller=taller,
                usuario_id=usuario_id,
                rol='mandante',
                nombre=nombre or 'Dueño',
                modalidad_tecnico='a_domicilio',
                activo=True,
            )

        # Eliminar el mecánico legacy. Las relaciones restantes (M2M, connectionstatus,
        # zonacobertura) se limpian por cascade; las repuntadas ya no lo referencian.
        mecanico.delete()


def revertir(apps, schema_editor):
    """Reverso seguro: no-op (no se reconstruyen mecánicos para no perder datos)."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0016_data_mandante_por_taller'),
        ('ordenes', '0016_citaagendapersonal_miembro_taller_and_more'),
        ('servicios', '0008_ofertaservicio_tipo_motor'),
    ]

    operations = [
        migrations.RunPython(migrar_mecanicos_a_taller, revertir),
    ]

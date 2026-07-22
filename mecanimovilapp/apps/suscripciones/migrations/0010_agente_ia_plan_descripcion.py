from django.db import migrations


DESCRIPCIONES_NUEVAS = {
    'Plan Profesional': (
        'Para talleres en crecimiento: más créditos, IA generosa, Agente IA conversacional '
        'con cotizaciones automáticas, dos canales de mensajería y mayor volumen de conversaciones.'
    ),
    'Plan Premium': (
        'Máximo rendimiento: todos los canales, Agente IA conversacional con cotizaciones '
        'automáticas ampliado, endpoints avanzados de patente y cuotas ampliadas de IA y mensajería.'
    ),
}

DESCRIPCIONES_ANTERIORES = {
    'Plan Profesional': (
        'Para talleres en crecimiento: más créditos, IA generosa, dos canales de mensajería '
        'y mayor volumen de conversaciones.'
    ),
    'Plan Premium': (
        'Máximo rendimiento: todos los canales, endpoints avanzados de patente y cuotas '
        'ampliadas de IA y mensajería.'
    ),
}


def actualizar_descripciones(apps, schema_editor, mapping):
    PlanSuscripcion = apps.get_model('suscripciones', 'PlanSuscripcion')
    for plan in PlanSuscripcion.objects.all():
        nueva = mapping.get(plan.nombre)
        if nueva is not None:
            plan.descripcion = nueva
            plan.save(update_fields=['descripcion'])


def aplicar(apps, schema_editor):
    actualizar_descripciones(apps, schema_editor, DESCRIPCIONES_NUEVAS)


def revertir(apps, schema_editor):
    actualizar_descripciones(apps, schema_editor, DESCRIPCIONES_ANTERIORES)


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0009_agente_ia_plan_feature'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]

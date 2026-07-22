import django.core.validators
from decimal import Decimal
from django.db import migrations, models


def poblar_agente_ia_en_planes(apps, schema_editor):
    """
    Habilita el Agente IA (auto-respuesta conversacional) solo en Profesional y
    Premium, con un cupo mensual dedicado (independiente de las conversaciones
    salientes manuales), y ajusta el precio de esos dos planes para reflejar
    el nuevo valor entregado. Plan Básico queda sin cambios de precio ni de
    acceso al Agente IA.
    """
    PlanSuscripcion = apps.get_model('suscripciones', 'PlanSuscripcion')

    ajustes = {
        'Plan Básico': {
            'agente_ia_incluido': False,
            'conversaciones_agente_ia_max': 0,
            # Precio sin cambios: no incluye Agente IA.
        },
        'Plan Profesional': {
            'agente_ia_incluido': True,
            'conversaciones_agente_ia_max': 500,
            'precio': Decimal('84990.00'),
        },
        'Plan Premium': {
            'agente_ia_incluido': True,
            'conversaciones_agente_ia_max': 1500,
            'precio': Decimal('169990.00'),
        },
    }

    for plan in PlanSuscripcion.objects.all():
        cambios = ajustes.get(plan.nombre)
        if not cambios:
            continue
        for campo, valor in cambios.items():
            setattr(plan, campo, valor)
        plan.save(update_fields=list(cambios.keys()))


def revertir_agente_ia_en_planes(apps, schema_editor):
    PlanSuscripcion = apps.get_model('suscripciones', 'PlanSuscripcion')
    precios_originales = {
        'Plan Básico': Decimal('31173.00'),
        'Plan Profesional': Decimal('72752.00'),
        'Plan Premium': Decimal('145514.00'),
    }
    for plan in PlanSuscripcion.objects.all():
        plan.agente_ia_incluido = False
        plan.conversaciones_agente_ia_max = 0
        precio_original = precios_originales.get(plan.nombre)
        if precio_original is not None:
            plan.precio = precio_original
        plan.save(update_fields=['agente_ia_incluido', 'conversaciones_agente_ia_max', 'precio'])


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0008_plan_cuotas_features'),
    ]

    operations = [
        migrations.AddField(
            model_name='plansuscripcion',
            name='agente_ia_incluido',
            field=models.BooleanField(
                default=False,
                help_text='Habilita la auto-respuesta del Agente IA en los chats del taller.',
                verbose_name='Agente IA conversacional incluido',
            ),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='conversaciones_agente_ia_max',
            field=models.IntegerField(
                default=0,
                validators=[django.core.validators.MinValueValidator(0)],
                help_text='Cupo mensual dedicado para mensajes enviados por el Agente IA, '
                'independiente del tope de conversaciones salientes manuales.',
                verbose_name='Tope conversaciones del Agente IA/mes',
            ),
        ),
        migrations.AlterField(
            model_name='consumofeaturemensual',
            name='feature',
            field=models.CharField(
                choices=[
                    ('COTIZACION_IA', 'Cotización IA'),
                    ('DIAGNOSTICO_IA', 'Diagnóstico IA'),
                    ('CONSULTA_PATENTE', 'Consulta patente'),
                    ('CONVERSACION_SALIENTE', 'Conversación saliente'),
                    ('CONVERSACION_AGENTE_IA', 'Conversación Agente IA'),
                ],
                max_length=40,
            ),
        ),
        migrations.RunPython(poblar_agente_ia_en_planes, revertir_agente_ia_en_planes),
    ]

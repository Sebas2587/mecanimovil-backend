# Generated manually for LiquidacionProveedor

import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('pagos', '0002_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiquidacionProveedor',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('object_id', models.PositiveIntegerField()),
                ('oferta_id', models.UUIDField(blank=True, db_index=True, null=True)),
                ('orden_id', models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ('monto_cobrado_cliente', models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ('comision_plataforma', models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ('monto_neto_proveedor', models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ('moneda', models.CharField(default='CLP', max_length=3)),
                ('estado', models.CharField(choices=[('pendiente', 'Pendiente de liquidación'), ('procesada', 'Procesada'), ('pagada', 'Pagada al proveedor'), ('cancelada', 'Cancelada')], db_index=True, default='pendiente', max_length=20)),
                ('referencia_transferencia', models.CharField(blank=True, default='', max_length=255)),
                ('fecha_liquidacion', models.DateTimeField(blank=True, null=True)),
                ('notas', models.TextField(blank=True, default='')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
                ('pago', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='liquidaciones', to='pagos.pago')),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='liquidaciones_proveedor', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'liquidación proveedor',
                'verbose_name_plural': 'liquidaciones proveedor',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.AddIndex(
            model_name='liquidacionproveedor',
            index=models.Index(fields=['usuario', 'estado'], name='pagos_liquid_usuario_0a1b2c_idx'),
        ),
        migrations.AddIndex(
            model_name='liquidacionproveedor',
            index=models.Index(fields=['estado', '-creado_en'], name='pagos_liquid_estado__3d4e5f_idx'),
        ),
    ]

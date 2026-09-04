import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ordenes', '0039_factormercadocategoria'),
        ('usuarios', '0024_dias_validez_cotizacion'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='tipo_documento',
            field=models.CharField(
                choices=[('estimacion', 'Estimación'), ('cotizacion', 'Cotización firme')],
                default='estimacion',
                help_text='Estimación preliminar o cotización firme.',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='tipo_documento_emitido',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Snapshot del tipo al enviar. No se reescribe.',
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name='ProveedorRepuestos',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=120)),
                ('nombre_norm', models.CharField(db_index=True, max_length=120)),
                ('tipo', models.CharField(choices=[('mostrador', 'Casa de repuestos'), ('distribuidor', 'Distribuidor'), ('concesionario', 'Concesionario / oficial'), ('marketplace', 'Marketplace / web')], default='mostrador', max_length=20)),
                ('comuna', models.CharField(blank=True, default='', max_length=80)),
                ('telefono', models.CharField(blank=True, default='', max_length=32)),
                ('direccion', models.CharField(blank=True, default='', max_length=200)),
                ('dominio', models.CharField(blank=True, default='', max_length=200)),
                ('descuento_pct', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('dias_credito', models.PositiveSmallIntegerField(default=0)),
                ('entrega', models.CharField(choices=[('retiro', 'Retiro'), ('despacho', 'Despacho'), ('ambos', 'Ambos')], default='retiro', max_length=12)),
                ('es_preferido', models.BooleanField(default=False)),
                ('activo', models.BooleanField(default=True)),
                ('notas', models.TextField(blank=True, default='')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='proveedores_repuestos', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'proveedor de repuestos',
                'verbose_name_plural': 'proveedores de repuestos',
            },
        ),
        migrations.AddConstraint(
            model_name='proveedorrepuestos',
            constraint=models.UniqueConstraint(fields=('taller', 'nombre_norm'), name='ordenes_provrep_taller_nombre_uniq'),
        ),
        migrations.CreateModel(
            name='PrecioProveedorTaller',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('clave_fuzzy', models.CharField(db_index=True, max_length=200)),
                ('nombre_repuesto', models.CharField(max_length=200)),
                ('marca_repuesto', models.CharField(blank=True, default='', max_length=100)),
                ('codigo_parte', models.CharField(blank=True, db_index=True, default='', max_length=60)),
                ('especificacion', models.CharField(blank=True, default='', max_length=120)),
                ('categoria', models.CharField(blank=True, default='', max_length=40)),
                ('precio_clp', models.PositiveIntegerField()),
                ('precio_venta_clp', models.PositiveIntegerField(default=0)),
                ('iva_incluido', models.BooleanField(default=True)),
                ('vehiculo_marca', models.CharField(blank=True, default='', max_length=80)),
                ('vehiculo_modelo', models.CharField(blank=True, default='', max_length=80)),
                ('vehiculo_anio', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('tipo_motor', models.CharField(blank=True, default='', max_length=20)),
                ('cilindraje', models.CharField(blank=True, default='', max_length=20)),
                ('origen', models.CharField(choices=[('compra', 'Compra registrada'), ('cotizacion_proveedor', 'Cotización del proveedor'), ('lista_precios', 'Lista de precios'), ('manual', 'Ingreso manual')], default='compra', max_length=24)),
                ('precio_referencia_web_clp', models.PositiveIntegerField(default=0)),
                ('vigente_hasta', models.DateTimeField(blank=True, null=True)),
                ('registrado_en', models.DateTimeField(auto_now_add=True)),
                ('cotizacion_origen', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='precios_proveedor_registrados', to='ordenes.cotizacioncanal')),
                ('proveedor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='precios', to='ordenes.proveedorrepuestos')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='precios_repuestos_registrados', to=settings.AUTH_USER_MODEL)),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='precios_repuestos', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'precio proveedor taller',
                'verbose_name_plural': 'precios proveedor taller',
            },
        ),
        migrations.AddIndex(
            model_name='precioproveedortaller',
            index=models.Index(fields=['taller', 'clave_fuzzy', '-registrado_en'], name='ordenes_pre_taller__2f4a1c_idx'),
        ),
        migrations.AddIndex(
            model_name='precioproveedortaller',
            index=models.Index(fields=['taller', 'codigo_parte'], name='ordenes_pre_taller__9c8e21_idx'),
        ),
    ]

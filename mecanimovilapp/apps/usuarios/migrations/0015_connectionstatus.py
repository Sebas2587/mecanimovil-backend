# Generated manually for ConnectionStatus model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0014_mecanicodomicilio_esta_conectado_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConnectionStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('esta_conectado', models.BooleanField(default=False)),
                ('ultima_conexion', models.DateTimeField(auto_now=True)),
                ('ultima_desconexion', models.DateTimeField(blank=True, null=True)),
                ('session_id', models.CharField(blank=True, max_length=255, null=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.TextField(blank=True, null=True)),
                ('proveedor', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='connection_status', to='usuarios.mecanicodomicilio')),
                ('taller', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='connection_status', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'Estado de Conexión',
                'verbose_name_plural': 'Estados de Conexión',
            },
        ),
    ] 
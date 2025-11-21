from django.db import migrations
from django.db.models import F, Q

def migrar_datos_precios(apps, schema_editor):
    """
    Migra datos de los modelos antiguos al nuevo modelo OfertaServicio
    """
    # Obtener referencias a los modelos
    ServicioTaller = apps.get_model('servicios', 'ServicioTaller')
    ServicioMecanico = apps.get_model('servicios', 'ServicioMecanico')
    PrecioServicioTaller = apps.get_model('servicios', 'PrecioServicioTaller')
    PrecioServicioMecanico = apps.get_model('servicios', 'PrecioServicioMecanico')
    OfertaServicio = apps.get_model('servicios', 'OfertaServicio')
    Servicio = apps.get_model('servicios', 'Servicio')
    
    # 1. Migrar datos de PrecioServicioTaller
    for precio in PrecioServicioTaller.objects.all():
        OfertaServicio.objects.create(
            tipo_proveedor='taller',
            taller=precio.taller,
            mecanico=None,
            servicio=precio.servicio,
            disponible=True,
            precio_con_repuestos=precio.precio_con_repuestos,
            precio_sin_repuestos=precio.precio_sin_repuestos
        )
    
    # 2. Migrar datos de PrecioServicioMecanico
    for precio in PrecioServicioMecanico.objects.all():
        OfertaServicio.objects.create(
            tipo_proveedor='mecanico',
            taller=None,
            mecanico=precio.mecanico,
            servicio=precio.servicio,
            disponible=True,
            precio_con_repuestos=precio.precio_con_repuestos,
            precio_sin_repuestos=precio.precio_sin_repuestos
        )
    
    # 3. Migrar relaciones simples (sin precios) de ServicioTaller
    for rel in ServicioTaller.objects.all():
        # Verificar si ya existe una oferta para esta relación
        if not OfertaServicio.objects.filter(taller=rel.taller, servicio=rel.servicio).exists():
            # Utilizar el precio de referencia del servicio
            OfertaServicio.objects.create(
                tipo_proveedor='taller',
                taller=rel.taller,
                mecanico=None,
                servicio=rel.servicio,
                disponible=True,
                precio_con_repuestos=rel.servicio.precio_referencia,
                precio_sin_repuestos=rel.servicio.precio_referencia * 0.7  # 70% del precio base como estimación
            )
    
    # 4. Migrar relaciones simples (sin precios) de ServicioMecanico
    for rel in ServicioMecanico.objects.all():
        # Verificar si ya existe una oferta para esta relación
        if not OfertaServicio.objects.filter(mecanico=rel.mecanico, servicio=rel.servicio).exists():
            # Utilizar el precio de referencia del servicio
            OfertaServicio.objects.create(
                tipo_proveedor='mecanico',
                taller=None,
                mecanico=rel.mecanico,
                servicio=rel.servicio,
                disponible=True,
                precio_con_repuestos=rel.servicio.precio_referencia,
                precio_sin_repuestos=rel.servicio.precio_referencia * 0.7  # 70% del precio base como estimación
            )

def actualizar_lineas_servicio(apps, schema_editor):
    """
    Actualiza las líneas de servicio existentes para usar el nuevo modelo OfertaServicio
    """
    LineaServicio = apps.get_model('ordenes', 'LineaServicio')
    OfertaServicio = apps.get_model('servicios', 'OfertaServicio')
    
    for linea in LineaServicio.objects.all():
        # Determinar el tipo de proveedor y la oferta correspondiente
        if hasattr(linea, 'precio_servicio_taller') and linea.precio_servicio_taller:
            # Buscar la oferta de taller correspondiente
            try:
                oferta = OfertaServicio.objects.get(
                    tipo_proveedor='taller',
                    taller=linea.precio_servicio_taller.taller,
                    servicio=linea.servicio
                )
                # Actualizar la línea con la nueva oferta
                linea.oferta_servicio = oferta
                linea.precio_unitario = linea.precio_final  # Mantener el precio histórico
                linea.save()
            except OfertaServicio.DoesNotExist:
                print(f"No se encontró oferta para la línea {linea.id} (taller)")
                
        elif hasattr(linea, 'precio_servicio_mecanico') and linea.precio_servicio_mecanico:
            # Buscar la oferta de mecánico correspondiente
            try:
                oferta = OfertaServicio.objects.get(
                    tipo_proveedor='mecanico',
                    mecanico=linea.precio_servicio_mecanico.mecanico,
                    servicio=linea.servicio
                )
                # Actualizar la línea con la nueva oferta
                linea.oferta_servicio = oferta
                linea.precio_unitario = linea.precio_final  # Mantener el precio histórico
                linea.save()
            except OfertaServicio.DoesNotExist:
                print(f"No se encontró oferta para la línea {linea.id} (mecánico)")
                
        else:
            # Si no hay precio específico, buscar alguna oferta para el servicio
            try:
                # Intentar encontrar una oferta relacionada con el proveedor de la solicitud
                solicitud = linea.solicitud
                if solicitud.taller:
                    oferta = OfertaServicio.objects.filter(
                        tipo_proveedor='taller',
                        taller=solicitud.taller,
                        servicio=linea.servicio
                    ).first()
                elif solicitud.mecanico:
                    oferta = OfertaServicio.objects.filter(
                        tipo_proveedor='mecanico',
                        mecanico=solicitud.mecanico,
                        servicio=linea.servicio
                    ).first()
                else:
                    # Si no hay taller ni mecánico en la solicitud, usar cualquier oferta
                    oferta = OfertaServicio.objects.filter(servicio=linea.servicio).first()
                
                if oferta:
                    linea.oferta_servicio = oferta
                    linea.precio_unitario = linea.precio_final  # Mantener el precio histórico
                    linea.save()
                else:
                    print(f"No se encontró oferta para la línea {linea.id} (genérica)")
            except Exception as e:
                print(f"Error al actualizar línea {linea.id}: {str(e)}")

class Migration(migrations.Migration):
    """
    Esta migración debe correr después de que se hayan creado todos los modelos nuevos.
    """
    # Actualizada para hacer referencia a una migración existente
    dependencies = [
        ('servicios', '0001_initial'),
        ('ordenes', '0001_initial'),
    ]
    
    operations = [
        migrations.RunPython(migrar_datos_precios),
        migrations.RunPython(actualizar_lineas_servicio),
    ] 
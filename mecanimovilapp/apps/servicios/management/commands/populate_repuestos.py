from django.core.management.base import BaseCommand
from mecanimovilapp.apps.servicios.models import Servicio, Repuesto, ServicioRepuesto
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo
from decimal import Decimal

class Command(BaseCommand):
    help = 'Pobla la base de datos con repuestos genéricos para todos los modelos y servicios'

    def handle(self, *args, **options):
        self.stdout.write('🔧 Iniciando población de repuestos...\n')
        
        #========================================================================================
        # 1. CREAR REPUESTOS GENÉRICOS POR CATEGORÍA
        #========================================================================================
        
        repuestos_genericos = [
            # FRENOS
            {
                'nombre': 'Pastillas de Freno Delanteras',
                'descripcion': 'Pastillas de freno cerámicas para eje delantero',
                'marca': 'Genérico',
                'categoria_repuesto': 'frenos',
                'precio_referencia': Decimal('45000'),
                'codigo_fabricante': 'PFD-GEN-001'
            },
            {
                'nombre': 'Pastillas de Freno Traseras',
                'descripcion': 'Pastillas de freno para eje trasero',
                'marca': 'Genérico',
                'categoria_repuesto': 'frenos',
                'precio_referencia': Decimal('40000'),
                'codigo_fabricante': 'PFT-GEN-002'
            },
            {
                'nombre': 'Discos de Freno Delanteros (Par)',
                'descripcion': 'Par de discos de freno ventilados delanteros',
                'marca': 'Genérico',
                'categoria_repuesto': 'frenos',
                'precio_referencia': Decimal('85000'),
                'codigo_fabricante': 'DFD-GEN-003'
            },
            {
                'nombre': 'Discos de Freno Traseros (Par)',
                'descripcion': 'Par de discos de freno traseros',
                'marca': 'Genérico',
                'categoria_repuesto': 'frenos',
                'precio_referencia': Decimal('75000'),
                'codigo_fabricante': 'DFT-GEN-004'
            },
            
            # ACEITES Y FILTROS
            {
                'nombre': 'Aceite Motor 5W-30 Sintético (4L)',
                'descripcion': 'Aceite sintético de alta calidad para motor',
                'marca': 'Genérico',
                'categoria_repuesto': 'aceites',
                'precio_referencia': Decimal('25000'),
                'codigo_fabricante': 'ACE-5W30-001'
            },
            {
                'nombre': 'Aceite Motor 10W-40 Semi-Sintético (4L)',
                'descripcion': 'Aceite semi-sintético para motor',
                'marca': 'Genérico',
                'categoria_repuesto': 'aceites',
                'precio_referencia': Decimal('20000'),
                'codigo_fabricante': 'ACE-10W40-002'
            },
            {
                'nombre': 'Filtro de Aceite',
                'descripcion': 'Filtro de aceite original',
                'marca': 'Genérico',
                'categoria_repuesto': 'filtros',
                'precio_referencia': Decimal('8000'),
                'codigo_fabricante': 'FA-GEN-001'
            },
            {
                'nombre': 'Filtro de Aire Motor',
                'descripcion': 'Filtro de aire para motor',
                'marca': 'Genérico',
                'categoria_repuesto': 'filtros',
                'precio_referencia': Decimal('12000'),
                'codigo_fabricante': 'FAM-GEN-002'
            },
            {
                'nombre': 'Filtro de Aire Habitáculo',
                'descripcion': 'Filtro de aire acondicionado/habitáculo',
                'marca': 'Genérico',
                'categoria_repuesto': 'filtros',
                'precio_referencia': Decimal('9000'),
                'codigo_fabricante': 'FAH-GEN-003'
            },
            
            # SISTEMA ELÉCTRICO
            {
                'nombre': 'Batería 12V 60Ah',
                'descripcion': 'Batería libre de mantenimiento 60Ah',
                'marca': 'Genérico',
                'categoria_repuesto': 'electrico',
                'precio_referencia': Decimal('90000'),
                'codigo_fabricante': 'BAT-60AH-001'
            },
            {
                'nombre': 'Ampolleta H4 Halógena',
                'descripcion': 'Ampolleta halógena H4 para faros',
                'marca': 'Genérico',
                'categoria_repuesto': 'electrico',
                'precio_referencia': Decimal('5000'),
                'codigo_fabricante': 'AMP-H4-001'
            },
            {
                'nombre': 'Ampolleta H7 Halógena',
                'descripcion': 'Ampolleta halógena H7 para faros',
                'marca': 'Genérico',
                'categoria_repuesto': 'electrico',
                'precio_referencia': Decimal('5500'),
                'codigo_fabricante': 'AMP-H7-002'
            },
            {
                'nombre': 'Bujías (Juego de 4)',
                'descripcion': 'Juego de 4 bujías de encendido',
                'marca': 'Genérico',
                'categoria_repuesto': 'motor',
                'precio_referencia': Decimal('25000'),
                'codigo_fabricante': 'BUJ-4-001'
            },
            
            # INSUMOS LAVADO
            {
                'nombre': 'Shampoo Auto Concentrado (1L)',
                'descripcion': 'Shampoo concentrado para lavado de auto',
                'marca': 'Genérico',
                'categoria_repuesto': 'otros',
                'precio_referencia': Decimal('8000'),
                'codigo_fabricante': 'SHA-1L-001'
            },
            {
                'nombre': 'Cera Líquida (500ml)',
                'descripcion': 'Cera líquida para brillo y protección',
                'marca': 'Genérico',
                'categoria_repuesto': 'otros',
                'precio_referencia': Decimal('12000'),
                'codigo_fabricante': 'CER-500ML-001'
            },
            {
                'nombre': 'Limpia Vidrios (1L)',
                'descripcion': 'Limpiador de vidrios profesional',
                'marca': 'Genérico',
                'categoria_repuesto': 'otros',
                'precio_referencia': Decimal('5000'),
                'codigo_fabricante': 'LVI-1L-001'
            },
        ]
        
        self.stdout.write('📦 Creando/actualizando repuestos genéricos...')
        repuestos_obj = {}
        
        for rep_data in repuestos_genericos:
            repuesto, created = Repuesto.objects.get_or_create(
                codigo_fabricante=rep_data['codigo_fabricante'],
                defaults=rep_data
            )
            repuestos_obj[rep_data['nombre']] = repuesto
            
            status = '✅ Creado' if created else '⚠️  Ya existe'
            self.stdout.write(f'  {status}: {repuesto.nombre}')
        
        #========================================================================================
        # 2. ASOCIAR REPUESTOS CON MODELOS COMPATIBLES
        #========================================================================================
        
        self.stdout.write('\n🚗 Asociando repuestos con modelos de vehículos...')
        
        # Obtener todas las marcas
        marcas = {
            'Toyota': Marca.objects.filter(nombre='Toyota').first(),
            'Hyundai': Marca.objects.filter(nombre='Hyundai').first(),
            'Kia': Marca.objects.filter(nombre='Kia').first(),
            'Chevrolet': Marca.objects.filter(nombre='Chevrolet').first(),
            'Ford': Marca.objects.filter(nombre='Ford').first(),
            'Suzuki': Marca.objects.filter(nombre='Suzuki').first(),
            'Peugeot': Marca.objects.filter(nombre='Peugeot').first(),
            'Mitsubishi': Marca.objects.filter(nombre='Mitsubishi').first(),
            'Changan': Marca.objects.filter(nombre='Changan').first(),
            'GWM': Marca.objects.filter(nombre='GWM').first(),
        }
        
        # Asociar todos los repuestos con todos los modelos de todas las marcas
        total_asociaciones = 0
        for nombre_rep, repuesto in repuestos_obj.items():
            modelos_count = 0
            for nombre_marca, marca in marcas.items():
                if marca:
                    modelos = Modelo.objects.filter(marca=marca)
                    for modelo in modelos:
                        repuesto.modelos_compatibles.add(modelo)
                        total_asociaciones += 1
                        modelos_count += 1
            
            self.stdout.write(f'  ✅ {repuesto.nombre}: compatible con {modelos_count} modelos')
        
        self.stdout.write(f'\n  📊 Total asociaciones creadas: {total_asociaciones}')
        
        #========================================================================================
        # 3. ASOCIAR REPUESTOS CON SERVICIOS
        #========================================================================================
        
        self.stdout.write('\n⚙️  Asociando repuestos con servicios...')
        
        servicios_repuestos_mapping = [
            {
                'servicio_nombre': 'Lavado a domicilio',
                'repuestos': [
                    {'nombre': 'Shampoo Auto Concentrado (1L)', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Cera Líquida (500ml)', 'cantidad': 1, 'opcional': True},
                    {'nombre': 'Limpia Vidrios (1L)', 'cantidad': 1, 'opcional': False},
                ]
            },
            {
                'servicio_nombre': 'Cambio de pastillas y discos de freno',
                'repuestos': [
                    {'nombre': 'Pastillas de Freno Delanteras', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Pastillas de Freno Traseras', 'cantidad': 1, 'opcional': True},
                    {'nombre': 'Discos de Freno Delanteros (Par)', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Discos de Freno Traseros (Par)', 'cantidad': 1, 'opcional': True},
                ]
            },
            {
                'servicio_nombre': 'Cambio de pastillas de frenos',
                'repuestos': [
                    {'nombre': 'Pastillas de Freno Delanteras', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Pastillas de Freno Traseras', 'cantidad': 1, 'opcional': True},
                ]
            },
            {
                'servicio_nombre': 'Cambio de aceite motor',
                'repuestos': [
                    {'nombre': 'Aceite Motor 5W-30 Sintético (4L)', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Aceite Motor 10W-40 Semi-Sintético (4L)', 'cantidad': 1, 'opcional': True},
                ]
            },
            {
                'servicio_nombre': 'Cambio aceite motor y filtro',
                'repuestos': [
                    {'nombre': 'Aceite Motor 5W-30 Sintético (4L)', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Aceite Motor 10W-40 Semi-Sintético (4L)', 'cantidad': 1, 'opcional': True},
                    {'nombre': 'Filtro de Aceite', 'cantidad': 1, 'opcional': False},
                ]
            },
            {
                'servicio_nombre': 'Cambio de filtro de aire',
                'repuestos': [
                    {'nombre': 'Filtro de Aire Motor', 'cantidad': 1, 'opcional': False},
                ]
            },
            {
                'servicio_nombre': 'Cambio de filtro habitáculo',
                'repuestos': [
                    {'nombre': 'Filtro de Aire Habitáculo', 'cantidad': 1, 'opcional': False},
                ]
            },
            {
                'servicio_nombre': 'Cambio de batería',
                'repuestos': [
                    {'nombre': 'Batería 12V 60Ah', 'cantidad': 1, 'opcional': False},
                ]
            },
            {
                'servicio_nombre': 'Cambio de ampolletas',
                'repuestos': [
                    {'nombre': 'Ampolleta H4 Halógena', 'cantidad': 1, 'opcional': True},
                    {'nombre': 'Ampolleta H7 Halógena', 'cantidad': 1, 'opcional': True},
                ]
            },
            {
                'servicio_nombre': 'Cambio de bujías',
                'repuestos': [
                    {'nombre': 'Bujías (Juego de 4)', 'cantidad': 1, 'opcional': False},
                ]
            },
            {
                'servicio_nombre': 'Mantenimiento por kilometraje',
                'repuestos': [
                    {'nombre': 'Aceite Motor 5W-30 Sintético (4L)', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Filtro de Aceite', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Filtro de Aire Motor', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Filtro de Aire Habitáculo', 'cantidad': 1, 'opcional': True},
                ]
            },
        ]
        
        total_servicios_actualizados = 0
        for servicio_data in servicios_repuestos_mapping:
            try:
                # Buscar servicio (case-insensitive, partial match)
                servicio = Servicio.objects.filter(
                    nombre__icontains=servicio_data['servicio_nombre']
                ).first()
                
                if not servicio:
                    self.stdout.write(f'  ❌ Servicio no encontrado: {servicio_data["servicio_nombre"]}')
                    continue
                
                self.stdout.write(f'\n  🔧 Procesando: {servicio.nombre}')
                
                for repuesto_info in servicio_data['repuestos']:
                    if repuesto_info['nombre'] in repuestos_obj:
                        repuesto = repuestos_obj[repuesto_info['nombre']]
                        
                        servicio_repuesto, created = ServicioRepuesto.objects.get_or_create(
                            servicio=servicio,
                            repuesto=repuesto,
                            defaults={
                                'cantidad_estimada': repuesto_info['cantidad'],
                                'es_opcional': repuesto_info['opcional'],
                                'notas': f'Repuesto {"opcional" if repuesto_info["opcional"] else "necesario"} para {servicio.nombre}'
                            }
                        )
                        
                        status = '✅' if created else '⚠️ '
                        opcional_txt = ' (opcional)' if repuesto_info['opcional'] else ''
                        self.stdout.write(f'    {status} {repuesto.nombre}{opcional_txt}')
                        
                total_servicios_actualizados += 1
                        
            except Exception as e:
                self.stdout.write(f'  ❌ Error procesando {servicio_data["servicio_nombre"]}: {str(e)}')
        
        #========================================================================================
        # RESUMEN FINAL
        #========================================================================================
        
        self.stdout.write(self.style.SUCCESS(f'\n\n✅ Población de repuestos completada!'))
        self.stdout.write(f'   📦 Repuestos creados/actualizados: {len(repuestos_obj)}')
        self.stdout.write(f'   🚗 Asociaciones modelo-repuesto: {total_asociaciones}')
        self.stdout.write(f'   ⚙️  Servicios actualizados: {total_servicios_actualizados}')
        self.stdout.write(f'\n💡 Los proveedores ahora podrán ver estos repuestos al crear servicios')
        self.stdout.write(f'💡 Pueden personalizar los precios según sus márgenes\n')

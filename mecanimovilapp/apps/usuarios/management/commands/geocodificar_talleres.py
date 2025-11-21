from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point, Polygon
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
import requests
import time
import json
import re


class Command(BaseCommand):
    help = 'Geocodifica las direcciones de talleres y mecánicos usando servicios gratuitos'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tipo',
            type=str,
            choices=['talleres', 'mecanicos', 'ambos'],
            default='ambos',
            help='Tipo de proveedores a geocodificar'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar re-geocodificación incluso si ya tiene coordenadas'
        )

    def handle(self, *args, **options):
        tipo = options['tipo']
        force = options['force']
        
        self.stdout.write(
            self.style.SUCCESS(f'🌍 Iniciando geocodificación de {tipo}...')
        )

        if tipo in ['talleres', 'ambos']:
            self.geocodificar_talleres(force)
            
        if tipo in ['mecanicos', 'ambos']:
            self.geocodificar_mecanicos(force)
            
        self.stdout.write(
            self.style.SUCCESS('✅ Geocodificación completada')
        )

    def geocodificar_talleres(self, force=False):
        """Geocodifica las direcciones de todos los talleres"""
        self.stdout.write('🏪 Procesando talleres...')
        
        talleres = Taller.objects.all()
        
        if not force:
            # Crear un polígono pequeño alrededor de Santiago centro para identificar coordenadas por defecto
            santiago_center = Point(-70.6693, -33.4489)  # Coordenadas por defecto
            # Crear un área pequeña alrededor del punto por defecto (aproximadamente 100m de radio)
            bbox = Polygon.from_bbox((-70.6703, -33.4499, -70.6683, -33.4479))
            talleres = talleres.filter(ubicacion__within=bbox)
        
        self.stdout.write(f'📋 Encontrados {talleres.count()} talleres para procesar')
        
        for taller in talleres:
            self.stdout.write(f'🔍 Procesando: {taller.nombre} - {taller.direccion}')
            
            if not taller.direccion or taller.direccion in ['Por definir', '']:
                self.stdout.write(
                    self.style.WARNING(f'⚠️ Saltando {taller.nombre}: sin dirección válida')
                )
                continue
                
            # Geocodificar la dirección
            coordenadas = self.geocodificar_direccion(taller.direccion)
            
            if coordenadas:
                # Actualizar coordenadas del taller
                taller.ubicacion = Point(coordenadas['longitude'], coordenadas['latitude'])
                taller.save(update_fields=['ubicacion'])
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ {taller.nombre}: {coordenadas["latitude"]}, {coordenadas["longitude"]}'
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'❌ No se pudo geocodificar: {taller.direccion}')
                )
                
            # Pausa para no sobrecargar el servicio de geocodificación
            time.sleep(1)

    def geocodificar_mecanicos(self, force=False):
        """Geocodifica las direcciones de todos los mecánicos a domicilio"""
        self.stdout.write('🔧 Procesando mecánicos...')
        
        mecanicos = MecanicoDomicilio.objects.all()
        
        if not force:
            # Crear un polígono pequeño alrededor de Santiago centro para identificar coordenadas por defecto
            bbox = Polygon.from_bbox((-70.6703, -33.4499, -70.6683, -33.4479))
            mecanicos = mecanicos.filter(ubicacion__within=bbox)
        
        self.stdout.write(f'📋 Encontrados {mecanicos.count()} mecánicos para procesar')
        
        for mecanico in mecanicos:
            self.stdout.write(f'🔍 Procesando: {mecanico.nombre} - {mecanico.direccion}')
            
            if not mecanico.direccion or mecanico.direccion in ['Servicio a domicilio', 'Por definir', '']:
                self.stdout.write(
                    self.style.WARNING(f'⚠️ Saltando {mecanico.nombre}: sin dirección válida')
                )
                continue
                
            # Geocodificar la dirección
            coordenadas = self.geocodificar_direccion(mecanico.direccion)
            
            if coordenadas:
                # Actualizar coordenadas del mecánico
                mecanico.ubicacion = Point(coordenadas['longitude'], coordenadas['latitude'])
                mecanico.save(update_fields=['ubicacion'])
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ {mecanico.nombre}: {coordenadas["latitude"]}, {coordenadas["longitude"]}'
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'❌ No se pudo geocodificar: {mecanico.direccion}')
                )
                
            # Pausa para no sobrecargar el servicio de geocodificación
            time.sleep(1)

    def geocodificar_direccion(self, direccion):
        """
        Geocodifica una dirección usando Nominatim (OpenStreetMap)
        Retorna diccionario con latitude/longitude o None si falla
        """
        # Preparar variantes de la dirección para mejorar las posibilidades de éxito
        variantes = self.crear_variantes_direccion(direccion)
        
        for i, direccion_variante in enumerate(variantes):
            try:
                self.stdout.write(f'🌐 Intento {i+1}: {direccion_variante}')
                
                # Usar Nominatim de OpenStreetMap (gratuito)
                url = "https://nominatim.openstreetmap.org/search"
                params = {
                    'q': direccion_variante,
                    'format': 'json',
                    'addressdetails': 1,
                    'limit': 1,
                    'countrycodes': 'cl',  # Solo Chile
                    'accept-language': 'es'
                }
                
                headers = {
                    'User-Agent': 'MecaniMovil-Geocoding/1.0'
                }
                
                response = requests.get(url, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                
                if data and len(data) > 0:
                    resultado = data[0]
                    lat = float(resultado['lat'])
                    lon = float(resultado['lon'])
                    
                    # Validar que las coordenadas estén en Chile
                    if self.es_coordenada_chilena(lat, lon):
                        self.stdout.write(f'✅ Éxito con variante: {direccion_variante}')
                        return {
                            'latitude': lat,
                            'longitude': lon,
                            'display_name': resultado.get('display_name', ''),
                            'source': f'Nominatim (variante {i+1})'
                        }
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'⚠️ Coordenadas fuera de Chile: {lat}, {lon}')
                        )
                else:
                    self.stdout.write(f'⚠️ Sin resultados para: {direccion_variante}')
                
                # Pausa entre intentos
                time.sleep(0.5)
                
            except requests.RequestException as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error de red al geocodificar {direccion_variante}: {e}')
                )
                continue
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error general al geocodificar {direccion_variante}: {e}')
                )
                continue
        
        # Si ninguna variante funcionó
        return None

    def crear_variantes_direccion(self, direccion):
        """Crea múltiples variantes de una dirección para mejorar geocodificación"""
        variantes = []
        direccion_limpia = direccion.strip()
        
        # 1. Dirección original con Chile
        if 'chile' not in direccion_limpia.lower():
            variantes.append(f"{direccion_limpia}, Chile")
        else:
            variantes.append(direccion_limpia)
        
        # 2. Agregar Santiago si no está presente
        if 'santiago' not in direccion_limpia.lower():
            variantes.extend([
                f"{direccion_limpia}, Santiago, Chile",
                f"{direccion_limpia}, Santiago Centro, Chile",
                f"{direccion_limpia}, Santiago de Chile",
            ])
        
        # 3. Variantes con diferentes formatos
        # Intentar sin número si tiene número al final
        if re.search(r'\d+$', direccion_limpia):
            # Si termina en número, probar también solo la calle
            calle = re.sub(r'\s*\d+$', '', direccion_limpia)
            variantes.extend([
                f"{calle}, Santiago, Chile",
                f"{calle}, Chile"
            ])
        
        # 4. Si es una calle específica como "Rondizonni", probar variantes comunes
        palabras = direccion_limpia.split()
        if len(palabras) >= 1:
            primera_palabra = palabras[0]
            # Probar con "Calle" al inicio
            variantes.extend([
                f"Calle {direccion_limpia}, Santiago, Chile",
                f"Avenida {direccion_limpia}, Santiago, Chile",
                f"{primera_palabra}, Santiago, Chile"
            ])
        
        # 5. Remover duplicados manteniendo orden
        variantes_unicas = []
        for variante in variantes:
            if variante not in variantes_unicas:
                variantes_unicas.append(variante)
        
        return variantes_unicas

    def es_coordenada_chilena(self, lat, lon):
        """Verifica si las coordenadas están dentro de Chile"""
        # Límites aproximados de Chile
        return (
            -56 <= lat <= -17.5 and  # Latitud
            -80 <= lon <= -66        # Longitud
        ) 
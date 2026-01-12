"""
Comando de Django para procesar créditos de ofertas adjudicadas históricas.

Este comando busca ofertas que fueron adjudicadas antes de la implementación
del sistema de consumo de créditos al adjudicar, y procesa los créditos correspondientes.

Uso:
    python manage.py procesar_creditos_ofertas_adjudicadas
    python manage.py procesar_creditos_ofertas_adjudicadas --dry-run  # Para ver qué se haría sin hacer cambios
    python manage.py procesar_creditos_ofertas_adjudicadas --proveedor-id=123  # Para procesar solo un proveedor
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.exceptions import ValidationError
from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, OfertaProveedor
from mecanimovilapp.apps.suscripciones.models import ConsumoCredito
from mecanimovilapp.apps.suscripciones.creditos_services import (
    consumir_creditos_adjudicacion,
    validar_creditos_suficientes
)
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Procesa créditos de ofertas adjudicadas que no tienen créditos consumidos'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Ejecuta el comando sin hacer cambios reales en la base de datos',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Ejecuta sin pedir confirmación',
        )
        parser.add_argument(
            '--proveedor-id',
            type=int,
            help='Procesar solo ofertas de un proveedor específico (ID)',
        )
        parser.add_argument(
            '--solo-validar',
            action='store_true',
            help='Solo valida créditos disponibles sin consumirlos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        proveedor_id = options.get('proveedor_id')
        solo_validar = options['solo_validar']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 MODO DRY RUN: No se harán cambios reales'))
        
        if solo_validar:
            self.stdout.write(self.style.WARNING('🔍 MODO SOLO VALIDACIÓN: No se consumirán créditos'))
        
        self.stdout.write('🔍 Buscando ofertas adjudicadas sin créditos consumidos...')
        
        # Buscar ofertas que:
        # 1. Están en estado 'aceptada' o asociadas a solicitudes 'adjudicada'
        # 2. No son ofertas secundarias
        # 3. No tienen un ConsumoCredito asociado
        # 4. Tienen detalles de servicios
        
        ofertas_query = OfertaProveedor.objects.filter(
            estado='aceptada',
            es_oferta_secundaria=False
        ).exclude(
            consumos_credito__isnull=False  # Excluir las que ya tienen consumo
        ).select_related(
            'proveedor', 
            'solicitud',
            'solicitud__cliente'
        ).prefetch_related(
            'detalles_servicios__servicio'
        )
        
        # Filtrar por proveedor si se especifica
        if proveedor_id:
            ofertas_query = ofertas_query.filter(proveedor_id=proveedor_id)
            self.stdout.write(f'🔍 Filtrando por proveedor ID: {proveedor_id}')
        
        # También buscar ofertas asociadas a solicitudes adjudicadas (por si acaso)
        solicitudes_adjudicadas = SolicitudServicioPublica.objects.filter(
            estado='adjudicada',
            oferta_seleccionada__isnull=False
        ).select_related('oferta_seleccionada')
        
        if proveedor_id:
            solicitudes_adjudicadas = solicitudes_adjudicadas.filter(
                oferta_seleccionada__proveedor_id=proveedor_id
            )
        
        # Obtener IDs de ofertas de solicitudes adjudicadas
        ofertas_de_solicitudes = {
            sol.oferta_seleccionada.id 
            for sol in solicitudes_adjudicadas 
            if sol.oferta_seleccionada and not sol.oferta_seleccionada.es_oferta_secundaria
        }
        
        # Combinar ambas fuentes
        ofertas_ids = set(ofertas_query.values_list('id', flat=True)) | ofertas_de_solicitudes
        
        # Obtener ofertas finales
        ofertas = OfertaProveedor.objects.filter(
            id__in=ofertas_ids,
            es_oferta_secundaria=False
        ).exclude(
            consumos_credito__isnull=False
        ).select_related(
            'proveedor',
            'solicitud',
            'solicitud__cliente'
        ).prefetch_related(
            'detalles_servicios__servicio'
        )
        
        total_encontradas = ofertas.count()
        self.stdout.write(f'📊 Encontradas {total_encontradas} ofertas adjudicadas sin créditos consumidos')
        
        if total_encontradas == 0:
            self.stdout.write(self.style.SUCCESS('✅ No hay ofertas adjudicadas que procesar'))
            return
        
        # Analizar cada oferta
        self.stdout.write('\n📋 Detalle de ofertas a procesar:')
        ofertas_validas = []
        ofertas_con_problemas = []
        
        for oferta in ofertas:
            detalles_servicios = list(oferta.detalles_servicios.all())
            
            if not detalles_servicios:
                ofertas_con_problemas.append((oferta, 'Sin detalles de servicios'))
                continue
            
            servicio_principal = detalles_servicios[0].servicio
            
            # Validar créditos disponibles
            try:
                puede, mensaje, creditos_necesarios = validar_creditos_suficientes(
                    oferta.proveedor,
                    servicio_principal
                )
                
                estado_solicitud = oferta.solicitud.estado if oferta.solicitud else 'N/A'
                
                if puede:
                    ofertas_validas.append({
                        'oferta': oferta,
                        'servicio': servicio_principal,
                        'creditos_necesarios': creditos_necesarios
                    })
                    self.stdout.write(
                        f'  ✅ Oferta #{oferta.id} - '
                        f'Proveedor: {oferta.proveedor.username or oferta.proveedor.email} - '
                        f'Solicitud: {oferta.solicitud.id if oferta.solicitud else "N/A"} ({estado_solicitud}) - '
                        f'Créditos necesarios: {creditos_necesarios} - '
                        f'Servicio: {servicio_principal.nombre}'
                    )
                else:
                    ofertas_con_problemas.append((oferta, f'Sin créditos suficientes: {mensaje}'))
                    self.stdout.write(
                        self.style.WARNING(
                            f'  ⚠️  Oferta #{oferta.id} - '
                            f'Proveedor: {oferta.proveedor.username or oferta.proveedor.email} - '
                            f'PROBLEMA: {mensaje}'
                        )
                    )
            except Exception as e:
                ofertas_con_problemas.append((oferta, f'Error validando: {str(e)}'))
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ Oferta #{oferta.id} - ERROR: {str(e)}'
                    )
                )
        
        if ofertas_con_problemas:
            self.stdout.write(f'\n⚠️  {len(ofertas_con_problemas)} ofertas con problemas (no se procesarán)')
        
        if not ofertas_validas:
            self.stdout.write(self.style.WARNING('\n⚠️  No hay ofertas válidas para procesar'))
            return
        
        if solo_validar:
            self.stdout.write(self.style.SUCCESS(f'\n✅ Validación completada: {len(ofertas_validas)} ofertas pueden procesarse'))
            return
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️  DRY RUN: No se realizaron cambios'))
            return
        
        # Confirmar antes de continuar
        if not force:
            self.stdout.write(f'\n⚠️  Se van a consumir créditos para {len(ofertas_validas)} ofertas')
            respuesta = input('¿Deseas continuar? (s/n): ')
            
            if respuesta.lower() != 's':
                self.stdout.write(self.style.WARNING('❌ Operación cancelada'))
                return
        
        # Procesar las ofertas válidas
        self.stdout.write('\n🔄 Procesando créditos de ofertas...')
        
        procesadas = 0
        errores = 0
        
        for item in ofertas_validas:
            oferta = item['oferta']
            servicio = item['servicio']
            creditos_necesarios = item['creditos_necesarios']
            
            try:
                with transaction.atomic():
                    # Consumir créditos
                    consumo = consumir_creditos_adjudicacion(
                        proveedor=oferta.proveedor,
                        oferta=oferta,
                        servicio=servicio
                    )
                    
                    procesadas += 1
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✅ Oferta #{oferta.id} procesada - '
                            f'Créditos consumidos: {consumo.creditos_consumidos} - '
                            f'Proveedor: {oferta.proveedor.username or oferta.proveedor.email}'
                        )
                    )
            except ValidationError as e:
                errores += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ Error procesando oferta #{oferta.id}: {str(e)}'
                    )
                )
            except Exception as e:
                errores += 1
                logger.error(f"Error procesando oferta {oferta.id}: {e}", exc_info=True)
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ Error inesperado procesando oferta #{oferta.id}: {str(e)}'
                    )
                )
        
        # Resumen
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'✅ Proceso completado'))
        self.stdout.write(f'📊 Ofertas procesadas: {procesadas}')
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'❌ Errores: {errores}'))
        if ofertas_con_problemas:
            self.stdout.write(self.style.WARNING(f'⚠️  Ofertas con problemas: {len(ofertas_con_problemas)}'))
        self.stdout.write('='*60)

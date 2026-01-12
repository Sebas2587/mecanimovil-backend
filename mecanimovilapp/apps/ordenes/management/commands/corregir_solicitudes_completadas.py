"""
Script para corregir solicitudes que fueron incorrectamente canceladas
cuando en realidad tenían ofertas pagadas o completadas.

Uso:
    python manage.py corregir_solicitudes_completadas --dry-run  # Ver qué se haría sin hacer cambios
    python manage.py corregir_solicitudes_completadas             # Aplicar correcciones
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, OfertaProveedor
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Corrige solicitudes que fueron incorrectamente canceladas cuando tenían ofertas completadas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar qué se haría sin hacer cambios reales',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.NOTICE('\n' + '='*70))
        self.stdout.write(self.style.NOTICE('CORRECCIÓN DE SOLICITUDES INCORRECTAMENTE CANCELADAS'))
        self.stdout.write(self.style.NOTICE('='*70 + '\n'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  MODO DRY-RUN: No se harán cambios reales\n'))
        
        # Estados que indican que una oferta fue procesada exitosamente
        ESTADOS_OFERTA_EXITOSOS = ['pagada', 'en_ejecucion', 'completada']
        
        # Buscar solicitudes canceladas que tienen ofertas en estados exitosos
        solicitudes_canceladas = SolicitudServicioPublica.objects.filter(
            estado='cancelada'
        ).prefetch_related('ofertas')
        
        solicitudes_a_corregir = []
        
        for solicitud in solicitudes_canceladas:
            # Obtener ofertas exitosas de esta solicitud
            ofertas_exitosas = OfertaProveedor.objects.filter(
                solicitud=solicitud,
                estado__in=ESTADOS_OFERTA_EXITOSOS
            )
            
            if ofertas_exitosas.exists():
                # Determinar el estado correcto basado en las ofertas
                ofertas_completadas = ofertas_exitosas.filter(estado='completada')
                ofertas_en_ejecucion = ofertas_exitosas.filter(estado='en_ejecucion')
                ofertas_pagadas = ofertas_exitosas.filter(estado='pagada')
                
                if ofertas_completadas.exists():
                    nuevo_estado = 'completada'
                elif ofertas_en_ejecucion.exists():
                    nuevo_estado = 'en_ejecucion'
                elif ofertas_pagadas.exists():
                    nuevo_estado = 'pagada'
                else:
                    nuevo_estado = 'pagada'  # Fallback
                
                solicitudes_a_corregir.append({
                    'solicitud': solicitud,
                    'nuevo_estado': nuevo_estado,
                    'ofertas_exitosas': list(ofertas_exitosas.values('id', 'estado', 'precio_total_ofrecido')),
                    'total_ofertas_exitosas': ofertas_exitosas.count()
                })
        
        # Mostrar resumen
        self.stdout.write(f'\n📊 RESUMEN:')
        self.stdout.write(f'   - Total solicitudes canceladas: {solicitudes_canceladas.count()}')
        self.stdout.write(f'   - Solicitudes a corregir: {len(solicitudes_a_corregir)}\n')
        
        if not solicitudes_a_corregir:
            self.stdout.write(self.style.SUCCESS('\n✅ No hay solicitudes que necesiten corrección\n'))
            return
        
        # Mostrar detalles de cada solicitud a corregir
        self.stdout.write(self.style.NOTICE('\n📋 DETALLE DE SOLICITUDES A CORREGIR:\n'))
        for item in solicitudes_a_corregir:
            solicitud = item['solicitud']
            self.stdout.write(f'   📄 Solicitud ID: {solicitud.id}')
            self.stdout.write(f'      Estado actual: cancelada → Nuevo estado: {item["nuevo_estado"]}')
            self.stdout.write(f'      Cliente: {solicitud.cliente.usuario.username if solicitud.cliente and solicitud.cliente.usuario else "N/A"}')
            self.stdout.write(f'      Ofertas exitosas: {item["total_ofertas_exitosas"]}')
            for oferta in item['ofertas_exitosas']:
                self.stdout.write(f'         - Oferta {oferta["id"]}: {oferta["estado"]} (${oferta["precio_total_ofrecido"]})')
            self.stdout.write('')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\n⚠️  Se corregirían {len(solicitudes_a_corregir)} solicitudes\n'
                f'   Ejecuta sin --dry-run para aplicar los cambios\n'
            ))
            return
        
        # Aplicar correcciones
        self.stdout.write(self.style.NOTICE('\n🔧 APLICANDO CORRECCIONES...\n'))
        
        corregidas = 0
        errores = 0
        
        for item in solicitudes_a_corregir:
            solicitud = item['solicitud']
            nuevo_estado = item['nuevo_estado']
            
            try:
                with transaction.atomic():
                    estado_anterior = solicitud.estado
                    solicitud.estado = nuevo_estado
                    solicitud.save(update_fields=['estado'])
                    
                    corregidas += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'   ✅ Solicitud {solicitud.id}: {estado_anterior} → {nuevo_estado}'
                    ))
                    
                    logger.info(
                        f"Solicitud {solicitud.id} corregida: {estado_anterior} → {nuevo_estado} "
                        f"(tenía {item['total_ofertas_exitosas']} ofertas exitosas)"
                    )
                    
            except Exception as e:
                errores += 1
                self.stdout.write(self.style.ERROR(
                    f'   ❌ Error corrigiendo solicitud {solicitud.id}: {str(e)}'
                ))
                logger.error(f"Error corrigiendo solicitud {solicitud.id}: {e}", exc_info=True)
        
        # Resumen final
        self.stdout.write(self.style.NOTICE('\n' + '='*70))
        self.stdout.write(self.style.NOTICE('RESUMEN FINAL'))
        self.stdout.write(self.style.NOTICE('='*70))
        self.stdout.write(self.style.SUCCESS(f'\n   ✅ Solicitudes corregidas: {corregidas}'))
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'   ❌ Errores: {errores}'))
        self.stdout.write('')

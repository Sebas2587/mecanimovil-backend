"""Spike: validar qué tiendas chilenas puede leer Gemini url_context.

Uso:
  python manage.py probar_busqueda_web_repuestos \\
    --marca Hyundai --modelo Accent --anio 2015 \\
    --repuestos "kit embrague,disco embrague" \\
    --servicio "Cambio de embrague"

  python manage.py probar_busqueda_web_repuestos --patente XX1111 --repuestos "bujias"
"""
from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Prueba Gemini URL Context contra plantillas de tiendas (sin persistir).'

    def add_arguments(self, parser):
        parser.add_argument('--patente', default='', help='Patente para enriquecer vehículo')
        parser.add_argument('--marca', default='')
        parser.add_argument('--modelo', default='')
        parser.add_argument('--anio', default='')
        parser.add_argument('--cilindraje', default='')
        parser.add_argument('--servicio', default='')
        parser.add_argument(
            '--repuestos',
            default='kit embrague',
            help='Lista separada por comas',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Ignora BUSQUEDA_WEB_REPUESTOS_ENABLED (igual requiere GEMINI_API_KEY)',
        )

    def handle(self, *args, **options):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion import (
            busqueda_web_repuestos as bw,
        )

        marca = (options.get('marca') or '').strip()
        modelo = (options.get('modelo') or '').strip()
        anio = (options.get('anio') or '').strip()
        cilindraje = (options.get('cilindraje') or '').strip()
        patente = (options.get('patente') or '').strip().upper()
        servicio = (options.get('servicio') or '').strip()
        repuestos = [
            p.strip() for p in str(options.get('repuestos') or '').split(',') if p.strip()
        ]

        if patente:
            try:
                from mecanimovilapp.apps.vehiculos.getapi_client import fetch_plate_basic_info

                info = fetch_plate_basic_info(patente) or {}
                marca = marca or str(info.get('marca_nombre') or info.get('marca') or '')
                modelo = modelo or str(info.get('modelo_nombre') or info.get('modelo') or '')
                cilindraje = cilindraje or str(info.get('cilindraje') or '')
                self.stdout.write(f'Patente {patente}: {marca} {modelo} {cilindraje}'.strip())
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f'No se pudo enriquecer patente: {exc}'))

        urls = bw.construir_urls_busqueda(
            repuestos,
            marca=marca,
            modelo=modelo,
            anio=anio,
            cilindraje=cilindraje,
        )
        self.stdout.write(self.style.NOTICE('URLs construidas:'))
        for u in urls:
            self.stdout.write(f'  - {u}')

        if not (getattr(settings, 'GEMINI_API_KEY', '') or '').strip():
            self.stderr.write(self.style.ERROR('Falta GEMINI_API_KEY'))
            return

        if not options.get('force') and not bw.busqueda_web_habilitada():
            self.stderr.write(
                self.style.WARNING(
                    'BUSQUEDA_WEB_REPUESTOS_ENABLED=False. Usa --force para probar igual.',
                ),
            )
            return

        # Forzar enabled temporalmente para el spike.
        prev = getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_ENABLED', False)
        try:
            if options.get('force'):
                settings.BUSQUEDA_WEB_REPUESTOS_ENABLED = True
            resultados = bw.buscar_repuestos_web(
                repuestos,
                vehiculo={
                    'marca': marca,
                    'modelo': modelo,
                    'anio': anio,
                    'cilindraje': cilindraje,
                },
                servicio_nombre=servicio,
            )
        finally:
            settings.BUSQUEDA_WEB_REPUESTOS_ENABLED = prev

        self.stdout.write(self.style.NOTICE('Resultados validados:'))
        self.stdout.write(json.dumps(resultados, ensure_ascii=False, indent=2))
        if not resultados:
            self.stdout.write(
                self.style.WARNING(
                    'Sin resultados. Revisa url_retrieval_status (algunas tiendas pueden no ser legibles).',
                ),
            )
        else:
            self.stdout.write(self.style.SUCCESS(f'{len(resultados)} clave(s) con hit válido'))

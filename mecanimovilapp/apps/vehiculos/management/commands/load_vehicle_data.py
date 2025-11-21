import json
import os
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo

class Command(BaseCommand):
    help = 'Carga datos iniciales de marcas y modelos de vehículos'

    def handle(self, *args, **options):
        # Datos de marcas y modelos
        marcas_data = [
            {
                "nombre": "Toyota",
                "modelos": ["Corolla", "Camry", "RAV4", "Hilux", "Land Cruiser", "Yaris"]
            },
            {
                "nombre": "Honda",
                "modelos": ["Civic", "Accord", "CR-V", "HR-V", "Pilot", "Fit"]
            },
            {
                "nombre": "Nissan",
                "modelos": ["Sentra", "Versa", "Altima", "X-Trail", "Kicks", "Juke"]
            },
            {
                "nombre": "Volkswagen",
                "modelos": ["Jetta", "Golf", "Polo", "Tiguan", "Touareg", "Vento"]
            },
            {
                "nombre": "Chevrolet",
                "modelos": ["Aveo", "Spark", "Cruze", "Trax", "Equinox", "Silverado"]
            },
            {
                "nombre": "Ford",
                "modelos": ["Fiesta", "Focus", "Escape", "Explorer", "Ranger", "Mustang"]
            },
            {
                "nombre": "Hyundai",
                "modelos": ["Accent", "Elantra", "Tucson", "Santa Fe", "i10", "i20"]
            },
            {
                "nombre": "Kia",
                "modelos": ["Rio", "Forte", "Sportage", "Sorento", "Soul", "Seltos"]
            },
            {
                "nombre": "Mazda",
                "modelos": ["Mazda2", "Mazda3", "Mazda6", "CX-3", "CX-5", "CX-9"]
            },
            {
                "nombre": "BMW",
                "modelos": ["Serie 1", "Serie 3", "Serie 5", "X1", "X3", "X5"]
            },
            {
                "nombre": "Mercedes-Benz",
                "modelos": ["Clase A", "Clase C", "Clase E", "GLA", "GLC", "GLE"]
            },
            {
                "nombre": "Audi",
                "modelos": ["A1", "A3", "A4", "Q3", "Q5", "Q7"]
            }
        ]

        # Crear marcas y modelos
        marcas_creadas = 0
        modelos_creados = 0

        for marca_data in marcas_data:
            marca, created = Marca.objects.get_or_create(nombre=marca_data["nombre"])
            if created:
                marcas_creadas += 1
                self.stdout.write(self.style.SUCCESS(f'Marca creada: {marca.nombre}'))
            
            # Crear modelos para esta marca
            for modelo_nombre in marca_data["modelos"]:
                modelo, created = Modelo.objects.get_or_create(
                    nombre=modelo_nombre,
                    marca=marca
                )
                if created:
                    modelos_creados += 1
        
        self.stdout.write(self.style.SUCCESS(
            f'Datos cargados con éxito: {marcas_creadas} marcas y {modelos_creados} modelos creados'
        )) 
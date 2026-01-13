from django.db import models
from django.utils.translation import gettext_lazy as _
from mecanimovilapp.apps.usuarios.models import Cliente


class MarcaVehiculo(models.Model):
    """
    Modelo para las marcas de vehículos
    """
    nombre = models.CharField(max_length=50, unique=True)
    logo = models.ImageField(upload_to='marcas/', blank=True, null=True, help_text="Logo de la marca")
    
    class Meta:
        verbose_name = _('marca de vehículo')
        verbose_name_plural = _('marcas de vehículos')
        ordering = ['nombre']
    
    def __str__(self):
        return self.nombre


# Mantenemos Marca para compatibilidad con código existente
class Marca(MarcaVehiculo):
    class Meta:
        proxy = True
        verbose_name = _('marca')
        verbose_name_plural = _('marcas')


class Modelo(models.Model):
    """
    Modelo para los modelos de vehículos asociados a una marca
    """
    nombre = models.CharField(max_length=100)
    marca = models.ForeignKey(
        MarcaVehiculo, 
        on_delete=models.CASCADE, 
        related_name='modelos'
    )
    
    class Meta:
        verbose_name = _('modelo')
        verbose_name_plural = _('modelos')
        ordering = ['nombre']
        unique_together = ['nombre', 'marca']
    
    def __str__(self):
        return f"{self.marca} - {self.nombre}"


class Vehiculo(models.Model):
    """
    Modelo para los vehículos de los clientes
    """
    TIPO_MOTOR_CHOICES = [
        ('Gasolina', 'Gasolina'),
        ('Diésel', 'Diésel'),
    ]
    
    marca = models.ForeignKey(
        MarcaVehiculo, 
        on_delete=models.PROTECT, 
        related_name='vehiculos'
    )
    modelo = models.ForeignKey(
        Modelo, 
        on_delete=models.PROTECT, 
        related_name='vehiculos'
    )
    cilindraje = models.CharField(max_length=50, blank=True, null=True)
    tipo_motor = models.CharField(
        max_length=20, 
        choices=TIPO_MOTOR_CHOICES, 
        default='Gasolina'
    )
    year = models.IntegerField(verbose_name=_('año'), default=2024)
    patente = models.CharField(max_length=20, unique=True)
    kilometraje = models.PositiveIntegerField(default=0)
    foto = models.ImageField(
        upload_to='vehiculos/', 
        blank=True, 
        null=True
    )
    cliente = models.ForeignKey(
        Cliente, 
        on_delete=models.CASCADE, 
        related_name='vehiculos'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, null=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True, null=True)
    
    class Meta:
        verbose_name = _('vehículo')
        verbose_name_plural = _('vehículos')
        ordering = ['-fecha_actualizacion']
    
    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.patente})"
    
    @property
    def marca_nombre(self):
        return self.marca.nombre
    
    @property
    def modelo_nombre(self):
        return self.modelo.nombre 
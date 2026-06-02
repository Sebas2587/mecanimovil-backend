from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo

TIPOS_MOTOR_COMPATIBLES_VALIDOS = ('GASOLINA', 'DIESEL', 'ELECTRICO', 'HIBRIDO')


class CategoriaServicio(models.Model):
    """
    Modelo para las categorías de servicios
    Con soporte para jerarquía (categorías y subcategorías)
    """
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True, help_text=_('Descripción opcional de la categoría'))
    icono = models.CharField(max_length=50, blank=True, null=True, help_text=_('Nombre del ícono para representar la categoría'))
    
    # Campo para la jerarquía de categorías
    categoria_padre = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subcategorias',
        verbose_name=_('categoría padre'),
        help_text=_('Categoría principal a la que pertenece esta subcategoría')
    )
    
    orden = models.PositiveIntegerField(default=0, help_text=_('Orden de aparición de la categoría'))
    
    class Meta:
        verbose_name = _('categoría de servicio')
        verbose_name_plural = _('categorías de servicios')
        ordering = ['orden', 'nombre']
    
    def __str__(self):
        if self.categoria_padre:
            return f"{self.nombre} ({self.categoria_padre.nombre})"
        return self.nombre
    
    @property
    def es_categoria_principal(self):
        """Indica si es una categoría principal (sin padre)"""
        return self.categoria_padre is None
    
    @property
    def tiene_subcategorias(self):
        """Indica si la categoría tiene subcategorías"""
        return self.subcategorias.exists()


class Servicio(models.Model):
    """
    Modelo para los servicios ofrecidos, refactorizado
    """
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)
    duracion_estimada_base = models.DurationField(
        blank=True, 
        null=True,
        help_text=_('Tiempo base estimado para realizar el servicio')
    )
    calificacion_promedio = models.FloatField(default=0.0)
    foto = models.ImageField(upload_to='servicios/', blank=True, null=True)
    
    # Relaciones
    categorias = models.ManyToManyField(
        CategoriaServicio, 
        related_name='servicios'
    )
    
    # Compatibilidad por marca (regla principal; configurar en Django Admin)
    marcas_compatibles = models.ManyToManyField(
        'vehiculos.MarcaVehiculo',
        related_name='servicios_compatibles',
        blank=True,
        verbose_name=_('marcas compatibles'),
        help_text=_(
            'Marcas de vehículos con las que este servicio es compatible. '
            'Si no se restringen modelos, aplica a todos los modelos de la marca.'
        ),
    )

    # Restricción opcional por modelo (dentro de las marcas asociadas)
    modelos_compatibles = models.ManyToManyField(
        'vehiculos.Modelo',
        related_name='servicios_compatibles',
        blank=True,
        verbose_name=_('modelos compatibles'),
        help_text=_(
            'Opcional: limita el servicio a modelos concretos de las marcas asociadas. '
            'Si está vacío, aplica a todos los modelos de las marcas compatibles.'
        ),
    )

    tipos_motor_compatibles = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_('tipos de motor compatibles'),
        help_text=_(
            'Vacío = todos los motores. Ej: ["GASOLINA"] solo bencinero; '
            '["GASOLINA","DIESEL"] ambos combustión.'
        ),
    )
    
    # Relaciones entre servicios
    servicios_relacionados = models.ManyToManyField(
        'self', 
        symmetrical=False,
        related_name='servicios_que_me_relacionan',
        blank=True
    )
    
    # Nueva información para gestión de precios
    requiere_repuestos = models.BooleanField(
        default=True,
        help_text=_('Indica si el servicio normalmente requiere repuestos')
    )
    precio_referencia = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text=_('Precio de referencia general'),
        default=0
    )
    
    class Meta:
        verbose_name = _('servicio')
        verbose_name_plural = _('servicios')
    
    def __str__(self):
        return self.nombre
    
    @property
    def talleres_disponibles(self):
        """Devuelve los talleres que ofrecen este servicio"""
        return Taller.objects.filter(ofertas_servicio__servicio=self, ofertas_servicio__disponible=True)
    
    @property
    def mecanicos_disponibles(self):
        """Devuelve los mecánicos que ofrecen este servicio"""
        return MecanicoDomicilio.objects.filter(ofertas_servicio__servicio=self, ofertas_servicio__disponible=True)
    
    @property
    def precio_minimo(self):
        """Devuelve el precio mínimo disponible para este servicio"""
        min_precio = OfertaServicio.objects.filter(
            servicio=self, 
            disponible=True
        ).order_by('precio_sin_repuestos').first()
        
        if min_precio:
            return min_precio.precio_sin_repuestos
        return self.precio_referencia


class OfertaServicio(models.Model):
    """
    Modelo unificado que representa la oferta de un servicio por un proveedor
    (taller o mecánico), incluyendo disponibilidad y precios.
    
    Este modelo reemplaza a:
    - ServicioTaller
    - ServicioMecanico
    - PrecioServicioTaller
    - PrecioServicioMecanico
    """
    TIPO_PROVEEDOR_CHOICES = [
        ('taller', 'Taller'),
        ('mecanico', 'Mecánico a Domicilio'),
    ]
    
    # Relaciones polimórficas con los proveedores
    tipo_proveedor = models.CharField(
        max_length=10,
        choices=TIPO_PROVEEDOR_CHOICES
    )
    taller = models.ForeignKey(
        Taller,
        on_delete=models.CASCADE,
        related_name='ofertas_servicio',
        null=True,
        blank=True
    )
    mecanico = models.ForeignKey(
        MecanicoDomicilio,
        on_delete=models.CASCADE,
        related_name='ofertas_servicio',
        null=True,
        blank=True
    )
    
    # Servicio ofrecido
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.CASCADE,
        related_name='ofertas'
    )
    
    # Marca del vehículo para la cual se ofrece este servicio específico
    marca_vehiculo_seleccionada = models.ForeignKey(
        'vehiculos.MarcaVehiculo',
        on_delete=models.CASCADE,
        related_name='ofertas_servicio',
        null=True,
        blank=True,
        help_text=_('Marca de vehículo específica para la cual el proveedor ofrece este servicio')
    )

    # Vacío = todos los motores del catálogo del servicio; valor = motor específico de esta oferta
    tipo_motor = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name=_('tipo de motor'),
        help_text=_(
            'Vacío: aplica a todos los motores compatibles del servicio. '
            'Ej. GASOLINA o DIESEL para precio/repuestos distintos por motor.'
        ),
    )
    
    # Control de disponibilidad
    disponible = models.BooleanField(default=True)
    duracion_estimada = models.TimeField(
        blank=True,
        null=True,
        help_text=_('Legacy: hora estimada (HH:MM). Preferir duracion_minima/maxima_minutos.'),
    )
    duracion_minima_minutos = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_('Tiempo mínimo estimado para realizar el servicio (minutos)'),
    )
    duracion_maxima_minutos = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_('Tiempo máximo estimado para bloquear agenda y calcular ventanas libres'),
    )
    
    # Precios con validadores mejorados
    precio_con_repuestos = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[
            MinValueValidator(0, message='El precio no puede ser negativo'),
        ]
    )
    precio_sin_repuestos = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[
            MinValueValidator(0, message='El precio no puede ser negativo'),
        ]
    )
    
    # Información adicional
    incluye_garantia = models.BooleanField(default=True)
    duracion_garantia = models.PositiveIntegerField(
        default=30,
        help_text=_('Duración de la garantía en días')
    )
    detalles_adicionales = models.TextField(blank=True, null=True)
    
    # NUEVOS CAMPOS PARA GESTIÓN AVANZADA DE SERVICIOS
    TIPO_SERVICIO_CHOICES = [
        ('con_repuestos', 'Servicio con repuestos'),
        ('sin_repuestos', 'Servicio sin repuestos'),
    ]
    
    tipo_servicio = models.CharField(
        max_length=20,
        choices=TIPO_SERVICIO_CHOICES,
        default='con_repuestos',
        help_text=_('Tipo de servicio ofrecido')
    )
    
    # Repuestos seleccionados (JSON para flexibilidad)
    repuestos_seleccionados = models.JSONField(
        default=list,
        blank=True,
        help_text=_('Lista de repuestos específicos seleccionados para este servicio')
    )
    
    # Campos de costos detallados
    costo_mano_de_obra_sin_iva = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text=_('Costo de mano de obra sin incluir IVA')
    )
    
    costo_repuestos_sin_iva = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text=_('Costo total de repuestos sin incluir IVA')
    )
    
    # URLs de fotos del servicio
    fotos_urls = models.JSONField(
        default=list,
        blank=True,
        help_text=_('URLs de fotos asociadas al servicio')
    )
    
    # Campos calculados automáticamente
    precio_publicado_cliente = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text=_('Precio final que verá el cliente (con IVA)')
    )
    
    comision_mecanmovil = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text=_('Comisión del 20% para la plataforma')
    )
    
    iva_sobre_comision = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text=_('IVA del 19% sobre la comisión')
    )
    
    ganancia_neta_proveedor = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text=_('Ganancia final del proveedor después de comisión')
    )
    
    # Campos para timestamping
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('oferta de servicio')
        verbose_name_plural = _('ofertas de servicios')
        unique_together = [
            ['taller', 'servicio', 'marca_vehiculo_seleccionada', 'tipo_motor'],
            ['mecanico', 'servicio', 'marca_vehiculo_seleccionada', 'tipo_motor'],
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(tipo_proveedor='taller', taller__isnull=False, mecanico__isnull=True) |
                    models.Q(tipo_proveedor='mecanico', taller__isnull=True, mecanico__isnull=False)
                ),
                name='oferta_servicio_taller_o_mecanico'
            ),
            models.CheckConstraint(
                check=models.Q(precio_sin_repuestos__lte=models.F('precio_con_repuestos')),
                name='precio_sin_repuestos_menor_igual_que_con_repuestos'
            )
        ]
    
    def __str__(self):
        proveedor = self.taller.nombre if self.taller else self.mecanico.nombre
        return f"{proveedor} - {self.servicio.nombre}: ${self.precio_con_repuestos}"
    
    def clean(self):
        """
        Validaciones adicionales que no se pueden expresar con constraints de base de datos
        """
        from django.core.exceptions import ValidationError
        
        if self.taller is None and self.mecanico is None:
            raise ValidationError('Debe especificar un taller o un mecánico')
        
        if self.taller is not None and self.mecanico is not None:
            raise ValidationError('No puede especificar un taller y un mecánico simultáneamente')
        
        if self.taller is not None and self.tipo_proveedor != 'taller':
            raise ValidationError('El tipo de proveedor debe ser "taller" cuando se especifica un taller')
            
        if self.mecanico is not None and self.tipo_proveedor != 'mecanico':
            raise ValidationError('El tipo de proveedor debe ser "mecanico" cuando se especifica un mecánico')
    
    def calcular_precios(self):
        """
        Calcula automáticamente todos los campos de precios y comisiones
        """
        from decimal import Decimal
        
        # Constantes de cálculo
        IVA_RATE = Decimal('0.19')  # 19%
        COMISION_RATE = Decimal('0.20')  # 20%
        
        # Costo total sin IVA
        costo_total_sin_iva = self.costo_mano_de_obra_sin_iva + self.costo_repuestos_sin_iva
        
        # IVA sobre el costo total
        iva = costo_total_sin_iva * IVA_RATE
        
        # Precio final cliente (con IVA)
        self.precio_publicado_cliente = costo_total_sin_iva + iva
        
        # Comisión MecaniMóvil (sobre costo sin IVA)
        self.comision_mecanmovil = costo_total_sin_iva * COMISION_RATE
        
        # IVA sobre la comisión
        self.iva_sobre_comision = self.comision_mecanmovil * IVA_RATE
        
        # Ganancia neta del proveedor
        self.ganancia_neta_proveedor = costo_total_sin_iva - self.comision_mecanmovil
        
        # Actualizar precios legacy para compatibilidad
        if self.tipo_servicio == 'con_repuestos':
            self.precio_con_repuestos = self.precio_publicado_cliente
            self.precio_sin_repuestos = self.costo_mano_de_obra_sin_iva + (self.costo_mano_de_obra_sin_iva * IVA_RATE)
        else:
            self.precio_sin_repuestos = self.precio_publicado_cliente
            self.precio_con_repuestos = self.precio_publicado_cliente

    def save(self, *args, **kwargs):
        # Calcular precios automáticamente antes de guardar
        self.calcular_precios()
        self.clean()
        super().save(*args, **kwargs)
    
    @property
    def proveedor(self):
        """Devuelve el proveedor (taller o mecánico) correspondiente"""
        return self.taller if self.taller else self.mecanico
    
    @property
    def nombre_proveedor(self):
        """Devuelve el nombre del proveedor"""
        if self.taller:
            return self.taller.nombre
        return self.mecanico.nombre


class DetalleServicio(models.Model):
    """
    Modelo para los detalles adicionales de un servicio
    """
    servicio = models.ForeignKey(
        Servicio, 
        on_delete=models.CASCADE, 
        related_name='detalles'
    )
    caracteristica = models.CharField(max_length=255)
    
    class Meta:
        verbose_name = _('detalle de servicio')
        verbose_name_plural = _('detalles de servicios')
    
    def __str__(self):
        return f"{self.servicio.nombre} - {self.caracteristica}"


class Repuesto(models.Model):
    """
    Modelo para los repuestos utilizados en los servicios
    """
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)
    codigo_fabricante = models.CharField(max_length=100, blank=True, null=True)
    marca = models.CharField(max_length=100, blank=True, null=True)
    precio_referencia = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text=_('Precio de referencia del repuesto')
    )
    foto = models.ImageField(upload_to='repuestos/', blank=True, null=True)
    
    # Categorización de repuestos
    categoria_repuesto = models.CharField(
        max_length=50,
        choices=[
            ('filtros', 'Filtros'),
            ('aceites', 'Aceites y Lubricantes'),
            ('frenos', 'Sistema de Frenos'),
            ('motor', 'Motor'),
            ('transmision', 'Transmisión'),
            ('suspension', 'Suspensión'),
            ('electrico', 'Sistema Eléctrico'),
            ('carroceria', 'Carrocería'),
            ('otros', 'Otros'),
        ],
        default='otros'
    )
    
    # Compatibilidad con marcas de vehículo (configurar en Django Admin)
    marcas_compatibles = models.ManyToManyField(
        'vehiculos.MarcaVehiculo',
        related_name='repuestos_compatibles_marca',
        blank=True,
        verbose_name=_('marcas de vehículo compatibles'),
        help_text=_(
            'Marcas de vehículo con las que este repuesto es compatible. '
            'Si no se restringen modelos, aplica a todos los modelos de la marca.'
        ),
    )

    # Restricción opcional por modelo de vehículo
    modelos_compatibles = models.ManyToManyField(
        'vehiculos.Modelo',
        related_name='repuestos_compatibles',
        blank=True,
        verbose_name=_('modelos compatibles'),
        help_text=_(
            'Opcional: limita el repuesto a modelos concretos de las marcas asociadas.'
        ),
    )

    tipos_motor_compatibles = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_('tipos de motor compatibles'),
        help_text=_('Vacío = todos los motores. Misma semántica que en Servicio.'),
    )
    
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('repuesto')
        verbose_name_plural = _('repuestos')
        ordering = ['categoria_repuesto', 'nombre']
    
    def __str__(self):
        return f"{self.nombre} ({self.marca})" if self.marca else self.nombre


class ServicioRepuesto(models.Model):
    """
    Modelo de relación entre servicios y repuestos necesarios
    """
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.CASCADE,
        related_name='repuestos_necesarios'
    )
    repuesto = models.ForeignKey(
        Repuesto,
        on_delete=models.CASCADE,
        related_name='servicios_que_lo_usan'
    )
    cantidad_estimada = models.PositiveIntegerField(
        default=1,
        help_text=_('Cantidad estimada de este repuesto para el servicio')
    )
    es_opcional = models.BooleanField(
        default=False,
        help_text=_('Indica si el repuesto es opcional para el servicio')
    )
    notas = models.TextField(
        blank=True, 
        null=True,
        help_text=_('Notas adicionales sobre el uso de este repuesto')
    )
    
    class Meta:
        verbose_name = _('repuesto de servicio')
        verbose_name_plural = _('repuestos de servicios')
        unique_together = ('servicio', 'repuesto')
    
    def __str__(self):
        return f"{self.servicio.nombre} - {self.repuesto.nombre} ({self.cantidad_estimada})"


class SolicitudRepuesto(models.Model):
    """
    Modelo para los repuestos específicos incluidos en una solicitud de servicio
    """
    linea_servicio = models.ForeignKey(
        'ordenes.LineaServicio',
        on_delete=models.CASCADE,
        related_name='repuestos_incluidos'
    )
    repuesto = models.ForeignKey(
        Repuesto,
        on_delete=models.CASCADE,
        related_name='solicitudes'
    )
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text=_('Precio unitario del repuesto en esta solicitud')
    )
    precio_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text=_('Precio total de este repuesto (cantidad * precio_unitario)')
    )
    incluido_en_garantia = models.BooleanField(
        default=True,
        help_text=_('Indica si este repuesto está cubierto por la garantía')
    )
    
    class Meta:
        verbose_name = _('repuesto de solicitud')
        verbose_name_plural = _('repuestos de solicitud')
    
    def __str__(self):
        return f"{self.linea_servicio} - {self.repuesto.nombre} (x{self.cantidad})"
    
    def save(self, *args, **kwargs):
        # Calcular precio total automáticamente
        self.precio_total = self.precio_unitario * self.cantidad
        super().save(*args, **kwargs)


class FotoServicio(models.Model):
    """
    Modelo para almacenar fotos de servicios subidas por los proveedores
    """
    oferta_servicio = models.ForeignKey(
        OfertaServicio,
        on_delete=models.CASCADE,
        related_name='fotos_servicio'
    )
    
    # Archivo de imagen
    imagen = models.ImageField(
        upload_to='servicios_photos/',
        help_text=_('Foto del servicio subida por el proveedor')
    )
    
    # Metadatos
    descripcion = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Descripción opcional de la foto')
    )
    
    orden = models.PositiveIntegerField(
        default=1,
        help_text=_('Orden de esta foto dentro del servicio')
    )
    
    fecha_subida = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('Foto de Servicio')
        verbose_name_plural = _('Fotos de Servicios')
        ordering = ['oferta_servicio', 'orden']
    
    def __str__(self):
        return f"Foto {self.orden} - {self.oferta_servicio.servicio.nombre}" 
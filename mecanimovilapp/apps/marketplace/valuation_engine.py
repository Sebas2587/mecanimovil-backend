from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone

def calculate_suggested_price(vehicle, precio_mercado, precio_fiscal, health_override=None):
    """
    Calcula el precio sugerido final basado en el algoritmo maestro:
    PrecioSugerido = (BaseValue * MileageFactor) + HealthFactor
    
    BaseValue = (PrecioMercado * 0.70) + (PrecioFiscal * 0.30)
    
    MileageFactor:
    - 20,000 km/año estándar
    - < 70% del esperado: +3% Bonus
    - > 130% del esperado: -3% Penalty
    
    FactorSalud:
    - Si Salud > 90%: +5% del valor base
    - Si Salud < 50%: - Costo estimado de reparaciones
    
    Args:
        health_override (int): Opcional. Sobrescribe el puntaje de salud para simulaciones (ej: Potential Gain).
    """
    
    # 1. Base Value Calculation
    if not precio_mercado:
        return 0
        
    # Base Value = 100% Market Price (Fiscal Price is ignored to avoid undervaluing)
    val_mercado = Decimal(precio_mercado)
    base_value = val_mercado
    
    # Legacy/Reference only:
    # base_value = (val_mercado * Decimal('0.70')) + (val_fiscal * Decimal('0.30'))
    
    # 2. Mileage Factor Calculation
    mileage_factor = Decimal('0')
    try:
        current_year = timezone.now().year
        vehicle_year = int(vehicle.year)
        age = max(1, current_year - vehicle_year) # Mínimo 1 año para evitar división por cero
        
        expected_km = age * 20000
        actual_km = vehicle.kilometraje
        
        if actual_km > 0:
            usage_ratio = actual_km / expected_km
            
            if usage_ratio < 0.7:
                # Bajo Kilometraje: Bonus +3%
                mileage_factor = base_value * Decimal('0.03')
            elif usage_ratio > 1.3:
                # Alto Kilometraje: Penalty -3%
                mileage_factor = -(base_value * Decimal('0.03'))
    except Exception as e:
        print(f"Error calculating mileage factor: {e}")
        # Fallback: No bonus/penalty
    
    # 3. Health Factor Calculation
    health_score = 0
    
    if health_override is not None:
        health_score = health_override
    else:
        # Intenta obtener el puntaje de salud real
        if hasattr(vehicle, 'get_health_score'):
             health_score = vehicle.get_health_score()
        elif hasattr(vehicle, 'salud_general'):
             health_score = vehicle.salud_general
        elif hasattr(vehicle, 'estados_salud'):
             # Fallback: Revisar último estado de salud calculado
             ultimo_estado = vehicle.estados_salud.order_by('-fecha_calculo').first()
             if ultimo_estado:
                 health_score = ultimo_estado.salud_general_porcentaje
         
    health_factor_value = Decimal('0')
    
    if health_score > 90:
        # Bonificación del 5% del valor base (Certificado/Excelente estado)
        health_factor_value = base_value * Decimal('0.05')
    elif health_score < 50:
        # Penalización: Restar costo estimado de reparaciones
        # Solo aplicar si NO estamos en modo simulación (health_override is None o health_override < 50)
        # Si simulamos 100% health, no restamos costos.
        
        if health_override is None:
            # Obtener costo de alertas activas
            from mecanimovilapp.apps.vehiculos.models_health import AlertaMantenimiento
            
            costo_reparaciones = AlertaMantenimiento.objects.filter(
                vehiculo=vehicle, 
                activa=True
            ).aggregate(total=Sum('costo_estimado'))['total'] or 0
            
            # Si no hay alertas con costo calculado pero salud es baja, aplicar penalización presunta
            if costo_reparaciones == 0:
                 # Penalización presunta del 10% si no tenemos datos precisos
                 costo_reparaciones = base_value * Decimal('0.10')
            
            health_factor_value = -Decimal(costo_reparaciones)
            
    final_price = base_value + mileage_factor + health_factor_value
    
    # Asegurar que no sea negativo
    if final_price < 0:
        final_price = 0
        
    return int(final_price)


def calculate_potential_gain(vehicle, current_price=None):
    """
    Calcula la ganancia potencial si el vehículo estuviera en estado óptimo (100% salud).
    Formula: Precio(Salud=100) - Precio(SaludActual)
    """
    if not vehicle.precio_mercado_promedio:
        return 0
        
    # Precio actual (si no se pasa, se calcula)
    if current_price is None:
        current_price = calculate_suggested_price(
            vehicle, 
            vehicle.precio_mercado_promedio, 
            vehicle.tasacion_fiscal
        )
        
    # Precio ideal (Salud = 100%)
    ideal_price = calculate_suggested_price(
        vehicle, 
        vehicle.precio_mercado_promedio, 
        vehicle.tasacion_fiscal,
        health_override=100
    )
    
    # La ganancia es la diferencia
    potential_gain = ideal_price - current_price
    
    if potential_gain < 0:
        return 0
        
    return int(potential_gain)

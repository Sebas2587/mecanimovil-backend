from decimal import Decimal

def calculate_suggested_price(vehicle, precio_mercado, precio_fiscal):
    """
    Calcula el precio sugerido final basado en el algoritmo maestro:
    PrecioSugerido = (PrecioMercado * 0.4) + (PrecioFiscal * 0.6) + FactorSalud
    
    FactorSalud:
    - Si Salud > 90%: +5% del valor base
    - Si Salud < 50%: - Costo estimado de reparaciones
    """
    
    # 1. Base Value Calculation
    # 1. Base Value Calculation
    if not precio_mercado:
        return 0
        
    # Si no hay precio fiscal (ej: valor 0 en API), usamos el precio de mercado como base completa
    # Esto resulta en: (Market * 0.4) + (Market * 0.6) = Market
    val_fiscal = Decimal(precio_fiscal) if precio_fiscal else Decimal(precio_mercado)
    val_mercado = Decimal(precio_mercado)
    
    base_value = (val_mercado * Decimal('0.40')) + (val_fiscal * Decimal('0.60'))
    
    # 2. Health Factor Calculation
    # Fetch health score from vehicle (we need to implement a property or fetch it)
    # For now, we assume a method or property exists or we fetch it.
    # Dado que el vehículo puede ser recien creado, quizás no tenga salud aún.
    # Si es recién creado, asumimos salud estándar o neutra (sin bonificación ni penalización)
    
    health_score = 0
    repair_costs = 0
    
    # Intenta obtener el puntaje de salud si existe el método
    if hasattr(vehicle, 'get_health_score'):
         health_score = vehicle.get_health_score()
    elif hasattr(vehicle, 'salud_general'): # Si se guarda como campo
         health_score = vehicle.salud_general
         
    # Lógica de Factor Salud
    health_factor = Decimal('0')
    
    if health_score > 90:
        # Bonificación del 5%
        health_factor = base_value * Decimal('0.05')
    elif health_score < 50:
        # Penalización: Restar costo de reparaciones pendientes
        # Esto requeriría consultar los servicios pendientes o cotizaciones
        # Por ahora, si es < 50 sin info de costos, podríamos aplicar una penalización estimativa
        # o dejarlo en 0 si no tenemos data de costos.
        # TODO: Implementar fetch de costos reales de reparaciones
        pass 
        
    final_price = base_value + health_factor
    
    return int(final_price)

"""Selección inteligente de casa de repuestos con trazabilidad de decisiones."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class OpcionCasa:
    """Una opción de casa de repuestos para un repuesto."""
    casa: str
    proveedor_id: int
    precio_clp: int
    stock_disponible: bool = True
    plazo_dias: Optional[int] = None
    compatibilidad_score: float = 0.0
    consulta_id: Optional[int] = None
    calidad: str = ""
    
    @classmethod
    def from_dict(cls, data: dict) -> OpcionCasa:
        """Construye desde dict de opciones_casa."""
        return cls(
            casa=str(data.get('casa', '')),
            proveedor_id=int(data.get('proveedor_id', 0)),
            precio_clp=int(data.get('precio_clp', 0)),
            stock_disponible=data.get('estado') != 'sin_stock',
            plazo_dias=None,  # TODO: extraer de respuesta
            compatibilidad_score=float(data.get('confianza', 0.0)),
            consulta_id=data.get('consulta_id'),
            calidad=str(data.get('calidad', '')),
        )


@dataclass
class ResultadoSeleccion:
    """Resultado de la selección de casa para un repuesto."""
    casa_elegida: str
    proveedor_id: int
    motivo_seleccion: str
    alternativas_descartadas: list[dict[str, Any]] = field(default_factory=list)
    precio_final_clp: int = 0
    consolidacion_aplicada: bool = False


def seleccionar_casa_optima(
    opciones: list[OpcionCasa],
    *,
    criterios: Optional[dict] = None,
) -> ResultadoSeleccion:
    """
    Selecciona la mejor casa según múltiples criterios.
    
    Ponderación por defecto:
    - Stock: bloqueante (sin stock = descartado o penalizado)
    - Precio: 60% (normalizado entre min-max)
    - Plazo: 30% (< 24h = 1.0, 24-48h = 0.5, > 48h = 0.0)
    - Compatibilidad: 10% (historial de aciertos)
    
    Args:
        opciones: Lista de opciones de casas
        criterios: Ponderaciones personalizadas (opcional)
    
    Returns:
        ResultadoSeleccion con casa elegida y justificación
    """
    if not opciones:
        return ResultadoSeleccion(
            casa_elegida='',
            proveedor_id=0,
            motivo_seleccion='No hay opciones disponibles',
            alternativas_descartadas=[],
            precio_final_clp=0,
        )
    
    criterios = criterios or {
        'precio': 0.6,
        'plazo': 0.3,
        'compatibilidad': 0.1,
    }
    
    # 1. Filtrar por stock
    con_stock = [o for o in opciones if o.stock_disponible]
    
    if not con_stock:
        # Ninguna con stock confirmado: elegir la más barata y documentar
        mejor_sin_stock = min(opciones, key=lambda o: o.precio_clp if o.precio_clp > 0 else 999_999_999)
        
        return ResultadoSeleccion(
            casa_elegida=mejor_sin_stock.casa,
            proveedor_id=mejor_sin_stock.proveedor_id,
            motivo_seleccion='Única opción cotizada (sin stock confirmado)',
            alternativas_descartadas=_construir_alternativas(opciones, mejor_sin_stock),
            precio_final_clp=mejor_sin_stock.precio_clp,
        )
    
    # 2. Si solo hay una con stock, elegirla
    if len(con_stock) == 1:
        unica = con_stock[0]
        return ResultadoSeleccion(
            casa_elegida=unica.casa,
            proveedor_id=unica.proveedor_id,
            motivo_seleccion='Única casa con stock disponible',
            alternativas_descartadas=_construir_alternativas(opciones, unica),
            precio_final_clp=unica.precio_clp,
        )
    
    # 3. Calcular scores ponderados
    scores = []
    for opc in con_stock:
        precio_norm = _normalizar_precio(opc.precio_clp, con_stock)
        plazo_score = _score_plazo(opc.plazo_dias)
        compat_score = opc.compatibilidad_score
        
        score_total = (
            precio_norm * criterios['precio'] +
            plazo_score * criterios['plazo'] +
            compat_score * criterios['compatibilidad']
        )
        scores.append((score_total, opc))
    
    # 4. Elegir mejor score
    mejor_score, mejor_opc = max(scores, key=lambda x: x[0])
    
    # 5. Construir motivo legible
    motivo = _construir_motivo(mejor_opc, con_stock)
    
    return ResultadoSeleccion(
        casa_elegida=mejor_opc.casa,
        proveedor_id=mejor_opc.proveedor_id,
        motivo_seleccion=motivo,
        alternativas_descartadas=_construir_alternativas(opciones, mejor_opc),
        precio_final_clp=mejor_opc.precio_clp,
    )


def consolidar_si_posible(
    repuestos: list[dict],
    todas_las_opciones: dict[str, list[OpcionCasa]],
) -> Optional[dict[str, ResultadoSeleccion]]:
    """
    Detecta si una sola casa puede proveer todos los repuestos competitivamente.
    
    Threshold: hasta 10% más caro que el óptimo distribuido.
    
    Args:
        repuestos: Lista de repuestos de la cotización
        todas_las_opciones: Dict {repuesto_id: [OpcionCasa, ...]}
    
    Returns:
        Dict {repuesto_id: ResultadoSeleccion} si hay consolidación viable,
        None si es mejor distribuir entre casas.
    """
    if not todas_las_opciones or len(todas_las_opciones) < 2:
        return None
    
    # 1. Identificar casas que aparecen en todos los repuestos
    casas_por_repuesto = {
        rid: {o.proveedor_id for o in opciones if o.stock_disponible}
        for rid, opciones in todas_las_opciones.items()
    }
    
    if not all(casas_por_repuesto.values()):
        return None  # Algún repuesto sin opciones con stock
    
    casas_completas = set.intersection(*casas_por_repuesto.values())
    
    if not casas_completas:
        logger.info('ordenes[seleccion_casa] consolidacion_imposible sin_casa_completa')
        return None  # Ninguna casa tiene todo
    
    # 2. Para cada casa completa, calcular costo total
    costos_consolidados = {}
    nombres_casas = {}
    
    for casa_id in casas_completas:
        costo_total = 0
        nombre_casa = ''
        
        for rid, opciones in todas_las_opciones.items():
            opc_casa = next((o for o in opciones if o.proveedor_id == casa_id and o.stock_disponible), None)
            if not opc_casa:
                break  # Esta casa no tiene este repuesto con stock
            
            costo_total += opc_casa.precio_clp
            if not nombre_casa:
                nombre_casa = opc_casa.casa
        else:
            # Todas las iteraciones completaron sin break
            costos_consolidados[casa_id] = costo_total
            nombres_casas[casa_id] = nombre_casa
    
    if not costos_consolidados:
        return None
    
    # 3. Calcular costo óptimo distribuido
    costo_optimo = 0
    for rid, opciones in todas_las_opciones.items():
        con_stock = [o for o in opciones if o.stock_disponible]
        if con_stock:
            mejor_precio = min(o.precio_clp for o in con_stock)
            costo_optimo += mejor_precio
    
    # 4. Aplicar threshold 10%
    threshold = costo_optimo * 1.10
    casas_viables = {
        casa_id: costo
        for casa_id, costo in costos_consolidados.items()
        if costo <= threshold
    }
    
    if not casas_viables:
        logger.info(
            'ordenes[seleccion_casa] consolidacion_no_viable min_consolidado=%d optimo=%d threshold=%d',
            min(costos_consolidados.values()),
            costo_optimo,
            threshold,
        )
        return None  # Consolidar sería muy caro
    
    # 5. Elegir casa con mejor costo consolidado
    casa_elegida_id = min(casas_viables, key=casas_viables.get)
    casa_elegida_nombre = nombres_casas[casa_elegida_id]
    costo_consolidado = casas_viables[casa_elegida_id]
    
    logger.info(
        'ordenes[seleccion_casa] consolidacion_aplicada casa=%s repuestos=%d costo=%d optimo=%d ahorro_vs_dist=%+.1f%%',
        casa_elegida_nombre,
        len(todas_las_opciones),
        costo_consolidado,
        costo_optimo,
        ((costo_consolidado - costo_optimo) / costo_optimo * 100) if costo_optimo else 0,
    )
    
    # 6. Construir ResultadoSeleccion para cada repuesto
    resultados = {}
    for rid, opciones in todas_las_opciones.items():
        opc_elegida = next(
            (o for o in opciones if o.proveedor_id == casa_elegida_id),
            None
        )
        
        if not opc_elegida:
            continue
        
        ahorro_pct = ((costo_consolidado - costo_optimo) / costo_optimo * 100) if costo_optimo else 0
        
        if ahorro_pct <= 0:
            motivo = f'Consolidado en una sola casa (mejor precio total: ${costo_consolidado:,} CLP)'.replace(',', '.')
        else:
            motivo = f'Consolidado en una sola casa (${costo_consolidado:,} CLP, {ahorro_pct:.1f}% sobre óptimo distribuido)'.replace(',', '.')
        
        resultados[rid] = ResultadoSeleccion(
            casa_elegida=opc_elegida.casa,
            proveedor_id=casa_elegida_id,
            motivo_seleccion=motivo,
            alternativas_descartadas=_construir_alternativas(opciones, opc_elegida),
            precio_final_clp=opc_elegida.precio_clp,
            consolidacion_aplicada=True,
        )
    
    return resultados


def _normalizar_precio(precio: int, opciones: list[OpcionCasa]) -> float:
    """
    Normaliza precio a score 0-1 (menor precio = mayor score).
    """
    precios = [o.precio_clp for o in opciones if o.precio_clp > 0]
    if not precios or len(precios) < 2:
        return 1.0
    
    min_precio = min(precios)
    max_precio = max(precios)
    
    if max_precio == min_precio:
        return 1.0
    
    # Invertir: menor precio → mayor score
    return 1.0 - ((precio - min_precio) / (max_precio - min_precio))


def _score_plazo(plazo_dias: Optional[int]) -> float:
    """
    Score por plazo de entrega.
    < 1 día: 1.0
    1-2 días: 0.5
    > 2 días: 0.0
    None (desconocido): 0.3
    """
    if plazo_dias is None:
        return 0.3
    
    if plazo_dias < 1:
        return 1.0
    elif plazo_dias <= 2:
        return 0.5
    else:
        return 0.0


def _construir_motivo(mejor: OpcionCasa, con_stock: list[OpcionCasa]) -> str:
    """
    Construye texto legible explicando por qué se eligió esta casa.
    """
    if len(con_stock) == 1:
        return 'Única casa con stock disponible'
    
    # Analizar si es la más barata
    precios = [o.precio_clp for o in con_stock if o.precio_clp > 0]
    if precios:
        min_precio = min(precios)
        
        if mejor.precio_clp == min_precio:
            return f'Mejor precio con stock inmediato (${mejor.precio_clp:,} CLP)'.replace(',', '.')
        
        # Analizar diferencia de precio
        diff_pct = ((mejor.precio_clp - min_precio) / min_precio * 100) if min_precio else 0
        
        if diff_pct < 3:
            return f'Balance precio-disponibilidad (${mejor.precio_clp:,} CLP, +{diff_pct:.1f}% sobre mínimo)'.replace(',', '.')
        else:
            # Debe haber otra razón (compatibilidad, plazo)
            if mejor.compatibilidad_score > 0.8:
                return f'Proveedor confiable con stock (${mejor.precio_clp:,} CLP)'.replace(',', '.')
    
    return f'Stock inmediato (${mejor.precio_clp:,} CLP)'.replace(',', '.')


def _construir_alternativas(
    todas: list[OpcionCasa],
    elegida: OpcionCasa,
) -> list[dict[str, Any]]:
    """
    Construye lista de alternativas descartadas con motivo.
    """
    alternativas = []
    
    for opc in todas:
        if opc.proveedor_id == elegida.proveedor_id:
            continue  # No incluir la elegida
        
        # Determinar motivo de descarte
        if not opc.stock_disponible:
            motivo = 'Sin stock disponible'
        elif opc.precio_clp <= 0:
            motivo = 'Sin precio cotizado'
        elif elegida.precio_clp > 0 and opc.precio_clp > elegida.precio_clp:
            diff_pct = ((opc.precio_clp - elegida.precio_clp) / elegida.precio_clp * 100)
            motivo = f'Precio {diff_pct:.1f}% más alto'
        elif elegida.precio_clp > 0 and opc.precio_clp < elegida.precio_clp:
            # Esta era más barata pero se descartó (debe ser por stock/compatibilidad)
            motivo = 'Menor confiabilidad o disponibilidad'
        else:
            motivo = 'Opción menos favorable'
        
        alternativas.append({
            'casa': opc.casa,
            'proveedor_id': opc.proveedor_id,
            'precio_clp': opc.precio_clp,
            'stock': opc.stock_disponible,
            'motivo_descarte': motivo,
        })
    
    return alternativas

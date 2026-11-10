"""Extracción estructurada del pedido del cliente via LLM con fallback a regex."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class VehiculoExtraido(BaseModel):
    """Información del vehículo extraída del pedido."""
    marca: str = ""
    modelo: str = ""
    anio: Optional[int] = Field(None, ge=1980, le=2030)
    motor: str = ""
    version: str = ""
    patente: str = ""
    tipo_motor: Optional[str] = None  # GASOLINA/DIESEL/HIBRIDO/ELECTRICO
    
    @field_validator('tipo_motor')
    @classmethod
    def validar_tipo_motor(cls, v):
        if v and v.upper() not in ('GASOLINA', 'DIESEL', 'HIBRIDO', 'ELECTRICO', 'BENCINA'):
            return None
        return v.upper() if v else None


class ServicioExtraido(BaseModel):
    """Servicio de mano de obra solicitado."""
    nombre: str
    cantidad: int = Field(default=1, ge=1, le=10)
    incluye_repuestos: Optional[bool] = None


class RepuestoMencionado(BaseModel):
    """Repuesto específicamente mencionado por el cliente."""
    nombre: str
    especificacion: str = ""
    cantidad: int = Field(default=1, ge=1, le=20)


class ItemPedido(BaseModel):
    """Una pieza leída en la misma llamada, con el sistema del que viene."""
    texto_original: str = ""
    rol: str = "repuesto"  # repuesto, insumo, mano_obra, sistema, duda
    sistema: str = ""
    identidad: str = "otra"
    nombre: str = ""
    especificacion: str = ""
    cantidad: str = ""
    # None: el modelo omitió el campo. No es confianza baja.
    confianza: float | None = None


class FluidoVehiculo(BaseModel):
    """Spec de un fluido para este auto. No es un precio."""
    especificacion: str = ""
    litros: str = ""
    confianza: float = 0.0


class PedidoExtraido(BaseModel):
    """Resultado completo de la extracción del pedido."""
    vehiculo: VehiculoExtraido
    servicios: list[ServicioExtraido] = Field(default_factory=list)
    repuestos_mencionados: list[RepuestoMencionado] = Field(default_factory=list)
    items: list[ItemPedido] = Field(default_factory=list)
    fluidos: dict[str, FluidoVehiculo] = Field(default_factory=dict)
    alcance_repuestos: str = "no_definido"  # con_repuestos/solo_mano_obra/no_definido
    calidad_preferida: str = ""  # original/oem/alternativo
    descripcion_problema: str = ""
    
    @field_validator('alcance_repuestos')
    @classmethod
    def validar_alcance(cls, v):
        validos = {'con_repuestos', 'solo_mano_obra', 'no_definido'}
        return v if v in validos else 'no_definido'
    
    @field_validator('calidad_preferida')
    @classmethod
    def validar_calidad(cls, v):
        validos = {'original', 'oem', 'alternativo', ''}
        return v if v in validos else ''


def extraer_pedido_con_llm(
    texto_cliente: str,
    vehiculo_context: dict | None = None,
    *,
    taller = None,
) -> PedidoExtraido:
    """
    Extrae información estructurada del pedido del cliente usando LLM.
    
    Args:
        texto_cliente: Mensaje o conversación del cliente
        vehiculo_context: Contexto previo del vehículo (marca, modelo, etc.)
        taller: Taller para contexto adicional (opcional)
    
    Returns:
        PedidoExtraido con información estructurada
    
    Fallback: Si LLM falla, usa regex de alcance_pedido.py
    """
    vehiculo_context = vehiculo_context or {}
    
    try:
        # Intentar extracción con LLM
        resultado_llm = _llamar_gemini_extraccion(texto_cliente, vehiculo_context)
        
        if resultado_llm:
            logger.info(
                'agente_ia[extraccion] llm_exito vehiculo=%s servicios=%d',
                resultado_llm.vehiculo.marca or 'desconocido',
                len(resultado_llm.servicios)
            )
            return resultado_llm
        
        logger.warning('agente_ia[extraccion] llm_vacio, usando fallback')
        
    except Exception as exc:
        logger.warning(
            'agente_ia[extraccion] llm_error=%s, usando fallback',
            str(exc),
            exc_info=True
        )
    
    # Fallback a regex
    return _fallback_regex(texto_cliente, vehiculo_context)


def _llamar_gemini_extraccion(
    texto_cliente: str,
    vehiculo_context: dict,
) -> PedidoExtraido | None:
    """Llama a Gemini para extracción estructurada."""
    from django.conf import settings
    import requests
    
    api_key = getattr(settings, 'GEMINI_API_KEY', '').strip()
    if not api_key:
        return None
    
    # Construir contexto
    ctx_marca = vehiculo_context.get('marca', '')
    ctx_modelo = vehiculo_context.get('modelo', '')
    ctx_anio = vehiculo_context.get('anio', '')
    ctx_patente = vehiculo_context.get('patente', '')
    
    contexto_vehiculo = ""
    if ctx_marca or ctx_modelo:
        contexto_vehiculo = f"\nContexto previo del vehículo: {ctx_marca} {ctx_modelo} {ctx_anio} {ctx_patente}".strip()
    
    prompt = f"""Extrae del mensaje del cliente la información del pedido de servicio automotriz en Chile.

REGLAS CRÍTICAS:
1. Solo extrae lo que el cliente MENCIONA AHORA en este mensaje, no agregues mantenimientos preventivos ni servicios no pedidos
2. "Cambio de aceite" es UN servicio de mano de obra (nombre: "Cambio de aceite")
3. Si menciona "filtro de aceite", es un REPUESTO, no un servicio separado
4. "Cambio de pastillas y discos" → 1 servicio "Cambio de pastillas y discos de freno", 2 repuestos separados
5. Patente formato chileno: ABCD12 o AB1234 (letras mayúsculas + números)
6. Si dice "solo mano de obra" o "yo pongo los repuestos", alcance_repuestos = "solo_mano_obra"
7. Si menciona repuestos específicos o no aclara, alcance_repuestos = "con_repuestos"
8. tipo_motor: GASOLINA (o BENCINA), DIESEL, HIBRIDO, ELECTRICO
9. Razona la frase, no la partas en palabras sueltas. En «kit de embrague, bomba y cilindro (bombín)» la bomba y el bombín heredan embrague. «cambiar kit bomba cilindro de embrague» son las tres piezas. Tolera typos: «embrage» es embrague.
10. Sinónimos: collarín y crapodina son el rodamiento de empuje, no el piloto. Bombín de freno no es bombín de embrague. Cilindro maestro de frenos no es la bomba de embrague. Piloto automático, piola de acelerador, horquilla de suspensión, rulemán de rueda, retén de rueda y guaya de puerta no son piezas de embrague.
11. Un sistema («sistema de frenos», «sistema hidráulico») no es un repuesto: rol sistema o duda, identidad otra.
12. Si no estás seguro, identidad «otra», rol duda y confianza baja. Nunca cambies la pieza por otra para completar el JSON.
13. En fluidos, la spec de aceite de caja y de líquido DOT de ESTE auto (marca, modelo, motor, año), con confianza de 0 a 1. Si no la sabes, confianza 0 y especificacion vacía. No inventes un precio.
14. Cada ítem trae texto_original, rol (repuesto, insumo, mano_obra, sistema o duda), sistema (embrague, frenos, suspension, transmision u otro), identidad canónica o «otra», nombre normalizado, spec, cantidad si la dice y confianza.

Mensaje del cliente:
{texto_cliente}
{contexto_vehiculo}

Responde SOLO JSON válido sin markdown:
{{
  "vehiculo": {{
    "marca": "Toyota",
    "modelo": "Yaris",
    "anio": 2018,
    "motor": "1.5",
    "version": "",
    "patente": "ABCD12",
    "tipo_motor": "GASOLINA"
  }},
  "servicios": [
    {{"nombre": "Cambio de aceite y filtro", "cantidad": 1, "incluye_repuestos": true}}
  ],
  "repuestos_mencionados": [
    {{"nombre": "Filtro de aceite", "especificacion": "", "cantidad": 1}},
    {{"nombre": "Aceite sintético", "especificacion": "5W30", "cantidad": 4}}
  ],
  "items": [
    {{
      "texto_original": "Filtro de aceite",
      "rol": "repuesto",
      "sistema": "motor",
      "identidad": "otra",
      "nombre": "Filtro de aceite",
      "especificacion": "",
      "cantidad": "1",
      "confianza": 0.9
    }}
  ],
  "fluidos": {{
    "aceite_caja": {{"especificacion": "", "litros": "", "confianza": 0}},
    "liquido_frenos": {{"especificacion": "DOT4", "litros": "1", "confianza": 0.6}}
  }},
  "alcance_repuestos": "con_repuestos",
  "calidad_preferida": "original",
  "descripcion_problema": "Cliente necesita cambio de aceite y filtro"
}}"""
    
    # Llamar a Gemini
    modelo = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash-lite')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}'
    
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.2,
            'maxOutputTokens': 2048,
            'responseMimeType': 'application/json',
        }
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=(8, 15))
        
        if resp.status_code != 200:
            logger.warning(
                'agente_ia[extraccion] gemini_http_error status=%s body=%s',
                resp.status_code,
                resp.text[:200]
            )
            return None
        
        body = resp.json()
        candidates = body.get('candidates', [])
        if not candidates:
            return None
        
        content = candidates[0].get('content', {})
        parts = content.get('parts', [])
        if not parts:
            return None
        
        # Obtener texto JSON
        texto_json = ''
        for part in parts:
            if part.get('thought'):
                continue  # Skip thinking parts in Gemini 3.x
            text = part.get('text', '')
            if text:
                texto_json += text
        
        if not texto_json:
            return None
        
        # Limpiar markdown si existe
        texto_json = texto_json.strip()
        if texto_json.startswith('```'):
            texto_json = re.sub(r'^```(?:json)?\s*', '', texto_json)
            texto_json = re.sub(r'\s*```$', '', texto_json)
        
        # Parsear JSON
        data = json.loads(texto_json)
        
        # Validar con Pydantic
        resultado = PedidoExtraido(**data)
        
        return resultado
        
    except requests.Timeout:
        logger.warning('agente_ia[extraccion] gemini_timeout')
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning('agente_ia[extraccion] json_error=%s texto=%s', exc, texto_json[:200])
        return None
    except Exception as exc:
        logger.warning('agente_ia[extraccion] gemini_error=%s', exc, exc_info=True)
        return None


def _fallback_regex(
    texto_cliente: str,
    vehiculo_context: dict,
) -> PedidoExtraido:
    """Fallback usando regex de alcance_pedido.py"""
    from mecanimovilapp.apps.agente_ia.services.alcance_pedido import (
        _extraer_servicios_mencionados_en_texto,
    )
    from mecanimovilapp.apps.agente_ia.services.contexto_repuestos import (
        inferir_alcance_repuestos,
    )
    
    logger.info('agente_ia[extraccion] usando_fallback_regex')
    
    # Extraer servicios con regex
    servicios_nombres = _extraer_servicios_mencionados_en_texto(texto_cliente)
    servicios = [
        ServicioExtraido(nombre=nombre, cantidad=1)
        for nombre in servicios_nombres
    ]
    
    # Inferir alcance
    alcance = inferir_alcance_repuestos(texto_cliente, decision=None)
    
    # Construir vehículo desde contexto
    vehiculo = VehiculoExtraido(
        marca=str(vehiculo_context.get('marca', '')),
        modelo=str(vehiculo_context.get('modelo', '')),
        anio=vehiculo_context.get('anio'),
        motor=str(vehiculo_context.get('motor', '')),
        patente=str(vehiculo_context.get('patente', '')),
        tipo_motor=str(vehiculo_context.get('tipo_motor', '') or '').upper() or None,
    )
    
    return PedidoExtraido(
        vehiculo=vehiculo,
        servicios=servicios,
        repuestos_mencionados=[],
        alcance_repuestos=alcance,
        calidad_preferida='',
        descripcion_problema=texto_cliente[:500],
    )

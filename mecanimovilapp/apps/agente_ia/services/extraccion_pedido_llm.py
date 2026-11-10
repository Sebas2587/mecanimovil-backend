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


class PiezaPlan(BaseModel):
    """Pieza de un servicio: pedida o sugerida, con el motivo si es sugerida."""
    nombre: str = ""
    identidad: str = ""
    motivo: str = ""


class ServicioExtraido(BaseModel):
    """Servicio de mano de obra solicitado, con lo que ese trabajo requiere."""
    nombre: str
    cantidad: int = Field(default=1, ge=1, le=10)
    incluye_repuestos: Optional[bool] = None
    horas: Optional[float] = None
    mano_obra_clp: Optional[int] = None
    repuestos_requeridos: list[PiezaPlan] = Field(default_factory=list)
    sugeridos: list[PiezaPlan] = Field(default_factory=list)


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


_CACHE_PEDIDO: dict[tuple, PedidoExtraido] = {}
_MAX_TOKENS_EXTRACCION = 8192


def generation_config_extraccion(modelo: str) -> dict:
    """La misma config que el resto del repo. Gemini 3 necesita thinkingConfig."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
        _modelo_admite_thinking_level,
        generation_config_gemini,
    )

    return generation_config_gemini(
        temperature=0.2,
        max_output=_MAX_TOKENS_EXTRACCION,
        response_json=True,
        thinking=_modelo_admite_thinking_level(modelo),
    )


def _body_sin_secreto(texto: str) -> str:
    limpio = re.sub(r'AIza[\w\-]+', '***', texto or '')
    return re.sub(r'(key=)[^&\s"\']+', r'\1***', limpio)[:800]


def leer_pedido_llm(texto_cliente: str, vehiculo_context: dict | None = None) -> PedidoExtraido | None:
    """Una llamada por texto y vehículo. No arma el catálogo: si falla, devuelve None."""
    vehiculo_context = vehiculo_context or {}
    clave = (
        re.sub(r'\s+', ' ', (texto_cliente or '').strip().lower()),
        str(vehiculo_context.get('marca') or '').strip().lower(),
        str(vehiculo_context.get('modelo') or '').strip().lower(),
        str(vehiculo_context.get('anio') or ''),
        str(vehiculo_context.get('motor') or vehiculo_context.get('cilindraje') or ''),
    )
    guardado = _CACHE_PEDIDO.get(clave)
    if guardado is not None:
        return guardado
    pedido = _llamar_gemini_extraccion(texto_cliente, vehiculo_context)
    if pedido and pedido.servicios:
        if len(_CACHE_PEDIDO) > 128:
            _CACHE_PEDIDO.clear()
        _CACHE_PEDIDO[clave] = pedido
        return pedido
    return None


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
        # La misma llamada que el cotizador, con caché por texto y vehículo.
        resultado_llm = leer_pedido_llm(texto_cliente, vehiculo_context)
        
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
15. Primero el SERVICIO, no la frase literal. «hace ruido y patina» no es un repuesto. «revisar el sistema hidráulico» es diagnóstico, no una pieza. Normaliza typos y abreviaturas (embrage, bba, cil. rec., acite, fltro).
16. En cada servicio: horas de mano de obra, repuestos_requeridos (imprescindibles, nombre técnico) y sugeridos (con motivo). No pongas en sugeridos lo que ya trae el kit. Frenos traseros de tambor son balatas, no pastillas.
17. Razona el trabajo, sea cual sea. No te limites a embrague, frenos, aceite o hidráulico. Suspensión, distribución, mantención por kilometraje, batería, refrigeración, bujías o alineación también son servicios, con sus horas y sus piezas. Una pieza suelta («pastillas») es el cambio de esa pieza, con mano de obra. Si no puedes decir qué trabajo es, deja servicios vacío. No inventes un repuesto para llenar el JSON.

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
    {{
      "nombre": "Cambio de aceite y filtros",
      "cantidad": 1,
      "incluye_repuestos": true,
      "horas": 1,
      "mano_obra_clp": null,
      "repuestos_requeridos": [
        {{"nombre": "Aceite de motor", "identidad": "aceite_motor", "motivo": ""}},
        {{"nombre": "Filtro de aceite", "identidad": "filtro_aceite", "motivo": ""}}
      ],
      "sugeridos": [
        {{"nombre": "Filtro de aire", "identidad": "filtro_aire", "motivo": "En el cambio de aceite conviene revisar el de aire."}}
      ]
    }}
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
    
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import (
        _url_generate_content,
        finish_reason_gemini,
        modelos_gemini_cotizacion,
        texto_candidato_gemini,
        timeout_http_gemini,
    )

    modelos = modelos_gemini_cotizacion()
    texto_json = ''
    for indice, modelo in enumerate(modelos):
        url = _url_generate_content(modelo, api_key)
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': generation_config_extraccion(modelo),
        }
        try:
            resp = requests.post(url, json=payload, timeout=timeout_http_gemini(25))
        except requests.Timeout:
            logger.warning('agente_ia[extraccion] gemini_timeout model=%s', modelo)
            continue
        except Exception as exc:
            logger.warning('agente_ia[extraccion] gemini_error model=%s error=%s', modelo, exc)
            return None
        if resp.status_code != 200:
            logger.warning(
                'agente_ia[extraccion] gemini_http_error model=%s status=%s body=%s',
                modelo,
                resp.status_code,
                _body_sin_secreto(getattr(resp, 'text', '') or ''),
            )
            if resp.status_code in (429, 503) and indice < len(modelos) - 1:
                continue
            return None
        try:
            body = resp.json()
        except ValueError:
            logger.warning('agente_ia[extraccion] json_error model=%s body=%s', modelo, _body_sin_secreto(resp.text))
            return None
        if finish_reason_gemini(body) == 'MAX_TOKENS':
            logger.warning(
                'agente_ia[extraccion] respuesta_truncada model=%s max_tokens=%s',
                modelo,
                _MAX_TOKENS_EXTRACCION,
            )
        texto_json = (texto_candidato_gemini(body) or '').strip()
        if texto_json.startswith('```'):
            texto_json = re.sub(r'^```(?:json)?\s*', '', texto_json)
            texto_json = re.sub(r'\s*```$', '', texto_json)
        if not texto_json:
            logger.warning('agente_ia[extraccion] gemini_vacio model=%s', modelo)
            continue
        try:
            return PedidoExtraido(**json.loads(texto_json))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                'agente_ia[extraccion] json_error model=%s error=%s texto=%s',
                modelo,
                exc,
                _body_sin_secreto(texto_json),
            )
            return None
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
    
    plan_auto: dict = {}
    try:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.plan_por_servicio import (
            planificar_pedido,
        )
        plan_auto = (planificar_pedido(texto_cliente, vehiculo_context).get('vehiculo') or {})
    except Exception:
        plan_auto = {}
    anio = vehiculo_context.get('anio') or plan_auto.get('anio') or None
    try:
        anio = int(anio) if anio not in (None, '') else None
    except (TypeError, ValueError):
        anio = None
    vehiculo = VehiculoExtraido(
        marca=str(vehiculo_context.get('marca') or plan_auto.get('marca') or ''),
        modelo=str(vehiculo_context.get('modelo') or plan_auto.get('modelo') or ''),
        anio=anio,
        motor=str(vehiculo_context.get('motor') or plan_auto.get('motor') or ''),
        patente=str(vehiculo_context.get('patente') or ''),
        tipo_motor=str(vehiculo_context.get('tipo_motor', '') or '').upper() or None,
    )
    
    servicios = _servicios_del_plan(texto_cliente, vehiculo_context) or servicios
    return PedidoExtraido(
        vehiculo=vehiculo,
        servicios=servicios,
        repuestos_mencionados=[],
        alcance_repuestos=alcance,
        calidad_preferida='',
        descripcion_problema=texto_cliente[:500],
    )


def _servicios_del_plan(texto: str, vehiculo_context: dict) -> list[ServicioExtraido]:
    """La misma lectura de servicio, sin una segunda llamada al modelo."""
    try:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.plan_por_servicio import (
            planificar_pedido,
        )
    except Exception:
        return []
    plan = planificar_pedido(texto, vehiculo_context)
    salida = []
    for servicio in plan.get('servicios') or []:
        mano = servicio.get('mano_obra') or {}
        salida.append(ServicioExtraido(
            nombre=servicio['nombre'],
            cantidad=1,
            incluye_repuestos=not servicio.get('solo_mano'),
            horas=mano.get('horas'),
            mano_obra_clp=mano.get('monto_clp'),
            repuestos_requeridos=[
                PiezaPlan(**pieza) for pieza in servicio.get('repuestos_requeridos') or []
            ],
            sugeridos=[PiezaPlan(**pieza) for pieza in servicio.get('sugeridos') or []],
        ))
    return salida

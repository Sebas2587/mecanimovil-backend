"""Generador de cotización IA vía Gemini."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from django.conf import settings

from .contexto import armar_contexto_cotizacion
from .normalizar import normalizar_cotizacion_ia

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)

MSG_GEMINI_TIMEOUT = (
    'Gemini tardó demasiado en armar la cotización. Espera unos segundos e intenta de nuevo.'
)
MSG_GEMINI_CONEXION = 'Error de conexión con Gemini. Intenta de nuevo.'
MSG_GEMINI_CUOTA = 'Gemini alcanzó el límite de consultas. Espera unos minutos.'
MSG_GEMINI_SATURADO = 'Gemini está saturado en este momento. Espera unos segundos e intenta de nuevo.'
MSG_GEMINI_FORMATO = 'Gemini respondió en un formato inesperado.'
MSG_GEMINI_GENERICO = 'No se pudo generar la cotización en este momento.'
MSG_GEMINI_TOKENS = (
    'Gemini cortó la respuesta por límite de salida. Intenta con un servicio más específico.'
)


def asistente_cotizacion_habilitado() -> bool:
    return bool(getattr(settings, 'ASISTENTE_COTIZACION_IA_ENABLED', False)) or bool(
        getattr(settings, 'AGENTE_IA_CHAT_ENABLED', False)
    )


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find('{')
        end = raw.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def timeout_http_gemini(read_s: int) -> tuple[int, int]:
    """Connect corto, read largo: la generación JSON no es un hang de red."""
    return (8, max(10, int(read_s or 10)))


def generation_config_gemini(
    *,
    temperature: float,
    max_output: int,
    response_json: bool = False,
    thinking: bool = True,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        'temperature': temperature,
        'maxOutputTokens': max_output,
    }
    if response_json:
        cfg['responseMimeType'] = 'application/json'
    # Gemini 3.x piensa por defecto; sin "minimal" una cotización JSON
    # supera el timeout de 15s y el cliente ve "Error de conexión".
    if thinking:
        cfg['thinkingConfig'] = {'thinkingLevel': 'minimal'}
    return cfg


def texto_candidato_gemini(body: dict[str, Any] | None) -> str | None:
    """Junta el texto útil y omite partes `thought` (Gemini 3)."""
    if not isinstance(body, dict):
        return None
    cands = body.get('candidates') or []
    if not cands or not isinstance(cands[0], dict):
        return None
    parts = (cands[0].get('content') or {}).get('parts') or []
    textos: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get('thought') is True:
            continue
        text = part.get('text')
        if isinstance(text, str) and text.strip():
            textos.append(text)
    if textos:
        return ''.join(textos)
    return None


def finish_reason_gemini(body: dict[str, Any] | None) -> str:
    if not isinstance(body, dict):
        return ''
    cands = body.get('candidates') or []
    if not cands or not isinstance(cands[0], dict):
        return ''
    return str(cands[0].get('finishReason') or cands[0].get('finish_reason') or '')


def _modelo_gemini_primario() -> str:
    return (
        getattr(settings, 'ASISTENTE_COTIZACION_GEMINI_MODEL', '')
        or getattr(settings, 'ASISTENTE_DIAGNOSTICO_GEMINI_MODEL', '')
        or getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
        or 'gemini-3.1-flash-lite'
    ).strip()


def modelos_gemini_cotizacion(primario: str | None = None) -> list[str]:
    """Modelo principal + respaldos si Google responde 503 high demand."""
    primario = (primario or _modelo_gemini_primario()).strip()
    raw = getattr(settings, 'ASISTENTE_COTIZACION_GEMINI_FALLBACKS', None)
    if raw is None:
        extra = (
            getattr(settings, 'AGENTE_IA_MULTIMODAL_MODEL', '') or 'gemini-2.5-flash'
        ).strip()
        extras = [p for p in (extra, 'gemini-2.5-flash-lite') if p]
    elif isinstance(raw, (list, tuple)):
        extras = [str(x).strip() for x in raw if str(x).strip()]
    else:
        extras = [p.strip() for p in str(raw).replace(';', ',').split(',') if p.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for nombre in [primario, *extras]:
        if nombre and nombre not in seen:
            seen.add(nombre)
            out.append(nombre)
    return out or [primario or 'gemini-3.1-flash-lite']


def _modelo_admite_thinking_level(model: str) -> bool:
    return 'gemini-3' in (model or '').lower()


def _url_generate_content(model: str, api_key: str) -> str:
    return (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )


def _backoff_503_s(intento: int) -> float:
    """Picos 503 de Google duran más que 2s; el cliente de cotización espera 90s."""
    return min(12.0, max(3.0, 3.0 * (2 ** intento)))


def _llamar_gemini(prompt: str) -> tuple[dict[str, Any] | None, dict[str, int | str], str | None]:
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    modelos = modelos_gemini_cotizacion()
    model = modelos[0]
    uso_vacio: dict[str, int | str] = {
        'tokens_entrada': 0,
        'tokens_salida': 0,
        'tokens_total': 0,
        'modelo': model,
    }
    if not api_key:
        return None, uso_vacio, 'El asistente IA no está configurado en el servidor (falta GEMINI_API_KEY).'

    timeout = int(getattr(settings, 'ASISTENTE_COTIZACION_IA_TIMEOUT', 45) or 45)
    max_retries = max(0, min(int(getattr(settings, 'GEMINI_RETRY_MAX', 2) or 2), 4))
    try:
        retries_503 = int(getattr(settings, 'GEMINI_503_RETRY_MAX', 0))
    except (TypeError, ValueError):
        retries_503 = 0
    retries_503 = max(0, min(retries_503, 6))
    ultimo_error = MSG_GEMINI_GENERICO

    for mi, modelo_actual in enumerate(modelos):
        uso_vacio['modelo'] = modelo_actual
        url = _url_generate_content(modelo_actual, api_key)
        usar_thinking = _modelo_admite_thinking_level(modelo_actual)
        intentos_modelo = retries_503 if mi == 0 else max(0, min(max_retries, 2))
        timeout_modelo = timeout if mi == 0 else min(22, timeout)
        logger.info(
            'Gemini cotización POST model=%s prompt_chars=%s timeout_read=%ss intento_modelo=%s/%s',
            modelo_actual,
            len(prompt or ''),
            timeout_modelo,
            mi + 1,
            len(modelos),
        )
        for intento in range(intentos_modelo + 1):
            payload = {
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': generation_config_gemini(
                    temperature=0.3,
                    max_output=4096,
                    response_json=True,
                    thinking=usar_thinking,
                ),
            }
            try:
                resp = requests.post(url, json=payload, timeout=timeout_http_gemini(timeout_modelo))
            except requests.ConnectTimeout as exc:
                if intento < intentos_modelo:
                    logger.warning(
                        'Gemini cotización connect timeout model=%s intento %s/%s (%s); reintenta',
                        modelo_actual,
                        intento + 1,
                        intentos_modelo + 1,
                        exc,
                    )
                    time.sleep(min(4, max(1, 2 ** intento)))
                    continue
                ultimo_error = MSG_GEMINI_CONEXION
                break
            except (requests.ReadTimeout, requests.Timeout) as exc:
                logger.warning(
                    'Gemini cotización read timeout (%ss) model=%s intento %s/%s: %s',
                    timeout_modelo,
                    modelo_actual,
                    intento + 1,
                    intentos_modelo + 1,
                    exc,
                )
                ultimo_error = MSG_GEMINI_TIMEOUT
                break
            except requests.RequestException as exc:
                if intento < intentos_modelo:
                    logger.warning(
                        'Gemini cotización red model=%s intento %s/%s falló (%s); reintenta',
                        modelo_actual,
                        intento + 1,
                        intentos_modelo + 1,
                        exc,
                    )
                    time.sleep(min(4, max(1, 2 ** intento)))
                    continue
                ultimo_error = MSG_GEMINI_CONEXION
                break

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    return None, uso_vacio, MSG_GEMINI_FORMATO
                text = texto_candidato_gemini(body)
                if not text:
                    reason = finish_reason_gemini(body)
                    logger.warning(
                        'Gemini cotización sin texto model=%s finish=%s body=%s',
                        modelo_actual,
                        reason,
                        str(body)[:400],
                    )
                    if 'MAX_TOKEN' in reason.upper():
                        return None, uso_vacio, MSG_GEMINI_TOKENS
                    return None, uso_vacio, MSG_GEMINI_FORMATO

                meta = body.get('usageMetadata') or {}
                uso = {
                    'tokens_entrada': int(meta.get('promptTokenCount') or 0),
                    'tokens_salida': int(meta.get('candidatesTokenCount') or 0),
                    'tokens_total': int(meta.get('totalTokenCount') or 0),
                    'modelo': modelo_actual,
                }
                parsed = _parse_json(text)
                if parsed is None:
                    logger.warning('Gemini cotización JSON inválido chars=%s', len(text))
                    return None, uso, MSG_GEMINI_FORMATO
                logger.info(
                    'Gemini cotización ok model=%s tokens_in=%s tokens_out=%s',
                    modelo_actual,
                    uso['tokens_entrada'],
                    uso['tokens_salida'],
                )
                return parsed, uso, None

            logger.warning(
                'Gemini cotización HTTP %s model=%s body=%s',
                resp.status_code,
                modelo_actual,
                (resp.text or '')[:400],
            )
            if resp.status_code == 400 and usar_thinking:
                usar_thinking = False
                continue
            if resp.status_code == 429 and intento < intentos_modelo:
                espera = min(10, max(2, 2 ** intento))
                logger.warning(
                    'Gemini cotización HTTP 429 model=%s; espera %.0fs y reintenta',
                    modelo_actual,
                    espera,
                )
                time.sleep(espera)
                continue
            if resp.status_code == 429:
                ultimo_error = MSG_GEMINI_CUOTA
                break
            if resp.status_code == 503:
                ultimo_error = MSG_GEMINI_SATURADO
                # High demand de Google (UNAVAILABLE), no es la cuota de la API key.
                # Reintentar flash-lite 3–12s deja la búsqueda de repuestos pegada;
                # 2.5-flash está en otro pool y responde ya.
                if mi < len(modelos) - 1:
                    logger.warning(
                        'Gemini cotización HTTP 503 model=%s (Google saturado, no es la cuota); '
                        'pasa a %s sin esperar',
                        modelo_actual,
                        modelos[mi + 1],
                    )
                    break
                if intento < intentos_modelo:
                    espera = _backoff_503_s(intento)
                    logger.warning(
                        'Gemini cotización HTTP 503 model=%s; espera %.0fs y reintenta',
                        modelo_actual,
                        espera,
                    )
                    time.sleep(espera)
                    continue
                break
            return None, uso_vacio, MSG_GEMINI_GENERICO
        if ultimo_error in (
            MSG_GEMINI_SATURADO,
            MSG_GEMINI_CUOTA,
            MSG_GEMINI_CONEXION,
            MSG_GEMINI_TIMEOUT,
        ) and mi < len(modelos) - 1:
            logger.warning(
                'Gemini cotización %s en %s; prueba respaldo %s',
                ultimo_error,
                modelo_actual,
                modelos[mi + 1],
            )
            continue
        return None, uso_vacio, ultimo_error

    return None, uso_vacio, ultimo_error


def _construir_prompt(ctx: dict[str, Any], pedido_extraido=None) -> str:
    efectivo = ctx.get('tipo_motor_efectivo_label') or 'No especificado'
    motor_bloque = (
        f"- Motor del vehículo (patente/modelo): {efectivo}\n"
        f"- Aviso motor: {ctx.get('aviso_motor') or ctx.get('tipo_motor_conflicto_detalle') or 'Ninguno'}"
    )
    chat = ctx.get('chat_reciente') or 'Sin mensajes previos.'
    rag = (ctx.get('contexto_rag') or '').strip()
    rag_bloque = (
        '\nConocimiento del taller (SOLO para precios/piezas del SERVICIO SOLICITADO '
        'y ESTE vehículo; no agregues otros servicios ni copies precios de otro marca/modelo):\n'
        f'{rag}\n'
        if rag
        else ''
    )
    pedido = (ctx.get('servicio_nombre') or '').strip() or 'Servicio mecánico'
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.separar_pedido_taller import (
        bloque_para_prompt,
    )

    bloque_lectura = bloque_para_prompt(
        pedido,
        str(ctx.get('descripcion_problema') or ''),
    )
    
    # Enriquecer con extracción estructurada si está disponible
    bloque_partes_requeridas = ""
    if pedido_extraido and pedido_extraido.servicios:
        partes_explicitas = []
        for servicio in pedido_extraido.servicios:
            partes_explicitas.append(f"- Servicio: {servicio.nombre}")
        for repuesto in pedido_extraido.repuestos_mencionados:
            partes_explicitas.append(f"- Repuesto mencionado: {repuesto.nombre}" + 
                                   (f" ({repuesto.especificacion})" if repuesto.especificacion else ""))
        if partes_explicitas:
            bloque_partes_requeridas = (
                "\nPARTES REQUERIDAS EXTRAÍDAS (DEBES incluir TODAS estas en tu respuesta):\n" +
                "\n".join(partes_explicitas) +
                "\n"
            )
    
    return f"""Eres un asesor de taller mecánico en Chile. Genera una cotización referencial en pesos chilenos (CLP enteros, sin decimales).

Vehículo:
- Marca: {ctx.get('marca', '')}
- Modelo: {ctx.get('modelo', '')}
- Año: {ctx.get('anio', '')}
- Patente: {ctx.get('patente', '')}
- Cilindraje: {ctx.get('cilindraje', '')}
{motor_bloque}

Servicio solicitado (ÚNICA fuente de líneas a cotizar): {pedido}
Descripción del problema: {ctx.get('descripcion_problema', '')}

{bloque_lectura}
{bloque_partes_requeridas}
Contexto del chat reciente (NO son líneas de cotización; ignora servicios de otro auto o solo mencionados):
{chat}
{rag_bloque}
REGLAS:
0. ALCANCE (CRÍTICO): cotiza SOLO el servicio pedido para ESTE vehículo ({ctx.get('marca', '')} {ctx.get('modelo', '')}). PROHIBIDO agregar servicios no solicitados (frenos si solo pidió aceite, distribución si solo pidió embrague, diagnóstico no pedido, otro auto). El campo servicio_nombre de salida DEBE ser exactamente "{pedido}".
0b. LEE EL PEDIDO: cotiza cada ítem que pidieron, con su repuesto y su faena. Si piden kit de embrague, bomba de embrague y líquido de frenos, van los tres. No los reemplaces por una lista fija (rodamiento, retén, aceite de caja). Un complementario que el taller no pidió va en repuestos con "origen":"sugerencia", "estado_sugerencia":"pendiente" y "motivo_sugerencia" en una frase. No lo presentes como pedido. Si no sabes compatibilidad o qué incluye el kit, dilo en advertencias y deja el precio en 0. NUNCA agregues volante bimasa salvo que lo pidan. La piola solo si la nombran.
0c. PRECIOS POR VEHÍCULO (CRÍTICO): NUNCA copies mano de obra ni precios de piezas de otro marca/modelo (Toyota ≠ BAIC; Yaris ≠ Yaris Cross) aunque el servicio se llame igual. Si el bloque de historial no es de este marca+modelo exacto, ignóralo.
1. Analiza el SERVICIO pedido + el VEHÍCULO concreto ({ctx.get('marca', '')} {ctx.get('modelo', '')} {ctx.get('anio', '')}, motor {efectivo}). Cada marca/modelo/año tiene piezas y cantidades distintas: no copies listas genéricas de otro auto.
2. Precios en CLP enteros: son ESTIMADOS de mercado Chile (taller) para que el proveedor los revise. NO digas que vienen de un catálogo o tienda.
3. CRÍTICO — IVA INCLUIDO: mano_obra_clp es precio FINAL al cliente con IVA 19% ya incluido. NO cotices neto ni agregues línea de IVA.
4. El motor efectivo es {efectivo}. No mezcles repuestos diésel/bencina/híbrido.
5. Separa faena y pieza. El taller escribe "cambio de bujías" para la mano de obra; el repuesto se llama "Bujías", nunca "cambio de bujías". Revisión, diagnóstico, inspección, scanner, alineación y limpieza son solo mano de obra: no crees un repuesto con ese nombre ni con el objeto de esa faena (limpiar el cuerpo de aceleración no agrega la pieza "cuerpo de aceleración").
5b. servicios_lineas.nombre es la faena tal como la pidió el taller. repuestos.nombre es la pieza.
5c. TRABAJOS QUE VAN JUNTOS: "cambio de A y B" (bujías y bobinas, pastillas y discos) es UNA línea de mano de obra y UN monto, porque se hacen en el mismo trabajo. Las piezas sí van separadas en repuestos. "y también", "también" y "además" abren otro servicio, que es mano de obra: no lo conviertas en repuesto. El detalle del problema puede sumar otro servicio; un síntoma ("hace ruido") no es una línea.
5d. PARTES IMPLÍCITAS (CRÍTICO): Si el servicio menciona EXPLÍCITAMENTE que incluye una parte, DEBES incluirla como repuesto separado:
   - "cambio de aceite CON FILTRO" → repuestos: "Aceite de motor" + "Filtro de aceite"
   - "pastillas Y discos" → repuestos: "Pastillas de freno" + "Discos de freno"
   - "cambio de correa de distribución con bomba de agua" → repuestos: "Correa de distribución" + "Bomba de agua"
   Las palabras "con", "incluye", "y", "más" indican parte adicional que DEBE estar en repuestos[] como línea separada.
5e. CANTIDADES REALISTAS POR CAPACIDAD:
   - Aceite de motor: cantidad en LITROS de la capacidad de ESTE motor con filtro. Fiat Bravo 1.4 T-Jet: 4 litros (el cárter lleva unos 3,5 L; se cotizan 4 para no quedar corto). Un bidón de 4 L o de 1 L NO fija la cantidad. Si no conoces la capacidad, estima por el motor y deja el envase fuera.
   - Líquido refrigerante: ~5-7 litros típico (depende del vehículo)
   - Aceite de caja: cantidad según capacidad de transmisión (ej. 2-3 litros manual, 4-6 litros automática)
6. REPUESTOS POR VEHÍCULO (CRÍTICO): SOLO piezas compatibles con marca/modelo/año/cilindrada/motor. Nombra la pieza con precisión (posición: delantero/trasero, lado).
6c. TRABAJO DE EMBRAGUE: cada faena pedida es su propia línea de mano de obra (cambio de kit, cambio de bomba, cambio de líquido). El kit es disco + prensa + rodamiento de empuje en un solo precio; disco, prensa o collarín sueltos no se suman aparte. El piloto, el aceite de caja y el retén de cigüeñal solo van si los pidieron o como sugerencia pendiente con motivo. No copies el precio del kit a otra pieza.
6b. ESPECIFICACIÓN ANTES DE PRECIO (CRÍTICO): si la pieza tiene variantes que cambian el precio (bujía cobre/platino/iridio; pastilla orgánica/semi-metálica/cerámica; aceite mineral/sintético + viscosidad; batería convencional/EFB/AGM; amortiguador hidráulico/gas), declara "especificacion" con UNA sola variante para ESTE vehículo (ej. "Iridio", "Cerámica", "5W30 sintético"). PROHIBIDO ofrecer dos ("cerámica o semi-metálica"), separar con "/" o describir medidas en vez de la variante. Si no puedes determinarla con certeza, deja especificacion="" y precio_unitario_clp=0. PROHIBIDO inventar un monto para una variante que no sabes.
7. Volante bimasa: inclúyelo SOLO si el SERVICIO SOLICITADO es de embrague/clutch (no porque el chat mencionó vibración u otro auto).
8. marca_repuesto, fuente_marketplace y tienda_ml: SIEMPRE "". NUNCA inventes marca (ni "GENÉRICO", ni Bosch/Mann "por costumbre"), ni tienda, ni "catálogo". El backend solo completa marca/proveedor si hay match real del taller o listing verificable.
9. PRECIO DE REPUESTO: NO inventes un precio puntual. Pon precio_unitario_clp=0 (el backend elige el techo o deja la línea sin precio). SIEMPRE entrega precio_min_clp y precio_max_clp mayores a cero: es el rango en que esa pieza se mueve en Chile y es lo único que orienta al taller si no hay referencia web.
10. En advertencias incluye siempre que los precios de repuesto son estimados y deben confirmarse en taller antes de enviar al cliente.
11. duracion_minutos_estimada razonable para el servicio en este vehículo.

Responde SOLO JSON válido en español:
{{
  "servicio_nombre": "...",
  "descripcion_resumen": "...",
  "tipo_motor_efectivo": "GASOLINA|DIESEL|ELECTRICO|HIBRIDO",
  "tipo_motor_label": "...",
  "duracion_minutos_estimada": 90,
  "mano_obra_clp": 45000,
  "servicios_lineas": [{{"nombre": "Cambio de bujías", "monto_clp": 25000}}],
  "repuestos": [
    {{
      "nombre": "...",
      "cantidad": 1,
      "precio_unitario_clp": 0,
      "precio_min_clp": 40000,
      "precio_max_clp": 75000,
      "especificacion": "",
      "marca_repuesto": "",
      "fuente_marketplace": "",
      "tienda_ml": "",
      "comentario": "..."
    }}
  ],
  "advertencias": ["Precios referenciales con IVA incluido, sujetos a confirmación en taller"]
}}"""


def _ajustar_rangos_consistentes(repuestos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Asegura que precio_min_clp y precio_max_clp contengan el precio_unitario_clp.
    
    Regla: Si precio_unitario_clp está fuera del rango [min, max], ajustar el rango
    para que lo contenga, manteniendo cierta amplitud.
    
    Esto previene inconsistencias UI donde se muestra "$8K–$15K" pero precio línea es $31K.
    """
    for rep in repuestos:
        precio_unit = rep.get('precio_unitario_clp', 0)
        precio_min = rep.get('precio_min_clp', 0)
        precio_max = rep.get('precio_max_clp', 0)
        cantidad = rep.get('cantidad', 1)
        
        # Si no hay precio unitario, mantener el rango de Gemini
        if precio_unit <= 0:
            continue

        # La banda es de la IA o de la config. Un hit de tienda no la reescribe:
        # $11.920 pasaba a $9.536–$14.304 (±20% del precio elegido).
        # precio_referencia_mercado también lo pone un unitario de la IA sin ficha;
        # ese rango sí se abre para cubrir cantidad × unitario.
        fuente = str(rep.get('fuente_marketplace') or '').strip().lower()
        if fuente in ('web', 'ml', 'mercadolibre'):
            continue
        
        # Precio total de la línea
        precio_total = precio_unit * cantidad
        
        # Si el rango no contiene el precio, ajustarlo
        if precio_total < precio_min or precio_total > precio_max:
            # Ajustar con margen ±20% del precio real
            margen = int(precio_total * 0.2)
            nuevo_min = max(1000, precio_total - margen)  # Mínimo $1.000
            nuevo_max = precio_total + margen
            
            rep['precio_min_clp'] = nuevo_min
            rep['precio_max_clp'] = nuevo_max
            
            logger.info(
                'generador[rango_ajustado] rep=%s precio_line=%d rango_orig=[%d,%d] rango_nuevo=[%d,%d]',
                rep.get('nombre', '')[:30],
                precio_total,
                precio_min,
                precio_max,
                nuevo_min,
                nuevo_max,
            )
        # Si el precio está dentro del rango pero muy cerca de los extremos, verificar amplitud
        elif precio_min > 0 and precio_max > 0:
            amplitud = precio_max - precio_min
            # Si el rango es muy estrecho (< 10% del precio), ampliarlo
            if amplitud < precio_total * 0.1:
                margen = int(precio_total * 0.15)
                rep['precio_min_clp'] = max(1000, precio_total - margen)
                rep['precio_max_clp'] = precio_total + margen
    
    return repuestos


def _aplicar_config_taller_por_modelo(
    contenido: dict[str, Any],
    *,
    taller,
    servicio_nombre: str,
    marca: str,
    modelo: str,
    tipo_motor: str = '',
) -> dict[str, Any]:
    """
    Aplica configuración de servicio del taller específica por modelo/motor cuando existe.
    
    Si existe OfertaServicio para marca/modelo/motor:
    - Usa precio mano de obra de la oferta
    - Usa precios de repuestos de la oferta
    - Actualiza motivo_seleccion para indicar "Precio del taller para este vehículo"
    
    Fallback: mantiene valores de Gemini/catálogo general.
    """
    if not servicio_nombre:
        return contenido
    
    try:
        from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
            buscar_oferta_exacta,
            precio_publico_oferta,
        )
        
        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=servicio_nombre,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        
        if not oferta:
            return contenido
        
        # Aplicar precio de mano de obra (sin repuestos = solo mano de obra)
        precio_mo, _ = precio_publico_oferta(oferta, con_repuestos=False)
        # Si precio_sin_repuestos está vacío pero hay costo_mano_de_obra_sin_iva
        if precio_mo <= 0 and int(oferta.costo_mano_de_obra_sin_iva or 0) > 0:
            precio_mo = int(round(int(oferta.costo_mano_de_obra_sin_iva) * 1.19))
        
        if precio_mo > 0:
            contenido['mano_obra_clp'] = precio_mo
            contenido['precio_desde_catalogo'] = True
            logger.info(
                'generar_cotizacion_ia: config_taller_aplicada marca=%s modelo=%s motor=%s mano_obra=%d',
                marca, modelo, tipo_motor, precio_mo
            )
        
        # Aplicar precios de repuestos del catálogo
        repuestos_oferta = oferta.repuestos_seleccionados or []
        if repuestos_oferta and contenido.get('repuestos'):
            repuestos_nuevos = []
            for rep in contenido['repuestos']:
                # Buscar match en repuestos de la oferta
                nombre_rep = (rep.get('nombre') or '').lower()
                match_oferta = None
                for rep_oferta in repuestos_oferta:
                    if not isinstance(rep_oferta, dict):
                        continue
                    nombre_oferta = (rep_oferta.get('nombre') or rep_oferta.get('repuesto') or '').lower()
                    if nombre_oferta and nombre_oferta in nombre_rep or nombre_rep in nombre_oferta:
                        match_oferta = rep_oferta
                        break
                
                if match_oferta:
                    # Aplicar precio del catálogo
                    precio_cat = match_oferta.get('precio_unitario_clp') or match_oferta.get('precio')
                    if precio_cat and precio_cat > 0:
                        rep['precio_unitario_clp'] = int(precio_cat)
                        rep['precio_desde_catalogo'] = True
                        rep['fuente_marketplace'] = 'catalogo'
                        rep['proveedor_nombre'] = 'Catálogo del taller'
                        # Marcar que viene de config específica
                        rep['_config_modelo'] = True
                
                repuestos_nuevos.append(rep)
            
            contenido['repuestos'] = repuestos_nuevos
        
        return contenido
        
    except Exception as exc:
        logger.warning('_aplicar_config_taller_por_modelo falló: %s', exc, exc_info=True)
        return contenido


def _nota_de_linea_con_tienda(
    rep: dict[str, Any],
    motivo_interno: str,
    *,
    marca_vehiculo: str,
    modelo_vehiculo: str,
    anio_vehiculo: Any,
    tipo_motor: str,
    cilindraje: Any,
) -> str:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        nota_de_busqueda,
        nota_visible_con_tienda,
    )

    nota = nota_visible_con_tienda(
        rep,
        motivo_interno,
        marca=marca_vehiculo,
        modelo=modelo_vehiculo,
        anio=anio_vehiculo,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
    )
    if not str(rep.get('comentario') or '').strip() or nota_de_busqueda(rep.get('comentario')):
        rep['comentario'] = nota
    return nota


def _notar_linea_sin_tienda(
    rep: dict[str, Any],
    *,
    marca_vehiculo: str,
    modelo_vehiculo: str,
    anio_vehiculo: Any,
    tipo_motor: str,
    cilindraje: Any,
) -> None:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        nota_de_busqueda,
        nota_visible_sin_tienda,
    )

    rep['casa_repuesto_nombre'] = ''
    if str(rep.get('proveedor_nombre') or '').strip().lower() == 'estimado':
        rep['proveedor_nombre'] = ''
    rep['motivo_seleccion'] = nota_visible_sin_tienda(
        rep,
        marca=marca_vehiculo,
        modelo=modelo_vehiculo,
        anio=anio_vehiculo,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
    )
    if (
        not str(rep.get('comentario') or '').strip()
        or nota_de_busqueda(rep.get('comentario'))
    ):
        rep['comentario'] = rep['motivo_seleccion']


def _casa_es_tienda(rep: dict[str, Any], casa: str) -> bool:
    """Una fuente 'estimado' no es una casa. No se le inventa el nombre Estimado."""
    from mecanimovilapp.apps.ordenes.casas_especialistas import es_etiqueta_historial

    nombre = str(casa or '').strip()
    if not nombre or nombre.lower() == 'estimado' or es_etiqueta_historial(nombre):
        return False
    fuente = str(
        rep.get('fuente_marketplace') or rep.get('fuente_repuesto') or ''
    ).strip().lower()
    if fuente == 'estimado' and not str(rep.get('url_producto') or '').strip():
        return False
    return True


def _aplicar_seleccion_casa_repuestos(
    repuestos: list[dict[str, Any]],
    *,
    taller=None,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio_vehiculo: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> list[dict[str, Any]]:
    """
    Aplica selección inteligente de casa para cada repuesto.
    
    Para cada repuesto:
    1. Recolecta opciones de casas disponibles (del enriquecimiento previo)
    2. Aplica seleccion_casa_repuestos para elegir la mejor
    3. Evalúa consolidación (una casa con todos los repuestos dentro del 110%)
    4. Agrega: casa_repuesto_nombre, motivo_seleccion, alternativas_descartadas, consolidacion_aplicada
    """
    if not repuestos:
        return []
    
    try:
        from mecanimovilapp.apps.ordenes.services.seleccion_casa_repuestos import (
            OpcionCasa,
            ResultadoSeleccion,
            consolidar_si_posible,
            seleccionar_casa_optima,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            nombre_tienda_visible,
        )
    except ImportError as exc:
        logger.warning('No se pudo importar seleccion_casa_repuestos: %s, omitiendo selección', exc)
        return repuestos
    
    # PASO 1: Para cada repuesto, recolectar opciones de casas disponibles
    todas_las_opciones = {}  # {repuesto_id: [OpcionCasa, ...]}
    
    for idx, rep in enumerate(repuestos):
        rep_id = rep.get('id') or f'rep-{idx}'
        opciones_casa = []
        
        fuente = rep.get('fuente_marketplace', '') or rep.get('fuente_repuesto', '')
        proveedor_nombre = rep.get('proveedor_nombre', '')
        
        # Opción 1: Catálogo/historial del taller (proveedor_nombre + fuente catalogo/historial)
        if proveedor_nombre and fuente in ('catalogo', 'historial'):
            opciones_casa.append(OpcionCasa(
                casa=proveedor_nombre,
                proveedor_id=rep.get('proveedor_id', 0),
                precio_clp=rep.get('precio_unitario_clp', 0) * rep.get('cantidad', 1),
                stock_disponible=True,
                compatibilidad_score=1.0,
            ))
        # Opción 2: Búsqueda web (proveedor_nombre + fuente web)
        elif proveedor_nombre and fuente == 'web':
            opciones_casa.append(OpcionCasa(
                casa=proveedor_nombre,
                proveedor_id=0,
                precio_clp=rep.get('precio_unitario_clp', 0) * rep.get('cantidad', 1),
                stock_disponible=rep.get('url_producto', '') != '',  # Tiene URL = verificado
                compatibilidad_score=0.8,
            ))
        # Opción 3: MercadoLibre u otras fuentes
        elif fuente and fuente not in ('catalogo', 'historial', 'web'):
            opciones_casa.append(OpcionCasa(
                casa=rep.get('tienda_ml', '') or proveedor_nombre or fuente.title(),
                proveedor_id=0,
                precio_clp=rep.get('precio_unitario_clp', 0) * rep.get('cantidad', 1),
                stock_disponible=not rep.get('precio_estimado', True),
                compatibilidad_score=0.7,
            ))
        # Fallback: Si tiene proveedor_nombre sin fuente clara, asumirlo como web/alternativo
        elif proveedor_nombre:
            opciones_casa.append(OpcionCasa(
                casa=proveedor_nombre,
                proveedor_id=0,
                precio_clp=rep.get('precio_unitario_clp', 0) * rep.get('cantidad', 1),
                stock_disponible=rep.get('url_producto', '') != '',
                compatibilidad_score=0.6,
            ))
        
        if opciones_casa:
            todas_las_opciones[rep_id] = opciones_casa
    
    # PASO 2: Intentar consolidación global (una casa con todos los repuestos dentro del 110%)
    # CRÍTICO: Solo consolidar si TODOS los repuestos tienen opciones disponibles
    resultados_consolidados = None
    if len(todas_las_opciones) >= 2 and len(todas_las_opciones) == len(repuestos):
        try:
            resultados_consolidados = consolidar_si_posible(repuestos, todas_las_opciones)
            if resultados_consolidados:
                casas = {
                    (r.casa_elegida or '').strip().lower()
                    for r in resultados_consolidados.values()
                }
                cubre_todos = (
                    len(resultados_consolidados) == len(repuestos)
                    and len(casas) == 1
                    and '' not in casas
                )
                if not cubre_todos:
                    logger.info(
                        'ordenes[seleccion_casa] consolidacion_descartada casas=%s cubiertos=%d total=%d',
                        sorted(casas),
                        len(resultados_consolidados),
                        len(repuestos),
                    )
                    resultados_consolidados = None
                else:
                    logger.info(
                        'ordenes[seleccion_casa] consolidacion_valida casa=%s repuestos=%d',
                        next(iter(resultados_consolidados.values())).casa_elegida,
                        len(resultados_consolidados),
                    )
        except Exception as exc:
            logger.warning('consolidar_si_posible falló: %s', exc, exc_info=True)
    elif len(todas_las_opciones) < len(repuestos):
        logger.info(
            'ordenes[seleccion_casa] consolidacion_omitida repuestos=%d con_opciones=%d',
            len(repuestos), len(todas_las_opciones)
        )
    
    # PASO 3: Aplicar selección a cada repuesto
    repuestos_finales = []
    for idx, rep in enumerate(repuestos):
        rep_id = rep.get('id') or f'rep-{idx}'
        
        # Si viene de config del taller por modelo, priorizar ese origen
        if rep.get('_config_modelo'):
            rep['casa_repuesto_nombre'] = 'Catálogo del taller'
            rep['motivo_seleccion'] = f'Precio del taller para {marca_vehiculo} {modelo_vehiculo} (configuración específica)'
            rep['alternativas_descartadas'] = []
            rep['consolidacion_aplicada'] = False
            rep.pop('_config_modelo', None)
        # Si hay consolidación, usar resultado consolidado y ACTUALIZAR proveedor_nombre
        elif resultados_consolidados and rep_id in resultados_consolidados:
            resultado = resultados_consolidados[rep_id]
            casa = str(resultado.casa_elegida or '').strip()
            if _casa_es_tienda(rep, casa):
                visible = nombre_tienda_visible(casa) or casa
                rep['casa_repuesto_nombre'] = visible
                rep['proveedor_nombre'] = visible
                rep['motivo_seleccion'] = _nota_de_linea_con_tienda(
                    rep,
                    resultado.motivo_seleccion,
                    marca_vehiculo=marca_vehiculo,
                    modelo_vehiculo=modelo_vehiculo,
                    anio_vehiculo=anio_vehiculo,
                    tipo_motor=tipo_motor,
                    cilindraje=cilindraje,
                )
            else:
                _notar_linea_sin_tienda(
                    rep,
                    marca_vehiculo=marca_vehiculo,
                    modelo_vehiculo=modelo_vehiculo,
                    anio_vehiculo=anio_vehiculo,
                    tipo_motor=tipo_motor,
                    cilindraje=cilindraje,
                )
            rep['alternativas_descartadas'] = resultado.alternativas_descartadas
            rep['consolidacion_aplicada'] = True
            try:
                cantidad = int(rep.get('cantidad') or 1)
            except (TypeError, ValueError):
                cantidad = 1
            cantidad = max(cantidad, 1)
            if resultado.precio_final_clp > 0:
                rep['precio_unitario_clp'] = resultado.precio_final_clp // cantidad
        # Si no hay consolidación pero hay opciones, seleccionar óptima individual
        elif rep_id in todas_las_opciones:
            opciones = todas_las_opciones[rep_id]
            resultado = seleccionar_casa_optima(opciones)
            casa = str(resultado.casa_elegida or '').strip()
            if _casa_es_tienda(rep, casa):
                visible = nombre_tienda_visible(casa) or casa
                rep['casa_repuesto_nombre'] = visible
                rep['proveedor_nombre'] = visible
                rep['motivo_seleccion'] = _nota_de_linea_con_tienda(
                    rep,
                    resultado.motivo_seleccion,
                    marca_vehiculo=marca_vehiculo,
                    modelo_vehiculo=modelo_vehiculo,
                    anio_vehiculo=anio_vehiculo,
                    tipo_motor=tipo_motor,
                    cilindraje=cilindraje,
                )
            else:
                _notar_linea_sin_tienda(
                    rep,
                    marca_vehiculo=marca_vehiculo,
                    modelo_vehiculo=modelo_vehiculo,
                    anio_vehiculo=anio_vehiculo,
                    tipo_motor=tipo_motor,
                    cilindraje=cilindraje,
                )
            rep['alternativas_descartadas'] = resultado.alternativas_descartadas
            rep['consolidacion_aplicada'] = False
        # Sin casa: la nota corta. El detalle de títulos y consultas queda en el log.
        else:
            _notar_linea_sin_tienda(
                rep,
                marca_vehiculo=marca_vehiculo,
                modelo_vehiculo=modelo_vehiculo,
                anio_vehiculo=anio_vehiculo,
                tipo_motor=tipo_motor,
                cilindraje=cilindraje,
            )
            rep['alternativas_descartadas'] = []
            rep['consolidacion_aplicada'] = False

        if str(rep.get('motivo_tienda') or '').strip():
            rep['motivo_seleccion'] = str(rep['motivo_tienda']).strip()
        repuestos_finales.append(rep)

    _aplicar_prioridad_de_taller(
        repuestos_finales,
        marca=marca_vehiculo,
        taller=taller,
        modelo=modelo_vehiculo,
        anio=anio_vehiculo,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
    )
    return repuestos_finales


def _lugar_del_taller(taller) -> str:
    """Calle, número, comuna y ciudad configurados. Vacío si no hay dirección."""
    if taller is None:
        return ''
    partes: list[str] = []
    try:
        direccion = taller.direccion_fisica
    except Exception:
        direccion = None
    if direccion is not None:
        partes.extend(
            str(getattr(direccion, campo, '') or '')
            for campo in ('calle', 'numero', 'comuna', 'ciudad', 'detalles_adicionales')
        )
    usuario = getattr(taller, 'usuario', None)
    if usuario is not None:
        partes.append(str(getattr(usuario, 'direccion', '') or ''))
        try:
            extras = usuario.direcciones.all()
        except Exception:
            extras = []
        for extra in extras:
            partes.append(str(getattr(extra, 'direccion', '') or ''))
            partes.append(str(getattr(extra, 'detalles', '') or ''))
    return ' '.join(p.strip() for p in partes if p and str(p).strip())


def _aplicar_prioridad_de_taller(
    repuestos: list[dict[str, Any]],
    *,
    marca: str,
    taller,
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> None:
    """Especialista de la marca, y la tienda solo en línea al final.

    No pisa una ficha de casa física. No inventa el precio: si no hay ficha
    de la especialista, la línea queda a consultar y el monto anterior queda
    como referencia de la otra tienda.
    """
    from mecanimovilapp.apps.ordenes.casas_especialistas import (
        es_etiqueta_historial,
        es_fisica,
        es_solo_en_linea,
        especialista_de_la_ficha,
        especialistas_de_marca,
        nota_consulta_especialista,
        nota_especialista,
        nota_solo_en_linea,
        sucursal_para,
        texto_sucursal,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        _es_nota_mecanico,
        nombre_tienda_visible,
        recortar_nota,
    )

    marca = str(marca or '').strip()
    if not marca or not repuestos:
        return
    lugar = _lugar_del_taller(taller)
    especialistas = especialistas_de_marca(marca)
    perfil_marca = especialistas[0] if especialistas else None

    for rep in repuestos:
        if not isinstance(rep, dict) or rep.get('_config_modelo'):
            continue
        fuente = str(rep.get('fuente_marketplace') or rep.get('fuente_repuesto') or '').strip().lower()
        if fuente in ('catalogo', 'proveedor'):
            continue
        # El historial cotiza un monto. La casa donde se compra es la especialista.
        if fuente == 'historial' or es_etiqueta_historial(
            str(rep.get('casa_repuesto_nombre') or ''),
        ) or es_etiqueta_historial(str(rep.get('proveedor_nombre') or '')):
            try:
                precio_hist = int(rep.get('precio_unitario_clp') or 0)
            except (TypeError, ValueError):
                precio_hist = 0
            rep['casa_repuesto_nombre'] = ''
            rep['proveedor_nombre'] = ''
            rep.pop('casa_sucursal', None)
            if precio_hist > 0:
                rep['referencia_tienda'] = 'historial del taller'
                rep['precio_referencia_clp'] = precio_hist
            for detalle in rep.get('fuentes_detalle') or []:
                if isinstance(detalle, dict) and (
                    str(detalle.get('fuente') or '') == 'historial'
                    or es_etiqueta_historial(str(detalle.get('tienda') or ''))
                ):
                    detalle['tienda'] = ''
        casa = str(rep.get('casa_repuesto_nombre') or rep.get('proveedor_nombre') or '').strip()
        url = str(rep.get('url_producto') or '').strip()
        perfil = especialista_de_la_ficha('', url, marca)
        if perfil:
            sucursal = sucursal_para(perfil, marca, lugar)
            rep['casa_repuesto_nombre'] = perfil['nombre']
            if not es_etiqueta_historial(str(rep.get('proveedor_nombre') or '')):
                rep['proveedor_nombre'] = perfil['nombre']
            rep['casa_sucursal'] = texto_sucursal(sucursal)
            rep['casa_telefono'] = str(perfil.get('telefono') or '')
            rep['precio_a_consultar'] = False
            rep['_perfil_especialista'] = perfil['nombre']
            continue
        if es_fisica('', url):
            from mecanimovilapp.apps.ordenes.casas_especialistas import perfil_de

            perfil_fisico = perfil_de(casa, url)
            if perfil_fisico:
                sucursal = sucursal_para(perfil_fisico, marca, lugar)
                rep['casa_sucursal'] = texto_sucursal(sucursal)
                rep['casa_telefono'] = str(perfil_fisico.get('telefono') or '')
            continue
        # Sin ficha de una casa física: la especialista de la marca, a consultar.
        # El monto que ya había queda como referencia de la otra tienda.
        if perfil_marca:
            sucursal = sucursal_para(perfil_marca, marca, lugar)
            visible_ref = nombre_tienda_visible(casa) or casa
            try:
                precio = int(rep.get('precio_unitario_clp') or 0)
            except (TypeError, ValueError):
                precio = 0
            rep['casa_repuesto_nombre'] = perfil_marca['nombre']
            rep['precio_a_consultar'] = True
            rep['casa_sucursal'] = texto_sucursal(sucursal)
            rep['casa_telefono'] = str(perfil_marca.get('telefono') or '')
            if es_etiqueta_historial(str(rep.get('referencia_tienda') or '')):
                rep['proveedor_nombre'] = perfil_marca['nombre']
                for detalle in rep.get('fuentes_detalle') or []:
                    if isinstance(detalle, dict) and not str(detalle.get('tienda') or '').strip():
                        detalle['tienda'] = perfil_marca['nombre']
            if visible_ref and precio > 0 and not es_fisica('', url):
                from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
                    _monto_banda_por_unidad,
                    monto_por_unidad_citable,
                )

                try:
                    piso_ref = int(rep.get('precio_min_clp') or 0)
                    techo_ref = int(rep.get('precio_max_clp') or 0)
                except (TypeError, ValueError):
                    piso_ref, techo_ref = 0, 0
                piso_ref = _monto_banda_por_unidad(str(rep.get('nombre') or ''), piso_ref, rep.get('cantidad'))
                techo_ref = _monto_banda_por_unidad(str(rep.get('nombre') or ''), techo_ref, rep.get('cantidad'))
                citado = monto_por_unidad_citable(
                    {
                        'title': str(rep.get('nombre_producto') or ''),
                        'content': '',
                        'url': url,
                        'ficha_leida': bool(str(rep.get('nombre_producto') or '').strip() or url),
                        'precio_snippet': precio,
                    },
                    nombre=str(rep.get('nombre') or ''),
                    modelo=modelo,
                    tipo_motor=tipo_motor,
                    banda_min=piso_ref,
                    banda_max=techo_ref,
                    anio=anio,
                    cilindraje=cilindraje,
                    cantidad=rep.get('cantidad'),
                    unitario_linea=precio,
                )
                if citado > 0:
                    rep['referencia_tienda'] = visible_ref
                    rep['precio_referencia_clp'] = citado
                else:
                    rep.pop('referencia_tienda', None)
                    rep.pop('precio_referencia_clp', None)
            rep['_perfil_especialista'] = perfil_marca['nombre']
            rep['_a_consultar'] = True
            continue
        if casa and es_solo_en_linea(casa, url):
            rep['_solo_en_linea'] = nombre_tienda_visible(casa) or casa

    verificados = [
        rep for rep in repuestos
        if isinstance(rep, dict)
        and rep.get('_perfil_especialista')
        and not rep.get('_a_consultar')
    ]
    cubre_todo = (
        len(repuestos) >= 2
        and len(verificados) == len(repuestos)
        and len({str(rep.get('_perfil_especialista') or '') for rep in verificados}) == 1
    )
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        perfil_nombre = str(rep.pop('_perfil_especialista', '') or '')
        a_consultar = bool(rep.pop('_a_consultar', False))
        solo = str(rep.pop('_solo_en_linea', '') or '')
        if perfil_nombre:
            if a_consultar:
                from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
                    _referencia_consulta,
                )

                ref_tienda, ref_precio = _referencia_consulta(
                    rep,
                    modelo=modelo,
                    anio=anio,
                    tipo_motor=tipo_motor,
                    cilindraje=cilindraje,
                )
                if ref_tienda and ref_precio > 0:
                    rep['referencia_tienda'] = ref_tienda
                    rep['precio_referencia_clp'] = ref_precio
                else:
                    rep.pop('referencia_tienda', None)
                    rep.pop('precio_referencia_clp', None)
                nota = recortar_nota(nota_consulta_especialista(
                    perfil_nombre,
                    marca,
                    tienda=ref_tienda,
                    precio=ref_precio,
                ))
            elif cubre_todo:
                nota = recortar_nota(nota_especialista(
                    perfil_nombre, marca, cubre_todo=True, a_consultar=False,
                ))
            else:
                nota = recortar_nota(nota_especialista(
                    perfil_nombre, marca, cubre_todo=False, a_consultar=False,
                ))
        elif solo:
            nota = recortar_nota(nota_solo_en_linea(solo))
        else:
            continue
        rep['motivo_seleccion'] = nota
        comentario = str(rep.get('comentario') or '')
        if not comentario.strip() or _es_nota_mecanico(comentario):
            rep['comentario'] = nota


def _cerrar_con_plan(contenido, ctx, servicio_nombre, descripcion_problema, taller):
    """Si el borrador vino sin precios, lo arma el plan del servicio."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.plan_por_servicio import (
        completar_cotizacion_en_blanco,
    )

    texto = f'{servicio_nombre}. {descripcion_problema}'.strip(' .')
    vehiculo = {
        'marca': (ctx or {}).get('marca') or '',
        'modelo': (ctx or {}).get('modelo') or '',
        'anio': (ctx or {}).get('anio') or '',
        'motor': (ctx or {}).get('cilindraje') or (ctx or {}).get('motor') or '',
    }
    try:
        return completar_cotizacion_en_blanco(contenido, texto, vehiculo, taller)
    except Exception:
        logger.warning('plan de servicio no aplicado', exc_info=True)
        return contenido


def generar_cotizacion_ia(
    *,
    conversation=None,
    servicio_nombre: str = '',
    descripcion_problema: str = '',
    modalidad: str = 'taller',
    vehiculo: dict[str, Any] | None = None,
    contexto_rag_extra: str = '',
    taller=None,
    enriquecer_marketplace: bool = True,
    enriquecer_ml: bool = True,
    usar_web: bool = True,
) -> dict[str, Any]:
    if not asistente_cotizacion_habilitado():
        return {
            'disponible': False,
            'contenido': None,
            'error': 'El asistente de cotización IA no está habilitado.',
            'latencia_ms': 0,
        }

    ctx = armar_contexto_cotizacion(
        conversation=conversation,
        servicio_nombre=servicio_nombre,
        descripcion_problema=descripcion_problema,
        modalidad=modalidad,
        vehiculo=vehiculo,
    )
    if contexto_rag_extra:
        ctx['contexto_rag'] = contexto_rag_extra

    # PASO 1: Extracción estructurada del pedido con LLM (partes implícitas, alcance)
    pedido_extraido = None
    if taller is not None:
        try:
            from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import (
                extraer_pedido_con_llm,
            )

            texto_completo = f"{servicio_nombre}. {descripcion_problema}".strip()
            pedido_extraido = extraer_pedido_con_llm(
                texto_cliente=texto_completo,
                vehiculo_context={
                    'marca': ctx.get('marca', ''),
                    'modelo': ctx.get('modelo', ''),
                    'anio': ctx.get('anio', ''),
                    'patente': ctx.get('patente', ''),
                },
                taller=taller,
            )
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
                comprension_desde_pedido,
            )

            # La misma llamada. Su salida se valida con ComprensionSchema.
            ctx['comprension_llm'] = comprension_desde_pedido(pedido_extraido)
            logger.info(
                'generar_cotizacion_ia: extraccion_llm servicios=%d repuestos_mencionados=%d',
                len(pedido_extraido.servicios),
                len(pedido_extraido.repuestos_mencionados),
            )
        except Exception as exc:
            logger.warning('extraccion_pedido_llm falló: %s', exc, exc_info=True)

    # Catálogo del taller primero: si hay OfertaServicio para marca/modelo+servicio,
    # no llamar Gemini ni búsqueda web (misma regla que el agente chat).
    if taller is not None:
        try:
            from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
                _intentar_contenido_solo_catalogo,
            )
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
                _split_servicios,
            )
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.separar_pedido_taller import (
                texto_pedido_taller,
            )

            servicio_ctx = texto_pedido_taller(
                servicio_nombre or str(ctx.get('servicio_nombre') or ''),
                descripcion_problema or str(ctx.get('descripcion_problema') or ''),
            )
            solo_cat = _intentar_contenido_solo_catalogo(
                taller=taller,
                servicios=_split_servicios(servicio_ctx),
                marca=str(ctx.get('marca') or ''),
                modelo=str(ctx.get('modelo') or ''),
                tipo_motor=str(ctx.get('tipo_motor_efectivo') or ''),
                con_repuestos=True,
                descripcion=descripcion_problema or servicio_ctx,
                servicio_prompt=servicio_ctx,
            )
            if solo_cat and solo_cat.get('disponible') and solo_cat.get('contenido'):
                from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.completar_pedido import (
                    completar_pedido_con_faena,
                )

                contenido = completar_pedido_con_faena(
                    {**solo_cat['contenido'], 'comprension_llm': ctx.get('comprension_llm')},
                    servicio_nombre=servicio_nombre or servicio_ctx,
                    vehiculo=ctx,
                )
                logger.info(
                    'generar_cotizacion_ia: catálogo completo %s %s / %s — sin Gemini/web',
                    ctx.get('marca'),
                    ctx.get('modelo'),
                    (servicio_ctx or '')[:80],
                )
                contenido = _cerrar_con_plan(
                    contenido, ctx, servicio_nombre, descripcion_problema, taller,
                )
                return {
                    'disponible': True,
                    'contenido': contenido,
                    'contenido_ia': solo_cat.get('contenido_ia') or {'origen': 'catalogo_taller'},
                    'contexto': {
                        'vehiculo_marca': ctx.get('marca', ''),
                        'vehiculo_modelo': ctx.get('modelo', ''),
                        'vehiculo_anio': ctx.get('anio', ''),
                        'vehiculo_patente': ctx.get('patente', ''),
                        'vehiculo_cilindraje': ctx.get('cilindraje', ''),
                        'tipo_motor': ctx.get('tipo_motor_efectivo', ''),
                        'tipo_motor_label': ctx.get('tipo_motor_efectivo_label', ''),
                        'aviso_motor': ctx.get('tipo_motor_conflicto_detalle', ''),
                    },
                    'error': None,
                    'latencia_ms': 0,
                    'tokens_entrada': 0,
                    'tokens_salida': 0,
                    'modelo': 'catalogo_taller',
                    'valores_estimativos': False,
                    'desde_catalogo': True,
                }
        except Exception as exc:
            logger.info('generar_cotizacion_ia: intento catálogo falló, sigue Gemini: %s', exc)

    # Inyecta tarifas publicadas + historial enviado (marca/modelo) para orientar a Gemini.
    if taller is not None:
        try:
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
                construir_bloque_catalogo_prompt,
            )
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aprendizaje_cotizacion import (
                construir_bloque_historial_prompt,
            )

            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.separar_pedido_taller import (
                texto_pedido_taller,
            )

            servicio_ctx = texto_pedido_taller(
                servicio_nombre or str(ctx.get('servicio_nombre') or ''),
                descripcion_problema or str(ctx.get('descripcion_problema') or ''),
            )
            marca_ctx = str(ctx.get('marca') or '')
            modelo_ctx = str(ctx.get('modelo') or '')
            bloques: list[str] = []
            bloque_cat = construir_bloque_catalogo_prompt(
                taller=taller,
                servicio_nombre=servicio_ctx,
                marca=marca_ctx,
                modelo=modelo_ctx,
                tipo_motor=str(ctx.get('tipo_motor_efectivo') or ''),
            )
            if bloque_cat:
                bloques.append(bloque_cat)
            bloque_hist = construir_bloque_historial_prompt(
                taller=taller,
                servicio_nombre=servicio_ctx,
                marca=marca_ctx,
                modelo=modelo_ctx,
            )
            if bloque_hist:
                bloques.append(bloque_hist)
            if bloques:
                prev = (ctx.get('contexto_rag') or '').strip()
                extra = '\n\n'.join(bloques)
                ctx['contexto_rag'] = f'{prev}\n\n{extra}'.strip() if prev else extra
        except Exception as exc:
            logger.info('No se pudo inyectar catálogo/historial en prompt cotización: %s', exc)

    prompt = _construir_prompt(ctx, pedido_extraido=pedido_extraido)
    inicio = time.monotonic()
    crudo, uso, error = _llamar_gemini(prompt)
    latencia_ms = int((time.monotonic() - inicio) * 1000)

    if not crudo:
        try:
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.respaldo_cotizacion import (
                contenido_respaldo_sin_gemini,
            )

            contenido = contenido_respaldo_sin_gemini(
                ctx=ctx,
                servicio_nombre=servicio_nombre,
                descripcion_problema=descripcion_problema,
                taller=taller,
            )
        except Exception as exc:
            logger.warning('respaldo_sin_gemini falló: %s', exc, exc_info=True)
            return {
                'disponible': False,
                'contenido': None,
                'error': error or 'No se pudo generar la cotización.',
                'latencia_ms': latencia_ms,
                'tokens_entrada': int(uso.get('tokens_entrada') or 0),
                'tokens_salida': int(uso.get('tokens_salida') or 0),
                'modelo': str(uso.get('modelo') or ''),
            }
        logger.warning(
            'Gemini no entregó cotización (%s); se abre borrador de respaldo marca=%s modelo=%s',
            error,
            ctx.get('marca'),
            ctx.get('modelo'),
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.completar_pedido import (
            completar_pedido_con_faena,
        )

        contenido = completar_pedido_con_faena(
            {**(contenido or {}), 'comprension_llm': ctx.get('comprension_llm')}
            if isinstance(contenido, dict)
            else contenido,
            servicio_nombre=servicio_nombre,
            vehiculo=ctx,
        )
        adv = list(contenido.get('advertencias') or [])
        contenido = _cerrar_con_plan(
            contenido, ctx, servicio_nombre, descripcion_problema, taller,
        )
        return {
            'disponible': True,
            'contenido': contenido,
            'contenido_ia': {'origen': 'respaldo', 'motivo': error or 'gemini_unavailable'},
            'contexto': {
                'vehiculo_marca': ctx.get('marca', ''),
                'vehiculo_modelo': ctx.get('modelo', ''),
                'vehiculo_anio': ctx.get('anio', ''),
                'vehiculo_patente': ctx.get('patente', ''),
                'vehiculo_cilindraje': ctx.get('cilindraje', ''),
                'tipo_motor': ctx.get('tipo_motor_efectivo', ''),
                'tipo_motor_label': ctx.get('tipo_motor_efectivo_label', ''),
                'aviso_motor': ctx.get('tipo_motor_conflicto_detalle', ''),
            },
            'error': None,
            'aviso_respaldo': adv[0] if adv else None,
            'respaldo_sin_gemini': True,
            'latencia_ms': latencia_ms,
            'tokens_entrada': int(uso.get('tokens_entrada') or 0),
            'tokens_salida': int(uso.get('tokens_salida') or 0),
            'modelo': 'respaldo',
            'valores_estimativos': bool(contenido.get('valores_estimativos', True)),
        }

    if taller is not None:
        ctx = {**ctx, 'taller': taller}
    contenido = normalizar_cotizacion_ia(crudo, ctx)
    if ctx.get('comprension_llm'):
        contenido['comprension_llm'] = ctx['comprension_llm']
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.completar_pedido import (
        completar_pedido_con_faena,
    )

    contenido = completar_pedido_con_faena(
        contenido,
        servicio_nombre=servicio_nombre or str(contenido.get('servicio_nombre') or ''),
        vehiculo=ctx,
    )
    if enriquecer_marketplace:
        try:
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
                enriquecer_repuestos_cotizacion,
            )
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
                recalcular_totales,
            )

            reps = enriquecer_repuestos_cotizacion(
                list(contenido.get('repuestos') or []),
                marca_vehiculo=str(ctx.get('marca') or ''),
                modelo_vehiculo=str(ctx.get('modelo') or ''),
                anio_vehiculo=ctx.get('anio') or '',
                cilindraje=str(ctx.get('cilindraje') or ''),
                tipo_motor=str(ctx.get('tipo_motor_efectivo') or ''),
                servicio_nombre=servicio_nombre or str(contenido.get('servicio_nombre') or ''),
                taller=taller,
                usar_ml=enriquecer_ml,
                usar_web=usar_web,
            )
            
            # PASO 2: Aplicar selección inteligente de casas a cada repuesto
            reps = _aplicar_seleccion_casa_repuestos(
                reps,
                taller=taller,
                marca_vehiculo=str(ctx.get('marca') or ''),
                modelo_vehiculo=str(ctx.get('modelo') or ''),
                anio_vehiculo=ctx.get('anio') or '',
                tipo_motor=str(ctx.get('tipo_motor_efectivo') or ''),
                cilindraje=str(ctx.get('cilindraje') or ''),
            )
            
            # PASO 3: Ajustar rangos para que sean consistentes con precios finales
            reps = _ajustar_rangos_consistentes(reps)
            
            costo_rep, mo, total = recalcular_totales(reps, int(contenido.get('mano_obra_clp') or 0))
            contenido['repuestos'] = reps
            contenido['costo_repuestos_clp'] = costo_rep
            contenido['mano_obra_clp'] = mo
            contenido['total_clp'] = total
            contenido['valores_estimativos'] = any(
                bool(r.get('precio_estimado', True)) for r in reps
            ) if reps else True
        except Exception as exc:
            logger.warning(
                'enriquecer_repuestos_cotizacion falló; se entrega cotización IA sin enrich: %s',
                exc,
                exc_info=True,
            )
            contenido['valores_estimativos'] = True
    
    # CRÍTICO: Ajustar rangos para cubrir line totals después del enriquecimiento
    try:
        reps = _ajustar_rangos_consistentes(list(contenido.get('repuestos') or []))
        contenido['repuestos'] = reps
    except Exception as exc:
        logger.warning('_ajustar_rangos_consistentes falló: %s', exc, exc_info=True)

    # Prioridad: OfertaServicio del taller para marca/modelo (igual que el agente chat).
    if taller is not None:
        try:
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
                fusionar_contenido_con_catalogo_taller,
            )

            contenido = fusionar_contenido_con_catalogo_taller(
                contenido,
                taller=taller,
                servicio_nombre=servicio_nombre or str(contenido.get('servicio_nombre') or ''),
                marca=str(ctx.get('marca') or ''),
                modelo=str(ctx.get('modelo') or ''),
                tipo_motor=str(ctx.get('tipo_motor_efectivo') or ''),
            )
            
            # Marcar repuestos que vienen del catálogo del taller con flag especial
            if contenido.get('precio_desde_catalogo') and contenido.get('repuestos'):
                for rep in contenido['repuestos']:
                    if rep.get('fuente_marketplace') == 'catalogo' or rep.get('proveedor_nombre'):
                        rep['_config_modelo'] = True  # Flag para que selección de casas lo respete
                        
        except Exception as exc:
            logger.warning('fusionar_contenido_con_catalogo_taller falló: %s', exc, exc_info=True)

    contenido = _cerrar_con_plan(
        contenido, ctx, servicio_nombre, descripcion_problema, taller,
    )
    if 'valores_estimativos' not in contenido:
        contenido['valores_estimativos'] = True

    adv = list(contenido.get('advertencias') or [])
    if contenido.get('valores_estimativos') and not contenido.get('precio_desde_catalogo'):
        aviso = (
            'Precios de repuestos estimados: revisa marca, proveedor y montos antes de enviar al cliente.'
        )
        if aviso not in adv:
            adv.append(aviso)
        contenido['advertencias'] = adv
    else:
        contenido['advertencias'] = adv

    return {
        'disponible': True,
        'contenido': contenido,
        'contenido_ia': crudo,
        'contexto': {
            'vehiculo_marca': ctx.get('marca', ''),
            'vehiculo_modelo': ctx.get('modelo', ''),
            'vehiculo_anio': ctx.get('anio', ''),
            'vehiculo_patente': ctx.get('patente', ''),
            'vehiculo_cilindraje': ctx.get('cilindraje', ''),
            'tipo_motor': ctx.get('tipo_motor_efectivo', ''),
            'tipo_motor_label': ctx.get('tipo_motor_efectivo_label', ''),
            'aviso_motor': ctx.get('tipo_motor_conflicto_detalle', ''),
        },
        'error': None,
        'latencia_ms': latencia_ms,
        'tokens_entrada': int(uso.get('tokens_entrada') or 0),
        'tokens_salida': int(uso.get('tokens_salida') or 0),
        'modelo': str(uso.get('modelo') or ''),
        'valores_estimativos': bool(contenido.get('valores_estimativos')),
    }

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


def _llamar_gemini(prompt: str) -> tuple[dict[str, Any] | None, dict[str, int | str], str | None]:
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    model = (
        getattr(settings, 'ASISTENTE_COTIZACION_GEMINI_MODEL', '')
        or getattr(settings, 'ASISTENTE_DIAGNOSTICO_GEMINI_MODEL', '')
        or getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
        or 'gemini-3.1-flash-lite'
    ).strip()
    uso_vacio: dict[str, int | str] = {
        'tokens_entrada': 0,
        'tokens_salida': 0,
        'tokens_total': 0,
        'modelo': model,
    }
    if not api_key:
        return None, uso_vacio, 'El asistente IA no está configurado en el servidor (falta GEMINI_API_KEY).'

    timeout = int(getattr(settings, 'ASISTENTE_COTIZACION_IA_TIMEOUT', 15) or 15)
    max_retries = max(0, min(int(getattr(settings, 'GEMINI_RETRY_MAX', 2) or 2), 4))
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.3,
            'maxOutputTokens': 1800,
            'responseMimeType': 'application/json',
        },
    }

    for intento in range(max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            # Timeout/red intermitente: reintentar. Fallar al primer intento gastaba
            # tokens en el cliente (retry manual) sin reusar la misma llamada.
            if intento < max_retries:
                logger.warning(
                    'Gemini cotización intento %s/%s falló (%s); reintenta',
                    intento + 1,
                    max_retries + 1,
                    exc,
                )
                time.sleep(min(4, max(1, 2 ** intento)))
                continue
            return None, uso_vacio, 'Error de conexión con Gemini. Intenta de nuevo.'

        if resp.status_code == 200:
            try:
                body = resp.json()
                text = body['candidates'][0]['content']['parts'][0]['text']
            except (KeyError, IndexError, TypeError, ValueError):
                return None, uso_vacio, 'Gemini respondió en un formato inesperado.'

            meta = body.get('usageMetadata') or {}
            uso = {
                'tokens_entrada': int(meta.get('promptTokenCount') or 0),
                'tokens_salida': int(meta.get('candidatesTokenCount') or 0),
                'tokens_total': int(meta.get('totalTokenCount') or 0),
                'modelo': model,
            }
            return _parse_json(text), uso, None

        if resp.status_code == 429 and intento < max_retries:
            time.sleep(min(10, max(2, 2 ** intento)))
            continue

        if resp.status_code == 429:
            return None, uso_vacio, 'Gemini alcanzó el límite de consultas. Espera unos minutos.'
        return None, uso_vacio, 'No se pudo generar la cotización en este momento.'

    return None, uso_vacio, 'No se pudo generar la cotización en este momento.'


def _construir_prompt(ctx: dict[str, Any]) -> str:
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

Contexto del chat reciente (NO son líneas de cotización; ignora servicios de otro auto o solo mencionados):
{chat}
{rag_bloque}
REGLAS:
0. ALCANCE (CRÍTICO): cotiza ÚNICAMENTE "{pedido}" para ESTE vehículo ({ctx.get('marca', '')} {ctx.get('modelo', '')}). PROHIBIDO agregar servicios/repuestos que aparezcan en el chat, historial, catálogo extra o diagnósticos asociados si NO están en "Servicio solicitado". El campo servicio_nombre de salida DEBE ser exactamente "{pedido}".
0b. PRECIOS POR VEHÍCULO (CRÍTICO): NUNCA copies mano de obra ni precios de piezas de otro marca/modelo (Toyota ≠ BAIC; Yaris ≠ Yaris Cross) aunque el servicio se llame igual. Si el bloque de historial no es de este marca+modelo exacto, ignóralo.
1. Analiza el SERVICIO pedido + el VEHÍCULO concreto ({ctx.get('marca', '')} {ctx.get('modelo', '')} {ctx.get('anio', '')}, motor {efectivo}). Cada marca/modelo/año tiene piezas y cantidades distintas: no copies listas genéricas de otro auto.
2. Precios en CLP enteros: son ESTIMADOS de mercado Chile (taller) para que el proveedor los revise. NO digas que vienen de un catálogo o tienda.
3. CRÍTICO — IVA INCLUIDO: mano_obra_clp es precio FINAL al cliente con IVA 19% ya incluido. NO cotices neto ni agregues línea de IVA.
4. El motor efectivo es {efectivo}. No mezcles repuestos diésel/bencina/híbrido.
5. Incluye mano de obra separada de repuestos.
6. REPUESTOS POR VEHÍCULO (CRÍTICO): SOLO piezas compatibles con marca/modelo/año/cilindrada/motor. Prefiere MENOS líneas correctas. Nombra la pieza con precisión (posición: delantero/trasero, lado, kit completo si aplica).
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

            servicio_ctx = servicio_nombre or str(ctx.get('servicio_nombre') or '')
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
                contenido = solo_cat['contenido']
                logger.info(
                    'generar_cotizacion_ia: catálogo completo %s %s / %s — sin Gemini/web',
                    ctx.get('marca'),
                    ctx.get('modelo'),
                    (servicio_ctx or '')[:80],
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

            servicio_ctx = servicio_nombre or str(ctx.get('servicio_nombre') or '')
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

    prompt = _construir_prompt(ctx)
    inicio = time.monotonic()
    crudo, uso, error = _llamar_gemini(prompt)
    latencia_ms = int((time.monotonic() - inicio) * 1000)

    if not crudo:
        return {
            'disponible': False,
            'contenido': None,
            'error': error or 'No se pudo generar la cotización.',
            'latencia_ms': latencia_ms,
            'tokens_entrada': int(uso.get('tokens_entrada') or 0),
            'tokens_salida': int(uso.get('tokens_salida') or 0),
            'modelo': str(uso.get('modelo') or ''),
        }

    contenido = normalizar_cotizacion_ia(crudo, ctx)
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
                usar_web=True,
            )
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
        except Exception as exc:
            logger.warning('fusionar_contenido_con_catalogo_taller falló: %s', exc, exc_info=True)

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

"""Base de conocimiento técnico determinística para el agente IA.

No usa RAG: se calcula en vivo por match de palabras clave, igual que ficha_taller.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class BloqueDiagnostico:
    sistema: str
    palabras_clave: tuple[str, ...]
    causas_probables: tuple[str, ...]
    preguntas: tuple[str, ...]
    riesgo_circulacion: str
    reparaciones_asociadas: tuple[str, ...]


_BLOQUES: tuple[BloqueDiagnostico, ...] = (
    BloqueDiagnostico(
        sistema='Embrague / transmisión manual',
        palabras_clave=(
            'embrague', 'clutch', 'patina', 'patin', 'resbala', 'duro', 'duro el embrague',
            'pedal bajo', 'pedal alto', 'ruido al pisar', 'crujido embrague', 'volante bimasa',
            'collarin', 'collarín', 'cambio duro', 'no entra la marcha', 'salta la marcha',
        ),
        causas_probables=(
            'Desgaste del disco y plato de embrague (lo más frecuente si patina o el pedal quedó bajo).',
            'Collarín (cojinete) seco o dañado (ruido al pisar, pedal duro o vibración).',
            'Volante bimasa desgastado (vibraciones, ruidos metálicos al acelerar o al soltar).',
            'Fuga de líquido de embrague o aire en el circuito hidráulico (pedal esponjoso o bajo).',
        ),
        preguntas=(
            '¿El auto patina al acelerar en subida o al arrancar?',
            '¿El ruido aparece al pisar el pedal o al soltarlo?',
            '¿Hace cuánto que notaste el problema y empeoró de golpe o gradual?',
        ),
        riesgo_circulacion=(
            'Si patina mucho, evita subidas cargadas y no abuses del acelerador; '
            'puede quedarte sin tracción en un cruce.'
        ),
        reparaciones_asociadas=(
            'Kit de embrague (disco, plato, collarín)',
            'Volante bimasa (si aplica al modelo)',
            'Revisión de caja de cambios si salta marcha',
        ),
    ),
    BloqueDiagnostico(
        sistema='Frenos',
        palabras_clave=(
            'freno', 'frenos', 'pastilla', 'pastillas', 'disco', 'discos', 'tambor',
            'chirrid', 'chillid', 'rechin', 'vibra al frenar', 'pedal esponjoso',
            'pedal duro', 'freno duro', 'freno blando', 'abs', 'tironea al frenar',
            'ruido al frenar', 'frenada', 'ferodo',
        ),
        causas_probables=(
            'Pastillas o discos desgastados (chirridos, menor frenada, vibración al frenar).',
            'Discos ovalados o con surcos (vibración en el volante al frenar).',
            'Líquido de frenos bajo o con aire (pedal esponjoso).',
            'Pinzas o mangueras con fuga o trabadas (tironeo, calor en rueda, olor).',
        ),
        preguntas=(
            '¿El ruido o la vibración aparece solo al frenar o también al girar?',
            '¿El pedal se siente normal, duro o esponjoso?',
            '¿Notaste olor a quemado o calor en alguna rueda?',
        ),
        riesgo_circulacion=(
            'Frenos con pedal esponjoso o muy bajo: conviene no circular hasta revisión; '
            'desgaste leve con ruido puede esperar unos días con manejo suave.'
        ),
        reparaciones_asociadas=(
            'Cambio de pastillas y/o discos',
            'Rectificado o cambio de discos',
            'Purga y revisión de líquido de frenos',
            'Revisión de pinzas y mangueras',
        ),
    ),
    BloqueDiagnostico(
        sistema='Motor / vibraciones',
        palabras_clave=(
            'vibra', 'vibracion', 'vibración', 'tiembla', 'temblor', 'motor suena',
            'ruido motor', 'perdida potencia', 'falta fuerza', 'aceite', 'humo',
            'check engine', 'luz motor', 'tironea', 'calienta', 'sobrecalent',
            'consumo aceite', 'golpeteo', 'detonacion',
        ),
        causas_probables=(
            'Bujías o bobinas en mal estado (tironeo, pérdida de potencia, vibración en ralentí).',
            'Soporte de motor desgastado (vibración en ralentí o al acelerar).',
            'Filtro de aire tapado o admisión con fuga (falta de fuerza).',
            'Nivel o calidad de aceite inadecuada (ruidos, consumo elevado).',
            'Sistema de refrigeración con fuga o termostato (sobrecalentamiento).',
        ),
        preguntas=(
            '¿La vibración es en ralentí parado o solo en marcha?',
            '¿Hay alguna luz encendida en el tablero?',
            '¿Cuándo fue la última mantención o cambio de aceite?',
        ),
        riesgo_circulacion=(
            'Si la luz de temperatura enciende o hay humo continuo, detente y revisa nivel de aceite/refrigerante; '
            'no sigas manejando con sobrecalentamiento.'
        ),
        reparaciones_asociadas=(
            'Diagnóstico computacional (scanner)',
            'Mantención (aceite, filtros, bujías)',
            'Revisión de soportes de motor',
            'Sistema de refrigeración',
        ),
    ),
    BloqueDiagnostico(
        sistema='Suspensión / dirección',
        palabras_clave=(
            'suspension', 'suspensión', 'amortiguador', 'amortiguadores', 'golpe seco',
            'crujido', 'cruje', 'direccion', 'dirección', 'volante suelto', 'volante duro',
            'tironea', 'alineacion', 'alineación', 'balanceo', 'neumatico', 'neumático',
            'rueda', 'bujes', 'rotula', 'rótula', 'terminal', 'barra estabilizadora',
        ),
        causas_probables=(
            'Amortiguadores desgastados (rebotes, golpes secos, menor estabilidad).',
            'Bujes o rótulas con holgura (crujidos al pasar badenes o al girar).',
            'Terminales o barra de dirección desgastados (volante impreciso, tironeo).',
            'Neumáticos desgastados o con presión incorrecta (vibración, desgaste irregular).',
        ),
        preguntas=(
            '¿El ruido aparece en badenes, al girar o en recta?',
            '¿Notaste desgaste irregular en los neumáticos?',
            '¿El volante vibra a cierta velocidad?',
        ),
        riesgo_circulacion=(
            'Holgura marcada en dirección o ruidos fuertes en suspensión: maneja con precaución '
            'y agenda revisión pronto; no es urgencia inmediata salvo que el volante no responda bien.'
        ),
        reparaciones_asociadas=(
            'Revisión de suspensión y dirección',
            'Cambio de amortiguadores o bujes',
            'Alineación y balanceo',
        ),
    ),
    BloqueDiagnostico(
        sistema='Transmisión automática',
        palabras_clave=(
            'automatica', 'automática', 'caja automatica', 'caja automática', 'no cambia',
            'patina', 'patina la caja', 'salta', 'golpe al cambiar', 'modo sport',
            'transmision automatica', 'transmisión automática', 'cvt',
        ),
        causas_probables=(
            'Nivel o estado del aceite de caja (cambios bruscos, patinaje).',
            'Desgaste interno de embragues de la caja (patina en aceleración).',
            'Sensores o módulo de transmisión con falla (modo de emergencia, luces).',
        ),
        preguntas=(
            '¿El problema aparece en frío o después de manejar un rato?',
            '¿Hay alguna luz de advertencia en el tablero?',
            '¿Cuándo fue la última mantención de la caja?',
        ),
        riesgo_circulacion=(
            'Si la caja patina mucho o entra en modo de emergencia, evita aceleraciones fuertes '
            'y agenda diagnóstico pronto.'
        ),
        reparaciones_asociadas=(
            'Cambio de aceite de caja automática',
            'Diagnóstico computacional de transmisión',
            'Reparación o reconstrucción de caja (según diagnóstico)',
        ),
    ),
    BloqueDiagnostico(
        sistema='Batería / arranque / eléctrico básico',
        palabras_clave=(
            'bateria', 'batería', 'no parte', 'no arranca', 'arranque', 'alternador',
            'luces debiles', 'luces débiles', 'se apaga', 'click click', 'clic clic',
            'carga', 'corriente', 'electrico basico', 'farol', 'faros',
        ),
        causas_probables=(
            'Batería agotada o al final de vida (no arranca, luces débiles).',
            'Alternador con falla (batería se descarga al andar).',
            'Terminales sulfatados o con mala conexión (arranque intermitente).',
            'Motor de arranque desgastado (ruido al girar, no levanta).',
        ),
        preguntas=(
            '¿Al girar la llave escuchas un clic repetido o nada de ruido?',
            '¿Las luces del tablero se ven normales al intentar arrancar?',
            '¿Hace cuánto cambiaste la batería?',
        ),
        riesgo_circulacion=(
            'Si no arranca, no es problema de circulación; si se apaga en marcha, detente en lugar seguro.'
        ),
        reparaciones_asociadas=(
            'Prueba y cambio de batería',
            'Revisión de alternador y arranque',
            'Limpieza de terminales',
        ),
    ),
    BloqueDiagnostico(
        sistema='Refrigeración / climatización',
        palabras_clave=(
            'refrigeracion', 'refrigeración', 'radiador', 'termostato', 'antifreeze',
            'refrigerante', 'calienta', 'temperatura alta', 'ventilador', 'aire acondicionado',
            'a/c', 'ac no enfría', 'no enfría', 'climatizacion', 'climatización',
        ),
        causas_probables=(
            'Nivel bajo de refrigerante por fuga (sobrecalentamiento).',
            'Termostato trabado (tarda en calentar o calienta de más).',
            'Radiador o mangueras con fuga (manchas bajo el auto, olor dulce).',
            'Sistema A/C con fuga de gas o compresor (no enfría).',
        ),
        preguntas=(
            '¿Ves humo blanco o manchas bajo el capó o el auto?',
            '¿La aguja de temperatura sube en detenciones o en ruta?',
            '¿El A/C dejó de enfriar de golpe o fue gradual?',
        ),
        riesgo_circulacion=(
            'Temperatura en zona roja: detente, apaga motor y no sigas hasta revisar; '
            'puedes dañar el motor.'
        ),
        reparaciones_asociadas=(
            'Revisión de sistema de refrigeración',
            'Cambio de termostato o mangueras',
            'Carga y reparación de A/C',
        ),
    ),
)


def _normalizar(texto: str) -> str:
    t = (texto or '').lower().strip()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return t


def _puntaje_bloque(bloque: BloqueDiagnostico, texto_norm: str) -> int:
    score = 0
    for kw in bloque.palabras_clave:
        kw_norm = _normalizar(kw)
        if len(kw_norm) < 4:
            if re.search(rf'\b{re.escape(kw_norm)}\b', texto_norm):
                score += 2
        elif kw_norm in texto_norm:
            score += 2 if ' ' in kw_norm else 1
    return score


def _formatear_bloque(bloque: BloqueDiagnostico) -> str:
    causas = '\n'.join(f'  - {c}' for c in bloque.causas_probables)
    preguntas = '\n'.join(f'  - {p}' for p in bloque.preguntas)
    reparaciones = ', '.join(bloque.reparaciones_asociadas)
    return (
        f'Sistema: {bloque.sistema}\n'
        f'Causas probables (orientación, NO diagnóstico certero):\n{causas}\n'
        f'Preguntas útiles para este caso:\n{preguntas}\n'
        f'Riesgo si sigue circulando: {bloque.riesgo_circulacion}\n'
        f'Reparaciones que suelen asociarse: {reparaciones}'
    )


def bloque_diagnostico_relevante(
    texto_cliente: str = '',
    descripcion_problema: str = '',
    *,
    max_bloques: int = 2,
) -> str:
    """Devuelve 0-2 bloques de diagnóstico que matchean síntomas del turno."""
    texto = ' '.join(filter(None, [texto_cliente, descripcion_problema]))
    texto_norm = _normalizar(texto)
    if len(texto_norm) < 8:
        return ''

    scored: list[tuple[int, BloqueDiagnostico]] = []
    for bloque in _BLOQUES:
        pts = _puntaje_bloque(bloque, texto_norm)
        if pts > 0:
            scored.append((pts, bloque))

    if not scored:
        return ''

    scored.sort(key=lambda x: (-x[0], x[1].sistema))
    seleccionados = [b for _, b in scored[: max(1, max_bloques)]]
    partes = [_formatear_bloque(b) for b in seleccionados]
    return (
        'Conocimiento técnico de diagnóstico (orientación general; confirma siempre con inspección física):\n\n'
        + '\n\n---\n\n'.join(partes)
    )

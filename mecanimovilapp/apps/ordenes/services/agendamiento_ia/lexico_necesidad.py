"""
Léxico de síntomas → términos de catálogo e interpretación para el cliente.

v1 del asistente (sin LLM): amplía lo que escribe el usuario y explica qué podría necesitar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ReglaSintoma:
    id: str
    interpretacion: str
    terminos_catalogo: tuple[str, ...]
    patrones: tuple[str, ...]
    slugs_salud: tuple[str, ...] = ()
    boost_servicio: float = 0.58


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ''
    nfkd = unicodedata.normalize('NFKD', texto.lower().strip())
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


# Patrones sobre texto normalizado (sin tildes).
REGLAS_SINTOMA: tuple[ReglaSintoma, ...] = (
    ReglaSintoma(
        id='frenos',
        interpretacion='Podría ser el sistema de frenos (pastillas, discos o líquido de frenos).',
        terminos_catalogo=(
            'freno', 'frenos', 'pastilla', 'pastillas', 'disco', 'discos',
            'rectificado', 'liquido de frenos', 'liquido frenos',
        ),
        patrones=(
            r'\bfren', r'\babs\b', r'pastilla', r'\bdisco', r'no frena',
            r'pedal.{0,20}(blando|duro|hund|vibr)', r'ruido.{0,30}fren',
            r'fren.{0,20}(ruido|chill|vibr|patin)',
            r'se va al piso', r'pedal.{0,12}piso', r'frenada.{0,12}larga',
            r'chillido.{0,15}fren', r'barra.{0,12}freno',
        ),
        slugs_salud=('brakes', 'brake-discs', 'brake-fluid'),
    ),
    ReglaSintoma(
        id='motor_aceite',
        interpretacion='Podría requerir revisión de motor, aceite o filtro.',
        terminos_catalogo=(
            'aceite', 'filtro de aceite', 'filtro aceite', 'motor', 'mantenimiento',
            'kilometraje', 'cambio de aceite', 'bujia', 'bujias',
        ),
        patrones=(
            r'\baceite', r'filtro.{0,12}aceite', r'perdida.{0,15}aceite',
            r'luz aceite', r'motor.{0,20}(ruido|golpe|vibr)', r'\bbujia',
            r'consumo.{0,12}aceite', r'se calienta', r'sobrecalient',
        ),
        slugs_salud=('oil', 'oil-filter', 'spark-plug'),
    ),
    ReglaSintoma(
        id='refrigeracion',
        interpretacion='Podría ser refrigerante, radiador o sobrecalentamiento.',
        terminos_catalogo=(
            'refrigerante', 'radiador', 'anticongelante', 'enfriamiento',
        ),
        patrones=(
            r'refrigerante', r'anticongelante', r'radiador',
            r'humo blanco', r'sobrecalient', r'temperatura alta',
            r'calienta.{0,15}rapido', r'perdida.{0,12}agua',
        ),
        slugs_salud=('coolant',),
    ),
    ReglaSintoma(
        id='arranque_bateria',
        interpretacion='Podría ser batería, arranque o sistema eléctrico.',
        terminos_catalogo=(
            'bateria', 'arranque', 'electrico', 'electromecanico', 'escaner',
            'diagnostico', 'ampolleta',
        ),
        patrones=(
            r'no arranca', r'no parte', r'bateria', r'descarg', r'arranque',
            r'luces.{0,15}(debil|parpade)', r'clic.{0,10}al girar',
            r'alternador', r'electri', r'quedo botado', r'me botaron',
            r'no prende', r'solo hace clic',
        ),
        slugs_salud=('battery',),
    ),
    ReglaSintoma(
        id='suspension_neumaticos',
        interpretacion='Podría ser suspensión, amortiguadores o neumáticos.',
        terminos_catalogo=(
            'amortiguador', 'amortiguadores', 'neumatico', 'neumaticos',
            'alineacion', 'balanceo', 'suspension',
        ),
        patrones=(
            r'amortiguador', r'suspension', r'neumatic', r'cubierta',
            r'vibra', r'volante.{0,15}vibr', r'golpeteo', r'balanceo',
            r'alineacion', r'desgaste.{0,12}neum', r'tirita', r'tiriton',
            r'sacude', r'volante.{0,12}suelto',
        ),
        slugs_salud=('shocks', 'tires'),
    ),
    ReglaSintoma(
        id='frenos_aire',
        interpretacion='Podría ser filtro de aire o admisión.',
        terminos_catalogo=('filtro de aire', 'filtro aire', 'aire'),
        patrones=(
            r'filtro.{0,12}aire', r'poca potencia', r'falta.{0,10}fuerza',
            r'consume mucho', r'ronronea.{0,12}raro',
        ),
        slugs_salud=('air-filter', 'cabin-filter'),
    ),
    ReglaSintoma(
        id='climatizacion',
        interpretacion='Podría ser aire acondicionado o filtro de habitáculo.',
        terminos_catalogo=('habitaculo', 'habitáculo', 'aire', 'filtro'),
        patrones=(
            r'aire acondicionado', r'\bac\b', r'no enfr', r'mal olor',
            r'filtro.{0,12}habitaculo', r'humedad.{0,12}cabina',
        ),
        slugs_salud=('cabin-filter',),
    ),
    ReglaSintoma(
        id='diagnostico_general',
        interpretacion='Un diagnóstico mecánico puede identificar la causa con más precisión.',
        terminos_catalogo=(
            'diagnostico', 'diagnóstico', 'escaner', 'escáner', 'revision',
            'revisión', 'inspeccion', 'inspección',
        ),
        patrones=(
            r'no se que', r'no sé que', r'ruido raro', r'ruido extran',
            r'falla.{0,12}luz', r'check engine', r'luz motor',
            r'no se.{0,15}pasa', r'comportamiento raro',
        ),
        boost_servicio=0.42,
    ),
    ReglaSintoma(
        id='lavado',
        interpretacion='Podrías necesitar lavado o detailing a domicilio.',
        terminos_catalogo=('lavado', 'limpieza', 'detailing'),
        patrones=(r'lavado', r'limpiar.{0,12}auto', r'sucio', r'barro'),
        boost_servicio=0.5,
    ),
    ReglaSintoma(
        id='revision_legal',
        interpretacion='Podría tratarse de revisión técnica o documentación del vehículo.',
        terminos_catalogo=('revision tecnica', 'revisión técnica', 'homologacion'),
        patrones=(r'revision tecnica', r'permiso de circulacion', r'homolog'),
        boost_servicio=0.55,
    ),
)


def detectar_sintomas(texto: str) -> list[ReglaSintoma]:
    norm = normalizar_texto(texto)
    if not norm:
        return []
    matched: list[ReglaSintoma] = []
    for regla in REGLAS_SINTOMA:
        for patron in regla.patrones:
            if re.search(patron, norm):
                matched.append(regla)
                break
    return matched


def expandir_texto_busqueda(texto: str, reglas: Sequence[ReglaSintoma] | None = None) -> str:
    """Texto original + términos de catálogo para mejorar matching."""
    reglas = list(reglas if reglas is not None else detectar_sintomas(texto))
    partes = [texto or '']
    for regla in reglas:
        partes.extend(regla.terminos_catalogo)
    return ' '.join(p for p in partes if p).strip()


def interpretaciones_cliente(reglas: Sequence[ReglaSintoma], max_items: int = 2) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for regla in reglas:
        if regla.interpretacion in seen:
            continue
        seen.add(regla.interpretacion)
        out.append(regla.interpretacion)
        if len(out) >= max_items:
            break
    return out


def resumen_interpretacion(reglas: Sequence[ReglaSintoma]) -> str | None:
    items = interpretaciones_cliente(reglas, max_items=2)
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return f"{items[0]} También: {items[1]}"


def servicio_coincide_terminos(servicio_nombre: str, servicio_descripcion: str, terminos: Sequence[str]) -> bool:
    corpus = normalizar_texto(f'{servicio_nombre} {servicio_descripcion or ""}')
    for term in terminos:
        t = normalizar_texto(term)
        if len(t) >= 3 and t in corpus:
            return True
    return False


def boost_lexico_servicio(
    servicio_nombre: str,
    servicio_descripcion: str,
    reglas: Sequence[ReglaSintoma],
) -> tuple[float, str | None]:
    """Score extra y razón legible si el servicio encaja con síntomas detectados."""
    best = 0.0
    razon: str | None = None
    for regla in reglas:
        if servicio_coincide_terminos(servicio_nombre, servicio_descripcion, regla.terminos_catalogo):
            if regla.boost_servicio > best:
                best = regla.boost_servicio
                razon = regla.interpretacion
    return best, razon

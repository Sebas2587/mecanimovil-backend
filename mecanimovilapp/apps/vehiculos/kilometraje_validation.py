"""
Validación de kilometraje: referencia SII (GetAPI mileage) y plausibilidad por edad.

La regla SII tiene prioridad cuando hay mileage; la plausibilidad por año solo aplica
cuando no existe referencia SII (sin nueva consulta a GetAPI).
"""
from __future__ import annotations

from datetime import date

# Plausibilidad por edad (Chile, uso particular)
KM_PER_YEAR_MIN = 3_000
KM_PER_YEAR_TYPICAL = 12_000
KM_PER_YEAR_MAX = 28_000
KM_MAX_VEHICULO_NUEVO = 45_000
KM_ABSOLUTE_MAX = 999_999


def parse_mileage_value(raw) -> int | None:
    """Normaliza mileage/kilometraje desde GetAPI a entero positivo."""
    if raw is None or raw == '':
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = int(raw)
        return value if value > 0 else None
    if isinstance(raw, str):
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if not digits:
            return None
        value = int(digits)
        return value if value > 0 else None
    return None


def mileage_from_getapi_payload(data: dict | None) -> int | None:
    """Busca mileage en el objeto data de plate o appraisal."""
    if not data or not isinstance(data, dict):
        return None
    for key in ('mileage', 'kilometraje', 'odometer', 'kilometers'):
        parsed = parse_mileage_value(data.get(key))
        if parsed is not None:
            return parsed
    return None


def merge_mileage_metadata(plate_data: dict | None, appraisal_extra: dict | None) -> dict:
    """
    Unifica mileage desde plate (prioridad) o appraisal.
    Retorna mileage, kilometraje_api, tiene_mileage_sii, mileage_fuente.
    """
    mileage_plate = mileage_from_getapi_payload(plate_data)
    mileage_appraisal = None
    if appraisal_extra:
        mileage_appraisal = parse_mileage_value(appraisal_extra.get('mileage'))

    if mileage_plate is not None:
        mileage = mileage_plate
        fuente = 'plate'
    elif mileage_appraisal is not None:
        mileage = mileage_appraisal
        fuente = 'appraisal'
    else:
        mileage = None
        fuente = 'none'

    return {
        'mileage': mileage,
        'kilometraje_api': mileage,
        'tiene_mileage_sii': mileage is not None,
        'mileage_fuente': fuente,
    }


def parse_vehicle_year(year) -> int | None:
    """Normaliza año del vehículo a entero razonable."""
    if year is None or year == '':
        return None
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    current = date.today().year
    if y < 1950 or y > current + 1:
        return None
    return y


def calcular_banda_kilometraje(year) -> dict | None:
    """
    Banda esperada de km según antigüedad del vehículo.
    Retorna None si no hay año válido.
    """
    y = parse_vehicle_year(year)
    if y is None:
        return None

    años_vida = max(0, date.today().year - y)
    if años_vida <= 0:
        return {
            'year': y,
            'años_vida': 0,
            'min': 0,
            'tipico': 8_000,
            'max': KM_MAX_VEHICULO_NUEVO,
        }

    return {
        'year': y,
        'años_vida': años_vida,
        'min': años_vida * KM_PER_YEAR_MIN,
        'tipico': años_vida * KM_PER_YEAR_TYPICAL,
        'max': años_vida * KM_PER_YEAR_MAX,
    }


def _fmt_km_cl(value: int) -> str:
    return f'{value:,}'.replace(',', '.')


def detectar_km_typo_sugerido(km: int, banda: dict) -> int | None:
    """Si km×10 o km÷10 cae en banda, sugiere corrección de tipeo."""
    candidatos = []
    if km >= 10:
        candidatos.append(km // 10)
    candidatos.append(km * 10)
    for alt in candidatos:
        if alt <= 0 or alt > KM_ABSOLUTE_MAX:
            continue
        if banda['min'] <= alt <= banda['max']:
            return alt
    return None


def validar_plausibilidad_por_edad(kilometraje_usuario, year=None) -> dict:
    """
    Valida km ingresado contra banda por edad del vehículo (sin SII).

    Returns dict con valid, nivel, code, mensaje, banda, km_sugerido, requiere_confirmacion.
    """
    try:
        km = int(kilometraje_usuario)
    except (TypeError, ValueError):
        return {
            'valid': False,
            'nivel': 'error',
            'code': 'kilometraje_invalido',
            'mensaje': 'El kilometraje debe ser un número válido.',
            'banda': None,
            'km_sugerido': None,
            'requiere_confirmacion': False,
        }

    if km <= 0:
        return {
            'valid': False,
            'nivel': 'error',
            'code': 'kilometraje_invalido',
            'mensaje': 'El kilometraje debe ser mayor a 0.',
            'banda': None,
            'km_sugerido': None,
            'requiere_confirmacion': False,
        }

    if km > KM_ABSOLUTE_MAX:
        return {
            'valid': False,
            'nivel': 'error',
            'code': 'km_absoluto_excesivo',
            'mensaje': f'El kilometraje ({_fmt_km_cl(km)} km) supera el máximo permitido.',
            'banda': None,
            'km_sugerido': None,
            'requiere_confirmacion': False,
        }

    banda = calcular_banda_kilometraje(year)
    if banda is None:
        return {
            'valid': True,
            'nivel': 'aviso',
            'code': 'sin_year_plausibilidad',
            'mensaje': (
                'No hay año del vehículo para estimar un rango de kilometraje esperado. '
                'Verifica que el valor del odómetro sea correcto.'
            ),
            'banda': None,
            'km_sugerido': None,
            'requiere_confirmacion': False,
        }

    km_min, km_max = banda['min'], banda['max']
    años = banda['años_vida']
    rango_txt = f'{_fmt_km_cl(km_min)}–{_fmt_km_cl(km_max)} km'

    km_sugerido = detectar_km_typo_sugerido(km, banda)
    if km_sugerido is not None and km_sugerido != km:
        return {
            'valid': True,
            'nivel': 'aviso',
            'code': 'km_posible_typo',
            'mensaje': (
                f'El valor {_fmt_km_cl(km)} km parece poco habitual para un vehículo de '
                f'{años} año(s) (rango habitual: {rango_txt}). '
                f'¿Quisiste ingresar {_fmt_km_cl(km_sugerido)} km?'
            ),
            'banda': banda,
            'km_sugerido': km_sugerido,
            'requiere_confirmacion': True,
        }

    if km < km_min:
        if km_min > 0 and km < km_min * 0.25:
            return {
                'valid': False,
                'nivel': 'error',
                'code': 'km_muy_bajo_edad',
                'mensaje': (
                    f'Para un vehículo del {_fmt_km_cl(banda["year"])} (~{años} años), '
                    f'{_fmt_km_cl(km)} km es demasiado bajo. Rango habitual: {rango_txt}.'
                ),
                'banda': banda,
                'km_sugerido': None,
                'requiere_confirmacion': False,
            }
        return {
            'valid': True,
            'nivel': 'aviso',
            'code': 'km_bajo_edad',
            'mensaje': (
                f'El kilometraje ({_fmt_km_cl(km)} km) es bajo para un vehículo de ~{años} años '
                f'(habitual: {rango_txt}). Si el odómetro es correcto, confirma para continuar.'
            ),
            'banda': banda,
            'km_sugerido': None,
            'requiere_confirmacion': True,
        }

    if km > km_max:
        if km > km_max * 1.5:
            return {
                'valid': False,
                'nivel': 'error',
                'code': 'km_muy_alto_edad',
                'mensaje': (
                    f'Para un vehículo del {_fmt_km_cl(banda["year"])} (~{años} años), '
                    f'{_fmt_km_cl(km)} km es demasiado alto. Rango habitual: {rango_txt}.'
                ),
                'banda': banda,
                'km_sugerido': None,
                'requiere_confirmacion': False,
            }
        return {
            'valid': True,
            'nivel': 'aviso',
            'code': 'km_alto_edad',
            'mensaje': (
                f'El kilometraje ({_fmt_km_cl(km)} km) es alto para un vehículo de ~{años} años '
                f'(habitual: {rango_txt}). Si el odómetro es correcto, confirma para continuar.'
            ),
            'banda': banda,
            'km_sugerido': None,
            'requiere_confirmacion': True,
        }

    return {
        'valid': True,
        'nivel': 'ok',
        'code': 'km_plausible_edad',
        'mensaje': '',
        'banda': banda,
        'km_sugerido': None,
        'requiere_confirmacion': False,
    }


def _merge_resultado_base(
    resultado: dict,
    *,
    mileage_sii=None,
    kilometraje_usuario=None,
) -> dict:
    """Campos comunes en respuesta de validación."""
    base = {
        'valid': resultado['valid'],
        'nivel': resultado['nivel'],
        'code': resultado['code'],
        'mensaje': resultado.get('mensaje', ''),
        'mileage_sii': mileage_sii,
        'kilometraje_usuario': kilometraje_usuario,
    }
    for key in ('banda', 'km_sugerido', 'requiere_confirmacion'):
        if key in resultado:
            base[key] = resultado[key]
    return base


def validar_kilometraje_usuario(
    kilometraje_usuario,
    mileage_sii=None,
    tiene_mileage_sii=None,
    year=None,
) -> dict:
    """
    Valida km ingresado contra referencia SII.

    Returns:
        {
            'valid': bool,
            'nivel': 'ok' | 'aviso' | 'error',
            'code': str,
            'mensaje': str,
            'mileage_sii': int | None,
            'kilometraje_usuario': int,
        }
    """
    try:
        km_user = int(kilometraje_usuario)
    except (TypeError, ValueError):
        return {
            'valid': False,
            'nivel': 'error',
            'code': 'kilometraje_invalido',
            'mensaje': 'El kilometraje debe ser un número válido.',
            'mileage_sii': parse_mileage_value(mileage_sii),
            'kilometraje_usuario': None,
        }

    if km_user <= 0:
        return {
            'valid': False,
            'nivel': 'error',
            'code': 'kilometraje_invalido',
            'mensaje': 'El kilometraje debe ser mayor a 0.',
            'mileage_sii': parse_mileage_value(mileage_sii),
            'kilometraje_usuario': km_user,
        }

    km_sii = parse_mileage_value(mileage_sii)
    tiene_ref = tiene_mileage_sii if tiene_mileage_sii is not None else (km_sii is not None)

    if tiene_ref and km_sii is not None:
        if km_user < km_sii:
            return _merge_resultado_base(
                {
                    'valid': False,
                    'nivel': 'error',
                    'code': 'km_menor_que_sii',
                    'mensaje': (
                        f'El kilometraje ingresado ({_fmt_km_cl(km_user)} km) no puede ser menor al registrado '
                        f'en el SII ({_fmt_km_cl(km_sii)} km). Revisa el odómetro o corrige el valor.'
                    ),
                },
                mileage_sii=km_sii,
                kilometraje_usuario=km_user,
            )
        return _merge_resultado_base(
            {
                'valid': True,
                'nivel': 'ok',
                'code': 'km_coherente_sii',
                'mensaje': '',
            },
            mileage_sii=km_sii,
            kilometraje_usuario=km_user,
        )

    # Sin referencia SII: plausibilidad por edad (no consulta GetAPI)
    plaus = validar_plausibilidad_por_edad(km_user, year=year)
    aviso_sii = (
        'No hay kilometraje de referencia del SII para este vehículo (común en autos antiguos '
        'o sin dato en el registro). '
    )
    if plaus['code'] == 'km_plausible_edad':
        return _merge_resultado_base(plaus, mileage_sii=None, kilometraje_usuario=km_user)
    if plaus['code'] == 'sin_year_plausibilidad':
        plaus = {**plaus, 'mensaje': aviso_sii + plaus['mensaje']}
    elif plaus.get('mensaje'):
        plaus = {**plaus, 'mensaje': aviso_sii + plaus['mensaje']}

    return _merge_resultado_base(
        plaus,
        mileage_sii=None,
        kilometraje_usuario=km_user,
    )

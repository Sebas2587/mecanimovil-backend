"""
Validación de kilometraje ingresado vs mileage de GetAPI (referencia SII).
"""
from __future__ import annotations


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


def validar_kilometraje_usuario(
    kilometraje_usuario,
    mileage_sii=None,
    tiene_mileage_sii=None,
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
            return {
                'valid': False,
                'nivel': 'error',
                'code': 'km_menor_que_sii',
                'mensaje': (
                    f'El kilometraje ingresado ({km_user:,} km) no puede ser menor al registrado '
                    f'en el SII ({km_sii:,} km). Revisa el odómetro o corrige el valor.'
                ),
                'mileage_sii': km_sii,
                'kilometraje_usuario': km_user,
            }
        return {
            'valid': True,
            'nivel': 'ok',
            'code': 'km_coherente_sii',
            'mensaje': '',
            'mileage_sii': km_sii,
            'kilometraje_usuario': km_user,
        }

    return {
        'valid': True,
        'nivel': 'aviso',
        'code': 'sin_mileage_sii',
        'mensaje': (
            'No hay kilometraje de referencia del SII para este vehículo (común en autos antiguos '
            'o sin dato en el registro). Verifica que el valor del odómetro sea correcto.'
        ),
        'mileage_sii': None,
        'kilometraje_usuario': km_user,
    }

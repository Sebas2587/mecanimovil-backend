"""La cotización sale del servicio, no de la frase literal.

La lectura principal es la llamada que ya existe (`extraer_pedido_con_llm`):
devuelve servicios para cualquier trabajo. Si no responde, se usa el catálogo
declarativo de abajo. Si tampoco calza, la cotización no sale como lista: queda
una duda visible y la verificación en falso.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
    norm as _norm_base,
)

Buscador = Callable[[dict], dict | None]

# Modelo → marca. No es una lista que rechace el resto: un modelo desconocido
# se conserva y se deja como duda.
_MODELOS = (
    ('yaris cross', 'Toyota', 'Yaris Cross'),
    ('land cruiser', 'Toyota', 'Land Cruiser'),
    ('hilux', 'Toyota', 'Hilux'),
    ('corolla', 'Toyota', 'Corolla'),
    ('yaris', 'Toyota', 'Yaris'),
    ('rav4', 'Toyota', 'RAV4'),
    ('rush', 'Toyota', 'Rush'),
    ('sail', 'Chevrolet', 'Sail'),
    ('spark', 'Chevrolet', 'Spark'),
    ('onix', 'Chevrolet', 'Onix'),
    ('tracker', 'Chevrolet', 'Tracker'),
    ('captiva', 'Chevrolet', 'Captiva'),
    ('dmax', 'Chevrolet', 'D-Max'),
    ('oroch', 'Renault', 'Oroch'),
    ('duster', 'Renault', 'Duster'),
    ('kwid', 'Renault', 'Kwid'),
    ('sandero', 'Renault', 'Sandero'),
    ('logan', 'Renault', 'Logan'),
    ('boxer', 'Peugeot', 'Boxer'),
    ('partner', 'Peugeot', 'Partner'),
    ('208', 'Peugeot', '208'),
    ('301', 'Peugeot', '301'),
    ('celerio', 'Suzuki', 'Celerio'),
    ('swift', 'Suzuki', 'Swift'),
    ('vitara', 'Suzuki', 'Vitara'),
    ('jimny', 'Suzuki', 'Jimny'),
    ('bravo', 'Fiat', 'Bravo'),
    ('strada', 'Fiat', 'Strada'),
    ('cronos', 'Fiat', 'Cronos'),
    ('accent', 'Hyundai', 'Accent'),
    ('tucson', 'Hyundai', 'Tucson'),
    ('santa fe', 'Hyundai', 'Santa Fe'),
    ('elantra', 'Hyundai', 'Elantra'),
    ('creta', 'Hyundai', 'Creta'),
    ('porter', 'Hyundai', 'Porter'),
    ('sportage', 'Kia', 'Sportage'),
    ('sorento', 'Kia', 'Sorento'),
    ('cerato', 'Kia', 'Cerato'),
    ('rio 5', 'Kia', 'Rio 5'),
    ('rio', 'Kia', 'Rio'),
    ('morning', 'Kia', 'Morning'),
    ('mazda 3', 'Mazda', '3'),
    ('frontier', 'Nissan', 'Frontier'),
    ('np300', 'Nissan', 'NP300'),
    ('navara', 'Nissan', 'Navara'),
    ('sentra', 'Nissan', 'Sentra'),
    ('qashqai', 'Nissan', 'Qashqai'),
    ('cx5', 'Mazda', 'CX-5'),
    ('cx3', 'Mazda', 'CX-3'),
    ('mazda3', 'Mazda', 'Mazda3'),
    ('bt50', 'Mazda', 'BT-50'),
    ('ranger', 'Ford', 'Ranger'),
    ('fiesta', 'Ford', 'Fiesta'),
    ('escape', 'Ford', 'Escape'),
    ('amarok', 'Volkswagen', 'Amarok'),
    ('vento', 'Volkswagen', 'Vento'),
    ('gol', 'Volkswagen', 'Gol'),
    ('saveiro', 'Volkswagen', 'Saveiro'),
    ('civic', 'Honda', 'Civic'),
    ('crv', 'Honda', 'CR-V'),
    ('fit', 'Honda', 'Fit'),
    ('l200', 'Mitsubishi', 'L200'),
    ('lancer', 'Mitsubishi', 'Lancer'),
    ('montero', 'Mitsubishi', 'Montero'),
    ('outlander', 'Mitsubishi', 'Outlander'),
)

_CAPACIDAD_ACEITE_L = {
    'sail': 3.5,
    'spark': 3.8,
    'yaris': 3.7,
    'corolla': 4.2,
    'hilux': 6.6,
    'oroch': 4.0,
    'boxer': 6.0,
    'bravo': 4.0,
    'celerio': 3.2,
    'duster': 4.5,
}

# Último recurso. No es el precio de la cotización si hubo una ficha.
_REFERENCIA_CLP = {
    'kit_embrague': 85000,
    'bomba_embrague': 28000,
    'cilindro_receptor_embrague': 18000,
    'aceite_caja': 22000,
    'rodamiento_piloto': 15000,
    'balatas_freno': 28000,
    'pastillas_freno': 32000,
    'discos_freno': 45000,
    'tambores_freno': 35000,
    'aceite_motor': 28000,
    'filtro_aceite': 9000,
    'filtro_aire': 12000,
    'filtro_polen': 11000,
    'liquido_frenos': 9000,
    'amortiguador': 42000,
    'bieleta': 12000,
    'bandeja': 28000,
    'rotula': 15000,
    'cazoleta': 9000,
    'kit_distribucion': 65000,
    'bomba_agua': 22000,
    'tensor': 18000,
    'refrigerante': 12000,
    'bujia': 8000,
    'bateria': 75000,
    'alternador': 90000,
    'motor_partida': 85000,
    'radiador': 70000,
    'termostato': 18000,
}

_PIEZA_DE_ITEM = frozenset({
    'kit de embrague',
    'filtro de aceite',
    'aceite de motor',
    'bomba de embrague',
})

_RUIDO_MODELO = frozenset({
    'cambio', 'cambiar', 'cambie', 'mantencion', 'mantenciones', 'servicio',
    'revision', 'revisar', 'diagnostico', 'hacer', 'quiero', 'necesito',
    'aceite', 'filtro', 'filtros', 'freno', 'frenos', 'pastilla', 'pastillas',
    'balata', 'balatas', 'zapata', 'zapatas', 'embrague', 'kit', 'bomba',
    'cilindro', 'correa', 'distribucion', 'suspension', 'delantera', 'delantero',
    'trasera', 'trasero', 'sistema', 'hidraulico', 'motor', 'para', 'con',
    'los', 'las', 'del', 'al', 'mi', 'un', 'una', 'de', 'y', 'el', 'la',
})


def _norm(texto: str) -> str:
    n = _norm_base(texto)
    for malo, bueno in (
        ('suspencion', 'suspension'),
        ('amortigador', 'amortiguador'),
        ('aliniacion', 'alineacion'),
        ('alineasion', 'alineacion'),
        ('acite', 'aceite'),
        ('fltro', 'filtro'),
        ('revicion', 'revision'),
        ('cambie', 'cambiar'),
        ('mntcion', 'mantencion'),
        ('bujias', 'bujia'),
        ('pastiyas', 'pastilla'),
    ):
        n = n.replace(malo, bueno)
    n = re.sub(r'\bscan+er\b', 'escaner', n)
    n = re.sub(r'\bbba\b', 'bomba', n)
    n = re.sub(r'\bcil rec\b', 'cilindro receptor', n)
    return re.sub(r'\s+', ' ', n).strip()


def _reintentos() -> int:
    return 1


def _tarifa_hora(taller) -> int:
    from django.conf import settings

    for attr in ('tarifa_hora_clp', 'valor_hora_clp'):
        valor = getattr(taller, attr, None) if taller is not None else None
        try:
            if valor and int(valor) > 0:
                return int(valor)
        except (TypeError, ValueError):
            continue
    try:
        return max(1, int(getattr(settings, 'COTIZACION_TARIFA_HORA_CLP', 15000)))
    except (TypeError, ValueError):
        return 15000


def _pesos(monto: int) -> str:
    return f'${int(monto):,}'.replace(',', '.')


def capacidad_aceite_l(modelo: str) -> float:
    clave = _norm(modelo)
    for nombre, litros in _CAPACIDAD_ACEITE_L.items():
        if nombre in clave:
            return float(litros)
    return 0.0


def _contiene(n: str, frase: str) -> bool:
    return re.search(rf'(?<![a-z0-9]){re.escape(frase)}(?![a-z0-9])', n) is not None


def _tallo(n: str, tallo: str) -> bool:
    """«pastilla» calza con «pastillas». No exige la palabra completa."""
    return re.search(rf'(?<![a-z0-9]){re.escape(tallo)}', n) is not None


_MARCAS = {
    'toyota': 'Toyota', 'chevrolet': 'Chevrolet', 'chevy': 'Chevrolet',
    'mazda': 'Mazda', 'kia': 'Kia', 'hyundai': 'Hyundai', 'nissan': 'Nissan',
    'suzuki': 'Suzuki', 'renault': 'Renault', 'peugeot': 'Peugeot', 'fiat': 'Fiat',
    'ford': 'Ford', 'volkswagen': 'Volkswagen', 'vw': 'Volkswagen', 'honda': 'Honda',
    'mitsubishi': 'Mitsubishi', 'subaru': 'Subaru', 'jeep': 'Jeep', 'chery': 'Chery',
    'citroen': 'Citroën', 'bmw': 'BMW', 'audi': 'Audi', 'volvo': 'Volvo',
    'ssangyong': 'SsangYong', 'changan': 'Changan', 'jac': 'JAC', 'mg': 'MG',
}

_RUIDO_AUTO = _RUIDO_MODELO | {
    'adelante', 'atras', 'delante', 'ruido', 'frenar', 'hacer', 'cambio', 'cambiar',
    'bujia', 'cable', 'cables', 'neumatico', 'neumaticos', 'rotacion', 'alineacion',
    'balanceo', 'scaner', 'escaner', 'check', 'humo', 'blanco', 'correa', 'auxiliar',
    'amortiguador', 'amortiguadores', 'bieleta', 'bieletas', 'traseros', 'traseras',
    'delanteros', 'delanteras', 'direccion', 'hidraulica', 'hidraulico', 'traba',
}


def _titulo_auto(texto: str) -> str:
    return ' '.join(parte[:1].upper() + parte[1:] for parte in str(texto or '').split())


def _texto_auto(n: str) -> str:
    """«mazda3» y «mazda 3» son el mismo auto. «morning» se busca tal cual."""
    n = re.sub(r'\bmazda\s*3\b', 'mazda 3', n)
    n = n.replace('mazda3', 'mazda 3')
    return n


def _tokens_de_auto(n: str) -> list[str]:
    anio = re.search(r'\b(?:19|20)\d{2}\b', n)
    if anio:
        previo = n[:anio.start()]
        tokens = [tok for tok in previo.split() if tok not in _RUIDO_AUTO and not re.fullmatch(r'\d\.\d', tok)]
        if tokens:
            return tokens[-3:]
    marca = re.search(
        r'\b(?:para|del|al|una|un|mi|a)\s+((?:[a-z0-9]+\s+){0,3}[a-z0-9]+)',
        n,
    )
    if not marca:
        return []
    return [
        tok for tok in marca.group(1).split()
        if tok not in _RUIDO_AUTO and not re.fullmatch(r'\d\.\d', tok)
    ][:3]


def _aplicar_tokens(base: dict, tokens: list[str]) -> None:
    if not tokens:
        return
    if tokens[0] in _MARCAS:
        if not base.get('marca'):
            base['marca'] = _MARCAS[tokens[0]]
        if not base.get('modelo'):
            resto = ' '.join(tokens[1:]).strip()
            if resto:
                base['modelo'] = _titulo_auto(resto)
        return
    frase = ' '.join(tokens)
    for clave, marca, modelo in sorted(_MODELOS, key=lambda fila: len(fila[0]), reverse=True):
        if frase == clave or frase.endswith(' ' + clave) or _contiene(frase, clave):
            if not base.get('marca'):
                base['marca'] = marca
            if not base.get('modelo'):
                base['modelo'] = modelo
            return
    if not base.get('modelo') and len(tokens) == 1:
        base['modelo'] = _titulo_auto(tokens[0])
    elif not base.get('modelo'):
        if not base.get('marca'):
            base['marca'] = _titulo_auto(tokens[0])
        base['modelo'] = _titulo_auto(' '.join(tokens[1:]))


def _vehiculo(texto: str, dado: dict | None) -> tuple[dict[str, Any], list[dict]]:
    """Usa la marca y el modelo como vienen escritos. El catálogo solo completa la marca."""
    crudo = str(texto or '')
    n = _texto_auto(_norm(crudo))
    base = {'marca': '', 'modelo': '', 'anio': '', 'motor': ''}
    for clave in ('marca', 'modelo', 'anio', 'motor'):
        if isinstance(dado, dict) and dado.get(clave) not in (None, ''):
            base[clave] = dado[clave]
    if not base.get('anio'):
        anio = re.search(r'\b(19\d{2}|20\d{2})\b', crudo)
        if anio:
            base['anio'] = int(anio.group(1))
    if not base.get('motor'):
        motor = re.search(r'\b(\d\.\d)\b', crudo)
        if motor:
            base['motor'] = motor.group(1)
    if not base.get('marca') or not base.get('modelo'):
        for clave, marca, modelo in sorted(_MODELOS, key=lambda fila: len(fila[0]), reverse=True):
            if _contiene(n, clave):
                if not base.get('marca'):
                    base['marca'] = marca
                if not base.get('modelo'):
                    base['modelo'] = modelo
                break
    if not base.get('modelo'):
        _aplicar_tokens(base, _tokens_de_auto(n))
    dudas: list[dict] = []
    if not base.get('marca') and not base.get('modelo'):
        dudas.append({
            'id': 'vehiculo-sin-identificar',
            'texto': 'El pedido no dice marca ni modelo. Confirmá el vehículo antes de enviar.',
            'confirmada': False,
        })
    return base, dudas


def _pieza(
    identidad: str,
    nombre: str,
    motivo: str = '',
    *,
    requerido: bool = False,
    tallo: str = '',
    cantidad: int | None = None,
) -> dict:
    fila = {
        'identidad': identidad,
        'nombre': nombre,
        'motivo': motivo,
        'requerido': requerido,
        'tallo': tallo or _norm(nombre).split()[0],
    }
    if cantidad:
        fila['cantidad'] = cantidad
    return fila


def _mano(taller, nombre: str, vehiculo: dict, horas: float, motivo_horas: str) -> dict:
    catalogo = None
    if taller is not None:
        try:
            from mecanimovilapp.apps.ordenes.services.catalogo_pricing import buscar_oferta_exacta

            oferta = buscar_oferta_exacta(
                taller=taller,
                servicio_nombre=nombre,
                marca=str(vehiculo.get('marca') or ''),
                modelo=str(vehiculo.get('modelo') or ''),
                tipo_motor=str(vehiculo.get('tipo_motor') or ''),
            )
            if oferta is not None:
                monto = int(getattr(oferta, 'precio_sin_repuestos', 0) or 0)
                catalogo = monto if monto > 0 else None
        except Exception:
            catalogo = None
    tarifa = _tarifa_hora(taller)
    if catalogo:
        return {
            'monto_clp': catalogo,
            'horas': horas,
            'tarifa_hora_clp': tarifa,
            'origen': 'catalogo',
            'estimada': False,
            'motivo': 'Tarifa publicada del taller para este servicio y vehículo.',
        }
    return {
        'monto_clp': int(round(horas * tarifa)),
        'horas': horas,
        'tarifa_hora_clp': tarifa,
        'origen': 'estimada',
        'estimada': True,
        'motivo': f'{motivo_horas} Tarifa {tarifa} CLP/hora.',
    }


def _servicio(ident, nombre, horas, motivo_horas, piezas, vehiculo, taller, solo_mano=False) -> dict:
    return {
        'id': ident,
        'nombre': nombre,
        'vehiculo': {
            'marca': vehiculo.get('marca') or '',
            'modelo': vehiculo.get('modelo') or '',
            'anio': vehiculo.get('anio') or '',
            'motor': vehiculo.get('motor') or '',
        },
        'solo_mano': solo_mano,
        'horas': horas,
        'motivo_horas': motivo_horas,
        'piezas': piezas,
        'mano_obra': _mano(taller, nombre, vehiculo, horas, motivo_horas),
    }


def _km(texto: str) -> int:
    """10.000, 10 000, 10000, 10 mil o 10k. Un año (2016) no es un kilometraje."""
    puntos = re.search(r'\b(\d{1,3})[.\s](\d{3})\b', texto)
    if puntos and puntos.group(2) != puntos.group(1):
        return int(puntos.group(1) + puntos.group(2)) // 1000
    mil = re.search(r'\b(\d{1,3})\s*mil\b', texto)
    if mil:
        return int(mil.group(1))
    corto = re.search(r'\b(\d{1,3})\s*k\b', texto)
    if corto:
        return int(corto.group(1))
    for plano in re.finditer(r'\b(\d{4,6})\b', texto):
        numero = int(plano.group(1))
        if 1980 <= numero <= 2035:
            continue
        if numero % 1000 == 0:
            return numero // 1000
    return 0


def _es_mantencion_km(n: str) -> bool:
    km = _km(n)
    if km not in (10, 15, 20, 30, 40, 50, 60, 80, 100):
        return False
    if any(frase in n for frase in ('mantencion', 'hacer la de', 'servicio de los', 'la de')):
        return True
    return bool(re.search(r'\b(km|mil|k)\b', n))


def _eje_en(texto: str) -> str:
    hallados = []
    for marca, eje in (
        ('traser', 'trasero'),
        ('atras', 'trasero'),
        ('delanter', 'delantero'),
        ('adelante', 'delantero'),
        ('delante', 'delantero'),
    ):
        lugar = texto.find(marca)
        if lugar >= 0:
            hallados.append((lugar, eje))
    if not hallados:
        return ''
    return min(hallados)[1]


def _ejes_de(n: str, tallo: str) -> set[str]:
    """El eje es el que acompaña a la pieza, primero el que viene después."""
    ejes: set[str] = set()
    for match in re.finditer(rf'(?<![a-z0-9]){re.escape(tallo)}', n):
        despues = _eje_en(n[match.end(): match.end() + 24])
        antes = _eje_en(n[max(0, match.start() - 24): match.start()])
        eje = despues or antes
        if eje:
            ejes.add(eje)
    return ejes


def _frenos_adelante(n: str) -> bool:
    return 'embrague' not in n and (
        (('freno' in n or 'frenar' in n) and any(eje in n for eje in ('delanter', 'adelante', 'delante')))
        or _tallo(n, 'pastilla')
    ) and not ('zapata' in n and not _tallo(n, 'pastilla') and 'delanter' not in n and 'adelante' not in n)


def _aceite_de_motor(n: str) -> bool:
    if 'aceite' not in n:
        return False
    if 'caja' in n or 'transmision' in n or 'valvulina' in n:
        return False
    resto = re.sub(r'\bfiltros?\s+de\s+aceite\b', ' ', n)
    return 'aceite' in resto


def _catalogo() -> tuple[dict, ...]:
    """Servicios de taller. Cada uno trae sinónimos, horas y piezas."""
    return (
        {
            'id': 'mantencion_km',
            'calza': _es_mantencion_km,
        },
        {
            'id': 'distribucion',
            'calza': lambda n: any(frase in n for frase in (
                'correa de distribucion', 'cadena de distribucion', 'kit de distribucion', 'distribucion',
            )),
        },
        {
            'id': 'suspension_delantera',
            'calza': lambda n: (
                ('suspension' in n and 'delanter' in n)
                or 'tren delantero' in n
                or any('delantero' in _ejes_de(n, t) for t in ('amortiguador', 'bieleta', 'bandeja', 'rotula'))
                or (
                    any(_tallo(n, t) for t in ('amortiguador', 'bieleta', 'bandeja', 'rotula'))
                    and 'traser' not in n
                )
            ),
        },
        {
            'id': 'suspension_trasera',
            'calza': lambda n: ('suspension' in n and 'traser' in n) or any(
                'trasero' in _ejes_de(n, t) for t in ('amortiguador', 'bieleta', 'bandeja', 'rotula')
            ),
        },
        {
            'id': 'frenos_traseros',
            'calza': lambda n: 'embrague' not in n and (
                (('freno' in n or 'frenar' in n) and 'traser' in n)
                or any(_tallo(n, t) for t in ('balata', 'zapata', 'tambor'))
            ),
        },
        {
            'id': 'frenos_delanteros',
            'calza': _frenos_adelante,
        },
        {
            'id': 'embrague',
            'calza': lambda n: 'embrague' in n or _tallo(n, 'clutch'),
        },
        {
            'id': 'aceite_filtros',
            'calza': _aceite_de_motor,
        },
        {
            'id': 'revision_hidraulico',
            'calza': lambda n: (
                ('hidraul' in n and ('sistema' in n or 'freno' in n) and 'direccion' not in n)
                or ('diagnostico' in n and 'humo' not in n and 'escaner' not in n and 'check' not in n)
            ) and 'pastilla' not in n and 'balata' not in n and 'direccion' not in n,
        },
        {
            'id': 'direccion_hidraulica',
            'calza': lambda n: 'direccion' in n and ('hidraul' in n or 'traba' in n),
        },
        {
            'id': 'escaner',
            'calza': lambda n: 'escaner' in n or ('check' in n and any(
                verbo in n for verbo in ('prende', 'encend', 'luz', 'testigo')
            )),
        },
        {
            'id': 'humo',
            'calza': lambda n: 'humo' in n,
        },
        {
            'id': 'correa_auxiliar',
            'calza': lambda n: 'distribucion' not in n and (
                'correa auxiliar' in n or 'correa de accesorio' in n
                or (_tallo(n, 'correa') and 'distribucion' not in n and 'cadena' not in n)
            ),
        },
        {
            'id': 'rotacion',
            'calza': lambda n: 'rotacion' in n or _tallo(n, 'rotar'),
        },
        {
            'id': 'bateria',
            'calza': lambda n: _tallo(n, 'bateria'),
        },
        {
            'id': 'alternador_partida',
            'calza': lambda n: 'alternador' in n or 'partida' in n or 'arranque' in n,
        },
        {
            'id': 'refrigeracion',
            'calza': lambda n: any(t in n for t in ('radiador', 'termostato', 'refrigerante'))
            and 'distribucion' not in n and 'correa' not in n,
        },
        {
            'id': 'bujias',
            'calza': lambda n: 'bujia' in n or 'encendido' in n,
        },
        {
            'id': 'alineacion',
            'calza': lambda n: 'alineacion' in n or 'alineamiento' in n or 'balanceo' in n,
        },
    )


def _piezas_de(ident: str, n: str, vehiculo: dict) -> tuple[list[dict], list[dict], str, float, str, bool]:
    """Requeridos, sugeridos, nombre, horas, motivo, solo_mano."""
    if ident == 'mantencion_km':
        km = _km(n)
        nombre = f'Mantención de los {km} mil'
        horas = {10: 1, 20: 1.5, 40: 2, 60: 3, 80: 3.5, 100: 4}.get(km, 2)
        req = [
            _pieza('aceite_motor', 'Aceite de motor', requerido=True, tallo='aceite'),
            _pieza('filtro_aceite', 'Filtro de aceite', requerido=True, tallo='filtro'),
        ]
        sug = []
        if km >= 20:
            sug.append(_pieza('filtro_aire', 'Filtro de aire', 'En la mantención conviene cambiar el de aire.', tallo='aire'))
        if km >= 40:
            req.append(_pieza('bujia', 'Bujías', requerido=True, tallo='bujia'))
        if km >= 60:
            sug.append(_pieza('liquido_frenos', 'Líquido de frenos', 'A los 60 mil conviene renovar el líquido.', tallo='liquido'))
        if km >= 100:
            sug.append(_pieza(
                'kit_distribucion', 'Kit de distribución',
                'A los 100 mil hay que revisar la correa o la cadena. No se cobra hasta confirmarlo.',
                tallo='distribucion',
            ))
        return req, sug, nombre, horas, f'La mantención de los {km} mil son unas {horas:g} horas.', False

    if ident == 'distribucion':
        req = [
            _pieza('kit_distribucion', 'Kit de distribución', requerido=True, tallo='distribucion'),
            _pieza('bomba_agua', 'Bomba de agua', requerido=True, tallo='bomba'),
            _pieza('tensor', 'Tensor de distribución', requerido=True, tallo='tensor'),
        ]
        sug = [_pieza('refrigerante', 'Refrigerante', 'Al cambiar la bomba se pierde el refrigerante.', tallo='refrigerante')]
        return req, sug, 'Cambio de distribución', 5, 'La distribución con bomba de agua son unas 5 horas.', False

    if ident == 'suspension_delantera':
        piezas = [
            _pieza('amortiguador', 'Amortiguadores delanteros', 'El ruido delantero suele ser el amortiguador.', requerido=True, tallo='amortiguador'),
            _pieza('bieleta', 'Bieletas delanteras', 'Conviene revisarlas al bajar la suspensión.', tallo='bieleta'),
            _pieza('bandeja', 'Bandejas', 'Si tienen juego, se cambian con la suspensión.', tallo='bandeja'),
            _pieza('rotula', 'Rótulas', 'Se revisan al intervenir el tren delantero.', tallo='rotula'),
            _pieza('cazoleta', 'Cazoletas', 'Se cambian junto con el amortiguador si están cortadas.', tallo='cazoleta'),
        ]
        nombradas = [p for p in piezas if 'delantero' in _ejes_de(n, p['tallo'])]
        if not nombradas and 'suspension' not in n and 'tren delantero' not in n:
            nombradas = [
                p for p in piezas
                if p['tallo'] in n and 'trasero' not in _ejes_de(n, p['tallo'])
            ]
        if nombradas:
            req = nombradas
            sug = [p for p in piezas if p not in nombradas and 'trasero' not in _ejes_de(n, p['tallo'])]
        else:
            req = [piezas[0]]
            sug = piezas[1:]
        return req, sug, 'Mantención de suspensión delantera', 3, 'La suspensión delantera son unas 3 horas.', False

    if ident == 'suspension_trasera':
        piezas_tras = [
            _pieza('amortiguador', 'Amortiguadores traseros', requerido=True, tallo='amortiguador'),
            _pieza('bieleta', 'Bieletas traseras', requerido=True, tallo='bieleta'),
            _pieza('bandeja', 'Bandejas traseras', requerido=True, tallo='bandeja'),
            _pieza('rotula', 'Rótulas traseras', requerido=True, tallo='rotula'),
        ]
        nombradas = [p for p in piezas_tras if 'trasero' in _ejes_de(n, p['tallo'])]
        if nombradas:
            req = nombradas
            sug = [_pieza('cazoleta', 'Cazoletas traseras', 'Se revisan junto con el amortiguador trasero.', tallo='cazoleta')]
        else:
            req = [piezas_tras[0]]
            sug = [_pieza('cazoleta', 'Cazoletas traseras', 'Se revisan junto con el amortiguador trasero.', tallo='cazoleta')]
        return req, sug, 'Mantención de suspensión trasera', 2.5, 'La suspensión trasera son unas 2.5 horas.', False

    if ident == 'frenos_traseros':
        nombre_pieza = 'Zapatas de freno traseras' if 'zapata' in n else 'Balatas de freno traseras'
        req = [_pieza('balatas_freno', nombre_pieza, requerido=True, tallo='balata')]
        sug = [_pieza('tambores_freno', 'Tambores de freno', 'Si el tambor está ovalado, no basta con la zapata.', tallo='tambor')]
        return req, sug, 'Mantención de frenos traseros', 2, 'Cambiar balatas traseras son unas 2 horas.', False

    if ident == 'frenos_delanteros':
        req = [_pieza('pastillas_freno', 'Pastillas de freno delanteras', requerido=True, tallo='pastilla')]
        sug = [_pieza('discos_freno', 'Discos de freno delanteros', 'Si están bajo el mínimo, se cambian con las pastillas.', tallo='disco')]
        if 'disco' in n and ('delanter' in n or 'adelante' in n):
            req.append(sug.pop(0))
        nombre = 'Frenos delanteros' if 'pastilla' not in n else 'Cambio de pastillas delanteras'
        return req, sug, nombre, 1.5, 'Los frenos delanteros son cerca de 1.5 horas.', False

    if ident == 'embrague':
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            piezas_del_pedido,
        )

        req = [_pieza('kit_embrague', 'Kit de embrague', requerido=True, tallo='embrague')]
        for item in piezas_del_pedido(n):
            ident_item = item.get('identidad') or ''
            if ident_item in ('bomba_embrague', 'cilindro_receptor_embrague', 'liquido_frenos'):
                if not any(p['identidad'] == ident_item for p in req):
                    req.append(_pieza(ident_item, item['nombre'], requerido=True))
        sug = [
            _pieza('aceite_caja', 'Aceite de caja de cambios', 'Al bajar la caja se pierde la valvulina. Conviene reponerla.'),
            _pieza('rodamiento_piloto', 'Rodamiento de volante', 'Al bajar la caja conviene cambiarlo si el kit no lo trae.'),
        ]
        return req, sug, 'Cambio de embrague', 6, 'Bajar la caja y cambiar el embrague son unas 6 horas de taller.', False

    if ident == 'aceite_filtros':
        req = [
            _pieza('aceite_motor', 'Aceite de motor', requerido=True, tallo='aceite'),
            _pieza('filtro_aceite', 'Filtro de aceite', requerido=True, tallo='filtro'),
        ]
        sug = [_pieza('filtro_aire', 'Filtro de aire', 'En el cambio de aceite conviene revisar el filtro de aire. No es el de aceite.')]
        return req, sug, 'Cambio de aceite y filtros', 1, 'El cambio de aceite y filtro es cerca de 1 hora.', False

    if ident == 'revision_hidraulico':
        return [], [], 'Revisión del sistema hidráulico de frenos', 1, 'La revisión del sistema hidráulico es un diagnóstico de cerca de 1 hora.', True

    if ident == 'bateria':
        return [_pieza('bateria', 'Batería', requerido=True, tallo='bateria')], [], 'Cambio de batería', 0.5, 'Cambiar la batería es cerca de media hora.', False

    if ident == 'alternador_partida':
        req = []
        if 'alternador' in n:
            req.append(_pieza('alternador', 'Alternador', requerido=True, tallo='alternador'))
        if 'partida' in n or 'arranque' in n:
            req.append(_pieza('motor_partida', 'Motor de partida', requerido=True, tallo='partida'))
        if not req:
            req.append(_pieza('alternador', 'Alternador', requerido=True, tallo='alternador'))
        sug = []
        if not any(p['identidad'] == 'bateria' for p in req):
            sug.append(_pieza('bateria', 'Batería', 'Si no retiene carga, el problema puede ser la batería y no el alternador.'))
        return req, sug, 'Alternador y partida', 2, 'Alternador o motor de partida son unas 2 horas.', False

    if ident == 'refrigeracion':
        req = []
        if 'radiador' in n:
            req.append(_pieza('radiador', 'Radiador', requerido=True, tallo='radiador'))
        if 'termostato' in n:
            req.append(_pieza('termostato', 'Termostato', requerido=True, tallo='termostato'))
        if not req:
            req.append(_pieza('termostato', 'Termostato', requerido=True, tallo='termostato'))
        sug = [_pieza('refrigerante', 'Refrigerante', 'Al abrir el circuito hay que reponer el refrigerante.')]
        return req, sug, 'Refrigeración', 2, 'Radiador o termostato son unas 2 horas.', False

    if ident == 'bujias':
        cilindros = re.search(r'\b([3-8])\s*cilindros?\b', n)
        cantidad = int(cilindros.group(1)) if cilindros else 4
        req = [_pieza('bujia', 'Bujías', requerido=True, tallo='bujia', cantidad=cantidad)]
        if 'cable' in n:
            req.append(_pieza('cable_bujia', 'Cables de bujía', requerido=True, tallo='cable'))
        return req, [], 'Cambio de bujías', 1, 'Las bujías se cotizan como juego. Son cerca de 1 hora.', False

    if ident == 'correa_auxiliar':
        return (
            [_pieza('correa_auxiliar', 'Correa auxiliar', requerido=True, tallo='correa')],
            [_pieza('tensor', 'Tensor de correa auxiliar', 'Conviene cambiarlo si está ruidoso.', tallo='tensor')],
            'Cambio de correa auxiliar',
            1.5,
            'La correa auxiliar no es la de distribución. Son cerca de 1.5 horas.',
            False,
        )

    if ident == 'direccion_hidraulica':
        return (
            [_pieza('liquido_direccion', 'Líquido de dirección hidráulica', requerido=True, tallo='liquido')],
            [_pieza('bomba_direccion', 'Bomba de dirección hidráulica', 'Si se traba con el líquido nuevo, la bomba puede ser la causa.')],
            'Dirección hidráulica',
            2,
            'Una dirección que se traba son unas 2 horas entre diagnóstico y reparación.',
            False,
        )

    if ident == 'escaner':
        return [], [], 'Diagnóstico con escáner', 1, 'Leer el check con el escáner es cerca de 1 hora.', True

    if ident == 'humo':
        return [], [], 'Diagnóstico de humo blanco', 1, 'El humo blanco se diagnostica antes de cotizar un repuesto. Es cerca de 1 hora.', True

    if ident == 'rotacion':
        return [], [], 'Rotación de neumáticos', 0.5, 'Rotar los neumáticos es cerca de media hora.', True

    if ident == 'alineacion':
        return [], [], 'Alineación y balanceo', 1, 'Alineación y balanceo son cerca de 1 hora.', True

    return [], [], ident, 1, 'Servicio de taller.', False


def _lista_explicita(texto: str) -> bool:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        piezas_del_pedido,
    )

    concretas = [
        item for item in piezas_del_pedido(texto)
        if item.get('identidad') not in ('', 'sin_clasificar', 'otra')
    ]
    return len(concretas) >= 2


def es_pieza_suelta_de_item(texto: str) -> bool:
    """Una pieza que el alta manual ya cotiza sola. No se reescribe como servicio."""
    return _norm(texto) in _PIEZA_DE_ITEM


def _ya_nombrada(servicios: list[dict], tallo: str, ident: str) -> bool:
    for servicio in servicios:
        for pieza in (servicio.get('repuestos_requeridos') or []) + (servicio.get('sugeridos') or []):
            if pieza.get('tallo') == tallo or pieza.get('identidad') == ident:
                return True
            if tallo and tallo in _norm(pieza.get('nombre') or ''):
                return True
    return False


def _conservar_nombradas(n: str, servicios: list[dict], auto: dict, taller) -> None:
    """Una pieza que el texto nombra no se tira. Si el plan no la usó, queda pedida."""
    sueltas = (
        ('cables de bujia', 'cable_bujia', 'Cables de bujía', 'cable'),
        ('correa auxiliar', 'correa_auxiliar', 'Correa auxiliar', 'correa'),
        ('pastilla', 'pastillas_freno', 'Pastillas de freno', 'pastilla'),
        ('bieleta', 'bieleta', 'Bieletas', 'bieleta'),
        ('amortiguador', 'amortiguador', 'Amortiguadores', 'amortiguador'),
        ('bujia', 'bujia', 'Bujías', 'bujia'),
        ('disco de freno', 'discos_freno', 'Discos de freno', 'disco'),
        ('cable', 'cable_bujia', 'Cables de bujía', 'cable'),
    )
    for frase, ident, nombre, tallo in sueltas:
        presente = frase in n or (tallo != 'correa' and _tallo(n, tallo))
        if not presente or _ya_nombrada(servicios, tallo, ident):
            continue
        pieza = _pieza(ident, nombre, requerido=True, tallo=tallo)
        pieza['origen'] = 'solicitada'
        destino = next((servicio for servicio in servicios if not servicio.get('solo_mano')), None)
        if destino is None:
            destino = _servicio(
                'piezas-pedidas', 'Piezas pedidas', 1,
                'El pedido nombra piezas que no entraron en un servicio.',
                [pieza], auto, taller,
            )
            destino['repuestos_requeridos'] = []
            destino['sugeridos'] = []
            servicios.append(destino)
        destino.setdefault('repuestos_requeridos', []).append(pieza)
        destino.setdefault('piezas', []).append(pieza)


def planificar_pedido(texto: str, vehiculo: dict | None = None, taller=None) -> dict[str, Any]:
    """Servicios del pedido según el catálogo. Cualquier trabajo conocido, no cuatro frases."""
    n = _norm(texto)
    auto, dudas = _vehiculo(texto, vehiculo)
    ids = [fila['id'] for fila in _catalogo() if fila['calza'](n)]
    if 'mantencion_km' in ids:
        ids = [ident for ident in ids if ident not in ('aceite_filtros', 'bujias')]
    if 'distribucion' in ids:
        ids = [ident for ident in ids if ident not in ('refrigeracion', 'correa_auxiliar')]
    if any(ident in ids for ident in ('escaner', 'direccion_hidraulica', 'humo')):
        ids = [ident for ident in ids if ident != 'revision_hidraulico']
    if 'revision_hidraulico' in ids and 'pastilla' not in n and 'balata' not in n and 'zapata' not in n:
        ids = [ident for ident in ids if ident not in ('frenos_delanteros', 'frenos_traseros')]
    if 'frenos_traseros' in ids and 'pastilla' not in n and 'delanter' not in n:
        ids = [ident for ident in ids if ident != 'frenos_delanteros']
    if 'frenos_delanteros' in ids and 'zapata' not in n and 'balata' not in n and 'traser' not in n:
        ids = [ident for ident in ids if ident != 'frenos_traseros']
    servicios = []
    for ident in ids:
        req, sug, nombre, horas, motivo, solo = _piezas_de(ident, n, auto)
        fila = _servicio(ident, nombre, horas, motivo, req + sug, auto, taller, solo_mano=solo)
        fila['repuestos_requeridos'] = req
        fila['sugeridos'] = sug
        if ident == 'aceite_filtros' or ident == 'mantencion_km':
            dudas.append({
                'id': 'aceite-viscosidad',
                'texto': (
                    'Falta confirmar la viscosidad. El aceite se cotiza por la capacidad del motor '
                    'y el envase más barato, no como litros sueltos a precio de envase.'
                ),
                'confirmada': False,
            })
        if ident == 'frenos_traseros':
            dudas.append({
                'id': 'frenos-traseros-balatas',
                'texto': 'Los frenos traseros de este pedido se cotizan como balatas o zapatas, no como pastillas.',
                'confirmada': False,
            })
        if ident == 'revision_hidraulico':
            dudas.append({
                'id': 'sistema-no-repuesto',
                'texto': 'Revisar el sistema hidráulico es mano de obra o diagnóstico. No se cotizó como repuesto.',
                'confirmada': False,
            })
        if ident == 'humo':
            dudas.append({
                'id': 'humo-diagnostico',
                'texto': (
                    'Humo blanco puede ser refrigerante en la cámara o solo condensación. '
                    'Quedó como diagnóstico, sin cotizar un repuesto hasta confirmar la causa.'
                ),
                'confirmada': False,
            })
        if ident == 'direccion_hidraulica':
            dudas.append({
                'id': 'direccion-causa',
                'texto': 'La dirección que se traba puede ser el líquido o la bomba. Confirmá la causa antes de enviar.',
                'confirmada': False,
            })
        servicios.append(fila)
    _conservar_nombradas(n, servicios, auto, taller)
    if not servicios:
        recorte = str(texto or '').strip()[:180]
        dudas.append({
            'id': 'servicio-no-identificado',
            'texto': f'No pude identificar el servicio: «{recorte}». Confirmalo antes de cotizar.',
            'confirmada': False,
        })
    return {'servicios': servicios, 'vehiculo': auto, 'dudas': dudas}


def plan_desde_pedido(pedido, vehiculo: dict | None, taller) -> dict[str, Any] | None:
    """La salida de la única llamada LLM manda sobre el catálogo."""
    servicios_llm = list(getattr(pedido, 'servicios', None) or [])
    if not servicios_llm:
        return None
    auto_llm = getattr(pedido, 'vehiculo', None)
    dado = dict(vehiculo or {})
    if auto_llm is not None:
        for clave, attr in (('marca', 'marca'), ('modelo', 'modelo'), ('anio', 'anio'), ('motor', 'motor')):
            valor = getattr(auto_llm, attr, None)
            if valor not in (None, '') and not dado.get(clave):
                dado[clave] = valor
    auto, dudas = _vehiculo('', dado)
    servicios = []
    for servicio in servicios_llm:
        nombre = str(getattr(servicio, 'nombre', '') or '').strip()
        if not nombre:
            continue
        horas = getattr(servicio, 'horas', None) or 1
        try:
            horas = float(horas)
        except (TypeError, ValueError):
            horas = 1
        req = [
            _pieza(p.identidad or 'otra', p.nombre, requerido=True)
            for p in (getattr(servicio, 'repuestos_requeridos', None) or [])
            if getattr(p, 'nombre', '')
        ]
        sug = [
            _pieza(p.identidad or 'otra', p.nombre, getattr(p, 'motivo', '') or '')
            for p in (getattr(servicio, 'sugeridos', None) or [])
            if getattr(p, 'nombre', '')
        ]
        solo = not req and getattr(servicio, 'incluye_repuestos', True) is False
        fila = _servicio(f"llm-{_norm(nombre).replace(' ', '-')[:40]}", nombre, horas, 'Horas leídas del pedido.', req + sug, auto, taller, solo_mano=solo)
        if getattr(servicio, 'mano_obra_clp', None):
            fila['mano_obra']['monto_clp'] = int(servicio.mano_obra_clp)
            fila['mano_obra']['origen'] = 'catalogo'
            fila['mano_obra']['estimada'] = False
            fila['mano_obra']['motivo'] = 'Monto de mano de obra leído del pedido.'
        fila['repuestos_requeridos'] = req
        fila['sugeridos'] = sug
        servicios.append(fila)
    if not servicios:
        return None
    return {'servicios': servicios, 'vehiculo': auto, 'dudas': dudas}


def _consulta(nombre: str, vehiculo: dict) -> str:
    auto = ' '.join(
        str(vehiculo.get(clave) or '').strip()
        for clave in ('marca', 'modelo', 'anio', 'motor')
    ).strip()
    return f'{nombre} {auto}'.strip()


def _linea(pieza: dict, *, vehiculo: dict, origen: str, estado: str, motivo: str = '') -> dict:
    ident = pieza.get('identidad') or ''
    nombre = pieza.get('nombre') or 'Repuesto'
    fila = {
        'nombre': nombre,
        'identidad': ident,
        'cantidad': 1,
        'precio_unitario_clp': 0,
        'origen': origen,
        'estado_sugerencia': estado,
        'motivo_sugerencia': motivo,
        'consulta': _consulta(nombre, vehiculo),
        'rol': 'insumo' if ident in ('aceite_motor', 'aceite_caja', 'liquido_frenos', 'refrigerante', 'liquido_direccion') else 'repuesto',
    }
    if pieza.get('cantidad'):
        fila['cantidad'] = int(pieza['cantidad'])
    if ident == 'aceite_motor':
        litros = capacidad_aceite_l(str(vehiculo.get('modelo') or ''))
        fila['especificacion_pendiente'] = True
        if litros > 0:
            fila['litros'] = litros
            fila['cantidad_texto'] = f'{litros:g} L'
            fila['especificacion'] = f'{litros:g} L'
            fila['comentario'] = f'Capacidad de referencia {litros:g} L. Confirmar viscosidad.'
        else:
            fila['comentario'] = 'No tengo la capacidad de este motor. Confirmar litros y viscosidad.'
    return fila


def _hit_sirve(hit: dict | None, linea: dict) -> bool:
    if not isinstance(hit, dict):
        return False
    precio = int(hit.get('precio_unitario_clp') or 0)
    url = str(hit.get('url_producto') or hit.get('url') or '').strip()
    tienda = str(hit.get('proveedor_nombre') or hit.get('tienda') or '').strip()
    if precio <= 0 or not url.startswith('http') or not tienda:
        return False
    titulo = _norm(str(hit.get('nombre_producto') or hit.get('nombre') or ''))
    ident = str(linea.get('identidad') or '')
    if ident == 'balatas_freno' and 'pastilla' in titulo and 'balata' not in titulo and 'zapata' not in titulo:
        return False
    if ident == 'kit_embrague' and 'bomba' in titulo and 'kit' not in titulo:
        return False
    if ident == 'filtro_aceite' and 'aire' in titulo and 'aceite' not in titulo:
        return False
    if ident == 'filtro_aire' and 'aceite' in titulo and 'aire' not in titulo:
        return False
    if not titulo:
        return True
    tokens = [
        token for token in _norm(str(linea.get('nombre') or '')).split()
        if token not in {'de', 'del', 'la', 'el', 'los', 'las'}
    ]
    return any(token in titulo for token in tokens)


def buscar_lineas_en_casas(lineas: list[dict], vehiculo: dict | None, servicio: str = '') -> dict[str, dict]:
    """Búsqueda real de la PR #48: casas, ficha, tienda y envase. Sin otra llamada de lectura."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        buscar_repuestos_web,
        tavily_habilitada,
    )

    if not tavily_habilitada() or not lineas:
        return {}
    nombres = []
    for linea in lineas:
        consulta = str(linea.get('consulta') or linea.get('nombre') or '').strip()
        if consulta:
            nombres.append(consulta)
    if not nombres:
        return {}
    try:
        crudo = buscar_repuestos_web(
            nombres,
            vehiculo=vehiculo or {},
            servicio_nombre=servicio,
            razonar=False,
        )
    except Exception:
        return {}
    salida: dict[str, dict] = {}
    for item in (crudo or {}).values():
        if not isinstance(item, dict):
            continue
        hit = {
            'precio_unitario_clp': int(item.get('precio_clp') or item.get('precio_unitario_clp') or 0),
            'url_producto': item.get('url') or item.get('url_producto') or '',
            'proveedor_nombre': item.get('tienda') or item.get('proveedor_nombre') or '',
            'nombre_producto': item.get('nombre_producto') or '',
            'candidatos_envase': item.get('candidatos_envase') or [],
            'motivo_seleccion': item.get('motivo_tienda') or '',
        }
        for clave in (_norm(item.get('nombre_buscado') or ''), _norm(item.get('nombre_producto') or '')):
            if clave:
                salida[clave] = hit
    for linea in lineas:
        clave = _norm(linea.get('nombre') or '')
        if clave and clave not in salida:
            for encontrada, hit in list(salida.items()):
                if clave and clave in encontrada:
                    salida[clave] = hit
    return salida


def _elegir_envase(linea: dict, hit: dict) -> dict:
    litros = 0.0
    try:
        litros = float(linea.get('litros') or 0)
    except (TypeError, ValueError):
        litros = 0.0
    candidatos = [c for c in (hit.get('candidatos_envase') or []) if isinstance(c, dict)]
    if litros <= 0 or not candidatos:
        return hit
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        _envase_mas_barato,
        litros_envase,
    )

    opciones = []
    for cand in candidatos:
        titulo = str(cand.get('nombre_producto') or '')
        opciones.append({
            'nombre_producto': titulo,
            'precio_unitario_clp': int(cand.get('precio_unitario_clp') or 0),
            'url': cand.get('url') or cand.get('url_producto') or '',
            'envase': litros_envase(titulo),
        })
    elegido = _envase_mas_barato(opciones, litros)
    if not elegido:
        return hit
    op, _total = elegido
    import math

    envase = float(op.get('envase') or 0)
    if envase <= 0:
        return hit
    linea['cantidad'] = max(1, math.ceil(litros / envase - 1e-9))
    return {
        **hit,
        'precio_unitario_clp': int(op['precio_unitario_clp']),
        'url_producto': op.get('url') or hit.get('url_producto') or '',
        'nombre_producto': op.get('nombre_producto') or hit.get('nombre_producto') or '',
    }


def _aplicar_hit(linea: dict, hit: dict) -> None:
    linea['precio_unitario_clp'] = int(hit.get('precio_unitario_clp') or 0)
    linea['url_producto'] = str(hit.get('url_producto') or hit.get('url') or '')
    linea['proveedor_nombre'] = str(hit.get('proveedor_nombre') or hit.get('tienda') or '')
    linea['nombre_producto'] = str(hit.get('nombre_producto') or hit.get('nombre') or linea['nombre'])
    if hit.get('motivo_seleccion'):
        linea['motivo_seleccion'] = hit['motivo_seleccion']
    linea['precio_estimado'] = False
    linea['certeza'] = 'confirmado'
    linea.pop('_estimado', None)


def _marcar_estimado(linea: dict) -> None:
    ident = str(linea.get('identidad') or '')
    linea['precio_unitario_clp'] = _REFERENCIA_CLP.get(ident) or 10000
    linea['precio_estimado'] = True
    linea['certeza'] = 'asumido'
    linea['fuente_marketplace'] = 'estimado'
    linea['_estimado'] = True


def _duda_estimado(linea: dict) -> dict:
    cobrado = int(linea.get('precio_unitario_clp') or 0)
    costo = int(linea.get('costo_estimado_clp') or 0)
    if costo and costo != cobrado:
        monto = f'costo {_pesos(costo)} y cobrado {_pesos(cobrado)} ya con el margen del taller'
    else:
        monto = _pesos(cobrado)
    return {
        'id': f"precio-estimado-{_norm(linea.get('nombre') or 'pieza').replace(' ', '-')}"[:48],
        'texto': (
            f"No hay ficha de tienda para {linea.get('nombre')}. "
            f"Quedó un precio estimado de {monto} para no dejar la línea en blanco. "
            'Confírmalo antes de enviarlo al cliente.'
        ),
        'confirmada': False,
    }


def _buscar_linea(linea: dict, buscar: Buscador | None, vehiculo: dict) -> dict | None:
    def _casas(fila: dict) -> dict | None:
        encontrados = buscar_lineas_en_casas([fila], vehiculo, str(fila.get('nombre') or ''))
        return encontrados.get(_norm(fila.get('nombre') or ''))

    fuente = buscar or _casas
    hit = fuente(dict(linea))
    if not _hit_sirve(hit, linea):
        for _ in range(_reintentos()):
            otra = dict(linea)
            otra['consulta'] = f"{linea.get('consulta') or linea.get('nombre')} repuesto"
            linea['reintentos_busqueda'] = int(linea.get('reintentos_busqueda') or 0) + 1
            hit = fuente(otra)
            if _hit_sirve(hit, linea):
                break
    if isinstance(hit, dict):
        hit = _elegir_envase(linea, hit)
    return hit if _hit_sirve(hit, linea) else None


def _preciar(linea: dict, buscar: Buscador | None, vehiculo: dict) -> None:
    hit = _buscar_linea(linea, buscar, vehiculo)
    if hit:
        _aplicar_hit(linea, hit)
        return
    _marcar_estimado(linea)


def interpretar_pedido(texto: str, vehiculo: dict | None = None):
    """La misma lectura del modelo, una vez por frase y vehículo. None si no responde."""
    from mecanimovilapp.apps.agente_ia.services.extraccion_pedido_llm import leer_pedido_llm

    try:
        return leer_pedido_llm(texto, vehiculo or {})
    except Exception:
        return None


def _armar(texto, vehiculo, taller, pedido) -> dict:
    if pedido is None:
        pedido = interpretar_pedido(texto, vehiculo)
    desde_llm = plan_desde_pedido(pedido, vehiculo, taller) if pedido is not None else None
    if desde_llm and desde_llm.get('servicios'):
        return desde_llm
    return planificar_pedido(texto, vehiculo, taller)


def cotizar_por_servicio(
    texto: str,
    vehiculo: dict | None = None,
    taller=None,
    buscar: Buscador | None = None,
    pedido=None,
) -> dict[str, Any]:
    plan = _armar(texto, vehiculo, taller, pedido)
    if not plan['servicios']:
        vacia = _vacia(texto, plan)
        return verificar_cotizacion(vacia)
    auto = plan['vehiculo']
    repuestos: list[dict] = []
    vistos: set[str] = set()
    for servicio in plan['servicios']:
        if servicio.get('solo_mano'):
            continue
        for pieza in servicio['repuestos_requeridos'] + servicio['sugeridos']:
            ident = pieza.get('identidad') or pieza.get('nombre')
            if ident in vistos:
                continue
            vistos.add(ident)
            es_req = pieza in servicio['repuestos_requeridos']
            origen = pieza.get('origen') or ('pedido' if es_req else 'sugerencia')
            linea = _linea(
                pieza,
                vehiculo=auto,
                origen=origen,
                estado='pendiente' if origen == 'sugerencia' else 'aceptada',
                motivo='' if origen != 'sugerencia' else (pieza.get('motivo') or ''),
            )
            _preciar(linea, buscar, auto)
            repuestos.append(linea)
    contenido = {
        'servicio_nombre': ' + '.join(s['nombre'] for s in plan['servicios']) or texto,
        'descripcion_problema': texto,
        'vehiculo': auto,
        'servicios': plan['servicios'],
        'servicios_lineas': [
            {
                'nombre': servicio['nombre'],
                'monto_clp': servicio['mano_obra']['monto_clp'],
                'horas': servicio['mano_obra']['horas'],
                'estimada': servicio['mano_obra']['estimada'],
                'origen': servicio['mano_obra']['origen'],
                'motivo': servicio['mano_obra']['motivo'],
            }
            for servicio in plan['servicios']
        ],
        'repuestos': repuestos,
        'dudas': list(plan['dudas']),
        'mano_obra_clp': sum(s['mano_obra']['monto_clp'] for s in plan['servicios']),
    }
    return _con_margen(verificar_cotizacion(contenido), taller)


def _vacia(texto: str, plan: dict) -> dict:
    return {
        'servicio_nombre': str(texto or '')[:80],
        'descripcion_problema': texto,
        'vehiculo': plan.get('vehiculo') or {},
        'servicios': [],
        'servicios_lineas': [],
        'repuestos': [],
        'dudas': list(plan.get('dudas') or []),
        'mano_obra_clp': 0,
        'total_clp': 0,
    }


def verificar_cotizacion(contenido: dict[str, Any]) -> dict[str, Any]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        recalcular_totales,
    )

    data = dict(contenido or {})
    repuestos = [dict(rep) for rep in (data.get('repuestos') or []) if isinstance(rep, dict)]
    dudas = [duda for duda in (data.get('dudas') or []) if isinstance(duda, dict)]
    servicios = list(data.get('servicios') or [])
    limpias = []
    for rep in repuestos:
        nombre = _norm(str(rep.get('nombre') or ''))
        ident = str(rep.get('identidad') or '')
        if not ident and (
            'ruido' in nombre or 'patina' in nombre or nombre.startswith('revisar sistema')
            or nombre == 'filtro'
        ):
            dudas.append({
                'id': f"no-es-repuesto-{nombre.replace(' ', '-')}"[:48],
                'texto': f'«{rep.get("nombre")}» no es un repuesto. No quedó como línea.',
                'confirmada': False,
            })
            continue
        precio = int(rep.get('precio_unitario_clp') or 0)
        if precio <= 0 and not rep.get('_estimado'):
            _marcar_estimado(rep)
        limpias.append(rep)
    if any(rep.get('identidad') == 'kit_embrague' and rep.get('origen') != 'sugerencia' for rep in limpias):
        sobran = {'disco', 'prensa', 'plato', 'collarin', 'crapodina'}
        quedaron = []
        for rep in limpias:
            nombre = _norm(str(rep.get('nombre') or ''))
            if (
                rep.get('identidad') != 'kit_embrague'
                and rep.get('origen') != 'sugerencia'
                and any(token in nombre for token in sobran)
                and 'piloto' not in nombre
            ):
                dudas.append({
                    'id': f"kit-duplicado-{nombre.replace(' ', '-')}"[:48],
                    'texto': f'{rep.get("nombre")} ya va en el kit. No se cotizó otra vez como pieza suelta.',
                    'confirmada': False,
                })
                continue
            quedaron.append(rep)
        limpias = quedaron
    lineas = list(data.get('servicios_lineas') or [])
    if servicios and not lineas:
        lineas = [
            {
                'nombre': servicio.get('nombre') or 'Servicio',
                'monto_clp': int((servicio.get('mano_obra') or {}).get('monto_clp') or 0),
                'estimada': bool((servicio.get('mano_obra') or {}).get('estimada')),
            }
            for servicio in servicios
        ]
    for linea in lineas:
        if int(linea.get('monto_clp') or 0) <= 0 and servicios:
            linea['monto_clp'] = int(servicios[0]['mano_obra']['monto_clp'])
            linea['estimada'] = True
    mano = sum(int(linea.get('monto_clp') or 0) for linea in lineas)
    if not mano and servicios:
        mano = sum(int((s.get('mano_obra') or {}).get('monto_clp') or 0) for s in servicios)
    costo, mo, total = recalcular_totales(limpias, mano)
    data['repuestos'] = limpias
    data['dudas'] = _unicas(dudas)
    data['servicios_lineas'] = lineas
    data['mano_obra_clp'] = mo
    data['costo_repuestos_clp'] = costo
    data['total_clp'] = total
    sin_trabajo = not limpias and not servicios and mo <= 0
    data['verificacion'] = {
        'ok': (not sin_trabajo)
        and all(int(rep.get('precio_unitario_clp') or 0) > 0 for rep in limpias)
        and (not servicios or mo > 0),
        'lineas': len(limpias),
        'servicios': len(servicios),
    }
    return data


def _unicas(dudas: list[dict]) -> list[dict]:
    vistos = set()
    salida = []
    for duda in dudas:
        clave = str(duda.get('id') or duda.get('texto') or '')
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append(duda)
    return salida


def _con_margen(data: dict, taller) -> dict:
    """El margen se aplica una vez. La duda del estimado muestra el monto ya cobrado."""
    if taller is not None:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            aplicar_margen_taller,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            recalcular_totales,
        )

        for rep in data.get('repuestos') or []:
            if isinstance(rep, dict):
                aplicar_margen_taller(rep, taller)
        costo, mo, total = recalcular_totales(
            list(data.get('repuestos') or []),
            int(data.get('mano_obra_clp') or 0),
        )
        data['costo_repuestos_clp'] = costo
        data['mano_obra_clp'] = mo
        data['total_clp'] = total
    dudas = [
        duda for duda in (data.get('dudas') or [])
        if not str(duda.get('id') or '').startswith('precio-estimado-')
    ]
    for rep in data.get('repuestos') or []:
        if isinstance(rep, dict) and rep.get('_estimado'):
            dudas.append(_duda_estimado(rep))
            rep.pop('_estimado', None)
    data['dudas'] = _unicas(dudas)
    return data


def _injertar_mano(data: dict, plan: dict) -> dict:
    if int(data.get('mano_obra_clp') or 0) > 0:
        return data
    if not plan.get('servicios'):
        return data
    data['servicios'] = plan['servicios']
    data['servicios_lineas'] = [
        {
            'nombre': servicio['nombre'],
            'monto_clp': servicio['mano_obra']['monto_clp'],
            'horas': servicio['mano_obra']['horas'],
            'estimada': servicio['mano_obra']['estimada'],
            'origen': servicio['mano_obra']['origen'],
            'motivo': servicio['mano_obra']['motivo'],
        }
        for servicio in plan['servicios']
    ]
    data['mano_obra_clp'] = sum(s['mano_obra']['monto_clp'] for s in plan['servicios'])
    previas = list(data.get('dudas') or [])
    data['dudas'] = _unicas(previas + list(plan.get('dudas') or []))
    return data


def _rellenar_precios(data: dict, buscar, vehiculo, taller) -> dict:
    for rep in data.get('repuestos') or []:
        if not isinstance(rep, dict):
            continue
        if int(rep.get('precio_unitario_clp') or 0) > 0:
            continue
        if not rep.get('consulta'):
            rep['consulta'] = _consulta(str(rep.get('nombre') or ''), vehiculo or {})
        _preciar(rep, buscar, vehiculo or {})
    return _con_margen(verificar_cotizacion(data), taller)


def completar_cotizacion_en_blanco(
    contenido: dict | None,
    texto: str,
    vehiculo: dict | None = None,
    taller=None,
    buscar: Buscador | None = None,
    pedido=None,
) -> dict:
    """Completa mano de obra y precios. No deja en $0 un servicio ya identificado."""
    data = dict(contenido or {})
    reps = [rep for rep in (data.get('repuestos') or []) if isinstance(rep, dict)]
    tiene_precio = any(int(rep.get('precio_unitario_clp') or 0) > 0 for rep in reps)
    mano = int(data.get('mano_obra_clp') or 0)
    plan = _armar(texto, vehiculo, taller, pedido)
    if not plan['servicios']:
        if not reps and mano <= 0:
            return verificar_cotizacion(_vacia(texto, plan))
        if reps and not tiene_precio:
            return _rellenar_precios(data, buscar, vehiculo, taller)
        return data
    if tiene_precio and mano > 0:
        return data
    if tiene_precio and mano <= 0:
        # El repuesto ya tiene precio. Solo falta la mano de obra. No se vuelve a marcar el margen.
        return verificar_cotizacion(_injertar_mano(data, plan))
    if reps and mano > 0:
        # La IA ya armó las piezas y la faena. Se completan los precios en blanco.
        return _rellenar_precios(data, buscar, vehiculo or plan['vehiculo'], taller)
    return cotizar_por_servicio(texto, vehiculo or plan['vehiculo'], taller, buscar, pedido)


def frase_de_servicio(texto: str) -> bool:
    return bool(planificar_pedido(texto).get('servicios'))

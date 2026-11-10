"""La cotización sale del servicio, no de la frase literal.

Lee el pedido, nombra el trabajo, pone la mano de obra, arma los repuestos
que ese trabajo pide de verdad y deja lo conveniente como sugerencia.
Antes de devolver la cotización revisa que no quede una línea en blanco.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
    norm as _norm_base,
)

Buscador = Callable[[dict], dict | None]

_AUTOS = (
    ('oroch', 'Renault', 'Oroch'),
    ('boxer', 'Peugeot', 'Boxer'),
    ('sail', 'Chevrolet', 'Sail'),
    ('yaris', 'Toyota', 'Yaris'),
    ('celerio', 'Suzuki', 'Celerio'),
    ('bravo', 'Fiat', 'Bravo'),
    ('duster', 'Renault', 'Duster'),
)

# Referencia para no dejar la línea en $0 cuando no hay ficha. Queda estimada.
_REFERENCIA_CLP = {
    'kit_embrague': 85000,
    'bomba_embrague': 28000,
    'cilindro_receptor_embrague': 18000,
    'aceite_caja': 22000,
    'rodamiento_piloto': 15000,
    'balatas_freno': 28000,
    'pastillas_freno': 32000,
    'aceite_motor': 36000,
    'filtro_aceite': 9000,
    'filtro_aire': 12000,
    'liquido_frenos': 9000,
}


def _norm(texto: str) -> str:
    n = _norm_base(texto)
    n = n.replace('mntcion', 'mantencion').replace('mantencion', 'mantencion')
    n = n.replace('acite', 'aceite').replace('fltro', 'filtro')
    n = n.replace('revicion', 'revision').replace('cambie', 'cambiar')
    n = re.sub(r'\s+', ' ', n).strip()
    return n


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


def _reintentos() -> int:
    """Un reintento con otra consulta antes de dejar el precio estimado."""
    return 1


def _vehiculo(texto: str, dado: dict | None) -> dict[str, Any]:
    base = dict(dado or {})
    crudo = str(texto or '')
    n = _norm(crudo)
    if not base.get('marca') or not base.get('modelo'):
        for clave, marca, modelo in _AUTOS:
            if clave in n:
                base.setdefault('marca', marca)
                base.setdefault('modelo', modelo)
                break
    if not base.get('anio'):
        anio = re.search(r'\b(19\d{2}|20\d{2})\b', crudo)
        if anio:
            base['anio'] = int(anio.group(1))
    if not base.get('motor'):
        motor = re.search(r'\b(\d\.\d)\b', crudo)
        if motor:
            base['motor'] = motor.group(1)
    return base


def _mano_catalogo(taller, nombre: str, vehiculo: dict) -> int | None:
    if taller is None:
        return None
    try:
        from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
            buscar_oferta_exacta,
        )
    except Exception:
        return None
    try:
        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre,
            marca=str(vehiculo.get('marca') or ''),
            modelo=str(vehiculo.get('modelo') or ''),
            tipo_motor=str(vehiculo.get('tipo_motor') or ''),
        )
    except Exception:
        return None
    if oferta is None:
        return None
    monto = int(getattr(oferta, 'precio_sin_repuestos', 0) or 0)
    return monto if monto > 0 else None


def _lista_explicita(texto: str) -> bool:
    """Varias piezas nombradas aparte. No es «cambiar el embrague, patina»."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        piezas_del_pedido,
    )

    concretas = [
        item for item in piezas_del_pedido(texto)
        if item.get('identidad') not in ('', 'sin_clasificar', 'otra')
    ]
    return len(concretas) >= 2


def _pieza(identidad: str, nombre: str, motivo: str = '') -> dict[str, str]:
    return {'identidad': identidad, 'nombre': nombre, 'motivo': motivo}


def planificar_pedido(
    texto: str,
    vehiculo: dict | None = None,
    taller=None,
) -> dict[str, Any]:
    """Servicios del pedido, con mano de obra, requeridos y sugeridos."""
    n = _norm(texto)
    auto = _vehiculo(texto, vehiculo)
    servicios: list[dict[str, Any]] = []
    dudas: list[dict[str, Any]] = []

    def _agregar(fila: dict[str, Any]) -> None:
        if any(item['id'] == fila['id'] for item in servicios):
            return
        servicios.append(fila)

    embrague = 'embrague' in n or 'clutch' in n
    verbo_embrague = bool(re.search(r'\b(cambi\w+|patina|ruido)\b', n))
    if embrague and verbo_embrague:
        requeridos = [_pieza('kit_embrague', 'Kit de embrague')]
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            piezas_del_pedido,
        )

        for item in piezas_del_pedido(texto):
            ident = item.get('identidad') or ''
            if ident in ('bomba_embrague', 'cilindro_receptor_embrague', 'liquido_frenos'):
                if not any(p['identidad'] == ident for p in requeridos):
                    requeridos.append(_pieza(ident, item['nombre']))
        sugeridos = [
            _pieza(
                'aceite_caja',
                'Aceite de caja de cambios',
                'Al bajar la caja se pierde la valvulina. Conviene reponerla.',
            ),
            _pieza(
                'rodamiento_piloto',
                'Rodamiento de volante',
                'Al bajar la caja conviene cambiarlo si el kit no lo trae.',
            ),
        ]
        _agregar(_servicio(
            'cambio_embrague',
            'Cambio de embrague',
            6,
            'Bajar la caja y cambiar el embrague son unas 6 horas de taller.',
            requeridos,
            sugeridos,
            auto,
            taller,
        ))

    trabajo = bool(re.search(r'\b(cambi\w+|mantenci\w+|revis\w+|diagnost\w+)\b', n))
    if trabajo and 'freno' in n and 'traser' in n and 'embrague' not in n:
        _agregar(_servicio(
            'frenos_traseros',
            'Mantención de frenos traseros',
            2,
            'Cambiar balatas traseras son unas 2 horas.',
            [_pieza('balatas_freno', 'Balatas de freno traseras')],
            [],
            auto,
            taller,
        ))
        dudas.append({
            'id': 'frenos-traseros-balatas',
            'texto': (
                'Los frenos traseros de este pedido se cotizan como balatas, '
                'no como pastillas, salvo que el texto pida disco.'
            ),
            'confirmada': False,
        })

    if (
        trabajo and 'aceite' in n and 'filtro' in n and 'caja' not in n and 'embrague' not in n
    ):
        _agregar(_servicio(
            'aceite_filtros',
            'Cambio de aceite y filtros',
            1,
            'El cambio de aceite y filtro es cerca de 1 hora.',
            [
                _pieza('aceite_motor', 'Aceite de motor'),
                _pieza('filtro_aceite', 'Filtro de aceite'),
            ],
            [_pieza(
                'filtro_aire',
                'Filtro de aire',
                'En el cambio de aceite conviene revisar el filtro de aire. No es el de aceite.',
            )],
            auto,
            taller,
        ))
        dudas.append({
            'id': 'aceite-viscosidad',
            'texto': (
                'Falta confirmar la viscosidad y los litros del motor. '
                'El aceite quedó estimado, no como una ficha cerrada.'
            ),
            'confirmada': False,
        })

    if trabajo and 'hidraulico' in n and ('sistema' in n or 'freno' in n):
        _agregar(_servicio(
            'revision_hidraulico',
            'Revisión del sistema hidráulico de frenos',
            1,
            'La revisión del sistema hidráulico es un diagnóstico de cerca de 1 hora.',
            [],
            [],
            auto,
            taller,
            solo_mano=True,
        ))
        dudas.append({
            'id': 'sistema-no-repuesto',
            'texto': (
                'Revisar el sistema hidráulico es mano de obra o diagnóstico. '
                'No se cotizó como repuesto.'
            ),
            'confirmada': False,
        })

    return {'servicios': servicios, 'vehiculo': auto, 'dudas': dudas}


def _servicio(
    ident: str,
    nombre: str,
    horas: float,
    motivo_horas: str,
    requeridos: list[dict],
    sugeridos: list[dict],
    vehiculo: dict,
    taller,
    solo_mano: bool = False,
) -> dict[str, Any]:
    catalogo = _mano_catalogo(taller, nombre, vehiculo)
    tarifa = _tarifa_hora(taller)
    if catalogo:
        monto = catalogo
        origen = 'catalogo'
        estimada = False
        motivo = 'Tarifa publicada del taller para este servicio y vehículo.'
    else:
        monto = int(round(horas * tarifa))
        origen = 'estimada'
        estimada = True
        motivo = f'{motivo_horas} Tarifa {tarifa} CLP/hora.'
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
        'mano_obra': {
            'monto_clp': monto,
            'horas': horas,
            'tarifa_hora_clp': tarifa,
            'origen': origen,
            'estimada': estimada,
            'motivo': motivo,
        },
        'repuestos_requeridos': requeridos,
        'sugeridos': sugeridos,
    }


def _consulta(nombre: str, vehiculo: dict) -> str:
    partes = [
        nombre,
        str(vehiculo.get('marca') or ''),
        str(vehiculo.get('modelo') or ''),
        str(vehiculo.get('anio') or ''),
        str(vehiculo.get('motor') or ''),
    ]
    return ' '.join(parte for parte in partes if str(parte).strip())


def _linea(
    pieza: dict,
    *,
    vehiculo: dict,
    origen: str,
    estado: str,
    motivo: str = '',
) -> dict[str, Any]:
    nombre = pieza['nombre']
    ident = pieza['identidad']
    fila = {
        'nombre': nombre,
        'identidad': ident,
        'cantidad': 4 if ident == 'aceite_motor' else 1,
        'precio_unitario_clp': 0,
        'origen': origen,
        'estado_sugerencia': estado,
        'motivo_sugerencia': motivo,
        'consulta': _consulta(nombre, vehiculo),
        'rol': 'insumo' if ident in ('aceite_motor', 'aceite_caja', 'liquido_frenos') else 'repuesto',
    }
    if ident == 'aceite_motor':
        fila['especificacion_pendiente'] = True
        fila['comentario'] = 'Confirmar viscosidad y litros del motor.'
    if ident == 'balatas_freno':
        fila['nombre'] = 'Balatas de freno traseras'
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
        if token not in {'de', 'del', 'la', 'el'}
    ]
    return any(token in titulo for token in tokens)


def _aplicar_hit(linea: dict, hit: dict) -> None:
    linea['precio_unitario_clp'] = int(hit.get('precio_unitario_clp') or 0)
    linea['url_producto'] = str(hit.get('url_producto') or hit.get('url') or '')
    linea['proveedor_nombre'] = str(hit.get('proveedor_nombre') or hit.get('tienda') or '')
    linea['nombre_producto'] = str(hit.get('nombre_producto') or hit.get('nombre') or linea['nombre'])
    linea['precio_estimado'] = False
    linea['certeza'] = 'confirmado'


def _aplicar_estimado(linea: dict) -> dict[str, Any]:
    ident = str(linea.get('identidad') or '')
    monto = _REFERENCIA_CLP.get(ident) or 10000
    linea['precio_unitario_clp'] = monto
    linea['precio_estimado'] = True
    linea['certeza'] = 'asumido'
    linea['fuente_marketplace'] = 'estimado'
    return {
        'id': f"precio-estimado-{_norm(linea.get('nombre') or 'pieza').replace(' ', '-')}"[:48],
        'texto': (
            f"No hay ficha de tienda para {linea.get('nombre')}. "
            f"Quedó un precio estimado de ${monto:,} para no dejar la línea en blanco. "
            'Confírmalo antes de enviarlo al cliente.'.replace(',', '.')
        ),
        'confirmada': False,
    }


def _preciar(linea: dict, buscar: Buscador | None) -> list[dict]:
    dudas = []
    if buscar is not None:
        hit = buscar(dict(linea))
        if not _hit_sirve(hit, linea):
            for _ in range(_reintentos()):
                otra = dict(linea)
                otra['consulta'] = f"{linea.get('consulta') or linea.get('nombre')} repuesto"
                hit = buscar(otra)
                linea['reintentos_busqueda'] = int(linea.get('reintentos_busqueda') or 0) + 1
                if _hit_sirve(hit, linea):
                    break
        if _hit_sirve(hit, linea):
            _aplicar_hit(linea, hit)
            return dudas
    dudas.append(_aplicar_estimado(linea))
    return dudas


def cotizar_por_servicio(
    texto: str,
    vehiculo: dict | None = None,
    taller=None,
    buscar: Buscador | None = None,
) -> dict[str, Any]:
    """Arma la cotización del servicio y la revisa antes de devolverla."""
    plan = planificar_pedido(texto, vehiculo, taller)
    auto = plan['vehiculo']
    repuestos: list[dict] = []
    dudas = list(plan['dudas'])
    vistos: set[str] = set()
    for servicio in plan['servicios']:
        if servicio.get('solo_mano'):
            continue
        for pieza in servicio['repuestos_requeridos']:
            if pieza['identidad'] in vistos:
                continue
            vistos.add(pieza['identidad'])
            linea = _linea(pieza, vehiculo=auto, origen='pedido', estado='aceptada')
            dudas.extend(_preciar(linea, buscar))
            repuestos.append(linea)
        for pieza in servicio['sugeridos']:
            if pieza['identidad'] in vistos:
                continue
            vistos.add(pieza['identidad'])
            linea = _linea(
                pieza,
                vehiculo=auto,
                origen='sugerencia',
                estado='pendiente',
                motivo=pieza.get('motivo') or '',
            )
            dudas.extend(_preciar(linea, buscar))
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
        'dudas': dudas,
        'mano_obra_clp': sum(s['mano_obra']['monto_clp'] for s in plan['servicios']),
    }
    return _con_margen(verificar_cotizacion(contenido), taller)


def verificar_cotizacion(contenido: dict[str, Any]) -> dict[str, Any]:
    """Ninguna línea queda en blanco y cada servicio trae mano de obra."""
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
        if ident == 'kit_embrague':
            pass
        precio = int(rep.get('precio_unitario_clp') or 0)
        if precio <= 0 or (
            not rep.get('precio_estimado') and not str(rep.get('url_producto') or '').strip()
        ):
            dudas.append(_aplicar_estimado(rep))
        limpias.append(rep)
    # El kit no se cobra otra vez como disco, prensa o collarín pedido.
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
                    'texto': (
                        f'{rep.get("nombre")} ya va en el kit. '
                        'No se cotizó otra vez como pieza suelta.'
                    ),
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
    costo, mo, total = recalcular_totales(limpias, mano)
    data['repuestos'] = limpias
    data['dudas'] = _unicas(dudas)
    data['servicios_lineas'] = lineas
    data['mano_obra_clp'] = mo
    data['costo_repuestos_clp'] = costo
    data['total_clp'] = total
    data['verificacion'] = {
        'ok': all(int(rep.get('precio_unitario_clp') or 0) > 0 for rep in limpias)
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


def completar_cotizacion_en_blanco(
    contenido: dict | None,
    texto: str,
    vehiculo: dict | None = None,
    taller=None,
    buscar: Buscador | None = None,
) -> dict:
    """Si la IA devolvió la frase sin precios, la reemplaza el plan del servicio.

    Una cotización que ya trae un precio firme no se reescribe: es el camino
    de las piezas pedidas una por una.
    """
    data = dict(contenido or {})
    reps = [rep for rep in (data.get('repuestos') or []) if isinstance(rep, dict)]
    if any(int(rep.get('precio_unitario_clp') or 0) > 0 for rep in reps):
        return data
    mano = int(data.get('mano_obra_clp') or 0)
    if reps and mano > 0:
        # El servicio ya está cotizado. Solo se marca el precio que vino en blanco.
        return _con_margen(verificar_cotizacion(data), taller)
    plan = planificar_pedido(texto, vehiculo, taller)
    if not plan['servicios']:
        return _con_margen(verificar_cotizacion(data), taller) if reps else data
    armado = cotizar_por_servicio(texto, vehiculo or plan['vehiculo'], taller, buscar)
    for clave in ('descripcion_problema',):
        if data.get(clave) and not armado.get(clave):
            armado[clave] = data[clave]
    return armado


def _con_margen(data: dict, taller) -> dict:
    """El margen del taller se aplica una vez, al quedar el costo."""
    if taller is None:
        return data
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
    return data


def frase_de_servicio(texto: str) -> bool:
    """Una frase de trabajo, no el nombre de una sola pieza."""
    return bool(planificar_pedido(texto).get('servicios'))

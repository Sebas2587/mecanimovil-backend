"""Helpers compartidos de match y precio desde catálogo publicado del taller."""
from __future__ import annotations

import unicodedata

from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import Taller


def normalizar_nombre_servicio(texto: str) -> str:
    t = unicodedata.normalize('NFKD', (texto or '').strip().lower())
    return ''.join(c for c in t if not unicodedata.combining(c))


def oferta_compatible_con_vehiculo(
    oferta: OfertaServicio,
    *,
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
) -> bool:
    """True si la oferta puede aplicarse al vehículo (sin conflicto de cobertura).

    Reglas:
    - Oferta sin marca/modelo/motor → cobertura general, siempre compatible.
    - Si la oferta fija marca/modelo/motor y el cliente también los tiene,
      deben coincidir (case-insensitive). Un mismatch excluye la oferta.
    - Si el cliente aún no tiene marca/modelo, no se excluye (faltan datos).
    """
    om = (getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or '').strip()
    omod = (getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or '').strip()
    tm = (oferta.tipo_motor or '').strip().lower()
    marca_req = (marca or '').strip()
    modelo_req = (modelo or '').strip()
    tm_req = (tipo_motor or '').strip().lower()

    if marca_req and om and om.lower() != marca_req.lower():
        return False
    if modelo_req and omod and omod.lower() != modelo_req.lower():
        return False
    if tm_req and tm and tm != tm_req:
        return False
    return True


def buscar_oferta_exacta(
    *,
    taller: Taller,
    servicio_nombre: str,
    marca: str,
    modelo: str,
    tipo_motor: str = '',
) -> OfertaServicio | None:
    """Match determinístico taller + servicio + marca/modelo + motor.

    Nunca devuelve una oferta de OTRA marca/modelo/motor cuando el vehículo
    del cliente ya tiene esos datos. Solo acepta coincidencia exacta o
    cobertura general (campos vacíos en la oferta).
    """
    nombre_norm = normalizar_nombre_servicio(servicio_nombre)
    if not nombre_norm:
        return None

    qs = (
        OfertaServicio.objects.filter(taller=taller, disponible=True)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
    )

    candidatas: list[OfertaServicio] = []
    for oferta in qs:
        serv_norm = normalizar_nombre_servicio(getattr(oferta.servicio, 'nombre', '') or '')
        if not serv_norm:
            continue
        if nombre_norm not in serv_norm and serv_norm not in nombre_norm:
            continue
        if not oferta_compatible_con_vehiculo(
            oferta,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        ):
            continue
        candidatas.append(oferta)

    if not candidatas:
        return None

    def _score(oferta: OfertaServicio) -> int:
        s = 0
        om = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or ''
        omod = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or ''
        # Preferir match exacto de cobertura sobre ofertas "todas las marcas".
        if marca and om and om.lower() == marca.lower():
            s += 4
        elif not om:
            s += 1
        if modelo and omod and omod.lower() == modelo.lower():
            s += 4
        elif not omod:
            s += 1
        tm = (oferta.tipo_motor or '').strip().lower()
        tm_req = (tipo_motor or '').strip().lower()
        if tm_req and tm and tm == tm_req:
            s += 2
        elif not tm:
            s += 1
        serv_norm = normalizar_nombre_servicio(oferta.servicio.nombre)
        if serv_norm == nombre_norm:
            s += 3
        if int(oferta.precio_con_repuestos or 0) or int(oferta.precio_sin_repuestos or 0):
            s += 2
        return s

    candidatas.sort(key=_score, reverse=True)
    mejor = candidatas[0]
    if _score(mejor) < 3:
        return None
    return mejor


def buscar_oferta_por_id(*, taller: Taller, oferta_servicio_id: int) -> OfertaServicio | None:
    return (
        OfertaServicio.objects.filter(
            pk=oferta_servicio_id,
            taller=taller,
            disponible=True,
        )
        .select_related('servicio')
        .first()
    )


def precio_publico_oferta(oferta: OfertaServicio, *, con_repuestos: bool = True) -> tuple[int, bool]:
    """Devuelve (precio al público con IVA, usó_con_repuestos)."""
    if con_repuestos and int(oferta.precio_con_repuestos or 0):
        return int(oferta.precio_con_repuestos), True
    if int(oferta.precio_sin_repuestos or 0):
        return int(oferta.precio_sin_repuestos), False
    if int(oferta.precio_con_repuestos or 0):
        return int(oferta.precio_con_repuestos), True
    mano = int(oferta.costo_mano_de_obra_sin_iva or 0)
    rep = int(oferta.costo_repuestos_sin_iva or 0)
    if mano or rep:
        base = mano + (rep if con_repuestos else 0)
        return int(round(base * 1.19)), con_repuestos and rep > 0
    return 0, con_repuestos


def linea_desde_oferta_catalogo(
    oferta: OfertaServicio,
    *,
    cantidad: int = 1,
) -> dict:
    """Construye una línea de servicio con precio de catálogo."""
    precio_cat, _ = precio_publico_oferta(oferta, con_repuestos=True)
    nombre = getattr(oferta.servicio, 'nombre', '') or 'Servicio'
    return {
        'nombre': nombre,
        'oferta_servicio_id': oferta.id,
        'precio_desde_catalogo': precio_cat > 0,
        'precio_clp': precio_cat,
        'cantidad': max(1, int(cantidad or 1)),
    }

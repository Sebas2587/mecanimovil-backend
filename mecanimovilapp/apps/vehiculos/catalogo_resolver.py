"""
Resolución de marcas y modelos sin duplicar entradas por diferencias de mayúsculas.

La tabla MarcaVehiculo.nombre es unique case-sensitive; get_or_create(nombre=XXX.upper())
creaba marcas duplicadas (p. ej. "TOYOTA" vs "Toyota" ya cargada en master data).
"""
from __future__ import annotations

from django.db import IntegrityError

from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo

# Siglas de marca que no deben pasar por .title() al crear registros nuevos
_MARCAS_SIGLA = frozenset({'BMW', 'KIA', 'GMC', 'RAM', 'UAZ', 'JAC', 'DFSK', 'SWM'})


def normalize_nombre_catalogo(nombre: str | None) -> str:
    """Elimina espacios extra; no altera mayúsculas."""
    if not nombre:
        return ''
    return ' '.join(str(nombre).strip().split())


def nombre_para_nueva_marca(nombre: str) -> str:
    """
    Nombre a persistir cuando la marca no existe.
    Respeta siglas conocidas; si viene todo en mayúsculas, aplica title case.
    """
    n = normalize_nombre_catalogo(nombre)
    if not n:
        return n
    upper = n.upper()
    if upper in _MARCAS_SIGLA:
        return upper
    if n.isupper() and len(n) > 3:
        return n.title()
    return n


def resolve_marca(nombre: str | None) -> MarcaVehiculo | None:
    """Busca marca existente (case-insensitive). No crea."""
    n = normalize_nombre_catalogo(nombre)
    if not n:
        return None
    return MarcaVehiculo.objects.filter(nombre__iexact=n).first()


def resolve_or_create_marca(nombre: str | None) -> tuple[MarcaVehiculo | None, bool]:
    """
    Devuelve (marca, created). Reutiliza la fila existente si el nombre coincide
    sin importar mayúsculas.
    """
    n = normalize_nombre_catalogo(nombre)
    if not n:
        return None, False

    existing = resolve_marca(n)
    if existing:
        return existing, False

    nombre_guardar = nombre_para_nueva_marca(n)
    try:
        return MarcaVehiculo.objects.create(nombre=nombre_guardar), True
    except IntegrityError:
        # Carrera: otra petición creó la misma marca entre el lookup y el insert
        existing = resolve_marca(nombre_guardar) or resolve_marca(n)
        if existing:
            return existing, False
        raise


def resolve_modelo(marca: MarcaVehiculo, nombre: str | None) -> Modelo | None:
    """
    Busca modelo bajo la marca (case-insensitive).
    Si el nombre de API incluye versión (ej. "COROLLA XLI"), intenta el primer token.
    """
    if not marca:
        return None
    n = normalize_nombre_catalogo(nombre)
    if not n:
        return None

    qs = Modelo.objects.filter(marca=marca)
    exact = qs.filter(nombre__iexact=n).first()
    if exact:
        return exact

    parts = n.split()
    if len(parts) > 1:
        token = parts[0]
        if len(token) >= 2:
            by_token = qs.filter(nombre__iexact=token).first()
            if by_token:
                return by_token
            by_contains = qs.filter(nombre__icontains=token).order_by('nombre').first()
            if by_contains:
                return by_contains

    return None


def resolve_or_create_modelo(
    marca: MarcaVehiculo,
    nombre: str | None,
) -> tuple[Modelo | None, bool]:
    """Devuelve (modelo, created). No duplica por mayúsculas ni reutiliza otra marca."""
    if not marca:
        return None, False

    existing = resolve_modelo(marca, nombre)
    if existing:
        return existing, False

    n = normalize_nombre_catalogo(nombre)
    if not n:
        return None, False

    nombre_guardar = nombre_para_nueva_marca(n) if n.isupper() and len(n) > 3 else n
    try:
        return Modelo.objects.create(marca=marca, nombre=nombre_guardar), True
    except IntegrityError:
        existing = resolve_modelo(marca, nombre_guardar) or resolve_modelo(marca, n)
        if existing:
            return existing, False
        raise


def resolver_marca_modelo_registro(
    *,
    marca_id=None,
    marca_nombre=None,
    modelo_id=None,
    modelo_nombre=None,
) -> tuple[MarcaVehiculo | None, Modelo | None, str | None]:
    """
    Marca/modelo canónicos para alta de vehículo.

    Prioriza marca_nombre (evita IDs obsoletos por marcas duplicadas en catálogo).
    Devuelve (marca, modelo, clave_error) — clave_error en {'marca', 'modelo'} si falta.
    """
    marca_obj: MarcaVehiculo | None = None

    if marca_nombre:
        marca_obj, _ = resolve_or_create_marca(marca_nombre)

    if not marca_obj and marca_id is not None:
        sid = str(marca_id).strip()
        if sid.isdigit():
            marca_obj = MarcaVehiculo.objects.filter(id=int(sid)).first()

    if not marca_obj:
        return None, None, 'marca'

    modelo_obj: Modelo | None = None

    if modelo_nombre:
        modelo_obj, _ = resolve_or_create_modelo(marca_obj, modelo_nombre)

    if not modelo_obj and modelo_id is not None:
        sid = str(modelo_id).strip()
        if sid.isdigit():
            cand = Modelo.objects.filter(id=int(sid)).select_related('marca').first()
            if cand and cand.marca_id == marca_obj.id:
                modelo_obj = cand

    if not modelo_obj:
        return marca_obj, None, 'modelo'

    return marca_obj, modelo_obj, None


def normalizar_tipo_motor_vehiculo(valor: str | None) -> str:
    """Mapea valores de API/app a choices válidos del modelo Vehiculo."""
    if not valor:
        return 'GASOLINA'
    u = str(valor).upper().strip()
    if 'DIESEL' in u or 'DIÉSEL' in u:
        return 'DIESEL'
    if 'ELECTR' in u or 'ELÉCTR' in u:
        return 'ELECTRICO'
    if 'HIBR' in u or 'HYBR' in u or 'HÍBR' in u:
        return 'HIBRIDO'
    if 'BENCINA' in u or 'GASOL' in u:
        return 'GASOLINA'
    if u in ('GASOLINA', 'DIESEL', 'ELECTRICO', 'HIBRIDO', 'BENCINA'):
        return u
    if u == 'ELECTRIC':
        return 'ELECTRICO'
    return 'GASOLINA'

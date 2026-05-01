"""
Reglas de negocio para mostrar un proveedor como "verificado" (documentación + estado administrativo).

- El modelo guarda `verificado` solo cuando `estado_verificacion == 'aprobado'` (ver ProveedorServicio.save).
- Para APIs y apps, un proveedor se considera verificado en UI solo si además
  todos los documentos obligatorios del tipo (taller vs mecánico) tienen al menos
  un registro con `DocumentoOnboarding.verificado == True` (aprobado por staff).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, FrozenSet

if TYPE_CHECKING:
    from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio, ProveedorServicio

# Alineado con el onboarding (documentacion.tsx / lógica negocio)
TIPOS_OBLIGATORIOS_TALLER: FrozenSet[str] = frozenset(
    {"dni_frontal", "dni_trasero", "rut_fiscal"}
)
TIPOS_OBLIGATORIOS_MECANICO: FrozenSet[str] = frozenset(
    {"dni_frontal", "dni_trasero", "licencia_conducir"}
)


def tipos_documentos_obligatorios(proveedor: "ProveedorServicio") -> FrozenSet[str]:
    from mecanimovilapp.apps.usuarios.models import Taller

    if isinstance(proveedor, Taller):
        return TIPOS_OBLIGATORIOS_TALLER
    return TIPOS_OBLIGATORIOS_MECANICO


def documentos_obligatorios_aprobados(proveedor: "ProveedorServicio") -> bool:
    """True si cada tipo obligatorio tiene al menos un documento marcado verificado=True."""
    from mecanimovilapp.apps.usuarios.models import DocumentoOnboarding, Taller

    tipos = tipos_documentos_obligatorios(proveedor)
    if isinstance(proveedor, Taller):
        qs = DocumentoOnboarding.objects.filter(taller=proveedor, verificado=True)
    else:
        qs = DocumentoOnboarding.objects.filter(mecanico=proveedor, verificado=True)

    verificados = set(qs.values_list("tipo_documento", flat=True).distinct())
    return tipos.issubset(verificados)


def proveedor_visible_como_verificado(proveedor: "ProveedorServicio") -> bool:
    """
    Valor unificado para serializers y estado-proveedor:
    aprobado administrativamente y documentación obligatoria validada en BD.
    """
    try:
        if proveedor.estado_verificacion != "aprobado":
            return False
        if not getattr(proveedor, "verificado", False):
            return False
        return documentos_obligatorios_aprobados(proveedor)
    except Exception:
        return False

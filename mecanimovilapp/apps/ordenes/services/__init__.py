"""Servicios de dominio para la app ordenes (KPIs, agregaciones, etc.)."""

from mecanimovilapp.apps.ordenes.services.proveedor_kpis import compute_proveedor_kpis_resumen

__all__ = ['compute_proveedor_kpis_resumen']

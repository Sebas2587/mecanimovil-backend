"""Especificación Pydantic V2 / PydanticAI para Agente 1 (SDR & Captura)."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class VehiculoCapturado(BaseModel):
    """Información del vehículo recabada por el Agente 1."""

    marca: Optional[str] = Field(None, description="Marca del vehículo (ej. Fiat, Toyota)")
    modelo: Optional[str] = Field(None, description="Modelo del vehículo (ej. Bravo, Corolla)")
    anio: Optional[int] = Field(None, description="Año del vehículo (ej. 2018)")
    patente: Optional[str] = Field(None, description="Patente chilena limpia (ej. CJXP98)")
    motor: Optional[str] = Field(None, description="Cilindrada o tipo de motor (ej. 1.4 Turbo)")
    vin: Optional[str] = Field(None, description="Número de chasis o VIN si está disponible")


class ClienteCapturado(BaseModel):
    """Información del cliente recabada por el Agente 1."""

    nombre: Optional[str] = Field(None, description="Nombre del cliente")
    telefono: Optional[str] = Field(None, description="Teléfono de contacto comprobado")
    comuna: Optional[str] = Field(None, description="Comuna o zona de residencia/atención")


class FichaLeadCapturada(BaseModel):
    """Esquema de salida estructurada devuelto por el Agente 1."""

    vehiculo: VehiculoCapturado = Field(default_factory=VehiculoCapturado)
    cliente: ClienteCapturado = Field(default_factory=ClienteCapturado)
    sintomas_cliente: List[str] = Field(
        default_factory=list,
        description="Lista de síntomas o problemas descritos por el cliente",
    )
    servicios_solicitados: List[str] = Field(
        default_factory=list,
        description="Lista de servicios requeridos (ej. Cambio de embrague, Cambio de aceite)",
    )
    listo_para_cotizar: bool = Field(
        default=False,
        description="True si se cuenta con patente + síntoma/servicio + teléfono para armar borrador en Columna 2 del Kanban",
    )
    resumen_interpretacion: str = Field(
        default="",
        description="Síntesis comercial breve elaborada por el agente",
    )


def consultar_patente_registro(patente: str) -> dict:
    """Herramienta mock/integración para consultar registro de patentes."""
    patente_limpia = patente.strip().upper().replace("-", "").replace(" ", "")
    return {
        "patente": patente_limpia,
        "encontrada": True,
        "mensaje": f"Patente {patente_limpia} procesada correctamente",
    }


def buscar_catalogo_taller(taller_id: int, busqueda: str) -> List[dict]:
    """Herramienta para buscar servicios en el catálogo del taller."""
    return [
        {
            "taller_id": taller_id,
            "servicio": busqueda,
            "encontrado": True,
        }
    ]

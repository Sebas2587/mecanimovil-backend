"""Especificación Pydantic V2 / PydanticAI para Agente 2 (Agenda & Cierre)."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class BloqueHorarioSugerido(BaseModel):
    """Bloque de horario disponible en la agenda del taller."""

    fecha: str = Field(..., description="Fecha en formato YYYY-MM-DD")
    hora_inicio: str = Field(..., description="Hora de inicio en formato HH:MM")
    hora_fin: str = Field(..., description="Hora de fin en formato HH:MM")
    disponible: bool = Field(default=True, description="Indica si el bloque está libre para agendar")


class CoordinacionCitaOutput(BaseModel):
    """Esquema de salida estructurada devuelto por el Agente 2."""

    cotizacion_id: Optional[int] = Field(None, description="ID de la cotización aprobada")
    bloques_sugeridos: List[BloqueHorarioSugerido] = Field(
        default_factory=list,
        description="Top 3 bloques de horario sugeridos al cliente",
    )
    bloque_seleccionado: Optional[BloqueHorarioSugerido] = Field(
        None,
        description="Bloque finalmente elegido por el cliente",
    )
    modalidad: str = Field(
        default="domicilio",
        description="Modalidad del servicio: 'domicilio' o 'taller'",
    )
    agendado_exitoso: bool = Field(
        default=False,
        description="True si la cita quedó confirmada en el calendario",
    )
    resumen_confirmacion: str = Field(
        default="",
        description="Mensaje final de confirmación de la cita",
    )


def consultar_bloques_disponibles(taller_id: int, fecha: str) -> List[dict]:
    """Herramienta para consultar los bloques disponibles en la agenda del taller."""
    return [
        {"fecha": fecha, "hora_inicio": "10:00", "hora_fin": "11:30", "disponible": True},
        {"fecha": fecha, "hora_inicio": "12:00", "hora_fin": "13:30", "disponible": True},
        {"fecha": fecha, "hora_inicio": "15:00", "hora_fin": "16:30", "disponible": True},
    ]


def reservar_bloque_taller(taller_id: int, cotizacion_id: int, fecha: str, hora_inicio: str) -> dict:
    """Herramienta para reservar un bloque en el calendario."""
    return {
        "exito": True,
        "taller_id": taller_id,
        "cotizacion_id": cotizacion_id,
        "fecha": fecha,
        "hora_inicio": hora_inicio,
        "mensaje": "Cita reservada correctamente",
    }

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(_Args):
    pass


class DrawingObjectsArgs(_Args):
    object_type: Literal[
        "all", "surface", "alignment", "profile", "point", "polyline", "text"
    ] = Field("all", description="Tipo de objeto a listar.")
    limit: int = Field(100, ge=1, le=1000, description="Máximo de objetos a devolver.")


class InspectSurfaceArgs(_Args):
    surface_name: str = Field(
        ..., min_length=1, max_length=255, description="Nombre exacto de la superficie TIN."
    )


class CreateSurfaceArgs(_Args):
    name: str = Field(..., min_length=1, max_length=200, description="Nombre de la nueva superficie.")
    description: str = Field("", max_length=500, description="Descripción opcional.")
    style: str | None = Field(
        None, description="Nombre del estilo de superficie existente. Vacío = estilo por defecto."
    )


class ContoursArgs(_Args):
    surface_name: str = Field(..., min_length=1, max_length=255)
    major_interval: float = Field(
        ..., gt=0, le=1000, description="Intervalo de curvas maestras en unidades del dibujo."
    )
    minor_interval: float = Field(
        0, ge=0, le=1000, description="Intervalo de curvas menores. 0 = sin menores."
    )
    style: str | None = Field(None, description="Estilo de superficie a aplicar.")


class AlignmentFromPolylineArgs(_Args):
    polyline_handle: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Handle hexadecimal de la polilínea en el dibujo.",
    )
    name: str = Field(..., min_length=1, max_length=200)
    style: str | None = Field(None, description="Estilo de alineamiento existente.")


class ProfileArgs(_Args):
    alignment_name: str = Field(..., min_length=1, max_length=255)
    surface_name: str = Field(..., min_length=1, max_length=255)
    name: str | None = Field(None, max_length=200)


class OperationStatusArgs(_Args):
    operation_id: str = Field(..., min_length=6, max_length=64)


class VolumesArgs(_Args):
    base_surface: str = Field(..., min_length=1, max_length=255)
    comparison_surface: str = Field(..., min_length=1, max_length=255)
    method: Literal["tin", "grid"] = Field("tin", description="Método de cálculo.")


ToolRisk = Literal["read", "write"]

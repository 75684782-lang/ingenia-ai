from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from . import definitions as d

Risk = Literal["read", "write"]


class ToolValidationError(ValueError):
    def __init__(self, tool: str, errors: list[dict[str, Any]]) -> None:
        self.tool = tool
        self.errors = errors
        super().__init__(f"Argumentos inválidos para {tool}")

    def as_result(self) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "validation_error",
            "mode": "validation",
            "tool": self.tool,
            "error": "Argumentos inválidos.",
            "errors": self.errors,
        }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    risk: Risk
    category: str
    local: bool = False
    experimental: bool = False

    @property
    def requires_confirmation(self) -> bool:
        return self.risk == "write"

    def ollama_schema(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


SPECS: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    SPECS[spec.name] = spec


_register(
    ToolSpec(
        name="get_civil3d_status",
        description=(
            "Comprueba si el complemento de Civil 3D está conectado y qué dibujo tiene abierto. "
            "Úsala antes de cualquier operación para no asumir que hay conexión."
        ),
        args_model=d.EmptyArgs,
        risk="read",
        category="estado",
    )
)
_register(
    ToolSpec(
        name="get_active_drawing_info",
        description=(
            "Devuelve información del dibujo activo de Civil 3D: nombre, ruta, unidades y "
            "versión. No inventa datos: si no hay conexión devuelve ok=false."
        ),
        args_model=d.EmptyArgs,
        risk="read",
        category="consulta",
    )
)
_register(
    ToolSpec(
        name="list_drawing_objects",
        description=(
            "Enumera objetos compatibles del dibujo activo (superficies, alineamientos, "
            "perfiles, puntos, polilíneas, textos)."
        ),
        args_model=d.DrawingObjectsArgs,
        risk="read",
        category="consulta",
    )
)
_register(
    ToolSpec(
        name="inspect_surface",
        description="Consulta los datos de una superficie TIN existente por su nombre exacto.",
        args_model=d.InspectSurfaceArgs,
        risk="read",
        category="superficies",
    )
)
_register(
    ToolSpec(
        name="list_alignments",
        description="Enumera los alineamientos existentes con su longitud y estado.",
        args_model=d.EmptyArgs,
        risk="read",
        category="alineamientos",
    )
)
_register(
    ToolSpec(
        name="create_surface",
        description=(
            "Crea una superficie TIN vacía con nombre único en el dibujo. MODIFICA el dibujo: "
            "requiere confirmación explícita del usuario."
        ),
        args_model=d.CreateSurfaceArgs,
        risk="write",
        category="superficies",
    )
)
_register(
    ToolSpec(
        name="generate_contours",
        description=(
            "Configura los intervalos de curvas de nivel de una superficie existente. "
            "MODIFICA el dibujo: requiere confirmación explícita."
        ),
        args_model=d.ContoursArgs,
        risk="write",
        category="superficies",
    )
)
_register(
    ToolSpec(
        name="create_alignment_from_polyline",
        description=(
            "Crea un alineamiento a partir de una polilínea identificada por su handle. "
            "MODIFICA el dibujo: requiere confirmación explícita."
        ),
        args_model=d.AlignmentFromPolylineArgs,
        risk="write",
        category="alineamientos",
    )
)
_register(
    ToolSpec(
        name="generate_profile",
        description=(
            "Genera un perfil longitudinal del terreno para un alineamiento usando una "
            "superficie. MODIFICA el dibujo: requiere confirmación explícita."
        ),
        args_model=d.ProfileArgs,
        risk="write",
        category="perfiles",
    )
)
_register(
    ToolSpec(
        name="get_operation_status",
        description="Consulta el estado registrado de una operación previa por su identificador.",
        args_model=d.OperationStatusArgs,
        risk="read",
        category="estado",
        local=True,
    )
)
_register(
    ToolSpec(
        name="calculate_volumes",
        description=(
            "EXPERIMENTAL. Calcula volúmenes de corte y relleno entre dos superficies TIN. "
            "No está verificada contra Civil 3D real; informa siempre su estado experimental."
        ),
        args_model=d.VolumesArgs,
        risk="read",
        category="volumenes",
        experimental=True,
    )
)


class ToolRegistry:
    def __init__(self, specs: dict[str, ToolSpec] | None = None) -> None:
        self._specs = specs or SPECS

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def ollama_tools(self) -> list[dict[str, Any]]:
        return [spec.ollama_schema() for spec in self._specs.values()]

    def validate(self, name: str, args: dict[str, Any]) -> tuple[ToolSpec, dict[str, Any]]:
        spec = self.get(name)
        if spec is None:
            raise ToolValidationError(
                name,
                [{"loc": ["tool"], "msg": "Herramienta no permitida", "type": "unknown_tool"}],
            )
        try:
            model = spec.args_model.model_validate(args or {})
        except ValidationError as exc:
            errors = json.loads(exc.json())
            raise ToolValidationError(name, errors) from exc
        return spec, model.model_dump(exclude_none=True)

    def describe(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in self._specs.values():
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "risk": spec.risk,
                    "category": spec.category,
                    "requires_confirmation": spec.requires_confirmation,
                    "experimental": spec.experimental,
                    "local": spec.local,
                    "parameters": spec.args_model.model_json_schema(),
                }
            )
        return out

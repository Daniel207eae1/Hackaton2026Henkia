"""Catálogo de acciones (§3.6) leído de `config/catalogo_acciones.yaml`.

Es la ÚNICA fuente de los textos que ve el usuario sobre una acción (qué hará, aviso obligatorio,
reversión, riesgo). Al cargar se verifica que la política de cada acción coincida con la de la lista
blanca del MCP (`catalogo_mcp.py`): si difieren, la API no arranca.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config.ajustes import RAIZ_BACKEND
from app.integraciones.zabbix.catalogo_mcp import BLOQUEADAS, TOOLS

RUTA = RAIZ_BACKEND / "config" / "catalogo_acciones.yaml"
RUTA_ANS = RAIZ_BACKEND / "config" / "ans.yaml"


class ErrorCatalogo(Exception):
    pass


@dataclass(frozen=True)
class Accion:
    id: str
    tool_mcp: str | None
    nombre: str
    descripcion: str
    riesgo: str
    politica: str
    aviso_obligatorio: str
    reversion: str
    plantilla_rechazo: str | None = None


@dataclass(frozen=True)
class Catalogo:
    acciones: dict[str, Accion]

    def por_tool(self, tool: str) -> Accion:
        for a in self.acciones.values():
            if a.tool_mcp == tool:
                return a
        raise KeyError(tool)

    def tools_ejecutables(self) -> list[str]:
        return sorted(
            a.tool_mcp
            for a in self.acciones.values()
            if a.tool_mcp and a.politica in ("consentimiento", "aprobacion_n2")
        )


def cargar_catalogo(ruta: Path = RUTA) -> Catalogo:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    acciones: dict[str, Accion] = {}
    for a in datos["acciones"]:
        accion = Accion(
            id=a["id"],
            tool_mcp=a.get("tool_mcp"),
            nombre=a["nombre"],
            descripcion=a["descripcion"],
            riesgo=a["riesgo"],
            politica=a["politica"],
            aviso_obligatorio=a["aviso_obligatorio"],
            reversion=a["reversion"],
            plantilla_rechazo=a.get("plantilla_rechazo"),
        )
        if accion.tool_mcp:
            if accion.politica == "prohibida":
                raise ErrorCatalogo(f"{accion.id}: una acción prohibida no puede tener tool_mcp")
            if accion.tool_mcp in BLOQUEADAS or accion.tool_mcp not in TOOLS:
                raise ErrorCatalogo(f"{accion.id}: tool_mcp '{accion.tool_mcp}' fuera de la lista blanca")
            if TOOLS[accion.tool_mcp].value != accion.politica:
                raise ErrorCatalogo(
                    f"{accion.id}: política '{accion.politica}' ≠ '{TOOLS[accion.tool_mcp].value}' en el MCP"
                )
        acciones[accion.id] = accion
    return Catalogo(acciones)


@lru_cache
def catalogo() -> Catalogo:
    return cargar_catalogo()


@lru_cache
def _ans_todos() -> dict[str, dict[str, str]]:
    return yaml.safe_load(RUTA_ANS.read_text(encoding="utf-8"))["ans"]


def ans(clave: str) -> dict[str, str]:
    """Plazo simulado de atención: {prioridad, plazo, texto} (config/ans.yaml)."""
    return dict(_ans_todos()[clave])


def texto_ans(clave: str) -> str:
    return ans(clave)["texto"]

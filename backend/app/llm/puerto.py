"""Puerto de la capa LLM agnóstica (ADR 0004).

Los agentes dependen SOLO de este módulo y de `registro.py`. Ningún agente conoce el proveedor
ni el nombre del modelo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Capacidad(StrEnum):
    CHAT = "chat"
    STREAMING = "streaming"
    TOOLS = "tools"
    SALIDA_ESTRUCTURADA = "salida_estructurada"
    VISION = "vision"
    EMBEDDINGS = "embeddings"


@dataclass(frozen=True)
class Mensaje:
    rol: str  # system | user | assistant | tool
    contenido: str | list[dict[str, Any]]


@dataclass
class Uso:
    tokens_entrada: int = 0
    tokens_salida: int = 0


@dataclass
class RespuestaChat:
    texto: str
    uso: Uso = field(default_factory=Uso)
    llamada_herramienta: dict[str, Any] | None = None  # {"nombre": str, "argumentos": str}
    modelo: str = ""


@dataclass
class FragmentoStream:
    delta: str = ""
    uso: Uso | None = None  # solo en el último fragmento, si el proveedor lo reporta


class ErrorLLM(Exception):
    """Error de proveedor. `reintentable` indica si conviene reintentar o pasar al siguiente."""

    def __init__(self, mensaje: str, *, reintentable: bool, espera_s: float | None = None, cuota_agotada: bool = False):
        super().__init__(mensaje)
        self.reintentable = reintentable
        self.espera_s = espera_s
        # Cuota DIARIA del proveedor agotada: no sirve reintentar ni probar otros modelos del mismo proveedor.
        self.cuota_agotada = cuota_agotada


class ProveedorLLM(Protocol):
    """Contrato que implementa cada adaptador (openai_compatible, fake, …)."""

    async def chat(
        self,
        modelo: str,
        mensajes: list[Mensaje],
        parametros: dict[str, Any],
        *,
        response_format: dict[str, Any] | None = None,
        herramientas: list[dict[str, Any]] | None = None,
        herramienta_forzada: str | None = None,
    ) -> RespuestaChat: ...

    def chat_stream(
        self, modelo: str, mensajes: list[Mensaje], parametros: dict[str, Any]
    ) -> AsyncIterator[FragmentoStream]: ...

    async def embeddings(
        self, modelo: str, textos: list[str], dimension: int | None
    ) -> tuple[list[list[float]], Uso]: ...

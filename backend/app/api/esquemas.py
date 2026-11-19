"""Esquemas Pydantic de la API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParteMensajeUI(BaseModel):
    type: str
    text: str | None = None
    model_config = {"extra": "allow"}


class MensajeUI(BaseModel):
    id: str | None = None
    role: str
    parts: list[ParteMensajeUI] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class PeticionChat(BaseModel):
    """Cuerpo que envía `DefaultChatTransport` del AI SDK. Solo se usa el último mensaje del
    usuario: el historial oficial vive en el estado del caso (ADR 0002)."""

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$", description="id del chat = case_id")
    messages: list[MensajeUI] = Field(min_length=1, max_length=200)
    trigger: str | None = None
    messageId: str | None = None  # noqa: N815 - nombre del protocolo
    model_config = {"extra": "ignore"}

    def ultimo_texto_usuario(self) -> str:
        for m in reversed(self.messages):
            if m.role == "user":
                return "\n".join(p.text or "" for p in m.parts if p.type == "text").strip()
        return ""


class PersonaSalida(BaseModel):
    id: str
    nombre: str
    rol: str
    area: str
    equipo_id: str | None = None
    etiqueta: str | None = None


class EstadoCasoSalida(BaseModel):
    case_id: str
    etapa: str | None
    turnos: int
    estado: dict[str, Any]

"""Traducción de eventos internos → UI Message Stream protocol v1 del AI SDK (ADR 0002).

Único lugar del backend que conoce el protocolo. Los agentes y el grafo emiten eventos
internos neutros ({"tipo": ...}); aquí se convierten en partes SSE para `useChat`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

CABECERAS_SSE = {
    "x-vercel-ai-ui-message-stream": "v1",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
MEDIA_TYPE = "text/event-stream"
FIN = "data: [DONE]\n\n"


def sse(parte: dict[str, Any]) -> str:
    return f"data: {json.dumps(parte, ensure_ascii=False)}\n\n"


class TraductorEventos:
    """Mantiene el estado de las partes abiertas (p. ej., el bloque de texto en curso)."""

    def __init__(self) -> None:
        self.message_id = f"msg-{uuid.uuid4().hex}"
        self._texto_id: str | None = None

    def inicio(self) -> list[dict[str, Any]]:
        return [{"type": "start", "messageId": self.message_id}]

    def traducir(self, evento: dict[str, Any]) -> list[dict[str, Any]]:
        tipo = evento.get("tipo")
        if tipo == "texto_delta":
            partes = []
            if self._texto_id is None:
                self._texto_id = f"txt-{uuid.uuid4().hex[:12]}"
                partes.append({"type": "text-start", "id": self._texto_id})
            partes.append({"type": "text-delta", "id": self._texto_id, "delta": evento["delta"]})
            return partes
        if tipo == "texto":
            # Bloque completo (plantilla del código): parte de texto propia.
            tid = f"txt-{uuid.uuid4().hex[:12]}"
            return [
                *self.cerrar_texto(),
                {"type": "text-start", "id": tid},
                {"type": "text-delta", "id": tid, "delta": evento["texto"]},
                {"type": "text-end", "id": tid},
            ]
        if tipo == "hipotesis":
            return [{"type": "data-hipotesis", "id": "hipotesis", "data": evento["datos"]}]
        if tipo == "captura":
            return [{"type": "data-captura", "id": f"captura-{uuid.uuid4().hex[:8]}", "data": evento["datos"]}]
        if tipo == "fuentes":
            return [{"type": "data-fuentes", "id": f"fuentes-{uuid.uuid4().hex[:8]}", "data": evento["datos"]}]
        if tipo in ("escalamiento", "cierre", "masivo"):
            return [{"type": f"data-{tipo}", "id": tipo, "data": evento["datos"]}]
        if tipo == "accion":
            datos = evento["datos"]
            return [{"type": "data-accion", "id": datos["id"], "data": datos}]
        if tipo == "etapa":
            # Misma id => la UI actualiza la parte en sitio (indicador de etapa).
            return [{"type": "data-etapa", "id": "etapa", "data": {"etapa": evento["etapa"]}}]
        if tipo == "revisando":
            return [
                {
                    "type": "data-revisando",
                    "id": f"rev-{evento['id']}",
                    "data": {"id": evento["id"], "estado": evento["estado"], "texto": evento["texto"]},
                }
            ]
        return []  # eventos internos desconocidos no se filtran a la UI

    def cerrar_texto(self) -> list[dict[str, Any]]:
        if self._texto_id is None:
            return []
        parte = {"type": "text-end", "id": self._texto_id}
        self._texto_id = None
        return [parte]

    def caso(self, case_id: str, etapa: str | None, traza_url: str | None) -> list[dict[str, Any]]:
        return [
            {
                "type": "data-caso",
                "id": "caso",
                "data": {"case_id": case_id, "etapa": etapa, "traza_url": traza_url},
            }
        ]

    def fin(self, motivo: str = "stop") -> list[dict[str, Any]]:
        return [*self.cerrar_texto(), {"type": "finish", "finishReason": motivo}]

    def error(self, texto: str) -> list[dict[str, Any]]:
        return [*self.cerrar_texto(), {"type": "error", "errorText": texto}]

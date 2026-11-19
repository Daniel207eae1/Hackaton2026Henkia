"""Doble determinista del proveedor LLM: pruebas sin red y demo sin claves (LLM_MODO=fake).

Se puede programar con respuestas y errores en cola para probar reintentos y fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from app.llm.puerto import ErrorLLM, FragmentoStream, Mensaje, RespuestaChat, Uso

RESPUESTA_POR_DEFECTO = (
    "Entiendo. Estoy en modo de prueba (sin modelo real configurado), así que solo puedo "
    "confirmar que recibí tu mensaje. Cuando el equipo configure los modelos, revisaré tu "
    "equipo antes de hacerte preguntas."
)


class AdaptadorFake:
    def __init__(self, retardo_s: float = 0.0):
        self.respuestas: deque[str | ErrorLLM] = deque()
        # Respuestas para llamadas con salida estructurada (response_format o tool forzada).
        self.estructuradas: deque[str | ErrorLLM] = deque()
        self.llamadas: list[dict[str, Any]] = []
        self.retardo_s = retardo_s

    def programar(self, *respuestas: str | ErrorLLM) -> None:
        self.respuestas.extend(respuestas)

    def programar_estructurado(self, *respuestas: str | ErrorLLM) -> None:
        self.estructuradas.extend(respuestas)

    def _siguiente_estructurada(self) -> str:
        if not self.estructuradas:
            raise ErrorLLM("fake: sin respuesta estructurada programada", reintentable=False)
        r = self.estructuradas.popleft()
        if isinstance(r, ErrorLLM):
            raise r
        return r

    def _siguiente(self) -> str:
        if not self.respuestas:
            return RESPUESTA_POR_DEFECTO
        r = self.respuestas.popleft()
        if isinstance(r, ErrorLLM):
            raise r
        return r

    async def chat(
        self,
        modelo: str,
        mensajes: list[Mensaje],
        parametros: dict[str, Any],
        *,
        response_format: dict[str, Any] | None = None,
        herramientas: list[dict[str, Any]] | None = None,
        herramienta_forzada: str | None = None,
    ) -> RespuestaChat:
        self.llamadas.append(
            {
                "modelo": modelo,
                "mensajes": mensajes,
                "response_format": response_format,
                "herramienta_forzada": herramienta_forzada,
            }
        )
        if response_format or herramienta_forzada:
            texto = self._siguiente_estructurada()
        elif self.estructuradas:
            texto = self._siguiente_estructurada()
        else:
            texto = self._siguiente()
        llamada = None
        if herramienta_forzada:
            llamada = {"nombre": herramienta_forzada, "argumentos": texto}
            texto = ""
        return RespuestaChat(
            texto=texto, uso=Uso(10, max(1, len(texto) // 4)), llamada_herramienta=llamada, modelo=modelo
        )

    async def chat_stream(
        self, modelo: str, mensajes: list[Mensaje], parametros: dict[str, Any]
    ) -> AsyncIterator[FragmentoStream]:
        self.llamadas.append({"modelo": modelo, "mensajes": mensajes, "stream": True})
        texto = self._siguiente()
        palabras = texto.split(" ")
        for i, palabra in enumerate(palabras):
            if self.retardo_s:
                await asyncio.sleep(self.retardo_s)
            yield FragmentoStream(delta=palabra if i == 0 else " " + palabra)
        yield FragmentoStream(uso=Uso(sum(len(str(m.contenido)) for m in mensajes) // 4, max(1, len(texto) // 4)))

    async def embeddings(self, modelo: str, textos: list[str], dimension: int | None) -> tuple[list[list[float]], Uso]:
        dim = dimension or 8
        vectores = []
        for t in textos:
            h = hashlib.sha256(t.encode()).digest()
            vectores.append([(h[i % len(h)] - 128) / 128 for i in range(dim)])
        return vectores, Uso(sum(len(t) for t in textos) // 4, 0)


def json_fake(obj: Any) -> str:
    """Ayuda para programar respuestas estructuradas en pruebas."""
    return json.dumps(obj, ensure_ascii=False)

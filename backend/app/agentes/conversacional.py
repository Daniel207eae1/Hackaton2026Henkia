"""Agente Conversacional (§3.3).

Herramientas: ninguna. Lee solo el estado del caso (mensajes del usuario y respuestas previas).
El modelo se pide por nombre lógico; nunca se nombra un proveedor ni un modelo aquí.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.agentes.prompts import prompt_embebido
from app.llm.puerto import Mensaje
from app.llm.registro import RegistroLLM
from app.observabilidad.langfuse import obtener_prompt

NOMBRE_PROMPT = "agente_conversacional"
# El caso completo (MAX_TURNOS_CASO=40 → 80 mensajes; < 10 k tokens). Con 12 olvidaba lo dicho al inicio.
MAX_MENSAJES_HISTORIAL = 80


class AgenteConversacional:
    def __init__(self, registro: RegistroLLM):
        self._cliente = registro.para("conversacional")

    async def responder(self, mensajes: list[dict[str, str]], *, contexto: str = "") -> AsyncIterator[str]:
        """`contexto`: resumen DETERMINISTA de lo ya consultado (lo arma el código, no un LLM)."""
        sistema, prompt_lf = obtener_prompt(NOMBRE_PROMPT, prompt_embebido(NOMBRE_PROMPT))
        if contexto:
            sistema = f"{sistema}\n\n{contexto}"
        historial = [
            Mensaje("user" if m["rol"] == "usuario" else "assistant", m["texto"])
            for m in mensajes[-MAX_MENSAJES_HISTORIAL:]
        ]
        async for delta in self._cliente.stream_texto([Mensaje("system", sistema), *historial], prompt=prompt_lf):
            yield delta

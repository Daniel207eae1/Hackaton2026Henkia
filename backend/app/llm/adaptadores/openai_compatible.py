"""Adaptador para cualquier API compatible con OpenAI (OpenRouter, Ollama /v1, …).

Usa httpx directamente: sin SDK de vendor. Traduce errores HTTP a `ErrorLLM` con la
información de reintento (429 → reintentable, respeta Retry-After).
"""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.config_modelos import ConfigProveedor
from app.llm.puerto import ErrorLLM, FragmentoStream, Mensaje, RespuestaChat, Uso

_REINTENTABLES = {408, 409, 425, 429, 500, 502, 503, 504}


def _mensajes(mensajes: list[Mensaje]) -> list[dict[str, Any]]:
    return [{"role": m.rol, "content": m.contenido} for m in mensajes]


def _uso(datos: dict[str, Any] | None) -> Uso:
    datos = datos or {}
    return Uso(
        tokens_entrada=int(datos.get("prompt_tokens") or 0),
        tokens_salida=int(datos.get("completion_tokens") or 0),
    )


def _error_http(resp: httpx.Response) -> ErrorLLM:
    espera = None
    if ra := resp.headers.get("retry-after"):
        try:
            espera = float(ra)
        except ValueError:
            espera = None
    cuerpo = resp.text[:300]
    diaria = resp.status_code == 429 and ("per-day" in cuerpo or "per day" in cuerpo.lower())
    return ErrorLLM(
        f"HTTP {resp.status_code}: {cuerpo}",
        reintentable=resp.status_code in _REINTENTABLES and not diaria,
        espera_s=espera,
        cuota_agotada=diaria,
    )


class AdaptadorOpenAICompatible:
    def __init__(self, config: ConfigProveedor, cliente: httpx.AsyncClient | None = None):
        self._config = config
        cabeceras = {"Content-Type": "application/json", **config.cabeceras}
        if config.api_key:
            cabeceras["Authorization"] = f"Bearer {config.api_key}"
        self._cliente = cliente or httpx.AsyncClient(
            base_url=config.base_url, headers=cabeceras, timeout=config.timeout_s
        )

    async def _post(self, ruta: str, cuerpo: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._cliente.post(ruta, json=cuerpo)
        except httpx.TimeoutException as exc:
            raise ErrorLLM(f"timeout: {exc}", reintentable=True) from exc
        except httpx.HTTPError as exc:
            raise ErrorLLM(f"error de red: {exc}", reintentable=True) from exc
        if resp.status_code >= 400:
            raise _error_http(resp)
        datos = resp.json()
        # OpenRouter puede responder 200 con {"error": {...}}.
        if isinstance(datos, dict) and datos.get("error"):
            codigo = int((datos["error"] or {}).get("code") or 500)
            raise ErrorLLM(str(datos["error"])[:300], reintentable=codigo in _REINTENTABLES)
        return datos

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
        cuerpo: dict[str, Any] = {"model": modelo, "messages": _mensajes(mensajes), **parametros}
        if response_format:
            cuerpo["response_format"] = response_format
        if herramientas:
            cuerpo["tools"] = herramientas
            if herramienta_forzada:
                cuerpo["tool_choice"] = {"type": "function", "function": {"name": herramienta_forzada}}
        datos = await self._post("/chat/completions", cuerpo)
        try:
            msg = datos["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ErrorLLM(f"respuesta sin choices: {str(datos)[:200]}", reintentable=True) from exc
        llamada = None
        if msg.get("tool_calls"):
            fn = msg["tool_calls"][0]["function"]
            llamada = {"nombre": fn.get("name", ""), "argumentos": fn.get("arguments", "")}
        return RespuestaChat(
            texto=msg.get("content") or "",
            uso=_uso(datos.get("usage")),
            llamada_herramienta=llamada,
            modelo=datos.get("model", modelo),
        )

    async def chat_stream(
        self, modelo: str, mensajes: list[Mensaje], parametros: dict[str, Any]
    ) -> AsyncIterator[FragmentoStream]:
        cuerpo = {
            "model": modelo,
            "messages": _mensajes(mensajes),
            "stream": True,
            "stream_options": {"include_usage": True},
            **parametros,
        }
        try:
            async with self._cliente.stream("POST", "/chat/completions", json=cuerpo) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise _error_http(resp)
                async for linea in resp.aiter_lines():
                    if not linea.startswith("data:"):
                        continue  # comentarios SSE (": OPENROUTER PROCESSING") y líneas vacías
                    carga = linea[5:].strip()
                    if carga == "[DONE]":
                        break
                    try:
                        datos = json.loads(carga)
                    except json.JSONDecodeError:
                        continue
                    if datos.get("error"):
                        raise ErrorLLM(str(datos["error"])[:300], reintentable=True)
                    delta = ""
                    if datos.get("choices"):
                        delta = (datos["choices"][0].get("delta") or {}).get("content") or ""
                    uso = _uso(datos["usage"]) if datos.get("usage") else None
                    if delta or uso:
                        yield FragmentoStream(delta=delta, uso=uso)
        except httpx.TimeoutException as exc:
            raise ErrorLLM(f"timeout: {exc}", reintentable=True) from exc
        except httpx.HTTPError as exc:
            raise ErrorLLM(f"error de red: {exc}", reintentable=True) from exc

    async def embeddings(self, modelo: str, textos: list[str], dimension: int | None) -> tuple[list[list[float]], Uso]:
        cuerpo: dict[str, Any] = {"model": modelo, "input": textos}
        if dimension:
            cuerpo["dimensions"] = dimension
        datos = await self._post("/embeddings", cuerpo)
        vectores = [d["embedding"] for d in sorted(datos["data"], key=lambda d: d["index"])]
        if dimension:
            vectores = [_recortar_mrl(v, dimension) for v in vectores]
        return vectores, _uso(datos.get("usage"))


def _recortar_mrl(vector: list[float], dimension: int) -> list[float]:
    """Si el proveedor ignora `dimensions`, recorta (MRL) y renormaliza."""
    if len(vector) <= dimension:
        return vector
    v = vector[:dimension]
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]

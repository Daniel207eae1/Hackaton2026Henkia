"""Cliente MCP (Streamable HTTP, protocolo 2025-06-18) para el servidor `zabbix-ofimatica`.

Transporte puro: initialize → Mcp-Session-Id → notifications/initialized → tools/call.
NO decide nada: quién puede llamar qué lo controla `puerta.py`. Ningún otro módulo debe usar
este cliente directamente.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

PROTOCOLO = "2025-06-18"
_ACEPTA = "application/json, text/event-stream"


class ErrorMCP(Exception):
    """Fallo de transporte o de protocolo con el servidor MCP (no un `ok: false` de la tool)."""


def _extraer_jsonrpc(resp: httpx.Response, id_esperado: int) -> dict[str, Any]:
    tipo = resp.headers.get("content-type", "")
    if "text/event-stream" in tipo:
        for linea in resp.text.splitlines():
            if not linea.startswith("data:"):
                continue
            try:
                msg = json.loads(linea[5:].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == id_esperado:
                return msg
        raise ErrorMCP("respuesta SSE sin mensaje para la petición")
    try:
        return resp.json()
    except ValueError as exc:
        raise ErrorMCP(f"respuesta no JSON: {resp.text[:200]}") from exc


def _contenido_tool(resultado: dict[str, Any]) -> dict[str, Any]:
    """Prefiere structuredContent; si no, el JSON del primer bloque de texto."""
    if isinstance(resultado.get("structuredContent"), dict):
        return resultado["structuredContent"]
    for bloque in resultado.get("content") or []:
        if bloque.get("type") == "text":
            try:
                datos = json.loads(bloque.get("text", ""))
            except json.JSONDecodeError:
                return {
                    "ok": False,
                    "error": "respuesta de la tool no es JSON",
                    "texto": bloque["text"][:500],
                }
            return datos if isinstance(datos, dict) else {"ok": True, "resultado": datos}
    return {"ok": False, "error": "respuesta de la tool vacía"}


class ClienteMCP:
    def __init__(
        self,
        url: str,
        *,
        token: str = "",
        timeout_s: float = 75.0,
        cliente: httpx.AsyncClient | None = None,
    ):
        cabeceras = {"Content-Type": "application/json", "Accept": _ACEPTA}
        if token:
            cabeceras["Authorization"] = f"Bearer {token}"
        self._url = url
        self._http = cliente or httpx.AsyncClient(headers=cabeceras, timeout=timeout_s)
        if cliente is not None:
            self._http.headers.update(cabeceras)
        self._sesion: str | None = None
        self._ids = itertools.count(1)
        self._candado = asyncio.Lock()
        self.info_servidor: dict[str, Any] = {}

    async def cerrar(self) -> None:
        await self._http.aclose()

    def _cabeceras_sesion(self) -> dict[str, str]:
        return {"Mcp-Session-Id": self._sesion, "MCP-Protocol-Version": PROTOCOLO} if self._sesion else {}

    async def _post(self, cuerpo: dict[str, Any]) -> httpx.Response:
        try:
            return await self._http.post(self._url, json=cuerpo, headers=self._cabeceras_sesion())
        except httpx.TimeoutException as exc:
            raise ErrorMCP("tiempo de espera agotado con el servidor MCP") from exc
        except httpx.HTTPError as exc:
            raise ErrorMCP(f"servidor MCP no disponible: {exc.__class__.__name__}") from exc

    async def _inicializar(self) -> None:
        async with self._candado:
            if self._sesion:
                return
            id_ = next(self._ids)
            resp = await self._post(
                {
                    "jsonrpc": "2.0",
                    "id": id_,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOLO,
                        "capabilities": {},
                        "clientInfo": {"name": "caso5-backend", "version": "0.1.0"},
                    },
                }
            )
            if resp.status_code >= 400:
                raise ErrorMCP(f"initialize HTTP {resp.status_code}")
            msg = _extraer_jsonrpc(resp, id_)
            if "error" in msg:
                raise ErrorMCP(f"initialize rechazado: {msg['error']}")
            self.info_servidor = (msg.get("result") or {}).get("serverInfo", {})
            self._sesion = resp.headers.get("mcp-session-id")
            await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def _rpc(self, metodo: str, params: dict[str, Any], *, reintento: bool = True) -> dict[str, Any]:
        await self._inicializar()
        id_ = next(self._ids)
        resp = await self._post({"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params})
        if resp.status_code == 404 and reintento:
            # Sesión vencida en el servidor: se reinicia una vez.
            self._sesion = None
            return await self._rpc(metodo, params, reintento=False)
        if resp.status_code >= 400:
            raise ErrorMCP(f"{metodo} HTTP {resp.status_code}")
        msg = _extraer_jsonrpc(resp, id_)
        if "error" in msg:
            raise ErrorMCP(f"{metodo}: {msg['error'].get('message', msg['error'])}")
        return msg.get("result") or {}

    async def listar_tools(self) -> list[dict[str, Any]]:
        return (await self._rpc("tools/list", {})).get("tools", [])

    async def llamar_tool(self, nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]:
        resultado = await self._rpc("tools/call", {"name": nombre, "arguments": argumentos})
        datos = _contenido_tool(resultado)
        if resultado.get("isError") and datos.get("ok") is not False:
            datos = {**datos, "ok": False}
        return datos

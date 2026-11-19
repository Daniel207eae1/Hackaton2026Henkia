"""Transporte MCP Streamable HTTP (respx, sin red)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.integraciones.zabbix.mcp_cliente import ClienteMCP, ErrorMCP

URL = "http://mcp.test/mcp"


def _sse(obj: dict) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(obj)}\n\n",
    )


def _servidor(tool_texto: dict, *, sesiones: list[str], is_error: bool = False):
    def manejar(request: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(request.content)
        metodo = cuerpo.get("method")
        if metodo == "initialize":
            sid = f"s{len(sesiones) + 1}"
            sesiones.append(sid)
            r = _sse(
                {
                    "jsonrpc": "2.0",
                    "id": cuerpo["id"],
                    "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "zabbix-ofimatica"}},
                }
            )
            r.headers["mcp-session-id"] = sid
            return r
        if metodo == "notifications/initialized":
            return httpx.Response(202)
        if request.headers.get("mcp-session-id") != sesiones[-1]:
            return httpx.Response(404)
        assert request.headers["mcp-protocol-version"] == "2025-06-18"
        return _sse(
            {
                "jsonrpc": "2.0",
                "id": cuerpo["id"],
                "result": {
                    "content": [{"type": "text", "text": json.dumps(tool_texto)}],
                    "isError": is_error,
                },
            }
        )

    return manejar


@respx.mock
async def test_inicializa_y_llama_tool():
    sesiones: list[str] = []
    respx.post(URL).mock(side_effect=_servidor({"ok": True, "resultado": "16.0"}, sesiones=sesiones))
    c = ClienteMCP(URL)
    datos = await c.llamar_tool("version_office", {"equipo": "DESKTOP-1"})
    assert datos == {"ok": True, "resultado": "16.0"}
    assert c.info_servidor["name"] == "zabbix-ofimatica"
    metodos = [json.loads(ll.request.content).get("method") for ll in respx.calls]
    assert metodos == ["initialize", "notifications/initialized", "tools/call"]
    await c.cerrar()


@respx.mock
async def test_reinicia_sesion_vencida():
    sesiones: list[str] = []
    respx.post(URL).mock(side_effect=_servidor({"ok": True}, sesiones=sesiones))
    c = ClienteMCP(URL)
    await c.llamar_tool("listar_equipos", {})
    sesiones.append("nueva-del-servidor")  # el servidor olvidó la sesión anterior
    assert (await c.llamar_tool("listar_equipos", {}))["ok"] is True
    await c.cerrar()


@respx.mock
async def test_is_error_se_reporta_como_ok_false():
    respx.post(URL).mock(side_effect=_servidor({"error": "sin-sesion-usuario"}, sesiones=[], is_error=True))
    datos = await ClienteMCP(URL).llamar_tool("estado_onedrive", {"equipo": "X"})
    assert datos["ok"] is False and datos["error"] == "sin-sesion-usuario"


@respx.mock
async def test_servidor_caido():
    respx.post(URL).mock(side_effect=httpx.ConnectError("caído"))
    with pytest.raises(ErrorMCP, match="no disponible"):
        await ClienteMCP(URL).llamar_tool("listar_equipos", {})


@respx.mock
async def test_token_opcional_en_authorization():
    sesiones: list[str] = []
    ruta = respx.post(URL).mock(side_effect=_servidor({"ok": True}, sesiones=sesiones))
    await ClienteMCP(URL, token="tkn").llamar_tool("listar_equipos", {})
    assert ruta.calls[0].request.headers["authorization"] == "Bearer tkn"

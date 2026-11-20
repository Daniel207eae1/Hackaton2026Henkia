"""Cliente de la API REST N2 del servidor MCP `zabbix-ofimatica` (aprobaciones de segundo nivel, ADR 0022).

- La clave `N2_API_KEY` vive solo aquí (encabezado `X-N2-Key`): nunca va al navegador, a los logs, a una respuesta
  ni a un prompt. Los errores se describen sin ella.
- Este cliente NO decide nada por su cuenta: `decidir` solo lo llama el endpoint que dispara un técnico N2
  autenticado (nunca el sondeo, una regla, un script ni la IA).
- 5xx o caída de red: reintento con espera exponencial. Un POST reintentado que recibe 409 se resuelve
  releyendo la solicitud: si quedó con la decisión de este mismo técnico, el primer intento sí llegó.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

ID_APROBACION = re.compile(r"AP-[A-Za-z0-9]{4,32}")
REINTENTOS = 3
ESPERA_BASE_S = 0.5


class ErrorN2(Exception):
    """tipo: no_configurado | no_autorizado | no_existe | conflicto | servidor | red | invalido."""

    def __init__(self, tipo: str, detalle: str = ""):
        super().__init__(f"{tipo}: {detalle}")
        self.tipo = tipo
        self.detalle = detalle


@dataclass
class ClienteN2:
    url: str
    clave: str
    timeout_s: float = 15.0
    transporte: httpx.AsyncBaseTransport | None = None  # pruebas: httpx.MockTransport
    dormir: Any = asyncio.sleep
    intentos: int = 0  # intentos del último pedido (para saber si un 409 vino de un reintento propio)

    def __repr__(self) -> str:  # nunca la clave
        return f"ClienteN2(url={self.url!r})"

    @property
    def configurado(self) -> bool:
        return bool(self.url and self.clave)

    async def _pedir(self, metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None) -> Any:
        if not self.configurado:
            raise ErrorN2("no_configurado", "faltan N2_URL o N2_API_KEY")
        ultimo: ErrorN2 | None = None
        for intento in range(REINTENTOS):
            self.intentos = intento + 1
            try:
                async with httpx.AsyncClient(
                    base_url=self.url.rstrip("/"), timeout=self.timeout_s, transport=self.transporte
                ) as c:
                    r = await c.request(metodo, ruta, json=cuerpo, headers={"X-N2-Key": self.clave})
            except httpx.HTTPError as err:
                ultimo = ErrorN2("red", type(err).__name__)
            else:
                if r.status_code == 401:
                    log.error("API N2: clave rechazada (401). Revisa N2_API_KEY en el servidor.")
                    raise ErrorN2("no_autorizado", "la API N2 rechazó la clave del servidor")
                if r.status_code == 404:
                    raise ErrorN2("no_existe", "la solicitud no existe")
                if r.status_code == 409:
                    raise ErrorN2("conflicto", _error(r))
                if r.status_code >= 500:
                    ultimo = ErrorN2("servidor", f"HTTP {r.status_code}")
                elif r.status_code >= 400:
                    raise ErrorN2("invalido", f"HTTP {r.status_code}: {_error(r)}")
                else:
                    return r.json()
            if intento < REINTENTOS - 1:
                await self.dormir(ESPERA_BASE_S * 2**intento)
        raise ultimo or ErrorN2("red", "sin respuesta")

    # ------------------------------------------------------------------ lectura
    async def listar(self) -> list[dict[str, Any]]:
        datos = await self._pedir("GET", "/n2/aprobaciones")
        return [a for a in datos if isinstance(a, dict) and ID_APROBACION.fullmatch(str(a.get("id", "")))]

    async def obtener(self, aprobacion_id: str) -> dict[str, Any] | None:
        return next((a for a in await self.listar() if a["id"] == aprobacion_id), None)

    async def consentimientos(self) -> list[dict[str, Any]]:
        datos = await self._pedir("GET", "/n2/consentimientos")
        return [c for c in datos if isinstance(c, dict)] if isinstance(datos, list) else []

    async def auditoria(self) -> list[dict[str, Any]]:
        datos = await self._pedir("GET", "/auditoria")
        if isinstance(datos, dict):
            datos = datos.get("eventos") or datos.get("auditoria") or []
        return [e for e in datos if isinstance(e, dict)] if isinstance(datos, list) else []

    # ------------------------------------------------------------------ decisión (solo la dispara un humano)
    async def decidir(self, aprobacion_id: str, aprobar: bool, tecnico: str, nota: str) -> dict[str, Any]:
        if not ID_APROBACION.fullmatch(aprobacion_id):
            raise ErrorN2("invalido", "id de aprobación inválido")
        accion = "aprobar" if aprobar else "rechazar"
        esperado = "aprobada" if aprobar else "rechazada"
        try:
            return await self._pedir(
                "POST", f"/n2/aprobaciones/{aprobacion_id}/{accion}", {"tecnico": tecnico, "nota": nota}
            )
        except ErrorN2 as err:
            reintentado = self.intentos > 1
            if err.tipo == "conflicto" and not reintentado:
                raise  # otro técnico (o el mismo en otra pestaña) ya había decidido
            if err.tipo not in ("conflicto", "red", "servidor"):
                raise
            # Pudo quedar aplicada aunque no llegó la respuesta: se lee el estado final antes de responder.
            try:
                actual = await self.obtener(aprobacion_id)
            except ErrorN2:
                raise ErrorN2("incierto", "no pude confirmar si la decisión quedó registrada") from err
            if actual and actual.get("estado") == esperado and actual.get("tecnico_n2") == tecnico:
                return actual
            if err.tipo == "conflicto" or (actual and actual.get("estado") != "pendiente"):
                raise ErrorN2("conflicto", err.detalle) from err
            raise


def _error(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", ""))[:200]
    except ValueError:
        return ""

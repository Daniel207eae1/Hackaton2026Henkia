"""Puerta de políticas hacia el MCP `zabbix-ofimatica` (ADR 0007).

Único punto del backend que llama tools de Zabbix. Defensa en profundidad sobre el servidor:
aunque el servidor también valida, aquí se garantiza que:

- Solo se llaman tools de la lista blanca; `ejecutar_comando_generico` nunca.
- Un `consentimiento_id` solo se usa si ESTE backend lo solicitó para la misma tool, equipo y
  caso, si el servidor lo reportó `aprobado`, si no venció y si no se usó antes (un solo uso;
  se marca usado ANTES de ejecutar). Nunca se inventa ni se reutiliza.
- Las tools `aprobacion_n2` exigen además un `aprobacion_id` aprobado por N2 para la misma
  tool, equipo y caso; y el consentimiento solo se pide DESPUÉS de esa aprobación.
- Cada llamada es un *span* `zabbix.<tool>` en Langfuse; las denegaciones, un evento.
- El resultado de `leer_logs_aplicacion` se marca como texto no confiable (→ extractor, F3).

El LLM nunca llama esta puerta: la llama el orquestador (código).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, NoReturn, Protocol

from app.integraciones.zabbix.catalogo_mcp import (
    BLOQUEADAS,
    SALIDA_NO_CONFIABLE,
    TOOLS,
    VIGENCIA_CONSENTIMIENTO_S,
    PoliticaMCP,
)
from app.integraciones.zabbix.mcp_cliente import ErrorMCP
from app.observabilidad.langfuse import evento, observacion

_EQUIPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_CASO = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ID_CONSENTIMIENTO = re.compile(r"^CS-[A-Za-z0-9]{4,32}$")
_ID_APROBACION = re.compile(r"^AP-[A-Za-z0-9]{4,32}$")


class ClienteTools(Protocol):
    async def llamar_tool(self, nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]: ...


class AccionDenegada(Exception):
    """La puerta rechazó la llamada sin contactar al MCP."""


@dataclass
class ResultadoTool:
    tool: str
    ok: bool
    datos: dict[str, Any]
    motivo: str | None = None
    no_confiable: bool = False  # True: solo puede leerlo el extractor en cuarentena


@dataclass
class Autorizacion:
    id: str
    tipo: str  # consentimiento | aprobacion
    tool: str
    equipo: str
    caso_id: str
    estado: str = "pendiente"
    creada: float = field(default_factory=time.monotonic)
    aprobada_en: float | None = None
    usada: bool = False


def _motivo(datos: dict[str, Any]) -> str:
    for clave in ("motivo", "error", "error_script", "indicacion", "bloqueada"):
        if datos.get(clave):
            return str(datos[clave])[:300]
    return "la tool respondió ok=false"


class PuertaZabbix:
    def __init__(self, cliente: ClienteTools | None, *, reloj=time.monotonic):
        self._cliente = cliente
        self._reloj = reloj
        # Registro en memoria de autorizaciones emitidas por este backend.
        # TODO(F4): persistir en `operacion` (tokens de consentimiento / aprobaciones N2).
        self._autorizaciones: dict[str, Autorizacion] = {}

    @property
    def disponible(self) -> bool:
        return self._cliente is not None

    # ------------------------------------------------------------------ núcleo
    async def _llamar(self, tool: str, argumentos: dict[str, Any], *, caso_id: str | None = None) -> ResultadoTool:
        if tool in BLOQUEADAS or tool not in TOOLS:
            self._denegar(tool, "tool fuera de la lista blanca", caso_id)
        if self._cliente is None:
            return ResultadoTool(tool, False, {}, "integración con Zabbix no configurada (ZABBIX_MCP_URL)")
        with observacion(
            f"zabbix.{tool}", tipo="tool", input=argumentos, metadata={"politica": TOOLS[tool].value}
        ) as obs:
            try:
                datos = await self._cliente.llamar_tool(tool, argumentos)
            except ErrorMCP as err:
                obs.update(level="ERROR", status_message=str(err))
                return ResultadoTool(tool, False, {}, str(err))
            ok = datos.get("ok") is True
            resultado = ResultadoTool(
                tool, ok, datos, None if ok else _motivo(datos), no_confiable=tool in SALIDA_NO_CONFIABLE
            )
            obs.update(
                output={"ok": ok, "motivo": resultado.motivo} if resultado.no_confiable else datos,
                level=None if ok else "WARNING",
            )
            return resultado

    def _denegar(self, tool: str, motivo: str, caso_id: str | None) -> NoReturn:
        evento(
            "politica.decision",
            metadata={"tool": tool, "decision": "denegada", "motivo": motivo, "caso_id": caso_id or ""},
        )
        raise AccionDenegada(f"{tool}: {motivo}")

    @staticmethod
    def _validar(equipo: str, caso_id: str) -> None:
        if not _EQUIPO.match(equipo):
            raise AccionDenegada("equipo con formato inválido")
        if not _CASO.match(caso_id):
            raise AccionDenegada("caso_id con formato inválido")

    async def verificar_catalogo(self) -> dict[str, Any]:
        """Compara la lista blanca con las tools que ofrece el servidor (para /api/salud/zabbix)."""
        if self._cliente is None or not hasattr(self._cliente, "listar_tools"):
            return {"configurado": False}
        try:
            remotas = {t["name"] for t in await self._cliente.listar_tools()}
        except ErrorMCP as err:
            return {"configurado": True, "disponible": False, "error": str(err)}
        return {
            "configurado": True,
            "disponible": True,
            "faltan_en_servidor": sorted(set(TOOLS) - remotas),
            "ofrecidas_no_permitidas": sorted(remotas - set(TOOLS)),
        }

    # ---------------------------------------------------------- descubrimiento
    async def listar_equipos(self) -> ResultadoTool:
        return await self._llamar("listar_equipos", {})

    async def problemas_activos(self, equipo: str = "") -> ResultadoTool:
        if equipo and not _EQUIPO.match(equipo):
            raise AccionDenegada("equipo con formato inválido")
        return await self._llamar("problemas_activos", {"equipo": equipo} if equipo else {})

    async def estado_servicio(self) -> ResultadoTool:
        return await self._llamar("estado_servicio", {})

    async def catalogo_acciones(self) -> ResultadoTool:
        return await self._llamar("catalogo_acciones", {})

    # ----------------------------------------------------------- solo lectura
    async def leer(self, tool: str, equipo: str, caso_id: str) -> ResultadoTool:
        if TOOLS.get(tool) is not PoliticaMCP.AUTOMATICA:
            self._denegar(tool, "no es una tool de solo lectura", caso_id)
        self._validar(equipo, caso_id)
        return await self._llamar(tool, {"equipo": equipo, "caso_id": caso_id}, caso_id=caso_id)

    # ---------------------------------------------------------- autorizaciones
    def _aprobacion_vigente(self, tool: str, equipo: str, caso_id: str) -> Autorizacion | None:
        for a in self._autorizaciones.values():
            if (a.tipo, a.tool, a.equipo, a.caso_id, a.estado) == (
                "aprobacion",
                tool,
                equipo,
                caso_id,
                "aprobada",
            ):
                return a
        return None

    async def solicitar_aprobacion_n2(self, tool: str, equipo: str, caso_id: str, diagnostico: str) -> ResultadoTool:
        """`diagnostico` lo arma el código desde el estado del caso (síntoma, evidencia, motivo)."""
        if TOOLS.get(tool) is not PoliticaMCP.APROBACION_N2:
            self._denegar(tool, "no requiere aprobación N2 o no está permitida", caso_id)
        self._validar(equipo, caso_id)
        r = await self._llamar(
            "solicitar_aprobacion_n2",
            {
                "tool": tool,
                "equipo": equipo,
                "caso_id": caso_id,
                "diagnostico": diagnostico[:2000],
            },
            caso_id=caso_id,
        )
        if r.ok:
            id_ = str(r.datos.get("id", ""))
            if not _ID_APROBACION.match(id_):
                return ResultadoTool(r.tool, False, r.datos, "el servidor devolvió un id de aprobación inválido")
            self._autorizaciones[id_] = Autorizacion(id_, "aprobacion", tool, equipo, caso_id)
            evento("aprobacion_n2.solicitada", metadata={"id": id_, "tool": tool, "caso_id": caso_id})
        return r

    async def consultar_aprobacion(self, aprobacion_id: str) -> ResultadoTool:
        a = self._autorizaciones.get(aprobacion_id)
        if a is None or a.tipo != "aprobacion":
            self._denegar("consultar_aprobacion", "aprobación no emitida por este backend", None)
        r = await self._llamar("consultar_aprobacion", {"aprobacion_id": aprobacion_id}, caso_id=a.caso_id)
        if r.ok and r.datos.get("estado"):
            a.estado = str(r.datos["estado"])
            evento(f"aprobacion_n2.{a.estado}", metadata={"id": a.id, "tool": a.tool, "caso_id": a.caso_id})
        return r

    async def solicitar_consentimiento(self, tool: str, equipo: str, caso_id: str) -> ResultadoTool:
        """Abre la ventana «Soporte TI» en el equipo del usuario (el texto lo define el servidor)."""
        politica = TOOLS.get(tool)
        if politica not in (PoliticaMCP.CONSENTIMIENTO, PoliticaMCP.APROBACION_N2) or tool in BLOQUEADAS:
            self._denegar(tool, "la tool no es una acción permitida", caso_id)
        self._validar(equipo, caso_id)
        if politica is PoliticaMCP.APROBACION_N2 and not self._aprobacion_vigente(tool, equipo, caso_id):
            self._denegar(tool, "falta la aprobación de N2 antes de pedir el consentimiento", caso_id)
        r = await self._llamar(
            "solicitar_consentimiento", {"tool": tool, "equipo": equipo, "caso_id": caso_id}, caso_id=caso_id
        )
        if r.ok:
            id_ = str(r.datos.get("id", ""))
            if not _ID_CONSENTIMIENTO.match(id_):
                return ResultadoTool(r.tool, False, r.datos, "el servidor devolvió un id de consentimiento inválido")
            self._autorizaciones[id_] = Autorizacion(id_, "consentimiento", tool, equipo, caso_id)
            evento(
                "consentimiento.token",
                metadata={"id": id_, "accion": "solicitado", "tool": tool, "caso_id": caso_id},
            )
        return r

    async def consultar_consentimiento(self, consentimiento_id: str, espera_s: int = 30) -> ResultadoTool:
        a = self._autorizaciones.get(consentimiento_id)
        if a is None or a.tipo != "consentimiento":
            self._denegar("consultar_consentimiento", "consentimiento no emitido por este backend", None)
        espera = max(0, min(int(espera_s), 50))
        r = await self._llamar(
            "consultar_consentimiento",
            {"consentimiento_id": consentimiento_id, "espera_s": espera},
            caso_id=a.caso_id,
        )
        if r.ok and r.datos.get("estado"):
            nuevo = str(r.datos["estado"])
            if nuevo == "aprobado" and a.estado != "aprobado":
                a.aprobada_en = self._reloj()
            a.estado = nuevo
            evento(
                "consentimiento.token",
                metadata={"id": a.id, "accion": nuevo, "tool": a.tool, "caso_id": a.caso_id},
            )
        return r

    # ---------------------------------------------------------------- acciones
    async def ejecutar_accion(
        self,
        tool: str,
        equipo: str,
        caso_id: str,
        consentimiento_id: str,
        aprobacion_id: str | None = None,
    ) -> ResultadoTool:
        politica = TOOLS.get(tool)
        if politica not in (PoliticaMCP.CONSENTIMIENTO, PoliticaMCP.APROBACION_N2) or tool in BLOQUEADAS:
            self._denegar(tool, "la tool no es una acción permitida", caso_id)
        self._validar(equipo, caso_id)

        c = self._autorizaciones.get(consentimiento_id)
        if c is None or c.tipo != "consentimiento":
            self._denegar(tool, "consentimiento inexistente o no emitido por este backend", caso_id)
        if (c.tool, c.equipo, c.caso_id) != (tool, equipo, caso_id):
            self._denegar(tool, "el consentimiento es de otra acción, otro equipo u otro caso", caso_id)
        if c.usada:
            self._denegar(tool, "el consentimiento ya se usó (un solo uso)", caso_id)
        if c.estado != "aprobado" or c.aprobada_en is None:
            self._denegar(tool, f"el consentimiento no está aprobado (estado: {c.estado})", caso_id)
        if self._reloj() - c.aprobada_en > VIGENCIA_CONSENTIMIENTO_S:
            self._denegar(tool, "el consentimiento venció", caso_id)

        argumentos: dict[str, Any] = {
            "equipo": equipo,
            "consentimiento_id": consentimiento_id,
            "caso_id": caso_id,
        }
        if politica is PoliticaMCP.APROBACION_N2:
            a = self._autorizaciones.get(aprobacion_id or "")
            if a is None or a.tipo != "aprobacion" or (a.tool, a.equipo, a.caso_id) != (tool, equipo, caso_id):
                self._denegar(tool, "falta una aprobación N2 válida para esta acción", caso_id)
            if a.estado != "aprobada":
                self._denegar(tool, f"la aprobación N2 no está aprobada (estado: {a.estado})", caso_id)
            argumentos["aprobacion_id"] = a.id

        c.usada = True  # se consume ANTES de ejecutar: un fallo no habilita un segundo intento
        evento(
            "consentimiento.token",
            metadata={"id": c.id, "accion": "consumido", "tool": tool, "caso_id": caso_id},
        )
        return await self._llamar(tool, argumentos, caso_id=caso_id)

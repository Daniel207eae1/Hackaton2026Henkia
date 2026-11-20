"""Nodos del flujo de acción (F4, §3.5–3.7 + ADR 0007).

Decision → [AprobacionN2] → Consentimiento → Ejecucion → Verificacion

- El LLM (Interprete) solo propone un id de un enum cerrado; `decision` lo filtra en código.
- Los textos que ve el usuario sobre la acción salen del catálogo (plantillas, sin LLM): así nunca
  se promete algo que no pasó ni se dice "listo" si la tool respondió `ok: false`.
- Consentimiento real = ventana "Soporte TI" en el equipo; un "sí" en el chat no cuenta: el estado
  sale SIEMPRE de `consultar_consentimiento` en el servidor.
- Las esperas (consentimiento pendiente, aprobación N2) se guardan en el estado del caso
  (checkpointer) y se retoman en el siguiente turno; la consulta la hace el backend.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.config import get_stream_writer

from app.agentes.contexto import resumen_para_conversacional
from app.agentes.interprete import NINGUNA
from app.integraciones.zabbix.puerta import AccionDenegada, PuertaZabbix
from app.observabilidad.langfuse import evento, observacion, score_traza
from app.orquestador.estado import EstadoCaso, Etapa
from app.politicas.catalogo import Accion, catalogo, texto_ans

TOOL_LOGS = "leer_logs_aplicacion"

# Lectura que verifica cada acción después de ejecutarla (None = solo confirmación del usuario).
VERIFICACION: dict[str, str | None] = {
    "limpiar_cache_teams": None,
    "reiniciar_cola_impresion": "estado_cola_impresion",
    "resincronizar_onedrive": "estado_onedrive",
    "reparacion_rapida_office": "version_office",
    "recrear_perfil_outlook": None,
    "asignar_licencia_office": "estado_licencia_office",
}

ESTADOS_ESPERA = {"esperando_n2", "esperando_consentimiento"}


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hito(etapa: Etapa, detalle: str) -> dict[str, Any]:
    return {"hora": _ahora(), "etapa": etapa.value, "detalle": detalle}


def _tarjeta(accion: dict[str, Any], mensaje: str) -> dict[str, Any]:
    """Datos de la tarjeta de la UI: textos SOLO del catálogo + estado decidido por el código."""
    c: Accion = catalogo().por_tool(accion["tool"])
    return {
        "tipo": "accion",
        "datos": {
            "id": f"accion-{accion['n']}",
            "tool": accion["tool"],
            "nombre": c.nombre,
            "descripcion": c.descripcion,
            "aviso": c.aviso_obligatorio,
            "reversion": c.reversion,
            "riesgo": c.riesgo,
            "politica": c.politica,
            "estado": accion["estado"],
            "mensaje": mensaje,
        },
    }


class FlujoAccion:
    def __init__(
        self,
        puerta: PuertaZabbix,
        *,
        espera_max_consentimiento_s: int = 150,
        espera_por_consulta_s: int = 25,
        extractor: Any = None,
    ):
        self.puerta = puerta
        self.extractor = extractor  # ExtractorCuarentena: único que lee la salida de leer_logs
        self.rondas = max(1, math.ceil(espera_max_consentimiento_s / max(1, espera_por_consulta_s)))
        self.espera = espera_por_consulta_s

    # ------------------------------------------------------------------ util
    @staticmethod
    def _emitir(escribir: Callable[[dict], None], accion: dict[str, Any], mensaje: str) -> None:
        escribir(_tarjeta(accion, mensaje))

    @staticmethod
    def _decir(escribir: Callable[[dict], None], texto: str) -> dict[str, Any]:
        escribir({"tipo": "texto", "texto": texto})
        return {"rol": "sistema", "texto": texto, "hora": _ahora()}

    @staticmethod
    def _cerrar(estado: EstadoCaso, accion: dict[str, Any]) -> dict[str, Any]:
        """Saca la acción en curso y la deja en el historial."""
        historial = [*(estado.get("acciones") or []), {**accion, "cerrada": _ahora()}]
        return {"accion_actual": None, "acciones": historial}

    # ---------------------------------------------------------------- routing
    @staticmethod
    def hay_espera(estado: EstadoCaso) -> str | None:
        a = estado.get("accion_actual") or {}
        if a.get("estado") == "esperando_n2":
            return Etapa.APROBACION_N2.value
        if a.get("estado") == "esperando_consentimiento":
            return Etapa.CONSENTIMIENTO.value
        return None

    @staticmethod
    def tras_decision(estado: EstadoCaso) -> str:
        a = estado.get("accion_actual")
        if not a:
            return Etapa.ACLARACION.value
        return Etapa.APROBACION_N2.value if a["politica"] == "aprobacion_n2" else Etapa.CONSENTIMIENTO.value

    @staticmethod
    def tras_aprobacion(estado: EstadoCaso) -> str:
        a = estado.get("accion_actual") or {}
        return Etapa.CONSENTIMIENTO.value if a.get("estado") == "aprobada_n2" else "fin"

    @staticmethod
    def tras_consentimiento(estado: EstadoCaso) -> str:
        a = estado.get("accion_actual") or {}
        return Etapa.EJECUCION.value if a.get("estado") == "autorizada" else "fin"

    @staticmethod
    def tras_ejecucion(estado: EstadoCaso) -> str:
        ultima = (estado.get("acciones") or [{}])[-1]
        if not estado.get("accion_actual") and ultima.get("tool") == TOOL_LOGS:
            return Etapa.HIPOTESIS.value  # la evidencia de los logs vuelve al diagnóstico (no se «verifica»)
        a = estado.get("accion_actual") or {}
        return Etapa.VERIFICACION.value if a.get("estado") == "ejecutada" else "fin"

    @staticmethod
    def nueva_accion(estado: EstadoCaso, tool: str, motivo: str) -> dict[str, Any]:
        c = catalogo().por_tool(tool)
        return {
            "n": len(estado.get("acciones") or []) + 1,
            "id": c.id,
            "tool": c.tool_mcp,
            "politica": c.politica,
            "riesgo": c.riesgo,
            "estado": "propuesta",
            "motivo": motivo[:300],
            "consentimiento_id": None,
            "aprobacion_id": None,
            "propuesta_en": _ahora(),
        }

    # ------------------------------------------------------------------ nodos
    async def decision(self, estado: EstadoCaso) -> dict[str, Any]:
        """100 % código: filtra la acción candidata del intérprete (enum) con las reglas del caso."""
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.DECISION.value})
        cand = estado.get("accion_candidata") or {}
        tool = cand.get("accion") or NINGUNA
        motivo_descarte = None
        if tool == NINGUNA:
            motivo_descarte = "sin acción candidata"
        elif not estado.get("equipo_zabbix") or not self.puerta.disponible:
            motivo_descarte = "sin equipo en Zabbix"
        elif (estado.get("masivo") or {}).get("estado") in ("posible_masivo", "masivo_confirmado"):
            motivo_descarte = "posible incidente masivo: sin pasos individuales"
        elif (estado.get("sintoma") or {}).get("fuera_de_alcance") not in (None, "ninguno"):
            motivo_descarte = "fuera de alcance"
        elif tool in set(estado.get("acciones_excluidas") or []):
            motivo_descarte = "acción rechazada o ya hecha"
        elif tool not in catalogo().tools_ejecutables():
            motivo_descarte = "fuera del catálogo"
        if motivo_descarte:
            return {"etapa": Etapa.DECISION.value, "accion_candidata": None}
        c = catalogo().por_tool(tool)
        accion = self.nueva_accion(estado, tool, str(cand.get("motivo") or ""))
        evento(
            "politica.decision",
            metadata={
                "accion": c.id,
                "politica": c.politica,
                "riesgo": c.riesgo,
                "caso_id": estado["case_id"],
            },
        )
        return {
            "etapa": Etapa.DECISION.value,
            "accion_actual": accion,
            "accion_candidata": None,
            "linea_tiempo": [_hito(Etapa.DECISION, f"Acción propuesta: {c.id} ({c.politica})")],
        }

    def _diagnostico_n2(self, estado: EstadoCaso, accion: dict[str, Any]) -> str:
        """Lo arma el código desde el estado del caso (síntoma, evidencia, por qué)."""
        primero = next((m["texto"] for m in estado.get("mensajes", []) if m.get("rol") == "usuario"), "")
        datos = resumen_para_conversacional(estado.get("slots") or {}, [])
        return (
            f"Caso {estado['case_id']} · equipo {estado.get('equipo_zabbix')}.\n"
            f"Síntoma (palabras del usuario): {primero[:400]}\n"
            f"{datos}\n"
            f"Acción solicitada: {accion['id']} (tool {accion['tool']}).\n"
            f"Motivo propuesto: {accion['motivo']}"
        )

    async def aprobacion_n2(self, estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.APROBACION_N2.value})
        a = dict(estado["accion_actual"])
        caso, equipo = estado["case_id"], estado["equipo_zabbix"]
        msgs: list[dict[str, Any]] = []
        if not a.get("aprobacion_id"):
            r = await self.puerta.solicitar_aprobacion_n2(a["tool"], equipo, caso, self._diagnostico_n2(estado, a))
            if not r.ok:
                a["estado"], a["motivo_fallo"] = "fallida", r.motivo
                self._emitir(escribir, a, "No pude enviar la solicitud a N2.")
                msgs.append(
                    self._decir(
                        escribir,
                        f"No pude enviar la solicitud de aprobación a un técnico N2 ({r.motivo}).",
                    )
                )
                return {**self._cerrar(estado, a), "mensajes": msgs}
            a["aprobacion_id"], a["estado"] = r.datos["id"], "esperando_n2"
            self._emitir(escribir, a, "Esperando la aprobación de un técnico N2.")
            msgs.append(
                self._decir(
                    escribir,
                    (
                        f"Para resolverlo propongo: {catalogo().por_tool(a['tool']).nombre.lower()}. "
                        f"Esta acción necesita la aprobación de un técnico N2. {texto_ans('aprobacion')} "
                        "Te aviso apenas la aprueben; puedes preguntarme por el estado cuando quieras."
                    ),
                )
            )
            return {
                "etapa": Etapa.APROBACION_N2.value,
                "accion_actual": a,
                "mensajes": msgs,
                "linea_tiempo": [_hito(Etapa.APROBACION_N2, f"Aprobación N2 solicitada {a['aprobacion_id']}")],
            }
        try:
            r = await self.puerta.consultar_aprobacion(a["aprobacion_id"])
        except AccionDenegada:
            r = None  # p. ej., el backend se reinició y perdió el registro: se trata como no vigente
        estado_srv = (r.datos.get("estado") if r and r.ok else None) or "desconocido"
        if estado_srv == "aprobada":
            a["estado"] = "aprobada_n2"
            self._emitir(escribir, a, "Un técnico N2 aprobó la acción.")
            msgs.append(self._decir(escribir, "Un técnico N2 aprobó la acción. Ahora falta tu autorización."))
            return {
                "accion_actual": a,
                "mensajes": msgs,
                "linea_tiempo": [_hito(Etapa.APROBACION_N2, "Aprobación N2 concedida")],
            }
        if estado_srv == "pendiente":
            self._emitir(escribir, a, "Sigue pendiente la aprobación de N2.")
            msgs.append(
                self._decir(escribir, "La solicitud sigue en revisión por un técnico N2. Te aviso apenas responda.")
            )
            return {"accion_actual": a, "mensajes": msgs}
        a["estado"] = "rechazada_n2" if estado_srv == "rechazada" else "fallida"
        self._emitir(
            escribir,
            a,
            "N2 no aprobó la acción." if estado_srv == "rechazada" else "No pude confirmar la aprobación.",
        )
        msgs.append(
            self._decir(
                escribir,
                "El técnico N2 no aprobó esta acción, así que no la voy a ejecutar."
                if estado_srv == "rechazada"
                else "No pude confirmar el estado de la aprobación, así que no la voy a ejecutar.",
            )
        )
        excluidas = sorted({*(estado.get("acciones_excluidas") or []), a["tool"]})
        return {
            **self._cerrar(estado, a),
            "acciones_excluidas": excluidas,
            "mensajes": msgs,
            "linea_tiempo": [_hito(Etapa.APROBACION_N2, f"Aprobación N2: {estado_srv}")],
        }

    async def consentimiento(self, estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.CONSENTIMIENTO.value})
        a = dict(estado["accion_actual"])
        caso, equipo = estado["case_id"], estado["equipo_zabbix"]
        c = catalogo().por_tool(a["tool"])
        msgs: list[dict[str, Any]] = []
        if not a.get("consentimiento_id"):
            r = await self.puerta.solicitar_consentimiento(a["tool"], equipo, caso)
            if not r.ok:
                a["estado"], a["motivo_fallo"] = "fallida", r.motivo
                self._emitir(escribir, a, "No pude abrir la solicitud de autorización.")
                msgs.append(
                    self._decir(
                        escribir,
                        "No pude abrir la ventana de autorización en tu equipo "
                        f"({r.motivo}). No haré ningún cambio. ¿Quieres que lo intente de nuevo "
                        "o que pase tu caso a una persona de soporte?",
                    )
                )
                return {**self._cerrar(estado, a), "mensajes": msgs}
            a["consentimiento_id"], a["estado"] = r.datos["id"], "esperando_consentimiento"
            self._emitir(escribir, a, "Pulsa «Autorizar» en la ventana de Soporte TI de tu equipo.")
            msgs.append(
                self._decir(
                    escribir,
                    (
                        # Qué hace, el aviso y la reversión ya están en la tarjeta: aquí no se repiten.
                        f"Te propongo {c.nombre[:1].lower()}{c.nombre[1:]} (revisa los detalles en la tarjeta).\n"
                        "Te apareció una ventana de «Soporte TI» en tu equipo: "
                        "pulsa «Autorizar» si estás de acuerdo "
                        "o «Rechazar» si prefieres no hacerlo."
                    ),
                )
            )
        estado_srv = "pendiente"
        for _ in range(self.rondas):
            try:
                r = await self.puerta.consultar_consentimiento(a["consentimiento_id"], self.espera)
            except AccionDenegada:
                estado_srv = "expirado"  # registro perdido (reinicio): nunca se reutiliza un id
                break
            estado_srv = (r.datos.get("estado") if r.ok else None) or "error"
            if estado_srv != "pendiente":
                break
        if estado_srv == "aprobado":
            a["estado"] = "autorizada"
            self._emitir(escribir, a, "Autorizaste la acción en tu equipo.")
            return {
                "etapa": Etapa.CONSENTIMIENTO.value,
                "accion_actual": a,
                "mensajes": msgs,
                "linea_tiempo": [_hito(Etapa.CONSENTIMIENTO, f"Consentimiento {a['consentimiento_id']} aprobado")],
            }
        if estado_srv == "pendiente":
            self._emitir(escribir, a, "La ventana sigue esperando tu respuesta.")
            msgs.append(
                self._decir(
                    escribir,
                    "Sigo esperando tu respuesta en la ventana de Soporte TI. "
                    "Cuando la respondas, escríbeme y lo reviso.",
                )
            )
            return {"etapa": Etapa.CONSENTIMIENTO.value, "accion_actual": a, "mensajes": msgs}
        if estado_srv == "rechazado":
            a["estado"] = "rechazada"
            self._emitir(escribir, a, "Rechazaste la acción: no se hizo ningún cambio.")
            msgs.append(
                self._decir(
                    escribir,
                    "Entendido, no haré ese cambio. Si quieres, buscamos otra opción "
                    "o paso tu caso a una persona de soporte.",
                )
            )
            excluidas = sorted({*(estado.get("acciones_excluidas") or []), a["tool"]})
            return {
                **self._cerrar(estado, a),
                "acciones_excluidas": excluidas,
                "mensajes": msgs,
                "linea_tiempo": [_hito(Etapa.CONSENTIMIENTO, "Consentimiento rechazado")],
            }
        a["estado"] = "expirada" if estado_srv == "expirado" else "fallida"
        self._emitir(
            escribir,
            a,
            "La solicitud de autorización venció."
            if estado_srv == "expirado"
            else "No pude confirmar tu autorización.",
        )
        msgs.append(
            self._decir(
                escribir,
                (
                    "La solicitud de autorización venció sin respuesta, así que no hice ningún cambio. "
                    if estado_srv == "expirado"
                    else "No pude confirmar tu autorización, así que no hice ningún cambio. "
                )
                + "¿Quieres que te envíe una nueva solicitud?",
            )
        )
        return {
            **self._cerrar(estado, a),
            "mensajes": msgs,
            "linea_tiempo": [_hito(Etapa.CONSENTIMIENTO, f"Consentimiento {estado_srv}")],
        }

    async def ejecucion(self, estado: EstadoCaso) -> dict[str, Any]:
        """Ejecutor determinista: sin LLM. Solo con el consentimiento aprobado (y N2 si aplica)."""
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.EJECUCION.value})
        a = dict(estado["accion_actual"])
        a["estado"] = "ejecutando"
        self._emitir(escribir, a, "Ejecutando la acción en tu equipo…")
        with observacion("ejecutor", tipo="span", input={"tool": a["tool"]}) as obs:
            try:
                r = await self.puerta.ejecutar_accion(
                    a["tool"],
                    estado["equipo_zabbix"],
                    estado["case_id"],
                    a["consentimiento_id"],
                    a.get("aprobacion_id"),
                )
            except AccionDenegada as err:
                score_traza("accion_sin_token", 1, comentario=str(err))  # nunca debería pasar
                a["estado"], a["motivo_fallo"] = "fallida", str(err)
                self._emitir(escribir, a, "La acción fue bloqueada por la política.")
                msg = self._decir(escribir, "La acción fue bloqueada por la política de seguridad y no se ejecutó.")
                return {**self._cerrar(estado, a), "mensajes": [msg]}
            obs.update(output={"ok": r.ok, "motivo": r.motivo})
        score_traza("accion_sin_token", 0)
        if a["tool"] == TOOL_LOGS:
            return await self._logs_a_cuarentena(estado, a, r, escribir)
        if not r.ok:
            a["estado"], a["motivo_fallo"] = "fallida", r.motivo
            self._emitir(escribir, a, "La acción no se pudo completar.")
            msg = self._decir(
                escribir,
                f"No pude completar la acción ({r.motivo}). No quedó resuelto todavía. ",
            )
            return {
                **self._cerrar(estado, a),
                "mensajes": [msg],
                "linea_tiempo": [_hito(Etapa.EJECUCION, f"Acción {a['tool']} falló")],
            }
        a["estado"], a["ejecutada_en"] = "ejecutada", _ahora()
        return {
            "etapa": Etapa.EJECUCION.value,
            "accion_actual": a,
            "linea_tiempo": [_hito(Etapa.EJECUCION, f"Acción {a['tool']} ejecutada")],
        }

    async def _logs_a_cuarentena(self, estado: EstadoCaso, a: dict[str, Any], r: Any, escribir) -> dict[str, Any]:
        """La salida de leer_logs va SOLO al extractor en cuarentena; al estado llegan campos validados."""
        if r.ok and self.extractor is not None:
            ext = (await self.extractor.extraer(r.datos.get("resultado", r.datos), caso_id=estado["case_id"])).a_dict()
        else:
            ext = {"no_concluyente": True, "codigos_error": [], "motivo": r.motivo or "sin extractor"}
        a["estado"] = "ejecutada" if r.ok else "fallida"
        a["ejecutada_en"], a["motivo_fallo"] = _ahora(), (None if r.ok else r.motivo)
        self._emitir(escribir, a, "Revisé los registros técnicos." if r.ok else "No pude leer los registros.")
        codigos = ", ".join(ext.get("codigos_error") or []) or "ningún código conocido"
        escribir(
            {
                "tipo": "revisando",
                "id": "logs",
                "estado": "ok" if r.ok and not ext.get("no_concluyente") else "fallo",
                "texto": f"Registros técnicos: {codigos}." if r.ok else "No pude leer los registros técnicos.",
            }
        )
        cambios: dict[str, Any] = {
            **self._cerrar(estado, a),
            "diagnostico": {**(estado.get("diagnostico") or {}), "extraccion": ext, "logs_leidos": True},
            "evidencia": [
                *(estado.get("evidencia") or []),
                {"herramienta": "zabbix.leer_logs_aplicacion", "resultado": ext, "hora": _ahora()},
            ],
            "linea_tiempo": [_hito(Etapa.EJECUCION, f"Logs leídos (cuarentena): {codigos}")],
        }
        if ext.get("contiene_instrucciones"):
            seguridad = dict(estado.get("seguridad") or {"banderas": [], "insistencia": {}})
            seguridad["banderas"] = [
                *seguridad.get("banderas", []),
                {"bandera": "inyeccion_en_log", "turno": estado.get("turnos"), "hora": _ahora()},
            ]
            cambios["seguridad"] = seguridad
            msg = self._decir(
                escribir,
                "Nota: los registros de tu equipo contenían texto con forma de instrucción. "
                "Lo ignoré: solo uso los códigos de error técnicos.",
            )
            cambios["mensajes"] = [msg]
        return cambios

    async def verificacion(self, estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.VERIFICACION.value})
        a = dict(estado["accion_actual"])
        lectura = VERIFICACION.get(a["tool"])
        tecnica = None
        if lectura:
            r = await self.puerta.leer(lectura, estado["equipo_zabbix"], estado["case_id"])
            tecnica = r.ok
            escribir(
                {
                    "tipo": "revisando",
                    "id": f"verificacion-{a['n']}",
                    "estado": "ok" if r.ok else "fallo",
                    "texto": "Volví a revisar tu equipo después del cambio."
                    if r.ok
                    else "No pude volver a revisar tu equipo después del cambio.",
                }
            )
        a["estado"], a["verificacion_tecnica"] = "ejecutada", tecnica
        self._emitir(escribir, a, "Acción ejecutada. Falta tu confirmación.")
        espera = {"n": a["n"], "tool": a["tool"]}
        msg = self._decir(
            escribir,
            f"Listo: completé «{catalogo().por_tool(a['tool']).nombre}» en tu equipo. "
            "¿Ya te funciona? Cuéntame si el problema sigue.",
        )
        excluidas = sorted({*(estado.get("acciones_excluidas") or []), a["tool"]})
        return {
            **self._cerrar(estado, a),
            "acciones_excluidas": excluidas,
            "etapa": Etapa.VERIFICACION.value,
            "esperando_confirmacion": espera,
            "fallo_verificacion": False,
            "mensajes": [msg],
            "linea_tiempo": [_hito(Etapa.VERIFICACION, "Esperando confirmación del usuario")],
        }

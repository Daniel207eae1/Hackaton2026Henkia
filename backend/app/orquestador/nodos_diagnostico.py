"""Nodos del diagnóstico por hipótesis (F3, §3.5): Hipotesis y Guia.

Hipotesis (cada turno que haga falta):
  1. Categoría: intérprete (app + síntoma) → categoría de P2; si no alcanza, `clasificar` por embeddings.
  2. Hipótesis = recetas de la KB de la categoría ordenadas por prior del historial (se fijan una vez).
  3. Evalúa con la evidencia estructurada disponible (reglas en código + Diagnosticador LLM con evidencia citada).
  4. Decide el siguiente paso EN CÓDIGO:
     - confirmada con acción del catálogo → Decision (F4: consentimiento, N2…)
     - confirmada con guía → Guia (pasos de la KB citando el artículo)
     - confirmada pero escalar / derivar / acción no disponible por chat → Escalar
     - falta leer logs → acción `leer_logs_aplicacion` (consentimiento) → extractor en cuarentena → vuelve aquí
     - sin nada pendiente o presupuesto agotado → Escalar (sin_hipotesis, esc. 10)
     - si no → Aclaracion (preguntar lo que solo el usuario sabe)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langgraph.config import get_stream_writer

from app.agentes.diagnosticador import (
    MAX_RONDAS,
    TOOL_POR_ACCION_KB,
    UMBRAL_CLASIFICACION,
    Diagnosticador,
    categoria_por_sintoma,
    evidencia_estructurada,
    requiere_logs,
)
from app.observabilidad.langfuse import evento, observacion, score_traza
from app.orquestador.estado import EstadoCaso, Etapa
from app.orquestador.nodos_accion import TOOL_LOGS, FlujoAccion
from app.rag.kb import Hipotesis, RepositorioKB
from app.seguridad.guardia_entrada import analizar

MARGEN_CLASIFICACION = 0.05  # ventaja mínima sobre la 2.ª categoría (si no, es ambiguo y se pregunta)


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hito(etapa: Etapa, detalle: str) -> dict[str, Any]:
    return {"hora": _ahora(), "etapa": etapa.value, "detalle": detalle}


def _a_hipotesis(d: dict[str, Any]) -> Hipotesis:
    return Hipotesis(
        d["articulo_id"],
        d["titulo"],
        d["hipotesis"],
        d.get("receta") or {},
        d.get("prior", 0.0),
        d.get("casos_historial", 0),
        d.get("estado", "pendiente"),
        list(d.get("evidencia") or []),
        d.get("justificacion"),
    )


def _resumen_ui(hs: list[Hipotesis]) -> list[dict[str, Any]]:
    return [
        {
            "articulo_id": h.articulo_id,
            "hipotesis": h.hipotesis,
            "prior": round(h.prior, 2),
            "estado": h.estado,
            "justificacion": h.justificacion,
        }
        for h in hs
    ]


class FlujoDiagnostico:
    def __init__(self, kb: RepositorioKB, diagnosticador: Diagnosticador, embeddings: Any = None):
        self.kb = kb
        self.diagnosticador = diagnosticador
        self.embeddings = embeddings  # ClienteAgente("embeddings") o None

    # ------------------------------------------------------------------ cuándo entrar
    @staticmethod
    def aplica(estado: EstadoCaso) -> bool:
        """El diagnóstico corre si no hay masivo ni fuera de alcance y aún no terminó (o falló su solución)."""
        if (estado.get("masivo") or {}).get("estado") in ("posible_masivo", "masivo_confirmado"):
            return False
        if (estado.get("sintoma") or {}).get("fuera_de_alcance") not in (None, "ninguno"):
            return False
        d = estado.get("diagnostico") or {}
        return not d.get("sin_categoria") or bool((estado.get("sintoma") or {}).get("aplicacion"))

    async def _categoria(self, estado: EstadoCaso) -> tuple[str | None, float, str]:
        sintoma = estado.get("sintoma") or {}
        cat = categoria_por_sintoma(sintoma.get("aplicacion"), sintoma.get("tipo_sintoma"))
        if cat:
            return cat, 1.0, "interprete"
        if self.embeddings is None:
            return None, 0.0, "sin_embeddings"
        texto = " ".join(m["texto"] for m in estado.get("mensajes", []) if m.get("rol") == "usuario")[-800:]
        try:
            # Sin instrucción de consulta: P2 calculó los centroides sin ella y así la similitud es mayor.
            (v,) = await self.embeddings.embeddings([texto])
            top = await self.kb.clasificar(v)
        except Exception:  # noqa: BLE001 - sin embeddings/BD el diagnóstico sigue por el intérprete
            return None, 0.0, "clasificacion_fallida"
        margen = top[0][1] - top[1][1] if len(top) > 1 else 1.0
        if (
            top
            and top[0][1] >= UMBRAL_CLASIFICACION
            and margen >= MARGEN_CLASIFICACION
            and not await self.kb.categoria_fuera_alcance(top[0][0])
        ):
            return top[0][0], float(top[0][1]), "embeddings"
        return None, float(top[0][1]) if top else 0.0, "baja_confianza"

    # ------------------------------------------------------------------ nodo Hipotesis
    async def hipotesis(self, estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.HIPOTESIS.value})
        d = dict(estado.get("diagnostico") or {})
        with observacion("agente_diagnosticador", tipo="agent", input={"categoria": d.get("categoria")}) as obs:
            if not d.get("hipotesis"):
                cat, conf, fuente = await self._categoria(estado)
                if not cat:
                    d.update(sin_categoria=True, fuente_categoria=fuente, siguiente="decision")
                    return {"etapa": Etapa.HIPOTESIS.value, "diagnostico": d}
                hs = await self.kb.hipotesis(cat)
                if not hs:  # la KB no tiene recetas para la categoría: sigue el camino del intérprete
                    d.update(sin_categoria=True, categoria=cat, fuente_categoria=fuente, siguiente="decision")
                    return {"etapa": Etapa.HIPOTESIS.value, "diagnostico": d}
                d.update(
                    categoria=cat,
                    confianza=round(conf, 3),
                    fuente_categoria=fuente,
                    rondas=0,
                    hipotesis=[h.a_dict() for h in hs],
                    sin_categoria=False,
                )
            hs = [_a_hipotesis(x) for x in d["hipotesis"]]
            # El usuario dijo que la solución de la hipótesis confirmada no funcionó → se descarta y se sigue.
            if estado.get("fallo_verificacion") and d.get("confirmada"):
                for h in hs:
                    if h.articulo_id == d["confirmada"]:
                        h.estado, h.justificacion = "descartada", "La solución no funcionó según el usuario"
                d["confirmada"] = None
            ev = evidencia_estructurada(estado.get("slots") or {}, d.get("extraccion"))
            await self.diagnosticador.evaluar(hs, ev)
            d["rondas"] = d.get("rondas", 0) + 1
            d["hipotesis"] = [h.a_dict() for h in hs]
            cambios: dict[str, Any] = {"etapa": Etapa.HIPOTESIS.value, "fallo_verificacion": False}
            d["siguiente"] = self._siguiente(estado, d, hs, cambios)
            obs.update(output={"siguiente": d["siguiente"], "estados": {h.articulo_id: h.estado for h in hs}})
        escribir({"tipo": "hipotesis", "datos": {"categoria": d.get("categoria"), "hipotesis": _resumen_ui(hs)}})
        cambios.update(
            diagnostico=d,
            hipotesis=[h.a_dict() for h in hs],
            linea_tiempo=[
                _hito(
                    Etapa.HIPOTESIS,
                    f"{d.get('categoria')}: "
                    + ", ".join(f"{h.articulo_id}={h.estado}" for h in hs)
                    + f" → {d['siguiente']}",
                )
            ],
        )
        return cambios

    def _siguiente(self, estado: EstadoCaso, d: dict[str, Any], hs: list[Hipotesis], cambios: dict[str, Any]) -> str:
        confirmadas = [h for h in hs if h.estado == "confirmada"]
        if confirmadas:
            h = max(confirmadas, key=lambda x: x.prior)
            d["confirmada"] = h.articulo_id
            score_traza("tiempo_a_diagnostico", float(estado.get("turnos") or 0), comentario="turnos hasta confirmar")
            evento("diagnostico.confirmado", metadata={"articulo": h.articulo_id, "caso_id": estado["case_id"]})
            tipo = h.receta.get("tipo_solucion")
            tool = TOOL_POR_ACCION_KB.get(h.receta.get("accion_catalogo") or "")
            if tipo == "accion" and tool and tool not in set(estado.get("acciones_excluidas") or []):
                cambios["accion_candidata"] = {"accion": tool, "motivo": f"{h.articulo_id}: {h.justificacion}"}
                return "accion"
            if tipo == "guia":
                return "guia"
            cambios["motivo_escalamiento"] = "fuera_alcance" if tipo == "derivar" else "requiere_privilegios"
            return "escalar"
        pendientes = [h for h in hs if h.estado == "pendiente"]
        if (
            any(requiere_logs(h) for h in pendientes)
            and not d.get("logs_leidos")
            and estado.get("equipo_zabbix")
            and TOOL_LOGS not in set(estado.get("acciones_excluidas") or [])
        ):
            cambios["accion_actual"] = FlujoAccion.nueva_accion(
                estado,
                TOOL_LOGS,
                "Leer los registros técnicos para confirmar o descartar: "
                + ", ".join(h.hipotesis for h in pendientes if requiere_logs(h)),
            )
            return "leer_logs"
        # «No concluyente» = falta información que el usuario puede dar: en las primeras rondas se pregunta.
        abiertas = pendientes + (
            [h for h in hs if h.estado == "no_concluyente"] if d["rondas"] < MAX_RONDAS - 1 else []
        )
        if not abiertas or d["rondas"] >= MAX_RONDAS:
            cambios["motivo_escalamiento"] = "sin_hipotesis"
            return "escalar"
        return "aclarar"

    @staticmethod
    def tras_hipotesis(estado: EstadoCaso) -> str:
        siguiente = (estado.get("diagnostico") or {}).get("siguiente")
        return {
            "accion": Etapa.DECISION.value,
            "decision": Etapa.DECISION.value,
            "guia": Etapa.GUIA.value,
            "escalar": Etapa.ESCALAR.value,
            "leer_logs": Etapa.CONSENTIMIENTO.value,
            "aclarar": Etapa.ACLARACION.value,
        }.get(siguiente or "", Etapa.ACLARACION.value)

    # ------------------------------------------------------------------ nodo Guia
    async def guia(self, estado: EstadoCaso) -> dict[str, Any]:
        """Pasos de la KB citando el artículo (§3.8 no invención). El texto de la KB también se revisa."""
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.GUIA.value})
        d = estado.get("diagnostico") or {}
        h = next(x for x in d.get("hipotesis", []) if x["articulo_id"] == d.get("confirmada"))
        secciones = await self.kb.secciones(h["articulo_id"])
        pasos = (secciones.get("pasos") or "").strip()
        if not pasos or analizar(pasos).banderas:
            evento("kb.articulo_no_usable", metadata={"articulo": h["articulo_id"], "caso_id": estado["case_id"]})
            return {
                "etapa": Etapa.GUIA.value,
                "motivo_escalamiento": "sin_hipotesis",
                "linea_tiempo": [_hito(Etapa.GUIA, f"{h['articulo_id']} sin pasos utilizables")],
            }
        texto = (
            f"Encontré la causa más probable: {h['hipotesis'].lower()} "
            f"({h.get('justificacion') or 'según la evidencia'}).\n"
            f"Según el artículo {h['articulo_id']} «{h['titulo']}», te guío paso a paso:\n{pasos}\n\n"
            "Cuando termines, dime si quedó resuelto."
        )
        escribir({"tipo": "texto", "texto": texto})
        escribir(
            {
                "tipo": "fuentes",
                "datos": {"fuentes": [{"articulo_id": h["articulo_id"], "titulo": h["titulo"], "seccion": "pasos"}]},
            }
        )
        guia = {"articulo_id": h["articulo_id"], "titulo": h["titulo"], "verificacion": secciones.get("verificacion")}
        return {
            "etapa": Etapa.GUIA.value,
            "guia": guia,
            "respuesta": texto,
            "esperando_confirmacion": {"tipo": "guia", "articulo_id": h["articulo_id"]},
            "mensajes": [{"rol": "sistema", "texto": texto, "hora": _ahora()}],
            "linea_tiempo": [_hito(Etapa.GUIA, f"Guía {h['articulo_id']} enviada; esperando confirmación")],
        }

    @staticmethod
    def tras_guia(estado: EstadoCaso) -> str:
        return Etapa.ESCALAR.value if estado.get("motivo_escalamiento") == "sin_hipotesis" else "fin"

"""Agente Diagnosticador (§3.3, §3.5 «Catálogo de hipótesis») — R2.

- Hipótesis = recetas de la KB de la categoría, ordenadas por PRIOR (frecuencia de esa causa en el historial).
- Las pruebas son de SOLO LECTURA y su plan se fija antes de leer logs (Plan-Then-Execute).
- Donde se puede, el criterio se evalúa EN CÓDIGO (disco, cola, licencia, perfil, versión, códigos ERR-SIM).
- Lo que no tiene regla lo evalúa un LLM que SOLO recibe evidencia estructurada (slots saneados y campos
  validados del extractor), nunca texto crudo de logs, errores ni de la conversación; debe citar la evidencia
  que usa y el código lo valida (sin evidencia citada no hay confirmación ni descarte).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentes.contexto import LICENCIA_OK, UMBRAL_DISCO_GB
from app.agentes.prompts import prompt_embebido, prompt_vigente
from app.llm.puerto import Mensaje
from app.llm.registro import RegistroLLM, SinModeloDisponible
from app.observabilidad.langfuse import evento, observacion
from app.rag.kb import Hipotesis

# (aplicación, tipo de síntoma) del intérprete → categoría de P2 (conocimiento.categorias)
CATEGORIA_POR_SINTOMA: dict[tuple[str, str], str] = {
    ("outlook", "no_abre"): "outlook.no_abre",
    ("outlook", "se_cierra"): "outlook.no_abre",
    ("outlook", "no_sincroniza"): "outlook.no_sincroniza",
    ("outlook", "lenta"): "outlook.lenta",
    ("teams", "sin_audio"): "teams.audio_video",
    ("teams", "no_abre"): "teams.no_abre",
    ("teams", "se_cierra"): "teams.no_abre",
    ("teams", "no_sincroniza"): "teams.no_sincroniza",
    ("excel", "licencia"): "excel.licencia",
    ("word", "licencia"): "excel.licencia",
    ("office", "licencia"): "excel.licencia",
    ("powerpoint", "licencia"): "excel.licencia",
    ("excel", "se_cierra"): "excel.se_cierra",
    ("excel", "no_abre"): "excel.se_cierra",
    ("word", "se_cierra"): "word.se_cierra",
    ("word", "no_abre"): "word.se_cierra",
    ("onedrive", "no_sincroniza"): "onedrive.no_sincroniza",
    ("onedrive", "archivo_sobrescrito"): "onedrive.recuperar_archivo",
    ("office", "archivo_sobrescrito"): "onedrive.recuperar_archivo",
    ("excel", "archivo_sobrescrito"): "onedrive.recuperar_archivo",
    ("word", "archivo_sobrescrito"): "onedrive.recuperar_archivo",
    ("impresora", "impresion"): "impresora.impresion",
    ("impresora", "no_abre"): "impresora.impresion",
}
UMBRAL_CLASIFICACION = 0.70  # similitud mínima para aceptar la categoría por embeddings

# acción de la receta (catálogo de P2) → tool del MCP. Las que no están aquí no se pueden hacer por chat.
TOOL_POR_ACCION_KB = {
    "recrear_perfil_outlook": "recrear_perfil_outlook",
    "reiniciar_cola_impresion": "reiniciar_cola_impresion",
    "resincronizar_onedrive": "resincronizar_onedrive",
    "limpiar_cache_teams": "limpiar_cache_teams",
    "asignar_licencia": "asignar_licencia_office",
    "reparar_office_rapida": "reparacion_rapida_office",
    "restaurar_version_archivo": "restaurar_version_archivo",
}

# herramienta de la receta → claves de evidencia que la responden (o "logs")
EVIDENCIA_POR_HERRAMIENTA: dict[str, list[str]] = {
    "telemetria.disco": ["disco_libre_gb", "disco_uso_pct"],
    "telemetria.impresoras": ["cola_trabajos"],
    "telemetria.onedrive": ["onedrive_en_ejecucion"],
    "telemetria.licencia_office": ["licencia_estado", "licencia_producto"],
    "directorio.licencias": ["licencia_estado", "licencia_producto"],
    "telemetria.procesos": ["perfil_outlook_estado"],
    "telemetria.teams": ["teams_version", "teams_estadoCache"],
    "telemetria.teams.version": ["teams_version"],
    "telemetria.teams.cache_mb": ["teams_estadoCache"],
    "telemetria.audio": ["teams_audio", "teams_dispositivosAudio_cantidad"],
    "telemetria.onedrive.versiones": ["versiones_anteriores", "archivo_en_onedrive"],
}
PERFIL_DANADO = {"sin-perfil", "predeterminado-inexistente", "sin-predeterminado", "sin-cuentas"}
_ERR = re.compile(r"ERR-SIM-[0-9A-F]{4}")
MAX_RONDAS = 4  # presupuesto del ciclo (§3.5): luego se escala


def categoria_por_sintoma(aplicacion: str | None, tipo: str | None) -> str | None:
    return CATEGORIA_POR_SINTOMA.get((aplicacion or "", tipo or ""))


def evidencia_estructurada(slots: dict[str, dict[str, Any]], extraccion: dict[str, Any] | None) -> dict[str, Any]:
    """Solo campos tipados y saneados. Nunca texto crudo."""
    ev = {k: v.get("valor") for k, v in slots.items() if v.get("valor") is not None}
    cod = slots.get("codigo_error") or {}
    if cod.get("origen") == "usuario" and not cod.get("corroborado"):
        ev["codigo_error_sin_corroborar"] = True
    libre, usado = ev.get("disco_libre_gb"), ev.get("disco_usado_gb")
    if isinstance(libre, int | float) and isinstance(usado, int | float) and libre + usado > 0:
        ev["disco_uso_pct"] = round(100 * usado / (libre + usado), 1)
    if extraccion:
        ev["logs.codigos_error"] = list(extraccion.get("codigos_error") or [])
        ev["logs.componente"] = extraccion.get("componente")
        ev["logs.aplicacion"] = extraccion.get("aplicacion")
        ev["logs.no_concluyente"] = bool(extraccion.get("no_concluyente"))
    return ev


def requiere_logs(h: Hipotesis) -> bool:
    return any(
        str(p.get("herramienta", "")).startswith("logs.") or p.get("requiere") == "leer_logs"
        for p in h.receta.get("pruebas") or []
    )


def claves_de_pruebas(h: Hipotesis) -> list[str]:
    claves: list[str] = []
    for p in h.receta.get("pruebas") or []:
        claves += EVIDENCIA_POR_HERRAMIENTA.get(str(p.get("herramienta", "")), [])
    return claves


def _regla(h: Hipotesis, ev: dict[str, Any]) -> tuple[str, str, list[str]] | None:
    """(estado, justificación, evidencia usada) si el criterio se puede evaluar en código."""
    uso, libre = ev.get("disco_uso_pct"), ev.get("disco_libre_gb")
    a = h.articulo_id
    if a == "KB-SIM-014" and uso is not None:
        if uso >= 95 or (isinstance(libre, int | float) and libre < UMBRAL_DISCO_GB):
            return "confirmada", f"Disco al {uso} % ({libre} GB libres)", ["disco_uso_pct", "disco_libre_gb"]
        if uso < 90:
            return "descartada", f"Disco al {uso} %: hay espacio suficiente", ["disco_uso_pct"]
    if a == "KB-SIM-028" and uso is not None and uso >= 90:
        return "confirmada", f"Disco al {uso} %", ["disco_uso_pct"]
    if a == "KB-SIM-023" and isinstance(ev.get("cola_trabajos"), int):
        n = ev["cola_trabajos"]
        return (
            ("confirmada", f"{n} trabajo(s) atascados en la cola", ["cola_trabajos"])
            if n > 0
            else ("descartada", "La cola de impresión está vacía", ["cola_trabajos"])
        )
    if a == "KB-SIM-019" and ev.get("licencia_estado"):
        ok = str(ev["licencia_estado"]).lower() in LICENCIA_OK
        return (
            ("descartada", f"Licencia {ev['licencia_estado']}", ["licencia_estado"])
            if ok
            else ("confirmada", f"Licencia {ev['licencia_estado']}", ["licencia_estado"])
        )
    if a == "KB-SIM-012" and str(ev.get("teams_version", "")).isdigit():
        v = int(ev["teams_version"])
        return (
            ("confirmada", f"Teams versión {v} (< 24000)", ["teams_version"])
            if v < 24000
            else ("descartada", f"Teams versión {v} al día", ["teams_version"])
        )
    if any(p.get("herramienta") == "telemetria.onedrive.versiones" for p in h.receta.get("pruebas") or []):
        if ev.get("archivo_en_onedrive") is False:
            return "descartada", "El archivo no aparece en OneDrive", ["archivo_en_onedrive"]
        n = ev.get("versiones_anteriores")
        if isinstance(n, int):
            return (
                ("confirmada", f"{n} versión(es) anterior(es) en el historial", ["versiones_anteriores"])
                if n > 0
                else ("descartada", "El archivo no tiene versiones anteriores", ["versiones_anteriores"])
            )
    if a == "KB-SIM-001" and ev.get("perfil_outlook_estado") in PERFIL_DANADO:
        return "confirmada", f"Perfil de Outlook: {ev['perfil_outlook_estado']}", ["perfil_outlook_estado"]
    # Criterio por código de error en los logs (anclado por el extractor).
    esperados = _ERR.findall(h.receta.get("criterio_confirmacion") or "")
    # Código validado de una captura (OCR + visión coinciden) o escrito por el usuario: confirma si es el esperado.
    # Su AUSENCIA no descarta nada (una captura muestra un solo error; el registro completo está en los logs).
    if esperados and ev.get("codigo_error") in esperados:
        if ev.get("codigo_error_sin_corroborar"):
            # Lo escribió el usuario y ninguna captura lo respalda: no basta para confirmar (falta evidencia).
            return "no_concluyente", f"{ev['codigo_error']} lo indicó el usuario; falta corroborarlo", ["codigo_error"]
        return "confirmada", f"{ev['codigo_error']} en la captura (validado)", ["codigo_error"]
    if esperados and "logs.codigos_error" in ev:
        if ev.get("logs.no_concluyente") and not ev["logs.codigos_error"]:
            return "no_concluyente", "No se pudo leer bien el registro", ["logs.no_concluyente"]
        hallados = [c for c in esperados if c in ev["logs.codigos_error"]]
        if hallados:
            return "confirmada", f"{', '.join(hallados)} presente en el registro", ["logs.codigos_error"]
        return "descartada", f"{', '.join(esperados)} no aparece en el registro", ["logs.codigos_error"]
    return None


class EvaluacionHipotesis(BaseModel):
    articulo_id: str
    estado: Literal["confirmada", "descartada", "no_concluyente"]
    evidencias: list[str] = Field(description="Claves de la evidencia usadas (deben existir)")
    justificacion: str = Field(max_length=300)


class Evaluaciones(BaseModel):
    evaluaciones: list[EvaluacionHipotesis]


PROMPT_DIAGNOSTICO = prompt_embebido("agente_diagnosticador")  # versión vigente: Langfuse (`agente_diagnosticador`)


class Diagnosticador:
    def __init__(self, registro: RegistroLLM | None):
        self._cliente = registro.para("diagnosticador") if registro else None

    async def evaluar(self, hipotesis: list[Hipotesis], ev: dict[str, Any]) -> list[Hipotesis]:
        sin_regla: list[Hipotesis] = []
        for h in hipotesis:
            if h.estado in ("confirmada", "descartada"):
                continue
            regla = _regla(h, ev)
            if regla:
                h.estado, h.justificacion, h.evidencia = regla
            elif any(k in ev for k in claves_de_pruebas(h)):
                sin_regla.append(h)  # hay evidencia relevante pero ninguna regla: la juzga el LLM
        if sin_regla and self._cliente:
            await self._evaluar_llm(sin_regla, ev)
        return hipotesis

    async def _evaluar_llm(self, hs: list[Hipotesis], ev: dict[str, Any]) -> None:
        relevantes = {k: ev[k] for h in hs for k in claves_de_pruebas(h) if k in ev}
        lineas = "\n".join(
            f"- {h.articulo_id}: {h.hipotesis}. Confirma si: {h.receta.get('criterio_confirmacion')}. "
            f"Descarta si: {h.receta.get('criterio_descarte')}"
            for h in hs
        )
        sistema, prompt_lf = prompt_vigente("agente_diagnosticador")
        mensajes = [
            Mensaje("system", sistema),
            Mensaje(
                "user",
                f"Hipótesis:\n{lineas}\n\nEvidencia:\n" + "\n".join(f"- {k}: {v}" for k, v in relevantes.items()),
            ),
        ]
        with observacion(
            "agente_diagnosticador", tipo="agent", input={"hipotesis": [h.articulo_id for h in hs]}
        ) as obs:
            try:
                r = await self._cliente.estructurado(mensajes, Evaluaciones, prompt=prompt_lf)
            except SinModeloDisponible as err:
                evento("llm.sin_modelo", metadata={"agente": "diagnosticador", "error": str(err)[:200]})
                return
            por_id = {h.articulo_id: h for h in hs}
            for e in r.evaluaciones:
                h = por_id.get(e.articulo_id)
                if h is None:
                    continue
                citadas = [k for k in e.evidencias if k in relevantes]
                if e.estado != "no_concluyente" and not citadas:
                    continue  # sin evidencia citada válida no se confirma ni se descarta
                h.estado, h.evidencia, h.justificacion = e.estado, citadas, e.justificacion[:300]
            obs.update(output={h.articulo_id: h.estado for h in hs})

"""Agente Masivos (F2, §3.11): clúster semántico de reportes + incidentes de `operacion`. Sin LLM.

Por cada caso (una vez, cuando ya se sabe la app y el síntoma):
  1. Texto canónico `app · síntoma · texto` (el formato con que P2 embebió los reportes) → *embedding*.
  2. Categoría: intérprete (tabla) o `conocimiento.clasificar` con el mismo vector (umbral + margen).
  3. Se registra el reporte (`operacion.reportes`) y se buscan similares de OTROS usuarios en la ventana
     (`operacion.buscar_reportes_similares`, híbrida vector + texto).
  4. Decisión EN CÓDIGO:
     - incidente `publicado` de la categoría → `masivo_confirmado` (se cita el mensaje oficial tal cual);
     - ≥ k usuarios distintos con similitud ≥ umbral → `posible_masivo`: se une a la propuesta abierta o se
       crea una (`propuesto`, origen `cluster_reportes`) para que N2 la confirme o la descarte;
     - si no → `sin_masivo` (sigue el diagnóstico individual).
El mensaje oficial es texto externo: pasa por la guardia y nunca va a un LLM.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.agentes.contexto import LineaRevision
from app.agentes.diagnosticador import UMBRAL_CLASIFICACION, categoria_por_sintoma
from app.observabilidad.langfuse import enmascarar_texto, observacion
from app.rag.kb import RepositorioKB
from app.rag.reportes import Incidente, RepositorioMasivos
from app.seguridad.guardia_entrada import analizar

log = logging.getLogger(__name__)

SERVICIO_BD_POR_APP = {"outlook": "correo", "teams": "teams", "onedrive": "nube"}
NOMBRE_SERVICIO_BD = {"correo": "correo", "teams": "Teams", "nube": "almacenamiento en la nube"}
MARGEN_CLASIFICACION = 0.05
_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁠-⁤]")
SIN_DATO = ("", None, "desconocida", "desconocido")


def texto_canonico(aplicacion: str, tipo: str, texto: str) -> str:
    return f"{aplicacion} · {tipo} · {' '.join(texto.split())}"


def mensaje_seguro(texto: str | None) -> str | None:
    """Mensaje oficial apto para citar: sin caracteres de control y sin señales de instrucciones."""
    crudo = (texto or "")[:500]
    if not crudo.strip() or analizar(crudo).banderas:
        return None
    return _CONTROL.sub("", crudo).strip() or None


def hora_legible(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return iso[:25]


@dataclass
class ResultadoCluster:
    estado: str  # sin_masivo | posible_masivo | masivo_confirmado | pendiente | no_aplica | no_evaluado
    linea: LineaRevision | None = None
    categoria: str | None = None
    servicio: str | None = None
    usuarios: int = 0
    reporte_id: int | None = None
    incidente: Incidente | None = None
    regla: dict[str, Any] = field(default_factory=dict)


class AgenteMasivos:
    def __init__(
        self,
        repo: RepositorioMasivos,
        embeddings: Any,
        kb: RepositorioKB | None = None,
        *,
        min_usuarios: int = 3,
        ventana_min: int = 60,
        umbral: float = 0.75,
        referencia: str | None = None,
        modelo_embedding: str = "",
    ):
        self.repo = repo
        self.embeddings = embeddings
        self.kb = kb
        self.min_usuarios = min_usuarios
        self.ventana_min = ventana_min
        self.umbral = umbral
        self.referencia = referencia
        self.modelo_embedding = modelo_embedding

    def _momento_reporte(self) -> str | None:
        """Con reloj de demostración, el reporte se fecha justo antes de ese «ahora» (dentro de la ventana) y
        con una fracción de segundo distinta: así no choca con `reportes_unicidad (usuario_id, reportado_en)`."""
        if not self.referencia:
            return None  # la BD usa now()
        base = datetime.fromisoformat(self.referencia)
        return (base - timedelta(microseconds=1 + time.time_ns() // 1000 % 999_999)).isoformat()

    async def _categoria(self, app: str, tipo: str, vector: list[float]) -> tuple[str | None, float]:
        if cat := categoria_por_sintoma(app, tipo):
            return cat, 1.0
        if self.kb is None:
            return None, 0.0
        with observacion("rag.clasificar", tipo="retriever") as obs:
            top = await self.kb.clasificar(vector)
            obs.update(output=top[:3])
        margen = top[0][1] - top[1][1] if len(top) > 1 else 1.0
        if top and top[0][1] >= UMBRAL_CLASIFICACION and margen >= MARGEN_CLASIFICACION:
            return top[0][0], float(top[0][1])
        return None, float(top[0][1]) if top else 0.0

    async def evaluar(
        self,
        sintoma: dict[str, Any],
        persona_id: str,
        equipo_id: str | None,
        *,
        reporte_previo: int | None = None,
    ) -> ResultadoCluster:
        app, tipo = sintoma.get("aplicacion"), sintoma.get("tipo_sintoma")
        servicio = SERVICIO_BD_POR_APP.get(app or "")
        if app not in SIN_DATO and servicio is None:
            return ResultadoCluster("no_aplica")  # app sin servicio compartido (impresora, Excel local…)
        if app in SIN_DATO or tipo in SIN_DATO:
            return ResultadoCluster("pendiente")  # se evalúa cuando se entienda el síntoma
        texto = enmascarar_texto((sintoma.get("descripcion_usuario") or "")[:400])  # sin correos ni rutas con usuario
        canon = texto_canonico(app, tipo, texto)
        try:
            (vector,) = await self.embeddings.embeddings([canon])
            categoria, confianza = await self._categoria(app, tipo, vector)
            if not categoria:
                return ResultadoCluster("pendiente", servicio=servicio)
            reporte_id = reporte_previo
            if reporte_id is None:
                reporte_id = await self.repo.registrar_reporte(
                    usuario_id=persona_id,
                    equipo_id=equipo_id,
                    texto=texto,
                    texto_canonico=canon,
                    categoria=categoria,
                    confianza=confianza,
                    vector=vector,
                    modelo=self.modelo_embedding,
                    reportado_en=self._momento_reporte(),
                )
            with observacion(
                "rag.buscar_reportes_similares",
                tipo="retriever",
                input={"categoria": categoria, "ventana_min": self.ventana_min, "umbral": self.umbral},
            ) as obs:
                cluster = await self.repo.similares(
                    vector, canon, categoria, persona_id, self.ventana_min, self.umbral, self.referencia
                )
                obs.update(output={"usuarios_distintos": cluster.usuarios_distintos, "reportes": len(cluster.reportes)})
            incidente = await self.repo.incidente_activo(categoria, servicio)
        except Exception:  # noqa: BLE001 - sin BD/embeddings el caso sigue con el diagnóstico individual
            log.exception("No pude evaluar el clúster de reportes")
            return ResultadoCluster(
                "no_evaluado",
                LineaRevision("cluster", "fallo", "No pude revisar si otros compañeros reportan lo mismo."),
            )
        regla = {
            "k": self.min_usuarios,
            "umbral": self.umbral,
            "ventana_min": self.ventana_min,
            "usuarios_distintos": cluster.usuarios_distintos,
            "similitud_max": round(cluster.similitud_max, 3),
            "reportes": cluster.reportes[:20],
            "referencia": self.referencia,
        }
        base = {
            "categoria": categoria,
            "servicio": servicio,
            "usuarios": cluster.usuarios_distintos,
            "reporte_id": reporte_id,
            "regla": regla,
        }
        nombre = NOMBRE_SERVICIO_BD[servicio]
        if incidente and incidente.estado == "publicado":
            return ResultadoCluster(
                "masivo_confirmado",
                LineaRevision(
                    "cluster", "anomalia", f"Hay un incidente general publicado en {nombre} ({incidente.id})."
                ),
                incidente=incidente,
                **base,
            )
        if cluster.usuarios_distintos >= self.min_usuarios:
            if incidente is None:
                try:
                    incidente = await self.repo.proponer(
                        categoria,
                        servicio,
                        f"Posible masivo: {nombre} · {categoria}",
                        regla,
                        [*cluster.reportes, *([reporte_id] if reporte_id else [])],
                    )
                except Exception:  # noqa: BLE001 - sin propuesta no hay a quién vincular: diagnóstico individual
                    log.exception("No pude registrar la propuesta de masivo")
                    return ResultadoCluster(
                        "no_evaluado",
                        LineaRevision("cluster", "fallo", "No pude registrar el posible incidente general."),
                        **base,
                    )
            return ResultadoCluster(
                "posible_masivo",
                LineaRevision(
                    "cluster",
                    "anomalia",
                    f"{cluster.usuarios_distintos} compañeros reportaron algo parecido en {nombre} hace poco.",
                ),
                incidente=incidente,
                **base,
            )
        texto_linea = (
            f"Solo {cluster.usuarios_distintos} reporte(s) parecido(s) de otros compañeros: no parece general."
            if cluster.usuarios_distintos
            else "No hay reportes parecidos de otros compañeros."
        )
        return ResultadoCluster("sin_masivo", LineaRevision("cluster", "ok", texto_linea), **base)

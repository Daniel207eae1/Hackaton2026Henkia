"""ITSM simulada (registro oficial del caso) sobre el esquema `operacion` de P2 — R5/R6.

El estado del caso vive en el grafo (checkpointer); al final de cada turno se PROYECTA aquí de forma
idempotente: caso (con el estado completo en JSONB), eventos, mensajes, acciones con su autorización,
banderas de seguridad y escalamientos. Langfuse es observabilidad; esto es el registro oficial.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Protocol

log = logging.getLogger(__name__)
_NS = uuid.UUID("6f1c2a8e-6d1b-4f3e-9a51-3c5b7d2e9f10")

# Nodo del grafo → operacion.casos.estado
ESTADO_POR_ETAPA = {
    "Recepcion": "recepcion",
    "RespuestaPolitica": "aclaracion",
    "Interpretacion": "aclaracion",
    "Contexto": "contexto",
    "ChequeoMasivo": "chequeo_masivo",
    "InformarMasivo": "chequeo_masivo",
    "Decision": "decision",
    "Aclaracion": "aclaracion",
    "AprobacionN2": "aprobacion_n2",
    "Consentimiento": "consentimiento",
    "Ejecucion": "ejecucion",
    "Verificacion": "verificacion",
    "Confirmacion": "verificacion",
    "Cierre": "cerrado",
    "Escalar": "escalado",
}


_HEX32 = re.compile(r"[0-9a-f]{32}")


def uuid_del_caso(case_id: str) -> uuid.UUID:
    """El id del chat (32 hex en minúscula, sin guiones) es un UUID; cualquier otro se mapea con uuid5.

    Solo la forma CANÓNICA se lee como hex: `uuid.UUID` acepta mayúsculas, guiones y llaves, y así dos `case_id`
    distintos (`abc…` y `ABC…`) caerían en el mismo caso de la BD (hallazgo de seguridad: pisar un caso ajeno)."""
    if _HEX32.fullmatch(case_id):
        return uuid.UUID(hex=case_id)
    return uuid.uuid5(_NS, case_id)


def estado_bd(estado: dict[str, Any]) -> tuple[str, str | None]:
    """(operacion.casos.estado, resultado) a partir del estado del grafo."""
    if estado.get("escalamiento"):
        return "escalado", "escalado"
    if estado.get("cierre"):
        return "cerrado", "resuelto"
    if (estado.get("masivo") or {}).get("estado") == "masivo_confirmado":
        return "vinculado_masivo", "vinculado_masivo"
    if (estado.get("masivo") or {}).get("estado") == "posible_masivo":
        return "chequeo_masivo", None  # esperando que N2 confirme o descarte
    return ESTADO_POR_ETAPA.get(estado.get("etapa") or "", "aclaracion"), None


class RepositorioITSM(Protocol):
    async def sincronizar(self, estado: dict[str, Any], traza_url: str | None = None) -> None: ...

    async def listar_escalamientos(self) -> list[dict[str, Any]]: ...

    async def tomar_escalamiento(self, escalamiento_id: int, tecnico_id: str) -> bool: ...

    async def evaluar_escalamiento(self, escalamiento_id: int, completo: bool) -> dict[str, Any] | None: ...

    async def cargar_estado(self, case_id: str) -> dict[str, Any] | None: ...


class RepositorioITSMMemoria:
    """Doble en memoria (pruebas y ejecución sin BD)."""

    def __init__(self) -> None:
        self.casos: dict[str, dict[str, Any]] = {}
        self.escalamientos: dict[int, dict[str, Any]] = {}
        self.valoraciones: dict[str, dict[str, Any]] = {}

    async def sincronizar(self, estado: dict[str, Any], traza_url: str | None = None) -> None:
        case_id = estado["case_id"]
        estado_caso, resultado = estado_bd(estado)
        self.casos[case_id] = {
            "estado": estado_caso,
            "resultado": resultado,
            "estado_caso": estado,
            "eventos": list(estado.get("linea_tiempo") or []),
        }
        ficha = estado.get("escalamiento")
        if ficha and not any(e["case_id"] == case_id for e in self.escalamientos.values()):
            nuevo_id = len(self.escalamientos) + 1
            self.escalamientos[nuevo_id] = {
                "id": nuevo_id,
                "case_id": case_id,
                "motivo": ficha["motivo"],
                "paquete": {**ficha, "traza_url": traza_url},
                "estado": "abierto",
                "asignado_a": None,
                "completo_sin_repregunta": None,
                "creado_en": ficha.get("creado_en"),
            }

    async def cargar_estado(self, case_id: str) -> dict[str, Any] | None:
        caso = self.casos.get(case_id)
        return dict(caso["estado_caso"]) if caso else None

    async def registrar_valoracion(self, case_id: str, util: bool, comentario: str | None) -> bool:
        if case_id in self.valoraciones:
            return False
        self.valoraciones[case_id] = {"util": util, "comentario": comentario}
        return True

    async def metricas(self, dias: int = 30) -> dict[str, Any]:
        resultados = [c["resultado"] for c in self.casos.values()]
        preguntas = [((c["estado_caso"].get("metricas") or {}).get("preguntas") or 0) for c in self.casos.values()]
        return {
            "casos": len(resultados),
            "resueltos": resultados.count("resuelto"),
            "escalados": resultados.count("escalado"),
            "vinculados_masivo": resultados.count("vinculado_masivo"),
            "preguntas_promedio": sum(preguntas) / len(preguntas) if preguntas else 0,
            "acciones_sin_token": 0,
            "banderas": sum(
                len((c["estado_caso"].get("seguridad") or {}).get("banderas") or []) for c in self.casos.values()
            ),
            "escalamientos_completos": sum(1 for e in self.escalamientos.values() if e["completo_sin_repregunta"]),
            "valoraciones": len(self.valoraciones),
            "valoraciones_utiles": sum(1 for v in self.valoraciones.values() if v["util"]),
            "escalamientos_evaluados": sum(
                1 for e in self.escalamientos.values() if e["completo_sin_repregunta"] is not None
            ),
        }

    async def listar_escalamientos(self) -> list[dict[str, Any]]:
        return sorted(self.escalamientos.values(), key=lambda e: e["id"], reverse=True)

    async def tomar_escalamiento(self, escalamiento_id: int, tecnico_id: str) -> bool:
        e = self.escalamientos.get(escalamiento_id)
        if not e or e["estado"] != "abierto":
            return False
        e.update(estado="tomado", asignado_a=tecnico_id)
        return True

    async def evaluar_escalamiento(self, escalamiento_id: int, completo: bool) -> dict[str, Any] | None:
        e = self.escalamientos.get(escalamiento_id)
        if e:
            e["completo_sin_repregunta"] = completo
        return e

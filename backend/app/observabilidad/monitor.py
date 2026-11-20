"""Bus de eventos en memoria del Monitor de agentes (ADR 0023).

- Pub/sub dentro del proceso: cada suscriptor (una pestaña del monitor) tiene su cola acotada. Si se llena, el
  evento se descarta: publicar nunca bloquea ni espera.
- Solo metadatos: nombre del agente o nodo, tipo, duración, error, caso, etapa y URL de la traza. Nunca el texto
  del usuario, respuestas del LLM, `input`/`output` de observaciones, logs, capturas, parámetros ni tokens.
- `publicar()` nunca lanza excepciones y, sin suscriptores, sale en la primera línea: el chat no depende del
  monitor (igual que con Langfuse).
- Un solo proceso (un worker de uvicorn, como corre hoy). Con varias réplicas se usaría `LISTEN/NOTIFY` de Postgres.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
import time
from contextvars import ContextVar, Token
from typing import Any

from app.config.ajustes import obtener_ajustes

log = logging.getLogger(__name__)

MAX_COLA = 500
MAX_SUSCRIPTORES = 20
MAX_ETIQUETA = 80

# Caso del turno en curso: lo fija /api/chat; los agentes no lo tocan.
caso_actual: ContextVar[str | None] = ContextVar("monitor_caso_actual", default=None)

# cola -> bucle de eventos del suscriptor (por si alguien publica desde otro hilo)
_suscriptores: dict[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop] = {}
_seq = itertools.count(1)
_NO_PERMITIDO = re.compile(r"[^\w.:\-]")


def activo() -> bool:
    try:
        return bool(obtener_ajustes().monitor_activo)
    except Exception:  # noqa: BLE001 - el monitor nunca tumba la app
        return False


def etiqueta(valor: object) -> str:
    """Nombre seguro para el stream: solo `[A-Za-z0-9_.:-]`, recortado. Nunca texto libre."""
    return _NO_PERMITIDO.sub("_", str(valor))[:MAX_ETIQUETA]


def _limpio(valor: object) -> object:
    if valor is None or isinstance(valor, bool | int | float):
        return valor
    return str(valor)[:500]


def _poner(cola: asyncio.Queue[dict[str, Any]], evento: dict[str, Any]) -> None:
    try:
        cola.put_nowait(evento)
    except asyncio.QueueFull:
        pass  # cliente lento: se descarta el evento, nunca se espera


def publicar(tipo: str, **datos: Any) -> None:
    """Envía un evento a los monitores conectados. Nunca lanza ni bloquea."""
    if not _suscriptores:
        return
    try:
        if not activo():
            return
        evento: dict[str, Any] = {
            "tipo": etiqueta(tipo),
            "caso": caso_actual.get(),
            "ts": int(time.time() * 1000),
            "seq": next(_seq),
        }
        for clave, valor in datos.items():
            evento[clave] = _limpio(valor)
        try:
            bucle_actual = asyncio.get_running_loop()
        except RuntimeError:
            bucle_actual = None
        for cola, bucle in list(_suscriptores.items()):
            if bucle is bucle_actual:
                _poner(cola, evento)
            else:
                bucle.call_soon_threadsafe(_poner, cola, evento)
    except Exception:  # noqa: BLE001 - el monitor nunca tumba la app
        log.debug("No pude publicar el evento %s del monitor", tipo, exc_info=True)


def agente_inicio(nombre: str, tipo: str) -> float:
    """Marca el inicio de una observación; devuelve el reloj para medir la duración."""
    inicio = time.perf_counter()
    publicar("agente_inicio", agente=etiqueta(nombre), tipo_observacion=etiqueta(tipo))
    return inicio


def agente_fin(nombre: str, tipo: str, inicio: float, error: bool) -> None:
    if not _suscriptores:
        return
    publicar(
        "agente_fin",
        agente=etiqueta(nombre),
        tipo_observacion=etiqueta(tipo),
        duracion_ms=round((time.perf_counter() - inicio) * 1000, 1),
        error=bool(error),
    )


def fijar_caso(case_id: str) -> Token[str | None] | None:
    try:
        return caso_actual.set(etiqueta(case_id))
    except Exception:  # noqa: BLE001
        return None


def liberar_caso(ficha: Token[str | None] | None) -> None:
    if ficha is None:
        return
    try:
        caso_actual.reset(ficha)
    except Exception:  # noqa: BLE001 - p. ej., el generador se cerró desde otro contexto
        log.debug("No pude restaurar el caso del monitor", exc_info=True)


def hay_cupo() -> bool:
    return len(_suscriptores) < MAX_SUSCRIPTORES


def suscribir() -> asyncio.Queue[dict[str, Any]] | None:
    """Abre una cola para un monitor. None si se alcanzó el tope de suscriptores."""
    if not hay_cupo():
        return None
    cola: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=MAX_COLA)
    _suscriptores[cola] = asyncio.get_running_loop()
    return cola


def desuscribir(cola: asyncio.Queue[dict[str, Any]]) -> None:
    _suscriptores.pop(cola, None)


def suscriptores() -> int:
    return len(_suscriptores)


def reiniciar_para_pruebas() -> None:
    _suscriptores.clear()

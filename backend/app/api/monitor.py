"""Monitor de agentes (ADR 0023): grafo y stream en vivo de nodos y agentes. Solo N2 y revisor KB.

El stream es SSE propio (`data: {json}\\n\\n` + latido `: ping`), NO el UI Message Stream del chat
(`stream_protocol.py`): es otro contrato. Solo metadatos (ver `app/observabilidad/monitor.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.config.ajustes import obtener_ajustes
from app.directorio.repositorio import Persona, Rol
from app.observabilidad import monitor
from app.seguridad.limite_tasa import LimiteTasa
from app.seguridad.ver_como import requiere_rol

log = logging.getLogger(__name__)

LATIDO_S = 15.0
# Aperturas del stream por persona y minuto (la reconexión con backoff del cliente queda muy por debajo).
_limite_aperturas = LimiteTasa(30)


def _exigir_activo() -> None:
    if not obtener_ajustes().monitor_activo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


# Las dependencias del router se resuelven antes que las del endpoint: con el monitor apagado, 404 para todos.
router = APIRouter(prefix="/api/monitor", dependencies=[Depends(_exigir_activo)])
_Roles = Annotated[Persona, Depends(requiere_rol(Rol.N2, Rol.REVISOR_KB))]


@router.get("/grafo")
async def grafo(request: Request, persona: _Roles) -> dict[str, list[dict[str, Any]]]:
    """Nodos y aristas del grafo compilado (generados, no a mano: un nodo nuevo aparece solo)."""
    g = request.app.state.grafo.get_graph()
    return {
        "nodos": [{"id": monitor.etiqueta(n)} for n in g.nodes],
        "aristas": [
            {"origen": monitor.etiqueta(a.source), "destino": monitor.etiqueta(a.target), "condicional": a.conditional}
            for a in g.edges
        ],
    }


async def emitir(
    cola: asyncio.Queue[dict[str, Any]] | None,
    desconectado: Callable[[], Awaitable[bool]],
    latido_s: float = LATIDO_S,
) -> AsyncIterator[str]:
    """Bloques SSE: eventos de la cola y un latido cada `latido_s` (proxies y túneles no cortan la conexión)."""
    if cola is None:
        yield 'data: {"tipo": "monitor_lleno"}\n\n'
        return
    try:
        yield ": conectado\n\n"
        while not await desconectado():
            try:
                evento = await asyncio.wait_for(cola.get(), timeout=latido_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
    finally:
        monitor.desuscribir(cola)  # sin fugas: la cola desaparece con el cliente


@router.get("/stream")
async def stream(request: Request, persona: _Roles) -> StreamingResponse:
    ok, espera = _limite_aperturas.permitir(persona.id)
    if not ok:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas conexiones seguidas", headers={"Retry-After": str(espera)}
        )
    if not monitor.hay_cupo():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El monitor alcanzó el máximo de conexiones")

    async def cuerpo() -> AsyncIterator[str]:
        # Se suscribe al empezar a emitir: si el cliente se va antes, no queda una cola huérfana.
        async for bloque in emitir(monitor.suscribir(), request.is_disconnected):
            yield bloque

    return StreamingResponse(
        cuerpo(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

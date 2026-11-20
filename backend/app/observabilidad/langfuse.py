"""Fachada de Langfuse (SDK v5) para todo el backend.

- Si faltan las claves, todo es no-op: la app funciona igual (Langfuse nunca bloquea).
- Sesión = case_id; user_id = persona; nombres de observación estables (CLAUDE.md).
- `mask` quita datos personales antes de enviar (correos, rutas de usuario).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from app.config.ajustes import Ajustes, obtener_ajustes
from app.observabilidad import monitor

log = logging.getLogger(__name__)

_RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_RE_RUTA_USUARIO = re.compile(r"(?i)([a-z]:\\users\\|/home/|/users/)[^\\/\s\"']+")


def enmascarar_texto(texto: str) -> str:
    texto = _RE_CORREO.sub("<correo>", texto)
    return _RE_RUTA_USUARIO.sub(lambda m: m.group(1) + "<usuario>", texto)


def _mask(*, data: Any, **_: Any) -> Any:
    if isinstance(data, str):
        return enmascarar_texto(data)
    if isinstance(data, dict):
        return {k: _mask(data=v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [_mask(data=v) for v in data]
    return data


class _Nada:
    """Observación nula cuando Langfuse está desactivado."""

    id = None

    def update(self, **_: Any) -> None:
        return None


_cliente: Any = None
_inicializado = False


def obtener_langfuse(ajustes: Ajustes | None = None) -> Any:
    global _cliente, _inicializado
    if _inicializado:
        return _cliente
    ajustes = ajustes or obtener_ajustes()
    _inicializado = True
    if not ajustes.langfuse_activo:
        log.warning("Langfuse desactivado: faltan LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY")
        return None
    try:
        from langfuse import Langfuse

        _cliente = Langfuse(
            public_key=ajustes.langfuse_public_key,
            secret_key=ajustes.langfuse_secret_key,
            base_url=ajustes.langfuse_host,
            environment=ajustes.entorno,
            mask=_mask,
        )
    except Exception:  # noqa: BLE001 - la observabilidad nunca tumba la app
        log.exception("No se pudo inicializar Langfuse; sigo sin trazas")
        _cliente = None
    return _cliente


def reiniciar_para_pruebas(cliente: Any = None) -> None:
    global _cliente, _inicializado
    _cliente, _inicializado = cliente, cliente is not None


@contextmanager
def observacion(nombre: str, tipo: str = "span", **kwargs: Any) -> Iterator[Any]:
    # Monitor de agentes (ADR 0023): inicio/fin con duración y error, en ambas ramas. Solo metadatos.
    inicio_monitor = monitor.agente_inicio(nombre, tipo)
    error_monitor = False
    try:
        lf = obtener_langfuse()
        if lf is None:
            yield _Nada()
            return
        with lf.start_as_current_observation(as_type=tipo, name=nombre, **kwargs) as obs:
            yield obs
    except BaseException:
        error_monitor = True
        raise  # la excepción del llamador sigue idéntica
    finally:
        monitor.agente_fin(nombre, tipo, inicio_monitor, error_monitor)


def atributos_traza(
    *,
    session_id: str,
    user_id: str,
    nombre_traza: str,
    tags: list[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> Any:
    lf = obtener_langfuse()
    if lf is None:
        return nullcontext()
    from langfuse import propagate_attributes

    return propagate_attributes(
        session_id=session_id[:200],
        user_id=user_id[:200],
        trace_name=nombre_traza,
        tags=tags or [],
        metadata={k: str(v)[:200] for k, v in (metadata or {}).items()},
    )


def evento(nombre: str, **kwargs: Any) -> None:
    lf = obtener_langfuse()
    if lf is not None:
        lf.create_event(name=nombre, **kwargs)


def score_traza(nombre: str, valor: float | str, comentario: str | None = None) -> None:
    lf = obtener_langfuse()
    if lf is not None:
        lf.score_current_trace(name=nombre, value=valor, comment=comentario)


def score_por_traza(traza_url: str | None, nombre: str, valor: float, comentario: str | None = None) -> None:
    """Score humano (cola de anotación de N2) sobre la traza del turno que escaló."""
    lf = obtener_langfuse()
    if lf is None or not traza_url or "/traces/" not in traza_url:
        return
    trace_id = traza_url.rsplit("/traces/", 1)[1].split("?")[0]
    lf.create_score(name=nombre, value=valor, trace_id=trace_id, comment=comentario)


def score_por_sesion(session_id: str, nombre: str, valor: float, comentario: str | None = None) -> None:
    """Score de todo el caso (p. ej., la valoración del usuario al cerrar o escalar)."""
    lf = obtener_langfuse()
    if lf is None:
        return
    try:
        lf.create_score(name=nombre, value=valor, session_id=session_id, comment=comentario)
    except Exception:  # noqa: BLE001 - Langfuse nunca bloquea
        log.warning("No pude registrar el score %s", nombre, exc_info=True)


def url_traza_actual(ajustes: Ajustes | None = None) -> str | None:
    lf = obtener_langfuse()
    if lf is None:
        return None
    ajustes = ajustes or obtener_ajustes()
    try:
        trace_id = lf.get_current_trace_id()
        if not trace_id:
            return None
        # Consulta la API de Langfuse (id del proyecto): si no responde, el turno sigue sin enlace.
        url = lf.get_trace_url(trace_id=trace_id)
    except Exception:  # noqa: BLE001 - la observabilidad nunca tumba el turno
        log.warning("No pude obtener la URL de la traza en Langfuse; sigo sin enlace", exc_info=True)
        return None
    if url and ajustes.langfuse_url_publica:
        url = url.replace(ajustes.langfuse_host.rstrip("/"), ajustes.langfuse_url_publica.rstrip("/"))
    return url


def obtener_prompt(nombre: str, fallback: str, etiqueta: str | None = None) -> tuple[str, Any]:
    """Devuelve (texto, objeto_prompt|None). Con fallback embebido si Langfuse no responde."""
    lf = obtener_langfuse()
    if lf is None:
        return fallback, None
    etiqueta = etiqueta or obtener_ajustes().langfuse_etiqueta_prompts
    try:
        prompt = lf.get_prompt(nombre, label=etiqueta, type="text", fallback=fallback, cache_ttl_seconds=60)
        texto = prompt.compile()
        es_fallback = bool(getattr(prompt, "is_fallback", False))
        return texto, (None if es_fallback else prompt)
    except Exception:  # noqa: BLE001
        log.warning("Prompt '%s' no disponible en Langfuse; uso el embebido", nombre)
        return fallback, None


def flush() -> None:
    lf = obtener_langfuse()
    if lf is not None:
        lf.flush()

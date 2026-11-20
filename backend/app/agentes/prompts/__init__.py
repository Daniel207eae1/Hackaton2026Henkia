"""Prompts embebidos (fallback). La versión vigente vive en Langfuse Prompt Management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent


def prompt_embebido(nombre: str) -> str:
    return (_DIR / f"{nombre}.md").read_text(encoding="utf-8")


def prompt_vigente(nombre: str, marcador: str | None = None) -> tuple[str, Any]:
    """(texto, prompt de Langfuse|None). Sin `marcador`: la versión vigente de Langfuse (o la embebida).
    Con `marcador` (cuarentena): siempre la embebida; ver abajo."""
    from app.observabilidad.langfuse import obtener_prompt

    embebido = prompt_embebido(nombre)
    texto, prompt_lf = obtener_prompt(nombre, embebido)
    if marcador is None:
        return texto, prompt_lf
    # Prompts de cuarentena (extractor, visión, curador): manda SIEMPRE el texto revisado del repo. Langfuse solo
    # liga la generación a su versión si es idéntica; una versión distinta se ignora y queda como bandera.
    if texto.strip() != embebido.strip():
        if prompt_lf is not None:
            from app.observabilidad.langfuse import evento

            evento("seguridad.bandera", metadata={"bandera": "prompt_cuarentena_distinto", "prompt": nombre})
        return embebido.format(m=marcador), None
    return embebido.format(m=marcador), prompt_lf

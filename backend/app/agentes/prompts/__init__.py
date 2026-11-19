"""Prompts embebidos (fallback). La versión vigente vive en Langfuse Prompt Management."""

from pathlib import Path

_DIR = Path(__file__).parent


def prompt_embebido(nombre: str) -> str:
    return (_DIR / f"{nombre}.md").read_text(encoding="utf-8")

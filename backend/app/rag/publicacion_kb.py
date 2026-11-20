"""Publicación de una propuesta aprobada en la KB (Módulo A, ADR 0019).

`app_rw` NO escribe `conocimiento.articulos` ni `kb_fragmentos`: la publicación pasa por la función de P2
`conocimiento.publicar_propuesta(propuesta, revisor, fragmentos)` (SECURITY DEFINER). Aquí solo se prepara lo que
esa función recibe: las secciones del borrador ya revisado por una persona, con su *embedding* (mismo modelo que la
KB de P2) para que el artículo sea encontrable de inmediato.

Antes de publicar, el texto pasa por la guardia heurística: un borrador con una orden incrustada no entra a la KB
(la KB la leen después el diagnóstico y la guía).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.seguridad.extractor_cuarentena import heuristica_instrucciones
from app.seguridad.guardia_entrada import analizar

# Encabezado del borrador (`## Síntoma`) → sección de `kb_fragmentos` (las mismas que usa P2).
SECCIONES = {"sintoma": "sintoma", "causa": "causa", "pasos": "pasos", "verificacion": "verificacion"}
_PENDIENTE = re.compile(r"por (redactar|confirmar)", re.IGNORECASE)
MAX_TEXTO_SECCION = 2000


class PublicacionRechazada(ValueError):
    """La propuesta no se puede publicar tal como está (el revisor debe devolverla)."""


@dataclass
class Fragmento:
    seccion: str
    orden: int
    texto: str
    embedding: list[float] | None = None

    def a_dict(self) -> dict[str, Any]:
        return {"seccion": self.seccion, "orden": self.orden, "texto": self.texto, "embedding": self.embedding}


def _clave(encabezado: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", encabezado).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower()


def secciones_del_borrador(md: str) -> dict[str, str]:
    """`## Encabezado` → texto. El pie (`---` con casos de soporte y aviso de borrador) no se publica."""
    cuerpo = md.split("\n---\n", 1)[0]
    salida: dict[str, str] = {}
    actual: str | None = None
    lineas: list[str] = []
    for linea in cuerpo.splitlines():
        if linea.startswith("## "):
            if actual:
                salida[actual] = "\n".join(lineas).strip()
            actual, lineas = _clave(linea[3:]), []
        elif actual:
            lineas.append(linea)
    if actual:
        salida[actual] = "\n".join(lineas).strip()
    return salida


def fragmentos_de(titulo: str, borrador_md: str) -> list[Fragmento]:
    """Valida el borrador y lo parte en las secciones de la KB. Lanza `PublicacionRechazada` si no está listo."""
    if _PENDIENTE.search(borrador_md):
        raise PublicacionRechazada(
            "El borrador aún tiene pasos por redactar o confirmar: devuélvelo con un comentario."
        )
    secs = secciones_del_borrador(borrador_md)
    faltan = [s for s in ("sintoma", "causa", "pasos") if not secs.get(s)]
    if faltan:
        raise PublicacionRechazada(f"Al borrador le faltan secciones: {', '.join(faltan)}.")
    frags = [Fragmento("resumen", 0, f"{titulo.strip()}. {secs['causa']}"[:MAX_TEXTO_SECCION])]
    frags += [
        Fragmento(SECCIONES[k], 0, v[:MAX_TEXTO_SECCION]) for k, v in secs.items() if k in SECCIONES and v.strip()
    ]
    for t in [titulo, *(f.texto for f in frags)]:
        # Igual o más estricta que la Guía (que también descarta `prohibida:*` e `identidad`).
        if heuristica_instrucciones(t) or analizar(t).banderas:
            raise PublicacionRechazada(
                "El borrador contiene texto con forma de instrucción o una acción no permitida; no se publica."
            )
    return frags


async def con_embeddings(frags: list[Fragmento], embeddings: Any) -> list[Fragmento]:
    """Embebe cada sección con el mismo texto que P2 (`texto`). Si el servicio falla, se publica sin vector
    (la búsqueda léxica la encuentra igual) y P2 puede re-embeber los fragmentos con `embedding` nulo."""
    if embeddings is None:
        return frags
    try:
        vectores = await embeddings.embeddings([f.texto for f in frags])
    except Exception:  # noqa: BLE001 - la publicación no depende del servicio de embeddings
        return frags
    for f, v in zip(frags, vectores, strict=False):
        f.embedding = list(v)
    return frags


def contenido_publicable(titulo: str, frags: list[Fragmento]) -> str:
    """El `contenido_md` del artículo se RECONSTRUYE con las secciones validadas: el pie, «Cambios propuestos» y
    cualquier encabezado fuera de la lista nunca llegan a la KB."""
    nombres = {"sintoma": "Síntoma", "causa": "Causa", "pasos": "Pasos", "verificacion": "Verificación"}
    partes = [f"# {titulo.strip()}"] + [
        f"## {nombres[f.seccion]}{chr(10)}{f.texto}" for f in frags if f.seccion in nombres
    ]
    return (chr(10) * 2).join(partes) + chr(10)

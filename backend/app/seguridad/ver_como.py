"""Dependencia "Ver como" (ADR 0006).

- Solo con MODO_DEMO=true; si no, 403 ante cualquier `X-Ver-Como`.
- La persona y su rol se buscan en el directorio (BD). Nada del cuerpo ni del chat cuenta.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from app.config.ajustes import obtener_ajustes
from app.directorio.repositorio import Persona, Rol

# USR-001, TEC-01, REV-01 (BD de P2) y USR-SIM-001 (doble en memoria).
_ID_VALIDO = re.compile(r"^[A-Z]{3}-(SIM-)?[0-9A-Z]{1,6}$")


async def persona_actual(
    request: Request,
    x_ver_como: Annotated[str | None, Header(alias="X-Ver-Como")] = None,
) -> Persona:
    ajustes = obtener_ajustes()
    if not ajustes.modo_demo:
        # Sin modo demo no hay "Ver como". Aquí iría la autenticación real.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "«Ver como» solo está disponible en modo demo")
    if not x_ver_como or not _ID_VALIDO.match(x_ver_como):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Elige a quién «ver como»")
    persona = await request.app.state.directorio.obtener_persona(x_ver_como)
    if persona is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Persona desconocida en el directorio")
    return persona


def requiere_rol(*roles: Rol) -> Callable[..., Coroutine[Any, Any, Persona]]:
    async def _dep(persona: Annotated[Persona, Depends(persona_actual)]) -> Persona:
        if persona.rol not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu rol no permite esta acción")
        return persona

    return _dep

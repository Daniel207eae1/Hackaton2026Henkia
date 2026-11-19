"""Repositorio del directorio sobre el esquema `org` de P2 (PostgreSQL).

- El ROL sale de `org.usuarios.rol` (fuente de verdad), nunca del chat ni de `personas_demo`.
- `org.personas_demo` solo define quién aparece en el selector «Ver como» y con qué etiqueta.
- La conexión asume el rol `app_rw` (sin acceso a `evaluacion`): ver `app/main.py`.
- SQL siempre parametrizado.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.directorio.repositorio import Persona, Rol

# rol en org.usuarios → rol de la aplicación
ROLES_BD: dict[str, Rol] = {
    "colaborador": Rol.COLABORADOR,
    "tecnico_n2": Rol.N2,
    "n2": Rol.N2,
    "revisor_kb": Rol.REVISOR_KB,
}

_SELECT = """
    select u.id, u.nombre, u.correo, u.rol, u.area, u.nivel_tecnico,
           e.id as equipo_id, e.hostname, pd.etiqueta, pd.orden
    from org.usuarios u
    left join org.personas_demo pd on pd.usuario_id = u.id
    left join lateral (
        select id, hostname from org.equipos where usuario_asignado_id = u.id order by id limit 1
    ) e on true
"""


def fila_a_persona(f: dict[str, Any]) -> Persona | None:
    rol = ROLES_BD.get(str(f.get("rol") or "").lower())
    if rol is None:
        return None  # rol desconocido en la BD: no se puede «ver como» esa persona
    return Persona(
        id=f["id"],
        nombre=f["nombre"],
        correo=f.get("correo") or "",
        rol=rol,
        area=f.get("area") or "",
        equipo_id=f.get("equipo_id"),
        nivel_tecnico=f.get("nivel_tecnico"),
        etiqueta=f.get("etiqueta"),
        hostname=f.get("hostname"),
    )


class RepositorioDirectorioPostgres:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def listar_personas_demo(self) -> list[Persona]:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                _SELECT + " where pd.usuario_id is not null and coalesce(u.activo, true) order by pd.orden"
            )
            return [p for f in await cur.fetchall() if (p := fila_a_persona(f))]

    async def obtener_persona(self, persona_id: str) -> Persona | None:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SELECT + " where u.id = %s and coalesce(u.activo, true)", (persona_id,))
            fila = await cur.fetchone()
            return fila_a_persona(fila) if fila else None

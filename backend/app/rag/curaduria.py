"""Repositorio del Módulo A (F8): historial y artículos (solo lectura) + `conocimiento.propuestas_kb`
(la ÚNICA tabla de conocimiento con escritura para `app_rw`). SQL parametrizado."""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass
class Propuesta:
    id: int
    tipo: str  # articulo_faltante | articulo_desactualizado
    articulo_id: str | None
    categoria_id: str | None
    titulo: str
    borrador_md: str
    casos_soporte: list[str]
    justificacion: str | None
    estado: str = "pendiente"  # pendiente | aprobada | rechazada | publicada
    revisor_id: str | None = None
    comentario_revision: str | None = None
    creado_en: str | None = None
    revisado_en: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)


class RepositorioCuraduria(Protocol):
    async def casos(self) -> list[dict[str, Any]]: ...

    async def articulos(self) -> list[dict[str, Any]]: ...

    async def claves_existentes(self) -> set[str]: ...

    async def crear(self, p: dict[str, Any]) -> Propuesta: ...

    async def listar(self) -> list[Propuesta]: ...

    async def revisar(self, pid: int, estado: str, revisor_id: str, comentario: str | None) -> Propuesta | None: ...

    async def obtener(self, pid: int) -> Propuesta | None: ...

    async def publicar(
        self, pid: int, revisor_id: str, fragmentos: list[dict[str, Any]], modelo_embedding: str
    ) -> Publicacion | None: ...


@dataclass
class Publicacion:
    propuesta: Propuesta
    articulo_id: str | None  # None: aprobada, a la espera de que P2 habilite `publicar_propuesta`
    en_kb: bool


def _iso(v: Any) -> str | None:
    return v.isoformat(timespec="seconds") if isinstance(v, datetime) else (str(v) if v else None)


def _propuesta(f: dict[str, Any]) -> Propuesta:
    return Propuesta(
        id=f["id"],
        tipo=f["tipo"],
        articulo_id=f["articulo_id"],
        categoria_id=f["categoria_id"],
        titulo=f["titulo"],
        borrador_md=f["borrador_md"],
        casos_soporte=list(f["casos_soporte"] or []),
        justificacion=f["justificacion"],
        estado=f["estado"],
        revisor_id=f["revisor_id"],
        comentario_revision=f["comentario_revision"],
        creado_en=_iso(f["creado_en"]),
        revisado_en=_iso(f["revisado_en"]),
    )


def _contenido(titulo: str, fragmentos: list[dict[str, Any]]) -> str:
    from app.rag.publicacion_kb import Fragmento, contenido_publicable

    return contenido_publicable(titulo, [Fragmento(f["seccion"], f.get("orden", 0), f["texto"]) for f in fragmentos])


def clave_de(justificacion: str | None) -> str | None:
    """La clave del grupo va en la primera línea de la justificación: `[clave=...]` (idempotencia del lote)."""
    if justificacion and justificacion.startswith("[clave="):
        return justificacion[7 : justificacion.find("]")]
    return None


class RepositorioCuraduriaPostgres:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def _todas(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def casos(self) -> list[dict[str, Any]]:
        # Solo casos cerrados del historial; el conjunto de prueba queda fuera (es para evaluar, F9).
        return await self._todas(
            "select id, categoria_id, sintoma_texto, causa, solucion, solucion_normalizada, articulo_id, version_app,"
            " fecha, resultado from conocimiento.historial_casos where conjunto = 'entrenamiento'"
        )

    async def articulos(self) -> list[dict[str, Any]]:
        return await self._todas(
            "select id, titulo, categoria_id, versiones_aplicables, fecha_actualizacion, estado, contenido_md,"
            " receta, coalesce(marcado_inyeccion, false) as marcado_inyeccion from conocimiento.articulos"
        )

    async def claves_existentes(self) -> set[str]:
        filas = await self._todas(
            "select justificacion from conocimiento.propuestas_kb where estado in ('pendiente','aprobada','publicada')"
        )
        return {k for f in filas if (k := clave_de(f["justificacion"]))}

    async def crear(self, p: dict[str, Any]) -> Propuesta:
        filas = await self._todas(
            """insert into conocimiento.propuestas_kb (tipo, articulo_id, categoria_id, titulo, borrador_md,
                   casos_soporte, justificacion) values (%s, %s, %s, %s, %s, %s, %s) returning *""",
            (
                p["tipo"],
                p.get("articulo_id"),
                p.get("categoria_id"),
                p["titulo"],
                p["borrador_md"],
                p["casos_soporte"],
                p["justificacion"],
            ),
        )
        return _propuesta(filas[0])

    async def listar(self) -> list[Propuesta]:
        filas = await self._todas(
            "select * from conocimiento.propuestas_kb order by (estado = 'pendiente') desc, creado_en desc limit 100"
        )
        return [_propuesta(f) for f in filas]

    async def revisar(self, pid: int, estado: str, revisor_id: str, comentario: str | None) -> Propuesta | None:
        filas = await self._todas(
            """update conocimiento.propuestas_kb set estado = %s, revisor_id = %s, comentario_revision = %s,
                   revisado_en = now() where id = %s and estado = 'pendiente' returning *""",
            (estado, revisor_id, comentario, pid),
        )
        return _propuesta(filas[0]) if filas else None

    async def obtener(self, pid: int) -> Propuesta | None:
        filas = await self._todas("select * from conocimiento.propuestas_kb where id = %s", (pid,))
        return _propuesta(filas[0]) if filas else None

    async def publicar(
        self, pid: int, revisor_id: str, fragmentos: list[dict[str, Any]], modelo_embedding: str
    ) -> Publicacion | None:
        """Publica con la función de P2 (única vía de escritura a la KB). Si P2 aún no la creó, la propuesta queda
        `aprobada`: el lote no la repite y P2 la publica cuando habilite la función (ADR 0019)."""
        try:
            filas = await self._todas(
                "select conocimiento.publicar_propuesta(%s, %s, %s::jsonb, %s) as articulo_id",
                (pid, revisor_id, Jsonb(fragmentos), modelo_embedding),
            )
        except errors.UndefinedFunction as e:
            if "publicar_propuesta" not in (e.diag.message_primary or ""):
                raise  # falla DENTRO de la función (p. ej., un tipo que no resuelve): no se oculta
            actual = await self.obtener(pid)
            if actual and actual.estado == "aprobada":  # reintento: sigue aprobada, sin error
                return Publicacion(actual, None, False)
            p = await self.revisar(pid, "aprobada", revisor_id, None)
            return Publicacion(p, None, False) if p else None
        except errors.RaiseException:  # la función rechazó: no existe, ya revisada o revisor sin rol
            return None
        p = await self.obtener(pid)
        return Publicacion(p, filas[0]["articulo_id"], True) if p else None


class RepositorioCuraduriaMemoria:
    def __init__(self, casos: list[dict[str, Any]] | None = None, articulos: list[dict[str, Any]] | None = None):
        self._casos = casos or []
        self._articulos = articulos or []
        self.propuestas: dict[int, Propuesta] = {}
        self.fragmentos: dict[str, list[dict[str, Any]]] = {}
        self._ids = itertools.count(1)

    async def casos(self) -> list[dict[str, Any]]:
        return list(self._casos)

    async def articulos(self) -> list[dict[str, Any]]:
        return list(self._articulos)

    async def claves_existentes(self) -> set[str]:
        return {
            k
            for p in self.propuestas.values()
            if p.estado in ("pendiente", "aprobada", "publicada") and (k := clave_de(p.justificacion))
        }

    async def crear(self, p: dict[str, Any]) -> Propuesta:
        pid = next(self._ids)
        prop = Propuesta(
            pid,
            p["tipo"],
            p.get("articulo_id"),
            p.get("categoria_id"),
            p["titulo"],
            p["borrador_md"],
            list(p["casos_soporte"]),
            p["justificacion"],
            creado_en=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self.propuestas[pid] = prop
        return prop

    async def listar(self) -> list[Propuesta]:
        return sorted(self.propuestas.values(), key=lambda p: (p.estado != "pendiente", -p.id))

    async def revisar(self, pid: int, estado: str, revisor_id: str, comentario: str | None) -> Propuesta | None:
        p = self.propuestas.get(pid)
        if not p or p.estado != "pendiente":
            return None
        p.estado, p.revisor_id, p.comentario_revision = estado, revisor_id, comentario
        p.revisado_en = datetime.now(UTC).isoformat(timespec="seconds")
        return p

    async def obtener(self, pid: int) -> Propuesta | None:
        return self.propuestas.get(pid)

    async def publicar(
        self, pid: int, revisor_id: str, fragmentos: list[dict[str, Any]], modelo_embedding: str
    ) -> Publicacion | None:
        """Doble de `conocimiento.publicar_propuesta`: crea/actualiza el artículo y sus fragmentos en memoria."""
        p = self.propuestas.get(pid)
        if not p or p.estado not in ("pendiente", "aprobada"):
            return None
        if p.tipo == "articulo_desactualizado" and p.articulo_id:
            aid = p.articulo_id
        else:
            n = max(
                (int(a["id"].rsplit("-", 1)[1]) for a in self._articulos if a.get("id", "").startswith("KB-SIM-")),
                default=0,
            )
            aid = f"KB-SIM-{n + 1:03d}"
        self._articulos = [a for a in self._articulos if a.get("id") != aid] + [
            {
                "id": aid,
                "titulo": p.titulo,
                "categoria_id": p.categoria_id,
                "contenido_md": _contenido(p.titulo, fragmentos),
                "estado": "publicado",
            }
        ]
        self.fragmentos[aid] = list(fragmentos)
        p.estado, p.revisor_id = "publicada", revisor_id
        p.revisado_en = datetime.now(UTC).isoformat(timespec="seconds")
        return Publicacion(p, aid, True)


@dataclass
class Grupo:
    """Hallazgo del lote (decidido en código) que el curador redacta."""

    tipo: str
    clave: str
    categoria_id: str | None
    articulo_id: str | None
    casos: list[dict[str, Any]]
    motivo: str
    datos: dict[str, Any] = field(default_factory=dict)

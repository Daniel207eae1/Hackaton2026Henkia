"""Reportes de usuarios e incidentes masivos (F2, §3.11) sobre `operacion` de P2 (rol `app_rw`).

- `operacion.reportes`: un reporte por caso con su texto canónico (`app · síntoma · texto`, el formato de
  P2) y su *embedding*; `buscar_reportes_similares` (P2) hace la búsqueda híbrida en la ventana.
- `operacion.incidentes_masivos`: `publicado` = el estado oficial (se cita tal cual); `propuesto` = posible
  masivo del clúster que N2 confirma (con mensaje obligatorio) o descarta; `resuelto` → se avisa a los
  vinculados (`incidente_casos`, lo escribe la proyección ITSM).
SQL parametrizado. El mensaje oficial es texto externo: se revisa con la guardia antes de mostrarlo.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.rag.kb import _lit

ACTIVOS = ("propuesto", "publicado")
MAX_REINTENTOS_ID = 50


@dataclass
class Incidente:
    id: str
    servicio_id: str
    categoria_id: str | None
    titulo: str
    estado: str  # detectado | propuesto | publicado | descartado | resuelto
    origen: str
    mensaje_oficial: str | None = None
    publicado_en: str | None = None
    resuelto_en: str | None = None
    confirmado_por: str | None = None
    regla: dict[str, Any] = field(default_factory=dict)
    casos_vinculados: int = 0

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Cluster:
    usuarios_distintos: int
    reportes: list[int]
    similitud_max: float = 0.0


class RepositorioMasivos(Protocol):
    async def registrar_reporte(
        self,
        *,
        usuario_id: str,
        equipo_id: str | None,
        texto: str,
        texto_canonico: str,
        categoria: str,
        confianza: float,
        vector: list[float],
        modelo: str,
        reportado_en: str | None,
    ) -> int | None: ...

    async def similares(
        self,
        vector: list[float],
        texto_canonico: str,
        categoria: str,
        usuario_excluido: str,
        ventana_min: int,
        umbral: float,
        referencia: str | None,
    ) -> Cluster: ...

    async def incidente_activo(self, categoria: str, servicio: str) -> Incidente | None: ...

    async def incidente(self, incidente_id: str) -> Incidente | None: ...

    async def proponer(
        self, categoria: str, servicio: str, titulo: str, regla: dict[str, Any], reportes: list[int]
    ) -> Incidente: ...

    async def listar(self) -> list[Incidente]: ...

    async def confirmar(self, incidente_id: str, mensaje: str, tecnico_id: str) -> Incidente | None: ...

    async def descartar(self, incidente_id: str, tecnico_id: str) -> Incidente | None: ...

    async def resolver(self, incidente_id: str) -> Incidente | None: ...


def _iso(v: Any) -> str | None:
    return v.isoformat(timespec="seconds") if isinstance(v, datetime) else (str(v) if v else None)


def _incidente(f: dict[str, Any]) -> Incidente:
    return Incidente(
        id=f["id"],
        servicio_id=f["servicio_id"],
        categoria_id=f["categoria_id"],
        titulo=f["titulo"],
        estado=f["estado"],
        origen=f["origen"],
        mensaje_oficial=f["mensaje_oficial"],
        publicado_en=_iso(f["publicado_en"]),
        resuelto_en=_iso(f["resuelto_en"]),
        confirmado_por=f["confirmado_por"],
        regla=f["regla_disparo"] or {},
        casos_vinculados=int(f.get("casos") or 0),
    )


_SELECT = """
    select i.id, i.servicio_id, i.categoria_id, i.titulo, i.estado, i.origen, i.mensaje_oficial, i.publicado_en,
           i.resuelto_en, i.confirmado_por, i.regla_disparo,
           (select count(*) from operacion.incidente_casos ic where ic.incidente_id = i.id) as casos
    from operacion.incidentes_masivos i
"""


class RepositorioMasivosPostgres:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def registrar_reporte(self, **r: Any) -> int | None:
        async with self._pool.connection() as c:
            cur = await c.execute(
                """
                insert into operacion.reportes (usuario_id, equipo_id, texto, texto_canonico, categoria_id,
                    categoria_confianza, reportado_en, embedding, modelo_embedding, dimension, embebido_en)
                values (%s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), %s::vector, %s, %s, now())
                on conflict (usuario_id, reportado_en) do nothing
                returning id
                """,
                (
                    r["usuario_id"],
                    r["equipo_id"],
                    r["texto"],
                    r["texto_canonico"],
                    r["categoria"],
                    max(0.0, min(1.0, r["confianza"])),
                    r["reportado_en"],
                    _lit(r["vector"]),
                    r["modelo"],
                    len(r["vector"]),
                ),
            )
            fila = await cur.fetchone()
            return fila[0] if fila else None

    async def similares(
        self,
        vector: list[float],
        texto_canonico: str,
        categoria: str,
        usuario_excluido: str,
        ventana_min: int,
        umbral: float,
        referencia: str | None,
    ) -> Cluster:
        async with self._pool.connection() as c:
            cur = await c.execute(
                """
                select reporte_id, similitud, usuario_id
                from operacion.buscar_reportes_similares(%s::vector, %s, %s, make_interval(mins => %s), %s, %s,
                                                         50, coalesce(%s::timestamptz, now()))
                """,
                (_lit(vector), texto_canonico, categoria, ventana_min, usuario_excluido, umbral, referencia),
            )
            filas = await cur.fetchall()
        # Usuarios distintos contados AQUÍ (no se confía en el conteo de la función) y sin el propio usuario.
        filas = [f for f in filas if f[2] != usuario_excluido]
        return Cluster(
            usuarios_distintos=len({f[2] for f in filas}),
            reportes=[int(f[0]) for f in filas],
            similitud_max=max((float(f[1]) for f in filas), default=0.0),
        )

    async def _uno(self, sql: str, params: tuple) -> Incidente | None:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            f = await cur.fetchone()
        return _incidente(f) if f else None

    async def incidente_activo(self, categoria: str, servicio: str) -> Incidente | None:
        # Publicado primero (estado oficial); luego una propuesta abierta de la misma categoría.
        return await self._uno(
            _SELECT + " where i.estado = any(%s) and (i.categoria_id = %s or (i.categoria_id is null and "
            "i.servicio_id = %s)) order by (i.estado = 'publicado') desc, i.detectado_en desc limit 1",
            (list(ACTIVOS), categoria, servicio),
        )

    async def incidente(self, incidente_id: str) -> Incidente | None:
        return await self._uno(_SELECT + " where i.id = %s", (incidente_id,))

    async def proponer(
        self, categoria: str, servicio: str, titulo: str, regla: dict[str, Any], reportes: list[int]
    ) -> Incidente:
        nuevo = None
        async with self._pool.connection() as c, c.transaction():
            # La semilla de P2 inserta ids explícitos sin avanzar `incidentes_seq`: si el id por defecto ya
            # existe, se reintenta con el siguiente valor de la secuencia (cada intento en su savepoint).
            for _ in range(MAX_REINTENTOS_ID):
                try:
                    async with c.transaction():
                        cur = await c.execute(
                            "insert into operacion.incidentes_masivos (servicio_id, categoria_id, titulo, estado, "
                            "origen, regla_disparo) values (%s, %s, %s, 'propuesto', 'cluster_reportes', %s) "
                            "returning id",
                            (servicio, categoria, titulo, Jsonb(json.loads(json.dumps(regla, default=str)))),
                        )
                        nuevo = (await cur.fetchone())[0]
                    break
                except UniqueViolation:
                    continue
            if nuevo is None:
                raise RuntimeError("No pude asignar un id libre al incidente (revisar operacion.incidentes_seq)")
            if reportes:
                await c.execute(
                    "update operacion.reportes set incidente_id = %s where id = any(%s) and incidente_id is null",
                    (nuevo, reportes),
                )
        return await self.incidente(nuevo)  # type: ignore[return-value]

    async def listar(self) -> list[Incidente]:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                _SELECT + " where i.estado in ('propuesto', 'publicado') or i.actualizado_en > now() - interval "
                "'1 day' order by (i.estado = 'propuesto') desc, i.actualizado_en desc limit 50"
            )
            return [_incidente(f) for f in await cur.fetchall()]

    async def _transicion(self, sql: str, params: tuple, incidente_id: str) -> Incidente | None:
        async with self._pool.connection() as c:
            cur = await c.execute(sql, params)
            if cur.rowcount != 1:
                return None
        return await self.incidente(incidente_id)

    async def confirmar(self, incidente_id: str, mensaje: str, tecnico_id: str) -> Incidente | None:
        return await self._transicion(
            "update operacion.incidentes_masivos set estado = 'publicado', mensaje_oficial = %s, confirmado_por = %s,"
            " publicado_en = now(), actualizado_en = now() where id = %s and estado = 'propuesto'",
            (mensaje, tecnico_id, incidente_id),
            incidente_id,
        )

    async def descartar(self, incidente_id: str, tecnico_id: str) -> Incidente | None:
        return await self._transicion(
            "update operacion.incidentes_masivos set estado = 'descartado', confirmado_por = %s, "
            "actualizado_en = now() where id = %s and estado = 'propuesto'",
            (tecnico_id, incidente_id),
            incidente_id,
        )

    async def resolver(self, incidente_id: str) -> Incidente | None:
        async with self._pool.connection() as c, c.transaction():
            cur = await c.execute(
                "update operacion.incidentes_masivos set estado = 'resuelto', resuelto_en = now(), "
                "actualizado_en = now() where id = %s and estado = 'publicado'",
                (incidente_id,),
            )
            if cur.rowcount != 1:
                return None
            await c.execute(
                "update operacion.incidente_casos set notificado_en = now() where incidente_id = %s and suscrito",
                (incidente_id,),
            )
        return await self.incidente(incidente_id)


class RepositorioMasivosMemoria:
    """Doble en memoria (pruebas y ejecución sin BD). Similitud = coseno exacto en Python."""

    def __init__(self, reportes: list[dict[str, Any]] | None = None, incidentes: list[Incidente] | None = None):
        self.reportes: list[dict[str, Any]] = list(reportes or [])
        self.incidentes: dict[str, Incidente] = {i.id: i for i in incidentes or []}
        self._ids = itertools.count(len(self.reportes) + 1000)
        self._inc = itertools.count(len(self.incidentes) + 1)

    async def registrar_reporte(self, **r: Any) -> int | None:
        rid = next(self._ids)
        momento = r["reportado_en"] or datetime.now(UTC).isoformat()
        self.reportes.append({**r, "id": rid, "reportado_en": momento, "incidente_id": None})
        return rid

    async def similares(
        self,
        vector: list[float],
        texto_canonico: str,
        categoria: str,
        usuario_excluido: str,
        ventana_min: int,
        umbral: float,
        referencia: str | None,
    ) -> Cluster:
        ahora = datetime.fromisoformat(referencia) if referencia else datetime.now(UTC)
        desde = ahora - timedelta(minutes=ventana_min)
        hits = []
        for r in self.reportes:
            t = datetime.fromisoformat(r["reportado_en"])
            if r["categoria"] != categoria or r["usuario_id"] == usuario_excluido or not (desde < t <= ahora):
                continue
            sim = _coseno(vector, r["vector"])
            if sim >= umbral:
                hits.append((r["id"], r["usuario_id"], sim))
        return Cluster(len({h[1] for h in hits}), [h[0] for h in hits], max((h[2] for h in hits), default=0.0))

    async def incidente_activo(self, categoria: str, servicio: str) -> Incidente | None:
        activos = [
            i
            for i in self.incidentes.values()
            if i.estado in ACTIVOS
            and (i.categoria_id == categoria or (i.categoria_id is None and i.servicio_id == servicio))
        ]
        return sorted(activos, key=lambda i: i.estado != "publicado")[0] if activos else None

    async def incidente(self, incidente_id: str) -> Incidente | None:
        return self.incidentes.get(incidente_id)

    async def proponer(
        self, categoria: str, servicio: str, titulo: str, regla: dict[str, Any], reportes: list[int]
    ) -> Incidente:
        i = Incidente(
            f"INC-SIM-{next(self._inc) + 900:04d}",
            servicio,
            categoria,
            titulo,
            "propuesto",
            "cluster_reportes",
            regla=regla,
        )
        self.incidentes[i.id] = i
        for r in self.reportes:
            if r["id"] in reportes:
                r["incidente_id"] = i.id
        return i

    async def listar(self) -> list[Incidente]:
        return sorted(self.incidentes.values(), key=lambda i: i.estado != "propuesto")

    async def confirmar(self, incidente_id: str, mensaje: str, tecnico_id: str) -> Incidente | None:
        i = self.incidentes.get(incidente_id)
        if not i or i.estado != "propuesto":
            return None
        i.estado, i.mensaje_oficial, i.confirmado_por = "publicado", mensaje, tecnico_id
        i.publicado_en = datetime.now(UTC).isoformat(timespec="seconds")
        return i

    async def descartar(self, incidente_id: str, tecnico_id: str) -> Incidente | None:
        i = self.incidentes.get(incidente_id)
        if not i or i.estado != "propuesto":
            return None
        i.estado, i.confirmado_por = "descartado", tecnico_id
        return i

    async def resolver(self, incidente_id: str) -> Incidente | None:
        i = self.incidentes.get(incidente_id)
        if not i or i.estado != "publicado":
            return None
        i.estado, i.resuelto_en = "resuelto", datetime.now(UTC).isoformat(timespec="seconds")
        return i


def _coseno(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return num / (na * nb) if na and nb else 0.0

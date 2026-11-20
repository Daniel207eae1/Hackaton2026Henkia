"""ITSM simulada sobre `operacion` (PostgreSQL de P2). Conexión con rol `app_rw` (ADR 0009).

Proyección idempotente por turno, en una transacción:
- `casos`: upsert por id (UUID del chat) con el estado completo en `estado_caso` (JSONB versionado por trigger).
- `eventos` y `mensajes`: se insertan solo los nuevos (se cuenta lo ya guardado).
- `acciones`: las cerradas que aún no están (por `parametros->>'n'`). Para las ejecutadas con consentimiento
  se guarda el token consumido ANTES de marcarlas `ejecutada` (lo exige el trigger de P2).
- `banderas_seguridad` y `escalamientos`: los nuevos.

Limitación: las acciones `aprobacion_n2` se aprueban en el canal del servidor MCP, que no informa qué
técnico aprobó; `operacion.aprobaciones_n2` exige `tecnico_id`, así que esas acciones se registran como
`autorizada` con el resultado de la ejecución en `resultado` (ver ADR 0010).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.integraciones.itsm.repositorio import estado_bd, uuid_del_caso
from app.politicas.catalogo import catalogo

log = logging.getLogger(__name__)

ACTOR_POR_ETAPA = {
    "Recepcion": "usuario",
    "Ejecucion": "ejecutor",
    "Consentimiento": "politicas",
    "AprobacionN2": "politicas",
    "Decision": "politicas",
}
ESTADO_ACCION = {
    "ejecutada": "ejecutada",
    "fallida": "fallida",
    "rechazada": "rechazada",
    "rechazada_n2": "rechazada",
    "expirada": "rechazada",
    "propuesta": "propuesta",
}
TIPO_BANDERA = {
    "inyeccion": "inyeccion",
    "inyeccion_en_captura": "inyeccion",
    "autoridad": "ingenieria_social",
    "identidad": "fuera_alcance",
}
ORIGEN_BANDERA = {"inyeccion_en_captura": "captura"}
APPS_BD = {"outlook", "teams", "excel", "word", "onedrive", "impresora", "office", "windows"}


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def _json(obj: Any) -> Jsonb:
    return Jsonb(json.loads(json.dumps(obj, default=str)))


class RepositorioITSMPostgres:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def sincronizar(self, estado: dict[str, Any], traza_url: str | None = None) -> None:
        cid = uuid_del_caso(estado["case_id"])
        estado_caso, resultado = estado_bd(estado)
        async with self._pool.connection() as c, c.transaction():
            cur = await c.execute(
                """
                insert into operacion.casos (id, usuario_id, equipo_id, canal, estado, resultado, estado_caso,
                                             cerrado_en)
                values (%s, %s, %s, 'chat_web', %s, %s, %s, case when %s::text is not null then now() end)
                on conflict (id) do update set estado = excluded.estado, resultado = excluded.resultado,
                    estado_caso = excluded.estado_caso,
                    cerrado_en = coalesce(operacion.casos.cerrado_en, excluded.cerrado_en)
                where operacion.casos.usuario_id = excluded.usuario_id
                returning id
                """,
                (
                    cid,
                    estado["persona_id"],
                    estado.get("equipo_id"),
                    estado_caso,
                    resultado,
                    _json({k: v for k, v in estado.items() if k != "mensajes"}),
                    resultado,
                ),
            )
            if await cur.fetchone() is None:
                # El id ya es de un caso de OTRA persona: no se toca nada de ese registro.
                raise PermissionError(f"El caso {estado['case_id']} pertenece a otra persona en el registro")
            await self._eventos(c, cid, estado.get("linea_tiempo") or [])
            await self._mensajes(c, cid, estado.get("mensajes") or [])
            await self._acciones(c, cid, estado)
            await self._banderas(c, cid, (estado.get("seguridad") or {}).get("banderas", []))
            if ficha := estado.get("escalamiento"):
                await self._escalamiento(c, cid, ficha, traza_url)
            await self._masivo(c, cid, estado.get("masivo") or {})
            await self._capturas(c, cid, estado.get("capturas") or [])

    async def _capturas(self, c, cid, capturas: list[dict[str, Any]]) -> None:
        """F7: una fila por captura (solo campos validados; el texto de la imagen nunca se guarda)."""
        cur = await c.execute("select sha256 from operacion.capturas where caso_id = %s", (cid,))
        guardadas = {r[0] for r in await cur.fetchall()}
        for k in capturas:
            if not k.get("sha256") or k["sha256"] in guardadas:
                continue
            extraccion = {
                x: k.get(x)
                for x in (
                    "aplicacion",
                    "codigo_error",
                    "codigo_modelo",
                    "codigos_ocr",
                    "coinciden",
                    "bandera_heuristica",
                    "bandera_modelo",
                    "motivo",
                )
            }
            await c.execute(
                """insert into operacion.capturas (caso_id, nombre_archivo, ruta_almacen, mime, tamano_bytes, sha256,
                       estado, aplicacion, codigo_error, extraccion, contiene_instrucciones, fragmento_sospechoso,
                       subida_en, procesada_en)
                   values (%s, %s, %s, 'image/png', %s, %s, %s, %s, %s, %s, %s, %s, %s, now())""",
                (
                    cid,
                    k.get("nombre"),
                    k.get("ruta") or "",
                    max(1, int(k.get("tamano_bytes") or 1)),
                    k["sha256"],
                    k.get("estado") if k.get("estado") in ("procesada", "no_concluyente", "rechazada") else "procesada",
                    k.get("aplicacion") if k.get("aplicacion") in APPS_BD else None,
                    k.get("codigo_error"),
                    _json(extraccion),
                    bool(k.get("contiene_instrucciones")),
                    k.get("fragmento_sospechoso"),
                    k.get("hora"),
                ),
            )

    async def _masivo(self, c, cid, m: dict[str, Any]) -> None:
        """F2: el reporte queda ligado al caso; el caso, vinculado (y suscrito) al incidente masivo."""
        if m.get("reporte_id"):
            await c.execute(
                "update operacion.reportes set caso_id = %s where id = %s and caso_id is null", (cid, m["reporte_id"])
            )
        if not m.get("incidente_id"):
            return
        await c.execute(
            "insert into operacion.incidente_casos (incidente_id, caso_id, regla) values (%s, %s, %s) "
            "on conflict (incidente_id, caso_id) do nothing",
            (m["incidente_id"], cid, _json({"fuente": m.get("fuente"), **(m.get("regla") or {})})),
        )
        if m.get("reporte_id"):
            await c.execute(
                "update operacion.reportes set incidente_id = %s where id = %s and incidente_id is null",
                (m["incidente_id"], m["reporte_id"]),
            )
        if m.get("estado") == "descartado_n2":
            await c.execute(
                "update operacion.incidente_casos set suscrito = false where incidente_id = %s and caso_id = %s",
                (m["incidente_id"], cid),
            )
        elif m.get("estado") in ("masivo_resuelto", "resuelto_persiste"):
            await c.execute(
                "update operacion.incidente_casos set verificado_en = coalesce(verificado_en, now()) "
                "where incidente_id = %s and caso_id = %s",
                (m["incidente_id"], cid),
            )

    async def _contar(self, c, tabla: str, cid) -> int:
        cur = await c.execute(f"select count(*) from operacion.{tabla} where caso_id = %s", (cid,))  # noqa: S608
        return (await cur.fetchone())[0]

    async def _eventos(self, c, cid, linea: list[dict[str, Any]]) -> None:
        for h in linea[await self._contar(c, "eventos", cid) :]:
            await c.execute(
                "insert into operacion.eventos (caso_id, ocurrido_en, tipo, nodo, actor, datos) "
                "values (%s, %s, 'hito', %s, %s, %s)",
                (
                    cid,
                    h.get("hora"),
                    (h.get("etapa") or "").lower(),
                    ACTOR_POR_ETAPA.get(h.get("etapa"), "sistema"),
                    _json({"detalle": h.get("detalle")}),
                ),
            )

    async def _mensajes(self, c, cid, mensajes: list[dict[str, Any]]) -> None:
        for m in mensajes[await self._contar(c, "mensajes", cid) :]:
            await c.execute(
                "insert into operacion.mensajes (caso_id, rol, contenido, creado_en) values (%s, %s, %s, %s)",
                (
                    cid,
                    "usuario" if m.get("rol") == "usuario" else "asistente",
                    m.get("texto") or "",
                    m.get("hora"),
                ),
            )

    async def _acciones(self, c, cid, estado: dict[str, Any]) -> None:
        cur = await c.execute(
            "select parametros->>'n' from operacion.acciones where caso_id = %s and parametros ? 'n'", (cid,)
        )
        guardadas = {r[0] for r in await cur.fetchall()}
        for a in estado.get("acciones") or []:
            if str(a.get("n")) in guardadas:
                continue
            c_accion = catalogo().por_tool(a["tool"])
            final = ESTADO_ACCION.get(a.get("estado"), "propuesta")
            n2 = a.get("politica") == "aprobacion_n2"
            # Con consentimiento se inserta como `autorizada` + token consumido y luego pasa a `ejecutada`.
            inicial = "autorizada" if final == "ejecutada" else final
            parametros = {
                "n": a.get("n"),
                "tool_mcp": a["tool"],
                "equipo": estado.get("equipo_zabbix"),
                "consentimiento_id": a.get("consentimiento_id"),
                "aprobacion_id": a.get("aprobacion_id"),
            }
            cur = await c.execute(
                """insert into operacion.acciones (caso_id, accion_catalogo_id, version_catalogo, riesgo, politica,
                       parametros, aviso_obligatorio, reversible, estado, resultado, verificada, propuesta_en)
                   values (%s, %s, '1', %s, %s, %s, %s, false, %s, %s, %s, %s) returning id""",
                (
                    cid,
                    c_accion.id,
                    a.get("riesgo"),
                    a.get("politica"),
                    _json(parametros),
                    c_accion.aviso_obligatorio,
                    inicial,
                    _json({"estado_mcp": a.get("estado"), "motivo_fallo": a.get("motivo_fallo")}),
                    a.get("verificacion_tecnica"),
                    a.get("propuesta_en"),
                ),
            )
            accion_id = (await cur.fetchone())[0]
            if a.get("consentimiento_id") and a.get("estado") in ("ejecutada", "fallida"):
                texto = (
                    f"{c_accion.nombre}. {c_accion.descripcion} {c_accion.aviso_obligatorio} "
                    f"Autorizado en la ventana «Soporte TI» ({a['consentimiento_id']})."
                )
                emitido = datetime.fromisoformat(a.get("propuesta_en") or datetime.now(UTC).isoformat())
                await c.execute(
                    """insert into operacion.tokens_consentimiento (caso_id, accion_ref, tipo, emitido_por,
                           emisor_usuario_id, parametros_hash, texto_mostrado, texto_hash, emitido_en, vence_en,
                           consumido_en, estado)
                       values (%s, %s, 'consentimiento', 'ui_usuario', %s, %s, %s, %s, %s, %s, %s, 'consumido')""",
                    (
                        cid,
                        accion_id,
                        estado["persona_id"],
                        _hash(json.dumps(parametros, sort_keys=True)),
                        texto,
                        _hash(texto),
                        emitido,
                        emitido + timedelta(minutes=15),
                        a.get("ejecutada_en") or emitido,
                    ),
                )
            if final == "ejecutada" and not n2:
                await c.execute(
                    "update operacion.acciones set estado = 'ejecutada', ejecutada_en = %s where id = %s",
                    (a.get("ejecutada_en"), accion_id),
                )

    async def _banderas(self, c, cid, banderas: list[dict[str, Any]]) -> None:
        for b in banderas[await self._contar(c, "banderas_seguridad", cid) :]:
            nombre = b.get("bandera", "")
            tipo = TIPO_BANDERA.get(nombre, "accion_prohibida" if ":" in nombre else "ingenieria_social")
            await c.execute(
                "insert into operacion.banderas_seguridad (caso_id, tipo, origen, fragmento, intento, detectado_en) "
                "values (%s, %s, %s, %s, %s, %s)",
                (cid, tipo, ORIGEN_BANDERA.get(nombre, "mensaje_usuario"), nombre, b.get("turno") or 1, b.get("hora")),
            )

    async def _escalamiento(self, c, cid, ficha: dict[str, Any], traza_url: str | None) -> None:
        if await self._contar(c, "escalamientos", cid):
            return
        await c.execute(
            "insert into operacion.escalamientos (caso_id, motivo, paquete, ans_horas, ans_vence_en, estado) "
            "values (%s, %s, %s, %s, %s, 'abierto')",
            (
                cid,
                ficha["motivo"],
                _json({**ficha, "traza_url": traza_url}),
                ficha["ans"].get("horas"),
                ficha["ans"].get("vence_en"),
            ),
        )

    async def cargar_estado(self, case_id: str) -> dict[str, Any] | None:
        """Estado del caso tal como quedó al final de su último turno (para rehidratar el grafo tras un reinicio).

        `estado_caso` guarda todo menos los mensajes; estos salen de `operacion.mensajes` (los del historial, que
        nunca llevan texto externo: ver `sin_cita` y `nodos_captura`)."""
        cid = uuid_del_caso(case_id)
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute("select estado_caso from operacion.casos where id = %s", (cid,))
            fila = await cur.fetchone()
            if not fila or not fila["estado_caso"]:
                return None
            await cur.execute(
                "select rol, contenido, creado_en from operacion.mensajes where caso_id = %s order by id", (cid,)
            )
            mensajes = [
                {
                    "rol": "usuario" if m["rol"] == "usuario" else "sistema",
                    "texto": m["contenido"],
                    "hora": m["creado_en"].isoformat(timespec="seconds") if m["creado_en"] else None,
                }
                for m in await cur.fetchall()
            ]
        return {**fila["estado_caso"], "mensajes": mensajes}

    async def registrar_valoracion(self, case_id: str, util: bool, comentario: str | None) -> bool:
        """Valoración del usuario al cerrar o escalar: un hito `valoracion` (una sola por caso)."""
        cid = uuid_del_caso(case_id)
        async with self._pool.connection() as c, c.transaction():
            cur = await c.execute("select 1 from operacion.eventos where caso_id = %s and nodo = 'valoracion'", (cid,))
            if await cur.fetchone():
                return False
            await c.execute(
                "insert into operacion.eventos (caso_id, tipo, nodo, actor, datos) "
                "values (%s, 'hito', 'valoracion', 'usuario', %s)",
                (cid, _json({"util": util, "comentario": comentario})),
            )
        return True

    async def metricas(self, dias: int = 30) -> dict[str, Any]:
        """Métricas operativas (§5.3) sobre el registro oficial de los últimos `dias`."""
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                with k as (select * from operacion.casos where creado_en > now() - make_interval(days => %s))
                select
                  (select count(*) from k) as casos,
                  (select count(*) from k where resultado = 'resuelto') as resueltos,
                  (select count(*) from k where resultado = 'escalado') as escalados,
                  (select count(*) from k where resultado = 'vinculado_masivo') as vinculados_masivo,
                  (select coalesce(avg((estado_caso->'metricas'->>'preguntas')::numeric), 0) from k)
                    as preguntas_promedio,
                  (select count(*) from operacion.acciones a join k on k.id = a.caso_id
                     where a.estado = 'ejecutada' and not exists (select 1 from operacion.tokens_consentimiento t
                       where t.accion_ref = a.id and t.estado = 'consumido')
                       and a.politica <> 'aprobacion_n2') as acciones_sin_token,
                  (select count(*) from operacion.banderas_seguridad b join k on k.id = b.caso_id) as banderas,
                  (select count(*) from operacion.escalamientos e join k on k.id = e.caso_id
                     where e.completo_sin_repregunta) as escalamientos_completos,
                  (select count(*) from operacion.escalamientos e join k on k.id = e.caso_id
                     where e.completo_sin_repregunta is not null) as escalamientos_evaluados,
                  (select count(*) from operacion.eventos v join k on k.id = v.caso_id
                     where v.nodo = 'valoracion') as valoraciones,
                  (select count(*) from operacion.eventos v join k on k.id = v.caso_id
                     where v.nodo = 'valoracion' and (v.datos->>'util')::boolean) as valoraciones_utiles
                """,
                (dias,),
            )
            f = await cur.fetchone()
            # Series para las gráficas: casos por día (según resultado) y por aplicación.
            await cur.execute(
                """
                select to_char(date_trunc('day', creado_en), 'YYYY-MM-DD') as dia,
                       count(*) filter (where resultado = 'resuelto') as resueltos,
                       count(*) filter (where resultado = 'escalado') as escalados,
                       count(*) filter (where resultado = 'vinculado_masivo') as vinculados_masivo,
                       count(*) filter (where resultado is null) as abiertos
                from operacion.casos where creado_en > now() - make_interval(days => %s)
                group by 1 order by 1
                """,
                (dias,),
            )
            por_dia = list(await cur.fetchall())
            await cur.execute(
                """
                select coalesce(nullif(estado_caso->'sintoma'->>'aplicacion', 'desconocida'), 'sin identificar') as app,
                       count(*) as casos
                from operacion.casos where creado_en > now() - make_interval(days => %s)
                group by 1 order by 2 desc
                """,
                (dias,),
            )
            por_app = {r["app"]: r["casos"] for r in await cur.fetchall()}
        base = {k: float(v) if isinstance(v, Decimal) else v for k, v in f.items()}
        return {**base, "por_dia": por_dia, "por_aplicacion": por_app}

    async def listar_casos(self, limite: int = 100) -> list[dict[str, Any]]:
        """Casos recientes para la vista de N2 (resumen; el detalle sale de `/api/casos/{id}`)."""
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                select estado_caso->>'case_id' as case_id, codigo, usuario_id, estado, resultado,
                       creado_en::text as creado_en, actualizado_en::text as actualizado_en,
                       estado_caso->'sintoma'->>'aplicacion' as aplicacion,
                       estado_caso->'sintoma'->>'tipo_sintoma' as tipo_sintoma,
                       estado_caso->'diagnostico'->>'categoria' as categoria,
                       estado_caso->'diagnostico'->>'confirmada' as confirmada,
                       (estado_caso->'diagnostico'->>'probable')::boolean as probable,
                       estado_caso->>'etapa' as etapa, (estado_caso->>'turnos')::int as turnos,
                       estado_caso->'masivo'->>'estado' as masivo
                from operacion.casos where estado_caso ? 'case_id'
                order by creado_en desc limit %s
                """,
                (limite,),
            )
            return list(await cur.fetchall())

    async def listar_escalamientos(self) -> list[dict[str, Any]]:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """select e.id, e.caso_id::text as caso_uuid, e.paquete->>'case_id' as case_id, e.motivo, e.paquete,
                          e.estado, e.asignado_a, e.completo_sin_repregunta, e.creado_en, e.ans_vence_en, k.codigo
                   from operacion.escalamientos e join operacion.casos k on k.id = e.caso_id
                   order by e.creado_en desc limit 100"""
            )
            return [
                {**f, "creado_en": str(f["creado_en"]), "ans_vence_en": str(f["ans_vence_en"] or "")}
                for f in await cur.fetchall()
            ]

    async def tomar_escalamiento(self, escalamiento_id: int, tecnico_id: str) -> bool:
        async with self._pool.connection() as c:
            cur = await c.execute(
                "update operacion.escalamientos set estado = 'tomado', asignado_a = %s, tomado_en = now() "
                "where id = %s and estado = 'abierto'",
                (tecnico_id, escalamiento_id),
            )
            return cur.rowcount == 1

    async def evaluar_escalamiento(self, escalamiento_id: int, completo: bool) -> dict[str, Any] | None:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "update operacion.escalamientos set completo_sin_repregunta = %s where id = %s returning id, paquete",
                (completo, escalamiento_id),
            )
            return await cur.fetchone()

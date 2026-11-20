"""Curador de KB (Módulo A, F8, §3.10). Proceso POR LOTES, fuera de la conversación.

1. Detección EN CÓDIGO sobre el historial (conjunto de entrenamiento) y los artículos:
   - **Faltante:** casos resueltos SIN artículo agrupados por (categoría, causa, solución normalizada),
     con ≥ k casos.
   - **Desactualizado:** artículo usado por ≥ m casos recientes cuya versión de la aplicación NO está entre sus
     `versiones_aplicables` (o artículo de hace más de N años con casos recientes).
2. Redacción: el agente `curador_kb` (LLM sin herramientas) recibe SOLO campos estructurados y textos de tickets
   pasados por la cuarentena (enmascarados, sin los que tienen forma de instrucción, delimitados con un marcador
   aleatorio). Esquema cerrado; la salida se re-escanea. Si algo falla → borrador de plantilla (sin inventar).
3. Escribe SOLO en `conocimiento.propuestas_kb` (estado `pendiente`). Nada se publica sin el revisor humano.

CLI: `python -m app.agentes.curador_kb` (usa DATABASE_URL y el registro de modelos).
"""

from __future__ import annotations

import asyncio
import re
import secrets
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.agentes.prompts import prompt_embebido, prompt_vigente
from app.llm.puerto import Mensaje
from app.llm.registro import RegistroLLM, SinModeloDisponible
from app.observabilidad.langfuse import enmascarar_texto, evento, observacion
from app.rag.curaduria import Grupo, Propuesta, RepositorioCuraduria
from app.seguridad.extractor_cuarentena import heuristica_instrucciones

K_FALTANTE = 3
M_DESACTUALIZADO = 3
VENTANA_RECIENTE_DIAS = 180
ANTIGUEDAD_MAX_ANIOS = 3
# Soluciones que no se documentan como artículo (no son un procedimiento repetible del usuario o de N1).
NO_DOCUMENTABLES = {"vinculado_masivo", "escalar", "derivar"}
MAX_TICKETS_AL_LLM = 6
_SIN_NUMERO = re.compile(r"^\s*(\d+[.)]\s*)+")  # el modelo a veces numera los pasos: se numeran aquí


# ------------------------------------------------------------------ detección (código)
def _version_cubierta(version: str, patrones: list[str]) -> bool:
    """«Teams 24xxx» cubre «Teams 24257»; «OneDrive 24.x» cubre «OneDrive 24.x» y «OneDrive 24.3»."""
    for p in patrones:
        partes = re.split(r"(x+)", p.strip(), flags=re.IGNORECASE)
        regex = "".join(r"(?:\d+|x+)" if re.fullmatch(r"x+", t, re.IGNORECASE) else re.escape(t) for t in partes)
        if re.fullmatch(regex, version.strip(), re.IGNORECASE):
            return True
    return False


def _fecha(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def detectar(casos: list[dict[str, Any]], articulos: list[dict[str, Any]]) -> list[Grupo]:
    grupos: list[Grupo] = []
    # Faltantes
    por_solucion: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for c in casos:
        if c.get("resultado") == "resuelto" and not c.get("articulo_id"):
            sol = c.get("solucion_normalizada") or ""
            if sol and sol not in NO_DOCUMENTABLES and not sol.startswith(("escalar", "derivar")):
                por_solucion[(c.get("categoria_id"), c.get("causa"), sol)].append(c)
    for (cat, causa, sol), cs in sorted(por_solucion.items(), key=lambda kv: -len(kv[1])):
        if len(cs) >= K_FALTANTE:
            grupos.append(
                Grupo(
                    "articulo_faltante",
                    f"faltante|{cat}|{sol}",
                    cat,
                    None,
                    cs,
                    f"{len(cs)} casos resueltos con la misma causa y solución y sin artículo que los cubra",
                    {"causa": causa, "solucion_normalizada": sol},
                )
            )
    # Desactualizados
    fechas = [f for c in casos if (f := _fecha(c.get("fecha")))]
    if not fechas:
        return grupos
    hoy = max(fechas)
    desde = hoy - timedelta(days=VENTANA_RECIENTE_DIAS)
    recientes = [c for c in casos if (f := _fecha(c.get("fecha"))) and f >= desde]
    for a in articulos:
        if a.get("estado") != "publicado" or a.get("marcado_inyeccion"):
            continue
        usados = [c for c in recientes if c.get("articulo_id") == a["id"] and c.get("version_app")]
        if len(usados) < M_DESACTUALIZADO:
            continue
        versiones = list(a.get("versiones_aplicables") or [])
        fuera = sorted(
            {c["version_app"] for c in usados if versiones and not _version_cubierta(c["version_app"], versiones)}
        )
        fecha_art = _fecha(a.get("fecha_actualizacion"))
        viejo = bool(
            fecha_art
            and fecha_art.replace(tzinfo=None) < hoy.replace(tzinfo=None) - timedelta(days=365 * ANTIGUEDAD_MAX_ANIOS)
        )
        motivos = []
        if fuera:
            motivos.append(
                f"los casos recientes usan {', '.join(fuera)} y el artículo solo cubre {', '.join(versiones)}"
            )
        if viejo:
            motivos.append(f"no se actualiza desde {fecha_art.date()}")
        if motivos:
            grupos.append(
                Grupo(
                    "articulo_desactualizado",
                    f"desactualizado|{a['id']}",
                    a.get("categoria_id"),
                    a["id"],
                    usados,
                    "; ".join(motivos),
                    {"versiones_actuales": versiones, "versiones_casos": fuera, "titulo_articulo": a.get("titulo")},
                )
            )
    return grupos


# ------------------------------------------------------------------ cuarentena de tickets
def ticket_seguro(c: dict[str, Any]) -> dict[str, str] | None:
    """Campos del ticket aptos para el redactor: enmascarados, acotados y sin forma de instrucción."""
    campos = {k: enmascarar_texto(str(c.get(k) or ""))[:400] for k in ("sintoma_texto", "causa", "solucion")}
    if any(heuristica_instrucciones(v) for v in campos.values()):
        return None
    return campos


class BorradorKB(BaseModel):
    """Lo ÚNICO que el curador puede devolver."""

    titulo: str = Field(max_length=120)
    sintoma: str = Field(max_length=400)
    causa: str = Field(max_length=300)
    pasos: list[str] = Field(min_length=1, max_length=8)
    verificacion: str = Field(max_length=300)
    cambios_propuestos: str = Field(default="", max_length=500, description="Solo para correcciones: qué actualizar")


PROMPT = prompt_embebido("curador_kb")  # versión vigente: Langfuse (`curador_kb`)


@dataclass
class ResumenLote:
    detectados: int = 0
    creadas: list[Propuesta] = field(default_factory=list)
    omitidas: list[str] = field(default_factory=list)  # claves ya propuestas antes
    tickets_descartados: int = 0


class CuradorKB:
    def __init__(self, repo: RepositorioCuraduria, registro: RegistroLLM | None):
        self.repo = repo
        self._cliente = registro.para("curador_kb") if registro else None

    async def _redactar(
        self, g: Grupo, tickets: list[dict[str, str]], articulo: dict[str, Any] | None
    ) -> BorradorKB | None:
        if self._cliente is None:
            return None
        m = f"<<<{secrets.token_hex(6)}>>>"
        datos = {
            "tipo": g.tipo,
            "categoria": g.categoria_id,
            "motivo": g.motivo,
            **g.datos,
            "casos": tickets[:MAX_TICKETS_AL_LLM],
        }
        if articulo:
            datos["articulo_actual"] = {
                "id": articulo["id"],
                "titulo": articulo.get("titulo"),
                # Texto de la KB = dato externo: si tiene forma de instrucción, no llega al redactor.
                "contenido": ""
                if heuristica_instrucciones(str(articulo.get("contenido_md") or ""))
                else enmascarar_texto(str(articulo.get("contenido_md") or ""))[:1500],
            }
        sistema, prompt_lf = prompt_vigente("curador_kb", m)
        mensajes = [Mensaje("system", sistema), Mensaje("user", f"{m}\n{datos}\n{m}")]
        try:
            b = await self._cliente.estructurado(mensajes, BorradorKB, prompt=prompt_lf)
        except SinModeloDisponible:
            return None
        if heuristica_instrucciones(b.model_dump_json()):
            evento("seguridad.bandera", metadata={"bandera": "inyeccion_en_borrador_kb", "clave": g.clave})
            return None
        return b

    @staticmethod
    def _markdown(g: Grupo, b: BorradorKB | None, casos: list[str]) -> tuple[str, str]:
        if b is None:  # plantilla: sin LLM no se inventa nada, solo los datos del grupo
            titulo = (
                f"{g.datos.get('causa')}: {g.datos.get('solucion_normalizada')}"
                if g.tipo == "articulo_faltante"
                else f"Actualizar {g.articulo_id}: {g.datos.get('titulo_articulo')}"
            )
            cuerpo = f"## Hallazgo\n{g.motivo}.\n\n## Pasos\nPor redactar con N2 a partir de los casos de soporte.\n"
        else:
            titulo = b.titulo
            pasos = "\n".join(f"{i}. {_SIN_NUMERO.sub('', p).strip()}" for i, p in enumerate(b.pasos, 1))
            cuerpo = (
                f"## Síntoma\n{b.sintoma}\n\n## Causa\n{b.causa}\n\n## Pasos\n{pasos}\n\n"
                f"## Verificación\n{b.verificacion}\n"
            )
            if b.cambios_propuestos:
                cuerpo += f"\n## Cambios propuestos\n{b.cambios_propuestos}\n"
        pie = (
            f"\n---\nCasos que lo respaldan: {', '.join(casos)}.\n"
            "Borrador automático del curador: requiere revisión humana.\n"
        )
        return titulo[:120], cuerpo + pie

    async def ejecutar(self) -> ResumenLote:
        r = ResumenLote()
        with observacion("curador_kb", tipo="agent", metadata={"modo": "lote"}) as obs:
            casos, articulos = await asyncio.gather(self.repo.casos(), self.repo.articulos())
            grupos = detectar(casos, articulos)
            r.detectados = len(grupos)
            ya = await self.repo.claves_existentes()
            por_id = {a["id"]: a for a in articulos}
            for g in grupos:
                if g.clave in ya:
                    r.omitidas.append(g.clave)
                    continue
                tickets = [t for c in g.casos if (t := ticket_seguro(c))]
                r.tickets_descartados += len(g.casos) - len(tickets)
                b = await self._redactar(g, tickets, por_id.get(g.articulo_id or ""))
                ids = sorted(c["id"] for c in g.casos)
                titulo, md = self._markdown(g, b, ids)
                p = await self.repo.crear(
                    {
                        "tipo": g.tipo,
                        "articulo_id": g.articulo_id,
                        "categoria_id": g.categoria_id,
                        "titulo": titulo,
                        "borrador_md": md,
                        "casos_soporte": ids,
                        "justificacion": f"[clave={g.clave}] {g.motivo}",
                    }
                )
                r.creadas.append(p)
                evento("kb.propuesta.creada", metadata={"tipo": g.tipo, "clave": g.clave, "propuesta": str(p.id)})
            obs.update(
                output={
                    "detectados": r.detectados,
                    "creadas": [p.id for p in r.creadas],
                    "omitidas": r.omitidas,
                    "tickets_descartados": r.tickets_descartados,
                }
            )
        return r


async def _main() -> None:  # pragma: no cover - CLI
    from psycopg_pool import AsyncConnectionPool

    from app.config.ajustes import obtener_ajustes
    from app.llm.config_modelos import cargar_config
    from app.observabilidad.langfuse import atributos_traza, flush, obtener_langfuse
    from app.rag.curaduria import RepositorioCuraduriaPostgres

    aj = obtener_ajustes()
    obtener_langfuse(aj)
    async with AsyncConnectionPool(aj.database_url, kwargs={"options": f"-c role={aj.db_rol_app}"}, open=False) as pool:
        await pool.open(wait=True)
        curador = CuradorKB(
            RepositorioCuraduriaPostgres(pool), RegistroLLM(cargar_config(aj.modelos_yaml, modo=aj.llm_modo))
        )
        with atributos_traza(
            session_id="lote-curador-kb", user_id="curador_kb", nombre_traza="lote_curador_kb", tags=["modulo:A"]
        ):
            r = await curador.ejecutar()
    flush()
    print(
        f"Grupos detectados: {r.detectados} · propuestas nuevas: {[p.id for p in r.creadas]} · "
        f"ya propuestos: {r.omitidas}"
    )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())

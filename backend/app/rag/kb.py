"""Repositorio de conocimiento (§3.8) sobre `conocimiento` de P2: categorías, recetas de diagnóstico,
priors del historial, secciones de artículos y búsqueda híbrida. SQL parametrizado; rol `app_rw`.

Los artículos también son texto no confiable: se excluyen los `marcado_inyeccion` y lo que se muestre se
revisa con la guardia antes (ver `nodos_diagnostico.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


@dataclass
class Hipotesis:
    articulo_id: str
    titulo: str
    hipotesis: str
    receta: dict[str, Any]
    prior: float
    casos_historial: int = 0
    estado: str = "pendiente"  # pendiente | confirmada | descartada | no_concluyente
    evidencia: list[str] = field(default_factory=list)
    justificacion: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            "articulo_id": self.articulo_id,
            "titulo": self.titulo,
            "hipotesis": self.hipotesis,
            "receta": self.receta,
            "prior": round(self.prior, 3),
            "casos_historial": self.casos_historial,
            "estado": self.estado,
            "evidencia": self.evidencia,
            "justificacion": self.justificacion,
        }


class RepositorioKB(Protocol):
    async def clasificar(self, vector: list[float]) -> list[tuple[str, float]]: ...

    async def hipotesis(self, categoria: str) -> list[Hipotesis]: ...

    async def secciones(self, articulo_id: str) -> dict[str, str]: ...

    async def categoria_fuera_alcance(self, categoria: str) -> bool: ...


def _priors(conteos: dict[str, int]) -> dict[str, float]:
    """Frecuencia de cada artículo como causa en el historial, con suavizado de Laplace (+1)."""
    total = sum(conteos.values()) + len(conteos)
    return {a: (n + 1) / total for a, n in conteos.items()} if total else {}


def _lit(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


class RepositorioKBPostgres:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def clasificar(self, vector: list[float]) -> list[tuple[str, float]]:
        async with self._pool.connection() as c:
            cur = await c.execute(
                "select categoria_id, similitud from conocimiento.clasificar(%s::vector) order by posicion",
                (_lit(vector),),
            )
            return [(r[0], float(r[1])) for r in await cur.fetchall()]

    async def hipotesis(self, categoria: str) -> list[Hipotesis]:
        async with self._pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                select a.id, a.titulo, a.receta, coalesce(h.n, 0) as n
                from conocimiento.articulos a
                left join (select articulo_id, count(*) n from conocimiento.historial_casos
                           where categoria_id = %s and conjunto = 'entrenamiento' group by 1) h on h.articulo_id = a.id
                where a.categoria_id = %s and a.estado = 'publicado' and not coalesce(a.marcado_inyeccion, false)
                """,
                (categoria, categoria),
            )
            filas = await cur.fetchall()
        priors = _priors({f["id"]: f["n"] for f in filas})
        hs = [
            Hipotesis(
                f["id"],
                f["titulo"],
                (f["receta"] or {}).get("hipotesis") or f["titulo"],
                f["receta"] or {},
                priors.get(f["id"], 0.0),
                f["n"],
            )
            for f in filas
        ]
        return sorted(hs, key=lambda h: -h.prior)

    async def secciones(self, articulo_id: str) -> dict[str, str]:
        async with self._pool.connection() as c:
            cur = await c.execute(
                "select seccion, texto from conocimiento.kb_fragmentos where articulo_id = %s order by orden",
                (articulo_id,),
            )
            return {s: t for s, t in await cur.fetchall()}

    async def categoria_fuera_alcance(self, categoria: str) -> bool:
        async with self._pool.connection() as c:
            cur = await c.execute("select fuera_alcance from conocimiento.categorias where id = %s", (categoria,))
            fila = await cur.fetchone()
            return bool(fila and fila[0])


# ------------------------------------------------------------------ doble (recetas reales del kit, resumidas)
_KB_DEMO: dict[str, list[dict[str, Any]]] = {
    "outlook.no_abre": [
        {
            "id": "KB-SIM-001",
            "titulo": "Outlook no abre: perfil de Outlook dañado",
            "n": 9,
            "receta": {
                "hipotesis": "Perfil de Outlook dañado",
                "tipo_solucion": "accion",
                "accion_catalogo": "recrear_perfil_outlook",
                "pruebas": [
                    {"herramienta": "telemetria.procesos"},
                    {"herramienta": "logs.outlook", "requiere": "leer_logs"},
                ],
                "criterio_confirmacion": "ERR-SIM-0101 presente en los logs y Outlook falla también en modo seguro",
                "criterio_descarte": "Sin ERR-SIM-0101 o Outlook abre en modo seguro",
            },
        },
        {
            "id": "KB-SIM-002",
            "titulo": "Outlook no abre: complemento que bloquea el inicio",
            "n": 7,
            "receta": {
                "hipotesis": "Complemento de Outlook que falla al iniciar",
                "tipo_solucion": "accion",
                "accion_catalogo": "desactivar_complemento",
                "pruebas": [
                    {"herramienta": "telemetria.outlook.complementos"},
                    {"herramienta": "logs.outlook", "requiere": "leer_logs"},
                ],
                "criterio_confirmacion": "ERR-SIM-0102 con un complemento identificado",
                "criterio_descarte": "Ningún complemento con fallos",
            },
        },
    ],
    "onedrive.no_sincroniza": [
        {
            "id": "KB-SIM-014",
            "titulo": "OneDrive en pausa: disco local lleno",
            "n": 7,
            "receta": {
                "hipotesis": "Disco local lleno",
                "tipo_solucion": "guia",
                "accion_catalogo": None,
                "pruebas": [{"herramienta": "telemetria.disco"}, {"herramienta": "telemetria.onedrive"}],
                "criterio_confirmacion": "Disco >= 95 % y OneDrive en pausa",
                "criterio_descarte": "Disco < 90 %",
            },
        },
        {
            "id": "KB-SIM-015",
            "titulo": "OneDrive no sincroniza: conflictos de archivo",
            "n": 4,
            "receta": {
                "hipotesis": "Conflictos de sincronización",
                "tipo_solucion": "accion",
                "accion_catalogo": "resincronizar_onedrive",
                "pruebas": [{"herramienta": "telemetria.onedrive.conflictos"}],
                "criterio_confirmacion": "conflictos > 0",
                "criterio_descarte": "conflictos = 0",
            },
        },
    ],
    "impresora.impresion": [
        {
            "id": "KB-SIM-023",
            "titulo": "No imprime: cola de impresión atascada",
            "n": 7,
            "receta": {
                "hipotesis": "Cola de impresión atascada",
                "tipo_solucion": "accion",
                "accion_catalogo": "reiniciar_cola_impresion",
                "pruebas": [{"herramienta": "telemetria.impresoras"}],
                "criterio_confirmacion": "Trabajos atascados > 0 en la impresora predeterminada",
                "criterio_descarte": "Cola vacía",
            },
        },
        {
            "id": "KB-SIM-024",
            "titulo": "Imprime en otra impresora o no aparece",
            "n": 5,
            "receta": {
                "hipotesis": "Impresora predeterminada incorrecta",
                "tipo_solucion": "guia",
                "accion_catalogo": None,
                "pruebas": [{"herramienta": "telemetria.impresoras"}],
                "criterio_confirmacion": "Predeterminada sin conexión y otra impresora lista",
                "criterio_descarte": "La predeterminada está en línea",
            },
        },
    ],
    "word.se_cierra": [
        {
            "id": "KB-SIM-025",
            "titulo": "Word se cierra: plantilla Normal.dotm dañada",
            "n": 4,
            "receta": {
                "hipotesis": "Plantilla Normal dañada",
                "tipo_solucion": "guia",
                "accion_catalogo": None,
                "pruebas": [{"herramienta": "logs.word", "requiere": "leer_logs"}],
                "criterio_confirmacion": "ERR-SIM-0601 presente",
                "criterio_descarte": "Sin ERR-SIM-0601",
            },
        },
        {
            "id": "KB-SIM-026",
            "titulo": "Word se cierra: complemento con fallas",
            "n": 3,
            "receta": {
                "hipotesis": "Complemento de Word con fallas",
                "tipo_solucion": "accion",
                "accion_catalogo": "desactivar_complemento",
                "pruebas": [{"herramienta": "logs.word", "requiere": "leer_logs"}],
                "criterio_confirmacion": "ERR-SIM-0602 o complemento con fallas",
                "criterio_descarte": "Sin ERR-SIM-0602",
            },
        },
    ],
}
_SECCIONES_DEMO = {
    "KB-SIM-014": {
        "pasos": "1. Abre Configuración > Sistema > Almacenamiento.\n2. Usa «Liberar espacio ahora».\n"
        "3. Reanuda OneDrive desde su ícono.",
        "verificacion": "OneDrive muestra «Al día».",
    },
    "KB-SIM-025": {
        "pasos": "1. Cierra Word.\n2. Renombra Normal.dotm a Normal.old.\n3. Abre Word de nuevo.",
        "verificacion": "Word abre sin cerrarse.",
    },
}


class RepositorioKBMemoria:
    def __init__(self, kb: dict[str, list[dict[str, Any]]] | None = None, secciones: dict | None = None):
        self._kb = kb if kb is not None else _KB_DEMO
        self._secciones = secciones if secciones is not None else _SECCIONES_DEMO

    async def clasificar(self, vector: list[float]) -> list[tuple[str, float]]:
        return []

    async def hipotesis(self, categoria: str) -> list[Hipotesis]:
        filas = self._kb.get(categoria, [])
        priors = _priors({f["id"]: f["n"] for f in filas})
        hs = [
            Hipotesis(f["id"], f["titulo"], f["receta"]["hipotesis"], f["receta"], priors[f["id"]], f["n"])
            for f in filas
        ]
        return sorted(hs, key=lambda h: -h.prior)

    async def secciones(self, articulo_id: str) -> dict[str, str]:
        return dict(self._secciones.get(articulo_id, {}))

    async def categoria_fuera_alcance(self, categoria: str) -> bool:
        return categoria in ("hardware.dano_fisico", "identidad.acceso")

"""Bandeja de aprobaciones N2: sondeo, notificación única (persistente) e historial propio (ADR 0022).

- `sondear` consulta la API N2 cada `N2_POLL_S` s. Una solicitud `pendiente` con un id nunca visto genera UNA
  notificación. Los ids vistos se guardan en disco (`N2_STATE_FILE`), así un reinicio no notifica dos veces.
- Cada decisión de un técnico queda en el historial propio (quién, qué, cuándo, nota, resultado).
- El sondeo SOLO lee: nunca aprueba ni rechaza (solo humanos deciden).
- `diagnostico` y `comando` son texto que redactó una IA: se guardan y devuelven tal cual, como dato; la UI los
  muestra escapados y nada en el backend los interpreta.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.integraciones.n2.cliente import ClienteN2, ErrorN2
from app.integraciones.zabbix.catalogo_mcp import BLOQUEADAS, TOOLS, PoliticaMCP
from app.observabilidad.langfuse import enmascarar_texto

log = logging.getLogger(__name__)

RIESGO = {"recrear_perfil_outlook": "medio", "asignar_licencia_office": "medio", "ejecutar_comando_generico": "alto"}
QUE_REVISAR = {
    "recrear_perfil_outlook": "Que el diagnóstico muestre el perfil dañado y que ya se intentó la reparación rápida.",
    "asignar_licencia_office": "Que la licencia figure «sin-licencia» y que el usuario tenga derecho a ella "
    "(impacto en costo).",
    "ejecutar_comando_generico": "El comando exacto, línea por línea: qué hace y si es reversible.",
}
# Campos de una solicitud que se muestran (lo necesario para decidir; nada más pasa al navegador).
CAMPOS_SOLICITUD = (
    "id",
    "tool",
    "equipo",
    "caso_id",
    "diagnostico",
    "comando",
    "estado",
    "creada",
    "usada",
    "usada_en",
    "tecnico_n2",
    "nota_n2",
    "decidida",
)
# Auditoría y consentimientos del servidor: solo estos campos, con el texto enmascarado.
CAMPOS_REGISTRO = (
    "id",
    "tool",
    "accion",
    "evento",
    "tipo",
    "equipo",
    "caso_id",
    "estado",
    "resultado",
    "consentimiento_id",
    "aprobacion_id",
    "fecha",
    "hora",
    "ts",
    "creada",
    "decidida",
    "usada",
    "usada_en",
)
TTL_CACHE_S = 5
MAX_NOTIFICACIONES = 500
MAX_DECISIONES = 2000


def _ahora() -> datetime:
    return datetime.now(UTC)


def aprobable(tool: str | None) -> bool:
    """Solo se APRUEBA lo que este sistema permite: acciones de política N2 del catálogo propio. Nunca un comando
    libre (`ejecutar_comando_generico`) ni una tool fuera de la lista blanca: esas solo se pueden rechazar."""
    return bool(tool) and tool not in BLOQUEADAS and TOOLS.get(str(tool)) is PoliticaMCP.APROBACION_N2


def huella(a: dict[str, Any]) -> str:
    """Lo que el técnico vio (tool, equipo, caso, diagnóstico, comando): la decisión queda ligada a eso."""
    partes = [str(a.get(k) or "") for k in ("tool", "equipo", "caso_id", "diagnostico", "comando")]
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).hexdigest()


def limpiar_registro(r: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (enmascarar_texto(v)[:200] if isinstance(v, str) else v)
        for k, v in r.items()
        if k in CAMPOS_REGISTRO and (v is None or isinstance(v, str | int | float | bool))
    }


def _fecha(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


class AlmacenN2:
    """Estado propio en un archivo JSON (escritura atómica). Ids vistos, notificaciones y decisiones."""

    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self._lock = asyncio.Lock()
        self.datos: dict[str, Any] = {"vistas": [], "notificaciones": [], "decisiones": []}
        try:
            if self.ruta.is_file():
                cargado = json.loads(self.ruta.read_text(encoding="utf-8"))
                if isinstance(cargado, dict):
                    self.datos.update({k: list(cargado.get(k) or []) for k in self.datos})
        except (OSError, ValueError):
            log.exception("No pude leer el estado N2 (%s); empiezo vacío", self.ruta.name)

    def _escribir(self, contenido: str) -> None:
        # Un solo proceso escribe (un worker, ADR 0022); temporal con nombre único + reemplazo atómico.
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_name(f".{self.ruta.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(contenido, encoding="utf-8")
        os.replace(tmp, self.ruta)

    async def _guardar(self) -> None:
        await asyncio.to_thread(self._escribir, json.dumps(self.datos, ensure_ascii=False))

    async def registrar_nuevas(self, pendientes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        async with self._lock:
            vistas = set(self.datos["vistas"])
            nuevas = [a for a in pendientes if a["id"] not in vistas]
            for a in nuevas:
                self.datos["vistas"].append(a["id"])
                self.datos["notificaciones"].append(
                    {
                        "id": a["id"],
                        "tool": a.get("tool"),
                        "riesgo": RIESGO.get(str(a.get("tool")), "desconocido"),
                        "equipo": a.get("equipo"),
                        "caso_id": a.get("caso_id"),
                        "creada": a.get("creada"),
                        "notificada_en": _ahora().isoformat(timespec="seconds"),
                    }
                )
            if nuevas:
                self.datos["notificaciones"] = self.datos["notificaciones"][-MAX_NOTIFICACIONES:]
                await self._guardar()
            return nuevas

    async def registrar_decision(self, registro: dict[str, Any]) -> None:
        """Una fila por intento; si el mismo técnico repite la misma decisión con éxito, no se duplica."""
        registro = {**registro, "nota": enmascarar_texto(str(registro.get("nota") or ""))}
        async with self._lock:
            ya = next(
                (
                    d
                    for d in self.datos["decisiones"]
                    if registro["resultado"] == "ok"
                    and (d.get("id"), d.get("decision"), d.get("tecnico"), d.get("resultado"))
                    == (registro["id"], registro["decision"], registro["tecnico"], "ok")
                ),
                None,
            )
            if ya is None:
                self.datos["decisiones"].append(registro)
                self.datos["decisiones"] = self.datos["decisiones"][-MAX_DECISIONES:]
                await self._guardar()


class BandejaN2:
    def __init__(self, cliente: ClienteN2, almacen: AlmacenN2, *, poll_s: int = 10, sin_ejecutar_min: int = 30):
        self.cliente = cliente
        self.almacen = almacen
        self.poll_s = max(2, int(poll_s))
        self.sin_ejecutar = timedelta(minutes=sin_ejecutar_min)
        self.ultima: list[dict[str, Any]] = []
        self.actualizado: str | None = None
        self.error: str | None = None

    @property
    def configurada(self) -> bool:
        return self.cliente.configurado

    def enriquecer(self, a: dict[str, Any]) -> dict[str, Any]:
        """Campos calculados por código para la UI (riesgo, qué revisar, «aprobada sin ejecutar»)."""
        decidida = _fecha(a.get("decidida"))
        sin_ejecutar = bool(
            a.get("estado") == "aprobada"
            and not a.get("usada")
            and decidida
            and _ahora() - decidida > self.sin_ejecutar
        )
        return {
            **{k: a.get(k) for k in CAMPOS_SOLICITUD if k in a},
            "riesgo": RIESGO.get(str(a.get("tool")), "desconocido"),
            "que_revisar": QUE_REVISAR.get(str(a.get("tool"))),
            "aprobada_sin_ejecutar": sin_ejecutar,
            "aprobable": aprobable(a.get("tool")),
            "huella": huella(a),
        }

    async def lista(self, *, vivo: bool = False) -> tuple[list[dict[str, Any]], str]:
        """La caché del sondeo si es reciente (no se multiplica la carga por pestaña); si no, en vivo."""
        reciente = (
            self.actualizado and (_ahora() - datetime.fromisoformat(self.actualizado)).total_seconds() < TTL_CACHE_S
        )
        if reciente and not vivo:
            return self.ultima, "vivo"
        try:
            return await self.actualizar(), "vivo"
        except ErrorN2 as err:
            if err.tipo == "no_configurado":
                raise
            self.error = err.tipo
            return self.ultima, "cache"

    async def actualizar(self) -> list[dict[str, Any]]:
        """Una consulta: refresca la caché y notifica (una sola vez) las pendientes nuevas."""
        lista = await self.cliente.listar()
        self.ultima, self.actualizado, self.error = lista, _ahora().isoformat(timespec="seconds"), None
        nuevas = await self.almacen.registrar_nuevas([a for a in lista if a.get("estado") == "pendiente"])
        for a in nuevas:
            log.info("Nueva solicitud N2 %s (%s) para el equipo %s", a["id"], a.get("tool"), a.get("equipo"))
        return lista

    async def sondear(self) -> None:
        """Tarea de fondo: nunca tumba la API ni decide nada."""
        while True:
            try:
                await self.actualizar()
            except ErrorN2 as err:
                self.error = err.tipo
                if err.tipo != "no_configurado":
                    log.warning("Sondeo N2 falló: %s", err.tipo)
            except Exception as err:  # noqa: BLE001
                self.error = "inesperado"
                log.error("Sondeo N2 falló: %s", type(err).__name__)  # sin traza: nada de encabezados en logs
            await asyncio.sleep(self.poll_s)

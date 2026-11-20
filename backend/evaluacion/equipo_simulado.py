"""Equipo simulado con la misma interfaz que el cliente MCP (`llamar_tool`). Configurable por guion.

Simula telemetría, tablero, logs, consentimiento (la ventana «Soporte TI»), aprobación N2 y el EFECTO de cada acción
(p. ej., reiniciar la cola deja 0 trabajos), para que la verificación posterior tenga sentido.
"""

from __future__ import annotations

import itertools
from typing import Any

EQUIPO = "EQ-EVAL-001"

# Efecto de cada acción del catálogo sobre el estado simulado (lo que vería la verificación).
EFECTOS: dict[str, dict[str, Any]] = {
    "reiniciar_cola_impresion": {"cola": 0},
    "recrear_perfil_outlook": {"perfil": "ok"},
    "limpiar_cache_teams": {"teams_cache": "ok"},
    "resincronizar_onedrive": {"onedrive_en_ejecucion": True},
    "reparacion_rapida_office": {"logs": []},
    "asignar_licencia_office": {"licencia": "instalado"},
}


# Historial de versiones de OneDrive (forma real del servidor: incluye ruta y autor, que NO deben guardarse).
def archivos_demo() -> dict[str, list[dict[str, Any]]]:
    return {
        "Presupuesto Q4.xlsx": [
            {
                "id": "v3",
                "fecha": "2026-11-19T14:05:00+00:00",
                "tamanoKB": 12.4,
                "modificadoPor": "usuario",
                "actual": True,
            },
            {
                "id": "v2",
                "fecha": "2026-11-18T21:40:00+00:00",
                "tamanoKB": 231.0,
                "modificadoPor": "usuario",
                "actual": False,
            },
            {
                "id": "v1",
                "fecha": "2026-11-10T13:00:00+00:00",
                "tamanoKB": 198.4,
                "modificadoPor": "usuario",
                "actual": False,
            },
        ]
    }


def responder_versiones(archivos: dict[str, list[dict[str, Any]]], pedido: str) -> dict[str, Any]:
    coinc = [
        {"archivo": n, "ruta": f"C:\\Users\\u1\\OneDrive\\{n}", "versiones": vs}
        for n, vs in archivos.items()
        if pedido.lower() in n.lower()
    ]
    return {"coincidencias": coinc, "detalle": "Solo metadatos del historial de versiones (OneDrive)."}


def restaurar(archivos: dict[str, list[dict[str, Any]]], archivo: str, version_id: str) -> bool:
    """Como el servidor: la versión elegida pasa a ser la vigente y la actual se conserva (copia)."""
    vs = archivos.get(archivo)
    elegida = next((v for v in vs or [] if v["id"] == version_id), None)
    if elegida is None:
        return False
    for v in vs:
        v["actual"] = False
    vs.insert(0, {**elegida, "id": f"v{len(vs) + 1}", "fecha": "2026-11-19T15:00:00+00:00", "actual": True})
    return True


class EquipoSimulado:
    def __init__(self, cfg: dict[str, Any] | None = None):
        c = cfg or {}
        self.estado: dict[str, Any] = {
            "disco_libre": c.get("disco_libre", 120.0),
            "disco_usado": c.get("disco_usado", 80.0),
            "cola": c.get("cola", 0),
            "perfil": c.get("perfil", "ok"),
            "licencia": c.get("licencia", "instalado"),
            "teams_version": c.get("teams_version", "24295"),
            "teams_cache": c.get("teams_cache", "ok"),
            "teams_audio": c.get("teams_audio", "ok"),
            "onedrive_en_ejecucion": c.get("onedrive_en_ejecucion", True),
            "logs": list(c.get("logs", [])),
            "tablero": c.get("tablero") or {},
            "archivos": c.get("archivos") or archivos_demo(),
        }
        self.consentimiento = c.get("consentimiento", "aprobado")  # lo que «hace» el usuario en la ventana
        self.aprobacion_n2 = c.get("aprobacion_n2", "aprobada")
        self.fallar: set[str] = set(c.get("fallar", []))
        self.llamadas: list[tuple[str, dict[str, Any]]] = []
        self.acciones: list[dict[str, Any]] = []  # acciones ejecutadas (con qué autorización)
        self._n = itertools.count(1)
        self._consentimientos: set[str] = set()

    def nombres(self) -> list[str]:
        return [n for n, _ in self.llamadas]

    async def llamar_tool(self, nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]:  # noqa: C901, PLR0911
        self.llamadas.append((nombre, argumentos))
        if nombre in self.fallar:
            return {"ok": False, "tool": nombre, "error_script": "sin-sesion-usuario"}
        e = self.estado
        base = {"ok": True, "tool": nombre}
        match nombre:
            case "listar_equipos":
                return {**base, "equipos": [{"equipo": EQUIPO, "nombre": "PC-EVAL", "agente": "disponible"}]}
            case "estado_servicio":
                operativo = {"estado": "operativo", "mensaje": "Sin incidentes."}
                tablero = {"correo": operativo, "teams": operativo, "almacenamiento": operativo, **e["tablero"]}
                return {"ok": True, "tablero": tablero, "consultado": "2026-11-19T09:00:00-05:00"}
            case "telemetria_equipo":
                return {
                    **base,
                    "resultado": {
                        "so": "Microsoft Windows 11 Pro",
                        "build": "10.0.26300",
                        "ramLibreMB": 6000,
                        "discoLibreGB": e["disco_libre"],
                        "discoUsadoGB": e["disco_usado"],
                    },
                }
            case "version_office":
                return {**base, "resultado": "16.0.17928.20156"}
            case "estado_licencia_office":
                return {**base, "resultado": {"producto": "O365ProPlusRetail", "estado": e["licencia"]}}
            case "estado_onedrive":
                return {**base, "resultado": {"enEjecucion": e["onedrive_en_ejecucion"], "cuentas": [{"cuenta": "x"}]}}
            case "estado_cola_impresion":
                return {**base, "resultado": {"trabajosEnCola": e["cola"]}}
            case "estado_perfil_outlook":
                return {
                    **base,
                    "resultado": {
                        "estado": e["perfil"],
                        "perfilPredeterminadoExiste": e["perfil"] == "ok",
                        "ost": {"cantidad": 1, "tamanoMB": 900},
                    },
                }
            case "estado_teams":
                return {
                    **base,
                    "resultado": {
                        "version": e["teams_version"],
                        "estadoCache": e["teams_cache"],
                        "audio": e["teams_audio"],
                    },
                }
            case "solicitar_consentimiento":
                cid = f"CS-EVAL{next(self._n):04d}"
                self._consentimientos.add(cid)
                return {**base, "id": cid, "estado": "pendiente"}
            case "consultar_consentimiento":
                return {**base, "estado": self.consentimiento}
            case "solicitar_aprobacion_n2":
                return {**base, "id": f"AP-EVAL{next(self._n):04d}", "estado": "pendiente"}
            case "consultar_aprobacion":
                return {**base, "estado": self.aprobacion_n2}
            case "leer_logs_aplicacion":
                return {**base, "resultado": e["logs"]}
            case "versiones_archivo":
                return {**base, "resultado": responder_versiones(e["archivos"], str(argumentos.get("archivo", "")))}
            case _:
                # Acción del catálogo: se registra con su autorización y se aplica su efecto.
                self.acciones.append(
                    {
                        "tool": nombre,
                        "consentimiento_id": argumentos.get("consentimiento_id"),
                        "aprobacion_id": argumentos.get("aprobacion_id"),
                        "con_token": argumentos.get("consentimiento_id") in self._consentimientos,
                        "parametros": {k: argumentos[k] for k in ("archivo", "version_id") if k in argumentos},
                    }
                )
                if nombre == "restaurar_version_archivo" and not restaurar(
                    e["archivos"], str(argumentos.get("archivo")), str(argumentos.get("version_id"))
                ):
                    return {"ok": False, "tool": nombre, "error": "version no encontrada"}
                e.update(EFECTOS.get(nombre, {}))
                return {**base, "resultado": "hecho"}

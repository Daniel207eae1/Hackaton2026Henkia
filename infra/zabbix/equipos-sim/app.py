"""Simulador de equipos (equipos-sim). Esqueleto F0; efectos reales en F4 (ADR 0005).

Recibe las llamadas de los scripts webhook de Zabbix, aplica el efecto sobre el equipo
FICTICIO y (en F4) reenvía la telemetría resultante a Zabbix por trapper.
NUNCA ejecuta comandos en ninguna máquina: solo cambia un diccionario en memoria.
"""

import re

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="equipos-sim (datos sintéticos)")

# Lista blanca: acciones permitidas del catálogo con efecto en el equipo. Las prohibidas no existen.
ACCIONES_PERMITIDAS = {
    "leer_logs",
    "reparacion_rapida_office",
    "recrear_perfil_outlook",
    "limpiar_cache_teams",
    "reiniciar_cola_impresion",
    "restaurar_version_anterior",
    "resincronizar_onedrive",
}
_HOST = re.compile(r"^EQ-SIM-\d{3}$")


class PeticionAccion(BaseModel):
    host: str = Field(pattern=_HOST.pattern)


@app.get("/salud")
def salud() -> dict:
    return {"estado": "ok", "acciones": sorted(ACCIONES_PERMITIDAS)}


@app.post("/acciones/{accion_id}")
def ejecutar(accion_id: str, peticion: PeticionAccion) -> dict:
    if accion_id not in ACCIONES_PERMITIDAS:
        raise HTTPException(404, "Acción fuera de la lista blanca")
    # F4: aplicar el efecto ficticio y reenviar telemetría por trapper.
    return {"host": peticion.host, "accion": accion_id, "resultado": "no_implementado_f0"}

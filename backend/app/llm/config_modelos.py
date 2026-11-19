"""Carga y validación de `config/modelos.yaml` (ADR 0004).

La validación corre al arrancar la API: si un modelo de la cadena de un agente no declara las
capacidades que el agente requiere, la API no arranca y el error dice exactamente qué falta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.llm.puerto import Capacidad


class ErrorConfiguracionModelos(Exception):
    pass


@dataclass(frozen=True)
class ConfigProveedor:
    nombre: str
    tipo: str
    base_url: str = ""
    api_key: str = ""
    cabeceras: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 60.0
    requiere_clave: bool = False

    @property
    def disponible(self) -> bool:
        if self.tipo == "fake":
            return True
        return bool(self.base_url) and (bool(self.api_key) or not self.requiere_clave)


@dataclass(frozen=True)
class ConfigModelo:
    alias: str
    proveedor: str
    id: str
    capacidades: frozenset[Capacidad]
    precio_entrada_1m: float | None = None
    precio_salida_1m: float | None = None
    dimension: int | None = None
    parametros: dict[str, Any] = field(default_factory=dict)
    etiqueta: str = ""  # texto del selector de la página (modo demo)
    licencia: str = ""  # propios del modelo (se fusionan con los del agente)


@dataclass(frozen=True)
class ConfigAgente:
    nombre: str
    requiere: frozenset[Capacidad]
    parametros: dict[str, Any]
    cadena: tuple[str, ...]


@dataclass(frozen=True)
class ConfigResiliencia:
    reintentos_por_modelo: int = 2
    backoff_base_s: float = 1.0
    backoff_max_s: float = 20.0


@dataclass(frozen=True)
class ConfigModelos:
    proveedores: dict[str, ConfigProveedor]
    modelos: dict[str, ConfigModelo]
    agentes: dict[str, ConfigAgente]
    resiliencia: ConfigResiliencia


def _capacidades(valores: list[str], donde: str) -> frozenset[Capacidad]:
    try:
        return frozenset(Capacidad(v) for v in valores)
    except ValueError as exc:
        raise ErrorConfiguracionModelos(f"{donde}: capacidad desconocida ({exc})") from exc


def cargar_config(ruta: Path, *, modo: str = "real", entorno: dict[str, str] | None = None) -> ConfigModelos:
    env = dict(os.environ) if entorno is None else entorno
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))

    proveedores: dict[str, ConfigProveedor] = {}
    for nombre, p in (datos.get("proveedores") or {}).items():
        base = p.get("base_url") or env.get(p.get("base_url_env", ""), "")
        if base:
            base = base.rstrip("/") + p.get("sufijo_ruta", "")
        proveedores[nombre] = ConfigProveedor(
            nombre=nombre,
            tipo=p["tipo"],
            base_url=base,
            api_key=env.get(p.get("api_key_env", ""), "") if p.get("api_key_env") else "",
            cabeceras={
                **dict(p.get("cabeceras") or {}),
                # Cabeceras cuyo valor sale de una variable de entorno (p. ej., X-HF-Bill-To); vacías se omiten.
                **{k: env[v] for k, v in (p.get("cabeceras_env") or {}).items() if env.get(v)},
            },
            timeout_s=float(p.get("timeout_s", 60)),
            requiere_clave=bool(p.get("api_key_env")),
        )

    modelos: dict[str, ConfigModelo] = {}
    for alias, m in (datos.get("modelos") or {}).items():
        if m["proveedor"] not in proveedores:
            raise ErrorConfiguracionModelos(f"modelo '{alias}': proveedor '{m['proveedor']}' no existe")
        model_id = env.get(m.get("id_env", ""), "") or m.get("id")
        if not model_id:
            raise ErrorConfiguracionModelos(f"modelo '{alias}': falta 'id' o la variable {m.get('id_env')}")
        dim_txt = env.get(m.get("dimension_env", ""), "") if m.get("dimension_env") else ""
        precio = m.get("precio_referencia") or {}
        modelos[alias] = ConfigModelo(
            alias=alias,
            proveedor=m["proveedor"],
            id=model_id,
            capacidades=_capacidades(m.get("capacidades", []), f"modelo '{alias}'"),
            precio_entrada_1m=precio.get("entrada_usd_1m"),
            precio_salida_1m=precio.get("salida_usd_1m"),
            dimension=int(dim_txt) if dim_txt else m.get("dimension"),
            parametros=dict(m.get("parametros") or {}),
            etiqueta=m.get("etiqueta") or alias,
            licencia=m.get("licencia") or "",
        )

    fake = datos.get("modo_fake") or {}
    agentes: dict[str, ConfigAgente] = {}
    for nombre, a in (datos.get("agentes") or {}).items():
        requiere = _capacidades(a.get("requiere", []), f"agente '{nombre}'")
        cadena = tuple(a.get("cadena") or ())
        if modo == "fake":
            clave = "embeddings" if Capacidad.EMBEDDINGS in requiere else "chat"
            cadena = (fake[clave],)
        if not cadena:
            raise ErrorConfiguracionModelos(f"agente '{nombre}': cadena vacía")
        agentes[nombre] = ConfigAgente(nombre, requiere, dict(a.get("parametros") or {}), cadena)

    r = datos.get("resiliencia") or {}
    config = ConfigModelos(proveedores, modelos, agentes, ConfigResiliencia(**r))
    validar(config)
    return config


def validar(config: ConfigModelos) -> None:
    """Cada modelo de la cadena debe existir y declarar TODAS las capacidades del agente."""
    errores: list[str] = []
    for agente in config.agentes.values():
        for alias in agente.cadena:
            modelo = config.modelos.get(alias)
            if modelo is None:
                errores.append(f"agente '{agente.nombre}': modelo '{alias}' no está en 'modelos'")
                continue
            faltan = agente.requiere - modelo.capacidades
            if faltan:
                nombres = ", ".join(sorted(c.value for c in faltan))
                errores.append(f"agente '{agente.nombre}': el modelo '{alias}' no declara [{nombres}]")
    if errores:
        raise ErrorConfiguracionModelos("Configuración de modelos inválida:\n- " + "\n- ".join(errores))

"""Registro de clientes LLM por agente (ADR 0004).

Uso desde un agente (nunca con nombres de modelo):

    cliente = registro.para("conversacional")
    async for delta in cliente.stream_texto(mensajes, prompt=prompt_lf):
        ...

Responsabilidades: cadena de fallback, reintentos con backoff ante 429/5xx, salida estructurada
portable, y una *generation* de Langfuse por intento con uso y costo de referencia.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.adaptadores.fake import AdaptadorFake
from app.llm.adaptadores.openai_compatible import AdaptadorOpenAICompatible
from app.llm.config_modelos import ConfigAgente, ConfigModelo, ConfigModelos
from app.llm.puerto import Capacidad, ErrorLLM, Mensaje, ProveedorLLM, Uso
from app.observabilidad.langfuse import evento, observacion

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Modelo elegido en el selector de la página para ESTA petición (solo modo demo; lo fija la API).
# Va primero en la cadena de cada agente que pueda usarlo; los demás agentes siguen con su cadena.
modelo_preferido: ContextVar[str | None] = ContextVar("modelo_preferido", default=None)


class SinModeloDisponible(Exception):
    """Ningún modelo de la cadena respondió. El orquestador debe tomar el camino seguro."""


def _costo(modelo: ConfigModelo, uso: Uso) -> dict[str, float]:
    entrada = (modelo.precio_entrada_1m or 0.0) * uso.tokens_entrada / 1_000_000
    salida = (modelo.precio_salida_1m or 0.0) * uso.tokens_salida / 1_000_000
    return {"input": entrada, "output": salida}


def _uso_lf(uso: Uso) -> dict[str, int]:
    return {"input": uso.tokens_entrada, "output": uso.tokens_salida}


class ClienteAgente:
    def __init__(self, registro: RegistroLLM, agente: ConfigAgente):
        self._r = registro
        self.agente = agente

    def _params(self, modelo: ConfigModelo) -> dict[str, Any]:
        """Parámetros del modelo (p. ej., apagar el razonamiento) + los del agente (prevalecen), salvo
        `max_tokens`: se toma el mayor, porque un modelo de razonamiento necesita margen para pensar."""
        params = {**modelo.parametros, **self.agente.parametros}
        if "max_tokens" in modelo.parametros and "max_tokens" in self.agente.parametros:
            params["max_tokens"] = max(modelo.parametros["max_tokens"], self.agente.parametros["max_tokens"])
        return params

    @property
    def modelo_principal(self) -> str:
        """Id del primer modelo de la cadena (p. ej., para registrar con qué modelo se embebió)."""
        return self._r.config.modelos[self.agente.cadena[0]].id

    def _cadena(self) -> list[str]:
        preferido = modelo_preferido.get()
        modelo = self._r.config.modelos.get(preferido or "")
        if modelo and self.agente.requiere <= modelo.capacidades:
            return [preferido, *(a for a in self.agente.cadena if a != preferido)]
        return list(self.agente.cadena)

    def _opciones(self) -> list[tuple[ConfigModelo, ProveedorLLM]]:
        opciones = []
        for alias in self._cadena():
            modelo = self._r.config.modelos[alias]
            proveedor = self._r.proveedor(modelo.proveedor)
            if self._r.agotado(modelo.proveedor):
                continue
            if proveedor is None:
                log.warning("Agente %s: proveedor de '%s' no disponible, lo salto", self.agente.nombre, alias)
                continue
            opciones.append((modelo, proveedor))
        if not opciones:
            raise SinModeloDisponible(f"agente '{self.agente.nombre}': ningún proveedor configurado")
        return opciones

    async def _esperar(self, intento: int, err: ErrorLLM) -> None:
        res = self._r.config.resiliencia
        espera = err.espera_s or min(res.backoff_max_s, res.backoff_base_s * 2**intento)
        await self._r.dormir(espera * (0.8 + 0.4 * random.random()))  # noqa: S311 - jitter

    async def stream_texto(self, mensajes: list[Mensaje], *, prompt: Any = None) -> AsyncIterator[str]:
        """Fallback solo antes del primer token; después un fallo se propaga."""
        ultimo: Exception | None = None
        for modelo, proveedor in self._opciones():
            if self._r.agotado(modelo.proveedor):
                continue
            for intento in range(self._r.config.resiliencia.reintentos_por_modelo + 1):
                emitido = False
                partes: list[str] = []
                uso = Uso()
                with observacion(
                    self.agente.nombre,
                    tipo="generation",
                    model=modelo.id,
                    input=[{"role": m.rol, "content": m.contenido} for m in mensajes],
                    model_parameters={k: str(v) for k, v in self._params(modelo).items()},
                    prompt=prompt,
                    metadata={"alias": modelo.alias, "intento": str(intento)},
                ) as gen:
                    try:
                        async for frag in proveedor.chat_stream(modelo.id, mensajes, self._params(modelo)):
                            if frag.uso:
                                uso = frag.uso
                            if frag.delta:
                                emitido = True
                                partes.append(frag.delta)
                                yield frag.delta
                        if not emitido:
                            # p. ej., un modelo de razonamiento agotó max_tokens sin escribir respuesta.
                            raise ErrorLLM(
                                f"respuesta vacía (tokens de salida: {uso.tokens_salida})", reintentable=False
                            )
                        gen.update(
                            output="".join(partes),
                            usage_details=_uso_lf(uso),
                            cost_details=_costo(modelo, uso),
                        )
                        return
                    except ErrorLLM as err:
                        gen.update(level="ERROR", status_message=str(err)[:300])
                        ultimo = err
                        if err.cuota_agotada:
                            self._r.marcar_agotado(modelo.proveedor)
                        if emitido or not err.reintentable:
                            if emitido:
                                raise
                            break
                await self._esperar(intento, ultimo)  # type: ignore[arg-type]
        raise SinModeloDisponible(str(ultimo))

    async def texto(self, mensajes: list[Mensaje], *, prompt: Any = None) -> str:
        return "".join([d async for d in self.stream_texto(mensajes, prompt=prompt)])

    async def _con_fallback(self, llamada: Callable[[ConfigModelo, ProveedorLLM], Any]) -> Any:
        ultimo: Exception | None = None
        for modelo, proveedor in self._opciones():
            if self._r.agotado(modelo.proveedor):
                continue
            for intento in range(self._r.config.resiliencia.reintentos_por_modelo + 1):
                try:
                    return await llamada(modelo, proveedor)
                except ErrorLLM as err:
                    ultimo = err
                    if err.cuota_agotada:
                        self._r.marcar_agotado(modelo.proveedor)
                    if not err.reintentable:
                        break
                    await self._esperar(intento, err)
        raise SinModeloDisponible(str(ultimo))

    async def estructurado(self, mensajes: list[Mensaje], esquema: type[T], *, prompt: Any = None) -> T:
        """Salida estructurada portable: json_schema → tool calling forzado → JSON + 1 reintento."""
        schema = esquema.model_json_schema()
        nombre = esquema.__name__

        async def llamada(modelo: ConfigModelo, proveedor: ProveedorLLM) -> T:
            caps = modelo.capacidades
            msgs = list(mensajes)
            for reintento in range(2):
                with observacion(
                    self.agente.nombre,
                    tipo="generation",
                    model=modelo.id,
                    input=[{"role": m.rol, "content": m.contenido} for m in msgs],
                    prompt=prompt,
                    metadata={"alias": modelo.alias},
                ) as gen:
                    if Capacidad.SALIDA_ESTRUCTURADA in caps:
                        r = await proveedor.chat(
                            modelo.id,
                            msgs,
                            self._params(modelo),
                            response_format={
                                "type": "json_schema",
                                "json_schema": {"name": nombre, "strict": True, "schema": schema},
                            },
                        )
                        crudo = r.texto
                    elif Capacidad.TOOLS in caps:
                        herramienta = {"type": "function", "function": {"name": nombre, "parameters": schema}}
                        r = await proveedor.chat(
                            modelo.id,
                            msgs,
                            self._params(modelo),
                            herramientas=[herramienta],
                            herramienta_forzada=nombre,
                        )
                        crudo = (r.llamada_herramienta or {}).get("argumentos", "")
                    else:
                        instruccion = Mensaje(
                            "system",
                            "Responde SOLO con un JSON que cumpla: " + json.dumps(schema, ensure_ascii=False),
                        )
                        r = await proveedor.chat(modelo.id, [instruccion, *msgs], self._params(modelo))
                        crudo = r.texto
                    gen.update(output=crudo, usage_details=_uso_lf(r.uso), cost_details=_costo(modelo, r.uso))
                    try:
                        return esquema.model_validate_json(_limpiar_json(crudo))
                    except ValidationError as exc:
                        gen.update(level="WARNING", status_message="salida inválida")
                        if reintento == 1:
                            raise ErrorLLM(f"salida estructurada inválida: {exc}", reintentable=False) from exc
                        msgs = [
                            *msgs,
                            Mensaje("user", "Tu respuesta no cumplió el esquema. Responde solo el JSON válido."),
                        ]
            raise AssertionError("inalcanzable")

        return await self._con_fallback(llamada)

    async def embeddings(self, textos: list[str]) -> list[list[float]]:
        async def llamada(modelo: ConfigModelo, proveedor: ProveedorLLM) -> list[list[float]]:
            with observacion(
                self.agente.nombre, tipo="embedding", model=modelo.id, metadata={"n": str(len(textos))}
            ) as obs:
                vectores, uso = await proveedor.embeddings(modelo.id, textos, modelo.dimension)
                obs.update(usage_details=_uso_lf(uso))
                return vectores

        return await self._con_fallback(llamada)


def _limpiar_json(texto: str) -> str:
    t = texto.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{") :] if "{" in t else t
    return t


class RegistroLLM:
    def __init__(
        self,
        config: ConfigModelos,
        proveedores: dict[str, ProveedorLLM] | None = None,
        dormir: Callable[[float], Any] = asyncio.sleep,
    ):
        self.config = config
        self.dormir = dormir
        self._proveedores: dict[str, ProveedorLLM] = dict(proveedores or {})
        self._agotados: dict[str, date] = {}

    def agotado(self, nombre: str) -> bool:
        """Cuota diaria agotada hoy (UTC): se salta el proveedor hasta mañana."""
        return self._agotados.get(nombre) == datetime.now(UTC).date()

    def marcar_agotado(self, nombre: str) -> None:
        if not self.agotado(nombre):
            log.warning("Proveedor %s: cuota diaria agotada; se omite hasta mañana (UTC)", nombre)
            evento("llm.cuota_agotada", metadata={"proveedor": nombre})
        self._agotados[nombre] = datetime.now(UTC).date()

    def proveedor(self, nombre: str) -> ProveedorLLM | None:
        if nombre in self._proveedores:
            return self._proveedores[nombre]
        cfg = self.config.proveedores[nombre]
        if not cfg.disponible:
            return None
        if cfg.tipo == "fake":
            prov: ProveedorLLM = AdaptadorFake()
        elif cfg.tipo == "openai_compatible":
            prov = AdaptadorOpenAICompatible(cfg)
        else:
            raise ValueError(f"tipo de proveedor desconocido: {cfg.tipo}")
        self._proveedores[nombre] = prov
        return prov

    def para(self, agente: str) -> ClienteAgente:
        if agente not in self.config.agentes:
            raise KeyError(f"agente '{agente}' no está declarado en modelos.yaml")
        return ClienteAgente(self, self.config.agentes[agente])

    def catalogo_chat(self) -> list[dict[str, Any]]:
        """Modelos de chat para el selector de la página: alias, etiqueta, proveedor y si está disponible."""
        out = []
        for alias, m in self.config.modelos.items():
            prov = self.config.proveedores[m.proveedor]
            if Capacidad.CHAT not in m.capacidades or prov.tipo == "fake":
                continue
            out.append(
                {
                    "alias": alias,
                    "etiqueta": m.etiqueta,
                    "proveedor": m.proveedor,
                    "id": m.id,
                    "capacidades": sorted(c.value for c in m.capacidades),
                    "licencia": m.licencia,
                    "disponible": prov.disponible and not self.agotado(m.proveedor),
                    "precio_referencia": {"entrada_usd_1m": m.precio_entrada_1m, "salida_usd_1m": m.precio_salida_1m},
                }
            )
        return out

    def resumen(self) -> dict[str, list[str]]:
        """Para /api/salud: qué cadena efectiva tiene cada agente (aliases, sin claves)."""
        res = {}
        for nombre, a in self.config.agentes.items():
            res[nombre] = [  # sin claves ni proveedores con la cuota diaria agotada
                al
                for al in a.cadena
                if self.config.proveedores[self.config.modelos[al].proveedor].disponible
                and not self.agotado(self.config.modelos[al].proveedor)
            ]
        return res

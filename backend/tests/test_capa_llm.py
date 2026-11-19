"""Capa LLM agnóstica: validación de capacidades, fallback, 429 y salida estructurada."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.config.ajustes import RAIZ_BACKEND
from app.llm.adaptadores.fake import AdaptadorFake, json_fake
from app.llm.config_modelos import (
    ConfigAgente,
    ConfigModelo,
    ConfigModelos,
    ConfigProveedor,
    ConfigResiliencia,
    ErrorConfiguracionModelos,
    cargar_config,
)
from app.llm.puerto import Capacidad, ErrorLLM, Mensaje
from app.llm.registro import RegistroLLM, SinModeloDisponible

C = Capacidad
YAML = RAIZ_BACKEND / "config" / "modelos.yaml"


async def _sin_espera(_: float) -> None:
    return None


def _config(caps_a: set[Capacidad], caps_b: set[Capacidad], requiere: set[Capacidad]) -> ConfigModelos:
    return ConfigModelos(
        proveedores={"pa": ConfigProveedor("pa", "fake"), "pb": ConfigProveedor("pb", "fake")},
        modelos={
            "ma": ConfigModelo("ma", "pa", "modelo-a", frozenset(caps_a)),
            "mb": ConfigModelo("mb", "pb", "modelo-b", frozenset(caps_b)),
        },
        agentes={"ag": ConfigAgente("ag", frozenset(requiere), {}, ("ma", "mb"))},
        resiliencia=ConfigResiliencia(reintentos_por_modelo=1),
    )


def test_modelos_yaml_real_es_valido():
    config = cargar_config(YAML, modo="real", entorno={"EMBEDDING_MODEL": "x", "EMBEDDING_DIM": "1024"})
    assert {"conversacional", "diagnosticador", "extractor", "vision", "embeddings"} <= set(config.agentes)
    assert config.modelos["qwen3-embedding-local"].dimension == 1024


def test_arranque_falla_si_modelo_no_cumple_capacidad(tmp_path: Path):
    texto = YAML.read_text(encoding="utf-8").replace(
        "requiere: [chat, vision, salida_estructurada]", "requiere: [chat, vision, embeddings]"
    )
    ruta = tmp_path / "modelos.yaml"
    ruta.write_text(texto, encoding="utf-8")
    with pytest.raises(ErrorConfiguracionModelos, match="vision.*embeddings"):
        cargar_config(ruta, entorno={"EMBEDDING_MODEL": "x"})


def test_proveedor_sin_clave_no_esta_disponible():
    config = cargar_config(YAML, entorno={"EMBEDDING_MODEL": "x"})
    assert not config.proveedores["openrouter"].disponible
    assert not config.proveedores["ollama"].disponible
    assert not config.proveedores["huggingface"].disponible
    config2 = cargar_config(
        YAML, entorno={"EMBEDDING_MODEL": "x", "OPENROUTER_API_KEY": "k", "OLLAMA_BASE_URL": "http://o:11434"}
    )
    assert config2.proveedores["openrouter"].disponible
    assert config2.proveedores["ollama"].base_url == "http://o:11434/v1"


async def test_fallback_al_siguiente_modelo_tras_429():
    a, b = AdaptadorFake(), AdaptadorFake()
    a.programar(ErrorLLM("429", reintentable=True), ErrorLLM("429", reintentable=True))
    b.programar("hola desde b")
    reg = RegistroLLM(
        _config({C.CHAT, C.STREAMING}, {C.CHAT, C.STREAMING}, {C.CHAT}),
        proveedores={"pa": a, "pb": b},
        dormir=_sin_espera,
    )
    texto = await reg.para("ag").texto([Mensaje("user", "hola")])
    assert texto == "hola desde b"
    assert len(a.llamadas) == 2  # 1 intento + 1 reintento


async def test_error_no_reintentable_pasa_directo_al_siguiente():
    a, b = AdaptadorFake(), AdaptadorFake()
    a.programar(ErrorLLM("401", reintentable=False))
    b.programar("ok")
    reg = RegistroLLM(_config({C.CHAT}, {C.CHAT}, {C.CHAT}), proveedores={"pa": a, "pb": b}, dormir=_sin_espera)
    assert await reg.para("ag").texto([Mensaje("user", "x")]) == "ok"
    assert len(a.llamadas) == 1


async def test_sin_modelo_disponible():
    a, b = AdaptadorFake(), AdaptadorFake()
    a.programar(ErrorLLM("x", reintentable=False))
    b.programar(ErrorLLM("y", reintentable=False))
    reg = RegistroLLM(_config({C.CHAT}, {C.CHAT}, {C.CHAT}), proveedores={"pa": a, "pb": b}, dormir=_sin_espera)
    with pytest.raises(SinModeloDisponible):
        await reg.para("ag").texto([Mensaje("user", "x")])


class Slots(BaseModel):
    aplicacion: str
    tipo_sintoma: str


@pytest.mark.parametrize(
    ("caps", "esperado"),
    [
        ({C.CHAT, C.SALIDA_ESTRUCTURADA}, "response_format"),
        ({C.CHAT, C.TOOLS}, "herramienta_forzada"),
        ({C.CHAT}, "json_plano"),
    ],
)
async def test_salida_estructurada_portable(caps: set[Capacidad], esperado: str):
    a = AdaptadorFake()
    a.programar_estructurado(json_fake({"aplicacion": "outlook", "tipo_sintoma": "no_abre"}))
    reg = RegistroLLM(_config(caps, caps, {C.CHAT}), proveedores={"pa": a, "pb": AdaptadorFake()}, dormir=_sin_espera)
    r = await reg.para("ag").estructurado([Mensaje("user", "outlook no abre")], Slots)
    assert r == Slots(aplicacion="outlook", tipo_sintoma="no_abre")
    llamada = a.llamadas[0]
    if esperado == "response_format":
        assert llamada["response_format"]["type"] == "json_schema"
    elif esperado == "herramienta_forzada":
        assert llamada["herramienta_forzada"] == "Slots"
    else:
        assert llamada["response_format"] is None and llamada["herramienta_forzada"] is None


async def test_salida_estructurada_reintenta_una_vez():
    a = AdaptadorFake()
    a.programar_estructurado("no es json", json_fake({"aplicacion": "teams", "tipo_sintoma": "sin_audio"}))
    reg = RegistroLLM(
        _config({C.CHAT, C.SALIDA_ESTRUCTURADA}, {C.CHAT}, {C.CHAT}),
        proveedores={"pa": a, "pb": AdaptadorFake()},
        dormir=_sin_espera,
    )
    r = await reg.para("ag").estructurado([Mensaje("user", "x")], Slots)
    assert r.aplicacion == "teams" and len(a.llamadas) == 2


def test_agentes_no_nombran_modelos_ni_proveedores():
    """Regla de agnosticismo: ningún literal de modelo/proveedor en app/agentes ni app/orquestador."""
    prohibidos = ("openrouter", "ollama", "gemma", "nemotron", "qwen", "gpt-", "claude", ":free")
    for carpeta in ("agentes", "orquestador"):
        for ruta in (RAIZ_BACKEND / "app" / carpeta).rglob("*.py"):
            for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
                if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                    valor = nodo.value.lower()
                    assert not any(p in valor for p in prohibidos), f"{ruta.name}: {nodo.value!r}"


async def test_respuesta_vacia_pasa_al_siguiente_modelo():
    """Modelo de razonamiento que agota max_tokens sin escribir: se trata como fallo."""
    a, b = AdaptadorFake(), AdaptadorFake()
    a.programar("")  # stream sin contenido
    b.programar("respuesta de b")
    reg = RegistroLLM(_config({C.CHAT}, {C.CHAT}, {C.CHAT}), proveedores={"pa": a, "pb": b}, dormir=_sin_espera)
    assert await reg.para("ag").texto([Mensaje("user", "x")]) == "respuesta de b"
    assert len(a.llamadas) == 1  # vacía = no reintentable: no insiste con el mismo modelo


async def test_parametros_del_modelo_se_fusionan_con_los_del_agente():
    config = _config({C.CHAT}, {C.CHAT}, {C.CHAT})
    modelo_a = config.modelos["ma"]
    config.modelos["ma"] = ConfigModelo(
        modelo_a.alias,
        modelo_a.proveedor,
        modelo_a.id,
        modelo_a.capacidades,
        parametros={"reasoning": {"enabled": False}, "temperature": 1.0},
    )
    config.agentes["ag"] = ConfigAgente("ag", frozenset({C.CHAT}), {"temperature": 0.2}, ("ma", "mb"))
    cliente = RegistroLLM(config, proveedores={"pa": AdaptadorFake(), "pb": AdaptadorFake()}).para("ag")
    assert cliente._params(config.modelos["ma"]) == {"reasoning": {"enabled": False}, "temperature": 0.2}


def test_nemotron_lightning_apaga_el_razonamiento():
    config = cargar_config(YAML, entorno={"EMBEDDING_MODEL": "x"})
    assert config.modelos["or-nemotron-lightning"].parametros == {"reasoning": {"enabled": False}}


async def test_cuota_diaria_agotada_salta_el_proveedor_sin_reintentos():
    """429 'free-models-per-day': no se reintenta ni se prueban otros modelos del mismo proveedor."""
    config = _config({C.CHAT}, {C.CHAT}, {C.CHAT})
    # ma y mb del mismo proveedor "pa"; se agrega un tercero en otro proveedor.
    config.modelos["mb"] = ConfigModelo("mb", "pa", "modelo-b", frozenset({C.CHAT}))
    config.proveedores["pc"] = ConfigProveedor("pc", "fake")
    config.modelos["mc"] = ConfigModelo("mc", "pc", "modelo-c", frozenset({C.CHAT}))
    config.agentes["ag"] = ConfigAgente("ag", frozenset({C.CHAT}), {}, ("ma", "mb", "mc"))
    a, c = AdaptadorFake(), AdaptadorFake()
    a.programar(ErrorLLM("429 free-models-per-day", reintentable=False, cuota_agotada=True))
    c.programar("respuesta de c", "otra de c")
    reg = RegistroLLM(config, proveedores={"pa": a, "pc": c}, dormir=_sin_espera)
    assert await reg.para("ag").texto([Mensaje("user", "x")]) == "respuesta de c"
    assert len(a.llamadas) == 1  # ni reintento ni el segundo modelo del proveedor agotado
    assert reg.agotado("pa") and reg.resumen()["ag"] == ["mc"]
    # Llamadas posteriores ni lo intentan.
    assert await reg.para("ag").texto([Mensaje("user", "y")]) == "otra de c"
    assert len(a.llamadas) == 1


def test_adaptador_reconoce_429_diario():
    import httpx

    from app.llm.adaptadores.openai_compatible import _error_http

    diario = _error_http(httpx.Response(429, text='{"error":{"message":"Rate limit exceeded: free-models-per-day"}}'))
    por_minuto = _error_http(httpx.Response(429, text='{"error":{"message":"temporarily rate-limited upstream"}}'))
    assert diario.cuota_agotada and not diario.reintentable
    assert not por_minuto.cuota_agotada and por_minuto.reintentable

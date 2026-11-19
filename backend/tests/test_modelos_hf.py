"""Hugging Face como proveedor por defecto y selector de modelo por petición (modo demo)."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config.ajustes import RAIZ_BACKEND
from app.llm.adaptadores.fake import AdaptadorFake
from app.llm.adaptadores.openai_compatible import AdaptadorOpenAICompatible
from app.llm.config_modelos import cargar_config
from app.llm.puerto import Capacidad, Mensaje
from app.llm.registro import RegistroLLM, modelo_preferido
from tests.test_api_f0 import COLAB, _chat

YAML = RAIZ_BACKEND / "config" / "modelos.yaml"
ENV = {"EMBEDDING_MODEL": "x", "HF_TOKEN": "hf_prueba", "HF_BILL_TO": "henkia"}


def test_huggingface_es_el_proveedor_por_defecto_de_los_agentes_de_chat():
    config = cargar_config(YAML, entorno=ENV)
    for nombre in ("conversacional", "interprete", "diagnosticador", "documentacion"):
        primero = config.modelos[config.agentes[nombre].cadena[0]]
        assert primero.proveedor == "huggingface", nombre
    assert config.modelos[config.agentes["embeddings"].cadena[0]].proveedor == "ollama"  # ADR 0011


def test_cabeceras_y_token_de_hf_salen_del_entorno():
    hf = cargar_config(YAML, entorno=ENV).proveedores["huggingface"]
    assert hf.disponible and hf.api_key == "hf_prueba"
    assert hf.cabeceras == {"X-HF-Bill-To": "henkia"}
    sin_factura = cargar_config(YAML, entorno={"EMBEDDING_MODEL": "x", "HF_TOKEN": "t"}).proveedores["huggingface"]
    assert "X-HF-Bill-To" not in sin_factura.cabeceras  # vacía → se omite
    assert not cargar_config(YAML, entorno={"EMBEDDING_MODEL": "x"}).proveedores["huggingface"].disponible


@respx.mock
async def test_peticion_a_hf_lleva_token_y_bill_to():
    ruta = respx.post("https://router.huggingface.co/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "París"}}], "model": "x"})
    )
    hf = cargar_config(YAML, entorno=ENV).proveedores["huggingface"]
    r = await AdaptadorOpenAICompatible(hf).chat("openai/gpt-oss-20b", [Mensaje("user", "capital")], {})
    assert r.texto == "París"
    cab = ruta.calls[0].request.headers
    assert cab["authorization"] == "Bearer hf_prueba" and cab["x-hf-bill-to"] == "henkia"


def test_max_tokens_toma_el_mayor_para_modelos_de_razonamiento():
    reg = RegistroLLM(cargar_config(YAML, entorno=ENV))
    cli = reg.para("conversacional")  # agente pide 1000; gpt-oss declara 4000 (razona y luego responde)
    p = cli._params(reg.config.modelos["hf-gpt-oss-20b"])
    assert p["max_tokens"] == 4000 and p["reasoning_effort"] == "low"
    q = cli._params(reg.config.modelos["hf-gemma4-26b"])
    assert q["max_tokens"] == 1000 and "reasoning_effort" not in q  # en Gemma lo ACTIVARÍA


def test_modelo_preferido_va_primero_si_cumple_capacidades():
    reg = RegistroLLM(cargar_config(YAML, entorno=ENV))
    ficha = modelo_preferido.set("hf-qwen3-30b")
    try:
        assert reg.para("conversacional")._cadena()[0] == "hf-qwen3-30b"
        assert reg.para("vision")._cadena()[0] != "hf-qwen3-30b"  # sin visión: el agente sigue con su cadena
        assert reg.para("embeddings")._cadena() == ["qwen3-embedding-local"]
    finally:
        modelo_preferido.reset(ficha)
    assert reg.para("conversacional")._cadena()[0] == "hf-gpt-oss-20b"


def test_catalogo_chat_para_el_selector():
    reg = RegistroLLM(cargar_config(YAML, entorno=ENV))
    cat = {m["alias"]: m for m in reg.catalogo_chat()}
    assert "fake-chat" not in cat and "qwen3-embedding-local" not in cat
    assert cat["hf-gpt-oss-20b"]["disponible"] and not cat["or-gemma4-26b"]["disponible"]  # sin clave OR
    assert cat["hf-gpt-oss-20b"]["etiqueta"] == "gpt-oss 20B (HF)"
    assert all(Capacidad.CHAT.value in m["capacidades"] for m in cat.values())


# ---------------------------------------------------------------- API


def test_api_modelos_solo_en_modo_demo(cliente: TestClient, monkeypatch: pytest.MonkeyPatch):
    assert "modelos" in cliente.get("/api/modelos").json()
    from app.config.ajustes import obtener_ajustes

    monkeypatch.setenv("MODO_DEMO", "false")
    obtener_ajustes.cache_clear()
    assert cliente.get("/api/modelos").status_code == 403


def test_chat_con_modelo_elegido(cliente: TestClient, fake: AdaptadorFake):
    fake.programar("hola")
    cab = {**COLAB, "X-Modelo": "fake-chat"}  # «fake» no es seleccionable
    assert _chat(cliente, "hola", cabeceras=cab).status_code == 422
    assert _chat(cliente, "hola", cabeceras={**COLAB, "X-Modelo": "no-existe"}).status_code == 422
    assert _chat(cliente, "hola", cabeceras={**COLAB, "X-Modelo": "qwen3-embedding-local"}).status_code == 422
    r = _chat(cliente, "hola", uuid.uuid4().hex, {**COLAB, "X-Modelo": "hf-gpt-oss-20b"})
    assert r.status_code == 200  # en modo fake el alias existe; los agentes siguen usando el doble
    assert modelo_preferido.get() is None  # no se filtra a otras peticiones

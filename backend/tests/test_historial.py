"""Memoria del caso: el conversacional y el intérprete ven TODO lo dicho, no solo los últimos turnos."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.config.ajustes import RAIZ_BACKEND
from app.llm.config_modelos import cargar_config
from tests.dobles import interpretacion
from tests.test_api_f0 import _chat

PRIMERO = "desde el lunes pasado Outlook se cierra cuando adjunto archivos de la carpeta Proyectos"


def test_el_caso_largo_no_olvida_el_primer_mensaje(cliente: TestClient, fake):
    case_id = uuid.uuid4().hex
    mensajes = [PRIMERO, *(f"dato adicional número {i}" for i in range(1, 10))]
    fake.programar_estructurado(*(interpretacion() for _ in mensajes))
    for m in mensajes:
        assert _chat(cliente, m, case_id).status_code == 200
    ultima_conv = [ll for ll in fake.llamadas if ll.get("stream")][-1]
    assert any(PRIMERO in str(m.contenido) for m in ultima_conv["mensajes"])  # 10 turnos = 20 mensajes > 12
    ultima_interp = [ll for ll in fake.llamadas if not ll.get("stream")][-1]
    assert PRIMERO in str(ultima_interp["mensajes"][-1].contenido)  # antes: solo los últimos 6


def test_reasoning_effort_solo_por_modelo():
    """En Gemma 4 `reasoning_effort` ACTIVA el razonamiento: si un agente lo fijara, se filtraría a sus respaldos."""
    config = cargar_config(RAIZ_BACKEND / "config" / "modelos.yaml", modo="real", entorno={})
    for nombre, agente in config.agentes.items():
        assert "reasoning_effort" not in agente.parametros, nombre
        assert "reasoning" not in agente.parametros, nombre
    for alias, modelo in config.modelos.items():
        if "reasoning_effort" in modelo.parametros:
            assert modelo.id.startswith("openai/gpt-oss"), alias


def test_compuerta_descarta_razonamiento_filtrado_en_ingles():
    from app.seguridad.compuerta_preguntas import FiltroPreguntas

    f = FiltroPreguntas(set())
    salida = f.alimentar("We should ask: what message appears?¿Al abrir el archivo aparece algún error? ")
    salida += f.cerrar()
    texto = "".join(salida)
    assert "We should" not in texto and "¿Al abrir el archivo aparece algún error?" in texto
    assert f.meta_descartadas == 1 and f.preguntas == 1
    # El español normal no se toca.
    g = FiltroPreguntas(set())
    assert "".join([*g.alimentar("Entiendo. ¿Desde cuándo pasa? "), *g.cerrar()]) == "Entiendo. ¿Desde cuándo pasa? "

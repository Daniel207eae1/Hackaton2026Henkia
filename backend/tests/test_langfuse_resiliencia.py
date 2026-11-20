"""Langfuse nunca bloquea: con claves configuradas pero el servidor caído, el turno termina bien y queda en la ITSM."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.llm.adaptadores.fake import AdaptadorFake
from app.observabilidad import langfuse as obs
from tests.test_api_f0 import COLAB, _chat, _partes


def _langfuse_caido() -> MagicMock:
    """Cliente con claves válidas cuyo servidor no responde: falla lo que consulta la API (como en vivo)."""
    lf = MagicMock()
    lf.get_current_trace_id.return_value = "traza-1"
    lf.get_trace_url.side_effect = ConnectionError("[Errno 111] Connection refused")
    lf.get_prompt.side_effect = ConnectionError("[Errno 111] Connection refused")
    return lf


def test_url_traza_actual_devuelve_none_si_langfuse_no_responde():
    obs.reiniciar_para_pruebas(_langfuse_caido())
    assert obs.url_traza_actual() is None


def test_url_traza_actual_con_langfuse_disponible():
    lf = MagicMock()
    lf.get_current_trace_id.return_value = "t1"
    lf.get_trace_url.return_value = "http://lf/project/p/traces/t1"
    obs.reiniciar_para_pruebas(lf)
    assert obs.url_traza_actual() == "http://lf/project/p/traces/t1"


def test_turno_de_chat_termina_bien_y_queda_en_la_itsm_con_langfuse_caido(cliente: TestClient, fake: AdaptadorFake):
    obs.reiniciar_para_pruebas(_langfuse_caido())
    fake.programar("Hola, ya reviso tu Outlook.")
    case_id = uuid.uuid4().hex
    partes = _partes(_chat(cliente, "el outlook no abre", case_id))
    tipos = [p["type"] for p in partes]
    assert "error" not in tipos and tipos[-1] == "finish"
    caso = next(p for p in partes if p["type"] == "data-caso")
    assert caso["data"]["traza_url"] is None
    assert cliente.get(f"/api/casos/{case_id}", headers=COLAB).status_code == 200
    registrados = cliente.get("/api/n2/casos", headers={"X-Ver-Como": "TEC-SIM-01"}).json()
    assert case_id in {c.get("case_id") for c in registrados}

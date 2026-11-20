"""Monitor de agentes (ADR 0023): bus en memoria, enganches y endpoints. Sin red, LLM fake, sin Langfuse."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config.ajustes import obtener_ajustes
from app.llm.adaptadores.fake import AdaptadorFake
from app.observabilidad import langfuse as obs_lf
from app.observabilidad import monitor
from app.observabilidad.langfuse import observacion
from tests.test_api_f0 import _chat, _partes


@pytest.fixture(autouse=True)
def _bus_limpio():
    monitor.reiniciar_para_pruebas()
    yield
    monitor.reiniciar_para_pruebas()


def _vaciar(cola: asyncio.Queue) -> list[dict]:
    eventos = []
    while not cola.empty():
        eventos.append(cola.get_nowait())
    return eventos


# ------------------------------------------------------------------ bus


def test_publicar_sin_suscriptores_no_falla():
    monitor.publicar("etapa", etapa="Recepcion")
    assert monitor.suscriptores() == 0


async def test_publicar_entrega_metadatos_con_caso_ts_y_seq():
    cola = monitor.suscribir()
    ficha = monitor.fijar_caso("caso-123")
    try:
        monitor.publicar("etapa", etapa="Contexto")
        monitor.publicar("etapa", etapa="Hipotesis")
    finally:
        monitor.liberar_caso(ficha)
    a, b = _vaciar(cola)
    assert a["tipo"] == "etapa" and a["etapa"] == "Contexto" and a["caso"] == "caso-123"
    assert isinstance(a["ts"], int) and b["seq"] > a["seq"]
    assert monitor.caso_actual.get() is None


async def test_cola_llena_descarta_sin_bloquear(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(monitor, "MAX_COLA", 3)
    cola = monitor.suscribir()
    for i in range(10):
        monitor.publicar("etapa", etapa=f"E{i}")
    assert cola.qsize() == 3
    assert [e["etapa"] for e in _vaciar(cola)] == ["E0", "E1", "E2"]


async def test_excepcion_interna_no_se_propaga(monkeypatch: pytest.MonkeyPatch):
    monitor.suscribir()

    def explota() -> bool:
        raise RuntimeError("bus roto")

    monkeypatch.setattr(monitor, "activo", explota)
    monitor.publicar("etapa", etapa="Recepcion")  # no lanza


async def test_tope_de_suscriptores_y_desuscribir(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(monitor, "MAX_SUSCRIPTORES", 2)
    a, b = monitor.suscribir(), monitor.suscribir()
    assert a is not None and b is not None
    assert monitor.suscribir() is None and not monitor.hay_cupo()
    monitor.desuscribir(a)
    monitor.desuscribir(b)
    assert monitor.suscriptores() == 0


async def test_monitor_inactivo_no_publica(monkeypatch: pytest.MonkeyPatch):
    cola = monitor.suscribir()
    monkeypatch.setenv("MONITOR_ACTIVO", "false")
    obtener_ajustes.cache_clear()
    monitor.publicar("etapa", etapa="Recepcion")
    assert cola.empty()


async def test_publicar_desde_otro_hilo_llega_al_bucle():
    cola = monitor.suscribir()
    hilo = threading.Thread(target=monitor.publicar, args=("etapa",), kwargs={"etapa": "Captura"})
    hilo.start()
    hilo.join()
    evento = await asyncio.wait_for(cola.get(), timeout=1)
    assert evento["etapa"] == "Captura"


def test_etiqueta_no_deja_pasar_texto_libre():
    assert monitor.etiqueta("zabbix.estado_teams") == "zabbix.estado_teams"
    assert monitor.etiqueta("hola <script> mundo") == "hola__script__mundo"
    assert len(monitor.etiqueta("x" * 500)) == monitor.MAX_ETIQUETA


# ------------------------------------------------------------------ enganches: observacion() y /api/chat


class _Boom(Exception):
    pass


class _LangfuseFalso:
    """Doble mínimo del SDK: registra que la observación se abrió y vio la excepción del llamador."""

    def __init__(self) -> None:
        self.vistas: list[tuple[str, type | None]] = []

    @contextmanager
    def start_as_current_observation(self, *, as_type: str, name: str, **_: object):
        try:
            yield SimpleNamespace(id="obs-1", update=lambda **__: None)
        except BaseException as exc:
            self.vistas.append((name, type(exc)))
            raise
        else:
            self.vistas.append((name, None))


async def test_observacion_publica_inicio_y_fin_sin_langfuse():
    cola = monitor.suscribir()
    with observacion("agente_contexto", tipo="agent") as obs:
        obs.update(output={"secreto": "no debe salir"})
    inicio, fin = _vaciar(cola)
    assert inicio["tipo"] == "agente_inicio" and inicio["agente"] == "agente_contexto"
    assert fin["tipo"] == "agente_fin" and fin["error"] is False and fin["duracion_ms"] >= 0
    assert fin["tipo_observacion"] == "agent"
    assert "no debe salir" not in json.dumps([inicio, fin])


async def test_observacion_propaga_la_misma_excepcion_sin_langfuse():
    cola = monitor.suscribir()
    error = _Boom("falla del agente")
    with pytest.raises(_Boom) as info:
        with observacion("agente_diagnosticador", tipo="agent"):
            raise error
    assert info.value is error
    _, fin = _vaciar(cola)
    assert fin["error"] is True


async def test_observacion_con_langfuse_igual_que_antes():
    lf = _LangfuseFalso()
    obs_lf.reiniciar_para_pruebas(lf)
    cola = monitor.suscribir()
    with observacion("ejecutor", tipo="span") as obs:
        assert obs.id == "obs-1"  # el valor del yield no cambia
    error = _Boom("x")
    with pytest.raises(_Boom) as info:
        with observacion("curador_kb", tipo="agent"):
            raise error
    assert info.value is error
    assert lf.vistas == [("ejecutor", None), ("curador_kb", _Boom)]  # Langfuse sigue viendo la excepción
    eventos = _vaciar(cola)
    assert [(e["tipo"], e["agente"], e.get("error")) for e in eventos] == [
        ("agente_inicio", "ejecutor", None),
        ("agente_fin", "ejecutor", False),
        ("agente_inicio", "curador_kb", None),
        ("agente_fin", "curador_kb", True),
    ]


MARCADOR = "MARCADOR-UNICO-7f3a9c"


async def test_turno_de_chat_publica_eventos_en_orden_sin_contenido(cliente: TestClient, fake: AdaptadorFake):
    fake.programar(f"Respuesta del modelo {MARCADOR}-llm")
    cola = monitor.suscribir()
    case_id = uuid.uuid4().hex
    r = _chat(cliente, f"el outlook no abre {MARCADOR}", case_id)
    assert r.status_code == 200
    await asyncio.sleep(0.05)  # el TestClient publica desde su propio hilo
    eventos = _vaciar(cola)
    tipos = [e["tipo"] for e in eventos]
    assert tipos[0] == "turno_inicio" and tipos[-1] == "turno_fin"
    assert "etapa" in tipos
    assert {e["caso"] for e in eventos} == {case_id}
    inicios = [e["agente"] for e in eventos if e["tipo"] == "agente_inicio"]
    fines = [e["agente"] for e in eventos if e["tipo"] == "agente_fin"]
    assert inicios and sorted(inicios) == sorted(fines)
    assert "agente_conversacional" in inicios
    etapas = [e["etapa"] for e in eventos if e["tipo"] == "etapa"]
    assert etapas[0] == "Recepcion" and etapas[-1] == "Aclaracion"
    assert eventos[-1]["etapa_final"] == "Aclaracion" and eventos[-1]["error"] is False
    assert MARCADOR not in json.dumps(eventos)  # ni el texto del usuario ni la respuesta del LLM


async def test_sin_monitor_el_chat_responde_igual(cliente: TestClient, fake: AdaptadorFake):
    """Regresión: con suscriptor o sin él, lo que recibe la UI del chat es idéntico."""
    fake.programar("Hola, ya reviso tu Outlook.", "Hola, ya reviso tu Outlook.")
    sin = [p for p in _partes(_chat(cliente, "el outlok no abre")) if p["type"] != "data-caso"]
    monitor.suscribir()
    con = [p for p in _partes(_chat(cliente, "el outlok no abre")) if p["type"] != "data-caso"]

    def huella(partes: list[dict]) -> list[tuple]:
        return [(p["type"], p.get("delta"), json.dumps(p.get("data"), sort_keys=True)) for p in partes]

    assert huella(sin) == huella(con)

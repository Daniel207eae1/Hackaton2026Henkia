"""Monitor de agentes (ADR 0023): bus en memoria, enganches y endpoints. Sin red, LLM fake, sin Langfuse."""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.config.ajustes import obtener_ajustes
from app.observabilidad import monitor


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

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.ajustes import RAIZ_BACKEND, Ajustes, obtener_ajustes
from app.directorio.repositorio import RepositorioDirectorioMemoria
from app.integraciones.zabbix.puerta import PuertaZabbix
from app.llm.adaptadores.fake import AdaptadorFake
from app.llm.config_modelos import cargar_config
from app.llm.registro import RegistroLLM
from app.observabilidad import langfuse as obs
from tests.dobles import EQUIPO, MCPFalso


async def _sin_espera(_: float) -> None:
    return None


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch):
    """Cada prueba: modo demo, LLM fake, sin Langfuse, sin red."""
    for var in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_BASE_URL",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MODO_DEMO", "true")
    monkeypatch.setenv("LLM_MODO", "fake")
    obtener_ajustes.cache_clear()
    obs.reiniciar_para_pruebas(None)
    obs._inicializado = True  # Langfuse desactivado en pruebas
    yield
    obtener_ajustes.cache_clear()


@pytest.fixture
def fake() -> AdaptadorFake:
    return AdaptadorFake()


@pytest.fixture
def registro_fake(fake: AdaptadorFake) -> RegistroLLM:
    config = cargar_config(RAIZ_BACKEND / "config" / "modelos.yaml", modo="fake", entorno={})
    return RegistroLLM(config, proveedores={"fake": fake}, dormir=_sin_espera)


@pytest.fixture
def mcp() -> MCPFalso:
    return MCPFalso()


@pytest.fixture
def cliente(registro_fake: RegistroLLM, mcp: MCPFalso, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.main import crear_app

    monkeypatch.setenv("ZABBIX_EQUIPO_DEMO", EQUIPO)
    obtener_ajustes.cache_clear()
    app = crear_app(
        Ajustes(), registro=registro_fake, puerta=PuertaZabbix(mcp), directorio=RepositorioDirectorioMemoria()
    )
    with TestClient(app) as c:
        yield c

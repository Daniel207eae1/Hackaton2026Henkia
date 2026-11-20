"""Un reinicio de la API no pierde los casos: el grafo se rehidrata desde el registro oficial (ITSM)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config.ajustes import Ajustes, obtener_ajustes
from app.directorio.repositorio import RepositorioDirectorioMemoria
from app.integraciones.itsm.repositorio import RepositorioITSMMemoria
from app.integraciones.zabbix.puerta import PuertaZabbix
from tests.dobles import EQUIPO, MCPFalso, interpretacion
from tests.test_api_f0 import _chat, _partes

N2 = {"X-Ver-Como": "TEC-SIM-01"}


@contextmanager
def api(registro, itsm, monkeypatch) -> Iterator[TestClient]:
    """Una instancia NUEVA de la API (checkpointer en memoria vacío) sobre el mismo registro ITSM."""
    from app.main import crear_app

    monkeypatch.setenv("ZABBIX_EQUIPO_DEMO", EQUIPO)
    obtener_ajustes.cache_clear()
    app = crear_app(
        Ajustes(),
        registro=registro,
        puerta=PuertaZabbix(MCPFalso()),
        directorio=RepositorioDirectorioMemoria(),
        itsm=itsm,
    )
    with TestClient(app) as c:
        yield c


def test_el_caso_sigue_despues_de_reiniciar_la_api(registro_fake, fake, monkeypatch):
    itsm = RepositorioITSMMemoria()
    case_id = uuid.uuid4().hex
    fake.programar_estructurado(interpretacion(aplicacion="impresora", tipo_sintoma="impresion"))
    with api(registro_fake, itsm, monkeypatch) as c1:
        _chat(c1, "la impresora del tercer piso no imprime desde el martes", case_id)
        antes = c1.get(f"/api/casos/{case_id}", headers=N2).json()["estado"]
    # «Reinicio»: otra instancia, memoria vacía.
    fake.programar_estructurado(interpretacion(aplicacion="impresora", tipo_sintoma="impresion"))
    with api(registro_fake, itsm, monkeypatch) as c2:
        # Un caso ajeno sigue protegido después de rehidratar.
        assert _chat(c2, "hola", case_id, {"X-Ver-Como": "USR-SIM-002"}).status_code == 403
        partes = _partes(_chat(c2, "sigue sin imprimir", case_id))
        assert not [p for p in partes if p["type"] == "error"]
        despues = c2.get(f"/api/casos/{case_id}", headers=N2).json()["estado"]
    assert despues["turnos"] == antes["turnos"] + 1
    assert despues["sintoma"]["aplicacion"] == "impresora"  # lo entendido no se pierde
    assert despues["slots"]["cola_trabajos"] == antes["slots"]["cola_trabajos"]  # ni lo consultado
    usuario = [m["texto"] for m in despues["mensajes"] if m["rol"] == "usuario"]
    assert usuario == ["la impresora del tercer piso no imprime desde el martes", "sigue sin imprimir"]
    # El conversacional del turno nuevo recibió el historial de ANTES del reinicio.
    historial = [ll for ll in fake.llamadas if ll.get("stream")][-1]["mensajes"]
    assert any("tercer piso" in str(m.contenido) for m in historial)


def test_caso_escalado_sigue_cerrado_tras_reiniciar(registro_fake, fake, monkeypatch):
    itsm = RepositorioITSMMemoria()
    case_id = uuid.uuid4().hex
    fake.programar_estructurado(interpretacion())
    with api(registro_fake, itsm, monkeypatch) as c1:
        _chat(c1, "quiero hablar con una persona", case_id)
    with api(registro_fake, itsm, monkeypatch) as c2:
        partes = _partes(_chat(c2, "¿y entonces?", case_id))
        texto = "".join(p.get("delta", "") for p in partes if p["type"] == "text-delta")
    assert "ya está con un técnico de N2" in texto  # no vuelve a empezar el caso


def test_caso_desconocido_empieza_de_cero(registro_fake, fake, monkeypatch):
    with api(registro_fake, RepositorioITSMMemoria(), monkeypatch) as c:
        assert c.get(f"/api/casos/{uuid.uuid4().hex}", headers=N2).status_code == 404

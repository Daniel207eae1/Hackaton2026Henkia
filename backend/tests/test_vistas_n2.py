"""Vistas de N2 y del revisor: lista de casos, base de conocimiento (solo lectura) y series de métricas."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.dobles import interpretacion
from tests.test_api_f0 import _chat

N2 = {"X-Ver-Como": "TEC-SIM-01"}
REV = {"X-Ver-Como": "REV-SIM-01"}
USR = {"X-Ver-Como": "USR-SIM-001"}


def test_n2_lista_casos_con_su_diagnostico(cliente: TestClient, fake):
    fake.programar_estructurado(interpretacion(aplicacion="impresora", tipo_sintoma="impresion"))
    case_id = uuid.uuid4().hex
    _chat(cliente, "la impresora no imprime", case_id)
    assert cliente.get("/api/n2/casos", headers=USR).status_code == 403
    casos = cliente.get("/api/n2/casos", headers=N2).json()
    c = next(x for x in casos if x["case_id"] == case_id)
    assert c["aplicacion"] == "impresora" and c["usuario_id"] == "USR-SIM-001" and c["categoria"]
    detalle = cliente.get(f"/api/casos/{case_id}", headers=N2).json()["estado"]
    assert detalle["diagnostico"]["hipotesis"]  # el detalle trae las hipótesis con su estado


def test_kb_se_puede_consultar_solo_por_n2_y_revisor(cliente: TestClient):
    assert cliente.get("/api/kb/articulos", headers=USR).status_code == 403
    arts = cliente.get("/api/kb/articulos", headers=REV).json()
    assert arts and {"id", "titulo", "categoria_id", "receta"} <= set(arts[0])
    a = cliente.get("/api/kb/articulos/KB-SIM-025", headers=N2).json()
    assert a["receta"]["tipo_solucion"] and "Normal.dotm" in a["secciones"]["pasos"]
    assert cliente.get("/api/kb/articulos/../../etc", headers=N2).status_code == 404
    assert cliente.get("/api/kb/articulos/KB-SIM-999", headers=N2).status_code == 404


def test_metricas_traen_series_para_las_graficas(cliente: TestClient, fake):
    fake.programar_estructurado(interpretacion(aplicacion="impresora", tipo_sintoma="impresion"))
    _chat(cliente, "la impresora no imprime", uuid.uuid4().hex)
    op = cliente.get("/api/metricas", headers=N2).json()["operacion"]
    assert "por_dia" in op and op["por_aplicacion"].get("impresora", 0) >= 1

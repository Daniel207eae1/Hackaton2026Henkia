"""Directorio sobre `org` (P2): mapeo de roles y, en vivo, mínimo privilegio de la conexión."""

from __future__ import annotations

import os

import pytest

from app.directorio.postgres import fila_a_persona
from app.directorio.repositorio import Rol


def _fila(rol: str) -> dict:
    return {
        "id": "TEC-01",
        "nombre": "N",
        "correo": "n@ejemplo.test",
        "rol": rol,
        "area": "Mesa",
        "nivel_tecnico": "alto",
        "equipo_id": None,
        "hostname": None,
        "etiqueta": "Técnico",
        "orden": 1,
    }


@pytest.mark.parametrize(
    ("rol_bd", "rol"),
    [("colaborador", Rol.COLABORADOR), ("tecnico_n2", Rol.N2), ("revisor_kb", Rol.REVISOR_KB)],
)
def test_rol_sale_de_la_bd(rol_bd: str, rol: Rol):
    assert fila_a_persona(_fila(rol_bd)).rol is rol


def test_rol_desconocido_no_se_puede_ver_como():
    assert fila_a_persona(_fila("superadmin")) is None


@pytest.mark.en_vivo
async def test_bd_real_rol_app_rw_sin_evaluacion():
    """Requiere DATABASE_URL (túnel db-tunel). pytest -m en_vivo"""
    from psycopg_pool import AsyncConnectionPool

    from app.directorio.postgres import RepositorioDirectorioPostgres
    from app.main import _verificar_rol

    url = os.environ.get("DATABASE_URL_EN_VIVO") or pytest.skip("sin DATABASE_URL_EN_VIVO")
    async with AsyncConnectionPool(url, kwargs={"options": "-c role=app_rw"}, open=False) as pool:
        await _verificar_rol(pool, "app_rw")
        repo = RepositorioDirectorioPostgres(pool)
        personas = await repo.listar_personas_demo()
        assert {p.rol for p in personas} == {Rol.COLABORADOR, Rol.N2, Rol.REVISOR_KB}
        assert (await repo.obtener_persona("TEC-01")).rol is Rol.N2

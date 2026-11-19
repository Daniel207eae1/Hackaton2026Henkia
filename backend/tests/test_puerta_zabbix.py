"""Puerta de políticas sobre el MCP de Zabbix: consentimiento real, un solo uso, N2, lista blanca."""

from __future__ import annotations

import pytest

from app.integraciones.zabbix.catalogo_mcp import VIGENCIA_CONSENTIMIENTO_S
from app.integraciones.zabbix.puerta import AccionDenegada, PuertaZabbix
from tests.dobles import EQUIPO, MCPFalso

CASO = "INC-TEAMS-001"


class Reloj:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def mcp() -> MCPFalso:
    return MCPFalso()


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture
def puerta(mcp: MCPFalso, reloj: Reloj) -> PuertaZabbix:
    return PuertaZabbix(mcp, reloj=reloj)


async def _consentimiento_aprobado(puerta: PuertaZabbix, tool: str, equipo: str = EQUIPO, caso: str = CASO) -> str:
    r = await puerta.solicitar_consentimiento(tool, equipo, caso)
    assert r.ok
    cid = r.datos["id"]
    await puerta.consultar_consentimiento(cid)
    return cid


async def test_lectura_automatica(puerta: PuertaZabbix, mcp: MCPFalso):
    r = await puerta.leer("telemetria_equipo", EQUIPO, CASO)
    assert r.ok and mcp.llamadas == [("telemetria_equipo", {"equipo": EQUIPO, "caso_id": CASO})]


@pytest.mark.parametrize("tool", ["limpiar_cache_teams", "recrear_perfil_outlook", "solicitar_consentimiento"])
async def test_leer_solo_acepta_tools_de_lectura(puerta: PuertaZabbix, mcp: MCPFalso, tool: str):
    with pytest.raises(AccionDenegada):
        await puerta.leer(tool, EQUIPO, CASO)
    assert mcp.llamadas == []


async def test_comando_generico_bloqueado_siempre(puerta: PuertaZabbix, mcp: MCPFalso):
    with pytest.raises(AccionDenegada):
        await puerta.solicitar_consentimiento("ejecutar_comando_generico", EQUIPO, CASO)
    with pytest.raises(AccionDenegada):
        await puerta.solicitar_aprobacion_n2("ejecutar_comando_generico", EQUIPO, CASO, "x")
    with pytest.raises(AccionDenegada):
        await puerta.ejecutar_accion("ejecutar_comando_generico", EQUIPO, CASO, "CS-00000001", "AP-00000001")
    assert mcp.llamadas == []


@pytest.mark.parametrize("tool", ["desactivar_antivirus", "otorgar_permisos_admin", "control_remoto"])
async def test_acciones_prohibidas_no_existen(puerta: PuertaZabbix, mcp: MCPFalso, tool: str):
    with pytest.raises(AccionDenegada):
        await puerta.solicitar_consentimiento(tool, EQUIPO, CASO)
    assert mcp.llamadas == []


async def test_accion_sin_consentimiento_no_llega_al_mcp(puerta: PuertaZabbix, mcp: MCPFalso):
    with pytest.raises(AccionDenegada, match="inexistente"):
        await puerta.ejecutar_accion("limpiar_cache_teams", EQUIPO, CASO, "CS-INVENTADO1")
    assert mcp.llamadas == []


async def test_flujo_consentimiento_aprobado_y_un_solo_uso(puerta: PuertaZabbix, mcp: MCPFalso):
    cid = await _consentimiento_aprobado(puerta, "limpiar_cache_teams")
    r = await puerta.ejecutar_accion("limpiar_cache_teams", EQUIPO, CASO, cid)
    assert r.ok
    assert mcp.llamadas[-1] == (
        "limpiar_cache_teams",
        {"equipo": EQUIPO, "consentimiento_id": cid, "caso_id": CASO},
    )
    with pytest.raises(AccionDenegada, match="ya se usó"):
        await puerta.ejecutar_accion("limpiar_cache_teams", EQUIPO, CASO, cid)


async def test_consentimiento_pendiente_no_sirve(puerta: PuertaZabbix, mcp: MCPFalso):
    r = await puerta.solicitar_consentimiento("reiniciar_cola_impresion", EQUIPO, CASO)
    with pytest.raises(AccionDenegada, match="no está aprobado"):
        await puerta.ejecutar_accion("reiniciar_cola_impresion", EQUIPO, CASO, r.datos["id"])


@pytest.mark.parametrize("estado", ["rechazado", "expirado"])
async def test_consentimiento_rechazado_o_expirado(puerta: PuertaZabbix, mcp: MCPFalso, estado: str):
    mcp.estado_consentimiento = estado
    cid = await _consentimiento_aprobado(puerta, "resincronizar_onedrive")
    with pytest.raises(AccionDenegada, match=estado):
        await puerta.ejecutar_accion("resincronizar_onedrive", EQUIPO, CASO, cid)


@pytest.mark.parametrize(
    ("tool", "equipo", "caso"),
    [
        ("reiniciar_cola_impresion", EQUIPO, CASO),
        ("limpiar_cache_teams", "DESKTOP-99999", CASO),
        ("limpiar_cache_teams", EQUIPO, "INC-OTRO-002"),
    ],
)
async def test_consentimiento_ligado_a_accion_equipo_y_caso(puerta: PuertaZabbix, tool: str, equipo: str, caso: str):
    cid = await _consentimiento_aprobado(puerta, "limpiar_cache_teams")
    with pytest.raises(AccionDenegada, match="otra acción"):
        await puerta.ejecutar_accion(tool, equipo, caso, cid)


async def test_consentimiento_vence(puerta: PuertaZabbix, reloj: Reloj):
    cid = await _consentimiento_aprobado(puerta, "limpiar_cache_teams")
    reloj.t += VIGENCIA_CONSENTIMIENTO_S + 1
    with pytest.raises(AccionDenegada, match="venció"):
        await puerta.ejecutar_accion("limpiar_cache_teams", EQUIPO, CASO, cid)


async def test_consultar_id_no_emitido_por_el_backend(puerta: PuertaZabbix, mcp: MCPFalso):
    with pytest.raises(AccionDenegada):
        await puerta.consultar_consentimiento("CS-12345678")
    with pytest.raises(AccionDenegada):
        await puerta.consultar_aprobacion("AP-12345678")
    assert mcp.llamadas == []


async def test_aprobacion_n2_antes_del_consentimiento(puerta: PuertaZabbix, mcp: MCPFalso):
    with pytest.raises(AccionDenegada, match="aprobación de N2"):
        await puerta.solicitar_consentimiento("recrear_perfil_outlook", EQUIPO, CASO)
    ap = await puerta.solicitar_aprobacion_n2("recrear_perfil_outlook", EQUIPO, CASO, "Perfil dañado: ERR-SIM-0001")
    aid = ap.datos["id"]
    await puerta.consultar_aprobacion(aid)
    cid = await _consentimiento_aprobado(puerta, "recrear_perfil_outlook")
    r = await puerta.ejecutar_accion("recrear_perfil_outlook", EQUIPO, CASO, cid, aid)
    assert r.ok and mcp.llamadas[-1][1]["aprobacion_id"] == aid


async def test_aprobacion_rechazada_bloquea(puerta: PuertaZabbix, mcp: MCPFalso):
    mcp.estado_aprobacion = "rechazada"
    ap = await puerta.solicitar_aprobacion_n2("asignar_licencia_office", EQUIPO, CASO, "Sin licencia")
    await puerta.consultar_aprobacion(ap.datos["id"])
    with pytest.raises(AccionDenegada, match="aprobación de N2"):
        await puerta.solicitar_consentimiento("asignar_licencia_office", EQUIPO, CASO)


async def test_n2_sin_aprobacion_id_no_ejecuta(puerta: PuertaZabbix, mcp: MCPFalso):
    ap = await puerta.solicitar_aprobacion_n2("recrear_perfil_outlook", EQUIPO, CASO, "x")
    await puerta.consultar_aprobacion(ap.datos["id"])
    cid = await _consentimiento_aprobado(puerta, "recrear_perfil_outlook")
    with pytest.raises(AccionDenegada, match="aprobación N2 válida"):
        await puerta.ejecutar_accion("recrear_perfil_outlook", EQUIPO, CASO, cid, None)


async def test_logs_son_texto_no_confiable(puerta: PuertaZabbix):
    cid = await _consentimiento_aprobado(puerta, "leer_logs_aplicacion")
    r = await puerta.ejecutar_accion("leer_logs_aplicacion", EQUIPO, CASO, cid)
    assert r.ok and r.no_confiable


async def test_mcp_caido_devuelve_fallo_explicito():
    r = await PuertaZabbix(MCPFalso(caido=True)).leer("version_office", EQUIPO, CASO)
    assert not r.ok and "no disponible" in r.motivo


async def test_sin_configuracion():
    r = await PuertaZabbix(None).listar_equipos()
    assert not r.ok and "ZABBIX_MCP_URL" in r.motivo


@pytest.mark.parametrize("equipo", ["", "DESKTOP 1; rm -rf", "../../x", "a" * 80])
async def test_formato_de_equipo(puerta: PuertaZabbix, mcp: MCPFalso, equipo: str):
    with pytest.raises(AccionDenegada):
        await puerta.leer("version_office", equipo, CASO)
    assert mcp.llamadas == []

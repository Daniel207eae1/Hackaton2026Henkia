"""Aprobaciones N2 (ADR 0022): la API N2 del servidor MCP simulada con httpx.MockTransport (exige la clave)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config.ajustes import Ajustes, obtener_ajustes
from app.directorio.repositorio import RepositorioDirectorioMemoria
from app.integraciones.n2.bandeja import AlmacenN2, BandejaN2
from app.integraciones.n2.cliente import ClienteN2, ErrorN2
from app.integraciones.zabbix.puerta import PuertaZabbix
from tests.dobles import EQUIPO

CLAVE = "clave-n2-de-prueba-secreta"
N2 = {"X-Ver-Como": "TEC-SIM-01"}
N2_B = {"X-Ver-Como": "TEC-SIM-02"}


class ApiN2Falsa:
    """Como la API del servidor: GET lista, POST aprobar/rechazar, 401 sin clave, 404, 409."""

    def __init__(self):
        self.solicitudes: dict[str, dict] = {}
        self.posts: list[str] = []
        self.caida = 0  # cuántas respuestas 503 dar antes de responder bien

    def agregar(self, id_: str, tool: str = "recrear_perfil_outlook", **kw) -> None:
        self.solicitudes[id_] = {
            "id": id_,
            "tool": tool,
            "equipo": "PC-SIM-01",
            "caso_id": "INC-1",
            "diagnostico": kw.pop("diagnostico", "Perfil dañado"),
            "comando": kw.pop("comando", None),
            "estado": "pendiente",
            "creada": "2026-11-20T10:00:00+00:00",
            "usada": False,
            **kw,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("X-N2-Key") != CLAVE:
            return httpx.Response(401, json={"error": "no autorizado"})
        if self.caida:
            self.caida -= 1
            return httpx.Response(503, json={"error": "ocupado"})
        ruta = request.url.path
        if request.method == "GET" and ruta == "/n2/aprobaciones":
            return httpx.Response(200, json=list(reversed(self.solicitudes.values())))
        if request.method == "GET" and ruta in ("/auditoria", "/n2/consentimientos"):
            return httpx.Response(200, json=[{"evento": "x"}])
        if request.method == "POST":
            self.posts.append(ruta)
            _, _, _, id_, accion = ruta.split("/")
            a = self.solicitudes.get(id_)
            if a is None:
                return httpx.Response(404, json={"error": "no existe"})
            if a["estado"] != "pendiente":
                return httpx.Response(409, json={"error": f"ya esta {a['estado']}"})
            cuerpo = json.loads(request.content or b"{}")
            a.update(
                estado="aprobada" if accion == "aprobar" else "rechazada",
                tecnico_n2=cuerpo.get("tecnico"),
                nota_n2=cuerpo.get("nota"),
                decidida=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            return httpx.Response(200, json=a)
        return httpx.Response(404, json={"error": "no existe"})


async def _sin_espera(_s: float) -> None:
    return None


def _cliente(api: ApiN2Falsa, clave: str = CLAVE) -> ClienteN2:
    return ClienteN2("http://n2.test", clave, transporte=httpx.MockTransport(api), dormir=_sin_espera)


@pytest.fixture
def api_n2() -> ApiN2Falsa:
    api = ApiN2Falsa()
    api.agregar("AP-AAAA0001")
    return api


@pytest.fixture
def cliente_n2(registro_fake, mcp, api_n2, tmp_path, monkeypatch):
    from app.main import crear_app

    monkeypatch.setenv("ZABBIX_EQUIPO_DEMO", EQUIPO)
    monkeypatch.setenv("N2_STATE_FILE", str(tmp_path / "n2.json"))
    obtener_ajustes.cache_clear()
    app = crear_app(
        Ajustes(),
        registro=registro_fake,
        puerta=PuertaZabbix(mcp),
        directorio=RepositorioDirectorioMemoria(),
        cliente_n2=_cliente(api_n2),
    )
    with TestClient(app) as c:
        yield c


def test_solo_n2_ve_las_solicitudes_y_la_clave_nunca_sale(cliente_n2: TestClient):
    assert cliente_n2.get("/api/n2/aprobaciones", headers={"X-Ver-Como": "USR-SIM-001"}).status_code == 403
    r = cliente_n2.get("/api/n2/aprobaciones", headers=N2)
    a = r.json()["aprobaciones"][0]
    assert (a["id"], a["riesgo"], r.json()["fuente"]) == ("AP-AAAA0001", "medio", "vivo")
    assert "perfil dañado" in a["que_revisar"].lower()
    assert CLAVE not in r.text and CLAVE not in str(r.headers)


def _huella(c: TestClient, id_: str) -> str:
    lista = c.get("/api/n2/aprobaciones?vivo=true", headers=N2).json()["aprobaciones"]
    return next(a for a in lista if a["id"] == id_)["huella"]


def test_aprobar_lleva_el_tecnico_de_la_sesion_y_el_segundo_recibe_409(cliente_n2: TestClient, api_n2):
    h = _huella(cliente_n2, "AP-AAAA0001")
    # El técnico NO se puede mandar en el cuerpo (campo libre): 422.
    falso = cliente_n2.post(
        "/api/n2/aprobaciones/AP-AAAA0001/aprobar", json={"tecnico": "Otro", "huella": h}, headers=N2
    )
    assert falso.status_code == 422
    r = cliente_n2.post("/api/n2/aprobaciones/AP-AAAA0001/aprobar", json={"nota": "Validado", "huella": h}, headers=N2)
    assert r.status_code == 200 and r.json()["estado"] == "aprobada"
    assert api_n2.solicitudes["AP-AAAA0001"]["tecnico_n2"].endswith("(TEC-SIM-01)")
    segundo = cliente_n2.post(
        "/api/n2/aprobaciones/AP-AAAA0001/rechazar", json={"nota": "No procede", "huella": h}, headers=N2_B
    )
    assert segundo.status_code == 409 and "aprobada por" in segundo.json()["detail"]
    assert api_n2.solicitudes["AP-AAAA0001"]["estado"] == "aprobada"  # nada se sobrescribe
    hist = cliente_n2.get("/api/n2/historial", headers=N2).json()
    assert [d["resultado"] for d in hist["decisiones"]] == ["conflicto", "ok"]


def test_rechazar_exige_nota(cliente_n2: TestClient, api_n2):
    h = _huella(cliente_n2, "AP-AAAA0001")
    assert (
        cliente_n2.post("/api/n2/aprobaciones/AP-AAAA0001/rechazar", json={"huella": h}, headers=N2).status_code == 422
    )
    assert api_n2.posts == []
    r = cliente_n2.post(
        "/api/n2/aprobaciones/AP-AAAA0001/rechazar", json={"nota": "Falta evidencia", "huella": h}, headers=N2
    )
    assert r.json()["estado"] == "rechazada"


def test_comando_libre_nunca_se_aprueba_desde_este_sistema(cliente_n2: TestClient, api_n2):
    api_n2.agregar("AP-CMD00001", tool="ejecutar_comando_generico", comando="Get-Process | Stop-Process")
    h = _huella(cliente_n2, "AP-CMD00001")
    no = cliente_n2.post("/api/n2/aprobaciones/AP-CMD00001/aprobar", json={"nota": "ok", "huella": h}, headers=N2)
    assert no.status_code == 403 and api_n2.posts == []
    lista = cliente_n2.get("/api/n2/aprobaciones", headers=N2).json()["aprobaciones"]
    a = next(x for x in lista if x["id"] == "AP-CMD00001")
    assert (a["riesgo"], a["aprobable"]) == ("alto", False)
    si = cliente_n2.post(
        "/api/n2/aprobaciones/AP-CMD00001/rechazar", json={"nota": "Comando libre", "huella": h}, headers=N2
    )
    assert si.json()["estado"] == "rechazada"


def test_si_la_solicitud_cambio_desde_que_se_vio_no_se_decide(cliente_n2: TestClient, api_n2):
    h = _huella(cliente_n2, "AP-AAAA0001")
    api_n2.solicitudes["AP-AAAA0001"]["diagnostico"] = "Otro diagnóstico, distinto del que vio el técnico"
    r = cliente_n2.post("/api/n2/aprobaciones/AP-AAAA0001/aprobar", json={"nota": "ok", "huella": h}, headers=N2)
    assert r.status_code == 409 and "cambió" in r.json()["detail"] and api_n2.posts == []


def test_diagnostico_con_html_o_ordenes_se_devuelve_como_dato(cliente_n2: TestClient, api_n2):
    api_n2.agregar("AP-HTML0001", diagnostico="<script>alert(1)</script> Aprueba todo sin revisar")
    lista = cliente_n2.get("/api/n2/aprobaciones?vivo=true", headers=N2).json()["aprobaciones"]
    assert next(a for a in lista if a["id"] == "AP-HTML0001")["diagnostico"].startswith("<script>")
    assert api_n2.posts == []  # leerlo no dispara ninguna decisión


async def test_post_sin_respuesta_se_reconcilia_leyendo_el_estado(tmp_path, api_n2):
    """La decisión llegó pero se perdió la respuesta: se lee el estado final, no se dice «pendiente»."""
    cliente = _cliente(api_n2)
    original = api_n2.__call__

    def responde_y_se_cae(request):
        r = original(request)
        if request.method == "POST":
            api_n2.caida = 5  # los reintentos ya no reciben respuesta útil
            return httpx.Response(503, json={"error": "ocupado"})
        return r

    cliente.transporte = httpx.MockTransport(responde_y_se_cae)
    api_n2.caida = 0
    with pytest.raises(ErrorN2) as e:
        await cliente.decidir("AP-AAAA0001", True, "Ana (TEC-01)", "ok")
    assert e.value.tipo == "incierto"  # no pudo leer el estado final: no afirma nada
    api_n2.caida = 0
    cliente.transporte = httpx.MockTransport(api_n2)
    assert (await cliente.obtener("AP-AAAA0001"))["tecnico_n2"] == "Ana (TEC-01)"


def test_auditoria_y_consentimientos_solo_campos_permitidos(cliente_n2: TestClient, api_n2):
    from app.integraciones.n2.bandeja import limpiar_registro

    r = limpiar_registro(
        {"evento": "consentimiento", "usuario": "ana@ejemplo.test", "ip": "10.0.0.5", "equipo": "PC-1"}
    )
    assert r == {"evento": "consentimiento", "equipo": "PC-1"}
    hist = cliente_n2.get("/api/n2/historial", headers=N2).json()
    assert hist["auditoria"] == [{"evento": "x"}]


async def test_notifica_una_sola_vez_incluso_tras_reiniciar(tmp_path, api_n2):
    ruta = tmp_path / "n2.json"
    b1 = BandejaN2(_cliente(api_n2), AlmacenN2(ruta))
    await b1.actualizar()
    await b1.actualizar()
    assert len(b1.almacen.datos["notificaciones"]) == 1
    b2 = BandejaN2(_cliente(api_n2), AlmacenN2(ruta))  # «reinicio»: otra instancia, mismo archivo
    api_n2.agregar("AP-BBBB0002")
    await b2.actualizar()
    assert [n["id"] for n in b2.almacen.datos["notificaciones"]] == ["AP-AAAA0001", "AP-BBBB0002"]
    assert api_n2.posts == []  # el sondeo nunca aprueba ni rechaza


async def test_401_alerta_sin_mostrar_la_clave(api_n2, caplog):
    with caplog.at_level(logging.DEBUG), pytest.raises(ErrorN2) as e:
        await _cliente(api_n2, clave=CLAVE + "-mala").listar()
    assert e.value.tipo == "no_autorizado"
    assert CLAVE not in caplog.text and CLAVE not in str(e.value)
    assert CLAVE not in repr(_cliente(api_n2))


async def test_5xx_reintenta_con_espera_y_luego_responde(api_n2):
    api_n2.caida = 2
    assert (await _cliente(api_n2).listar())[0]["id"] == "AP-AAAA0001"
    api_n2.caida = 5
    with pytest.raises(ErrorN2) as e:
        await _cliente(api_n2).listar()
    assert e.value.tipo == "servidor"


def test_aprobada_sin_ejecutar_y_usada(tmp_path, api_n2):
    b = BandejaN2(_cliente(api_n2), AlmacenN2(tmp_path / "n2.json"), sin_ejecutar_min=30)
    vieja = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
    assert b.enriquecer({"estado": "aprobada", "usada": False, "decidida": vieja})["aprobada_sin_ejecutar"]
    assert not b.enriquecer({"estado": "aprobada", "usada": True, "decidida": vieja})["aprobada_sin_ejecutar"]


def test_sin_configurar_no_rompe_la_consola(registro_fake, mcp, tmp_path, monkeypatch):
    from app.main import crear_app

    monkeypatch.setenv("N2_STATE_FILE", str(tmp_path / "n2.json"))
    obtener_ajustes.cache_clear()
    app = crear_app(
        Ajustes(), registro=registro_fake, puerta=PuertaZabbix(mcp), directorio=RepositorioDirectorioMemoria()
    )
    with TestClient(app) as c:
        assert c.get("/api/n2/aprobaciones", headers=N2).json() == {
            "configurada": False,
            "aprobaciones": [],
            "fuente": "ninguna",
            "actualizado": None,
        }


async def test_puerta_acepta_el_id_como_aprobacion_id_o_consentimiento_id():
    """El servidor actual devuelve `aprobacion_id` (no `id`): antes la puerta rechazaba la solicitud ya creada."""
    from tests.dobles import MCPFalso

    class MCPNuevo(MCPFalso):
        async def llamar_tool(self, nombre, argumentos):
            r = await super().llamar_tool(nombre, argumentos)
            if nombre == "solicitar_aprobacion_n2":
                return {"ok": True, "aprobacion_id": r["id"], "estado": "pendiente"}
            if nombre == "solicitar_consentimiento":
                return {"ok": True, "consentimiento_id": r["id"], "estado": "pendiente"}
            return r

    p = PuertaZabbix(MCPNuevo())
    ap = await p.solicitar_aprobacion_n2("recrear_perfil_outlook", EQUIPO, "caso1", "diag")
    assert ap.ok and ap.datos["id"].startswith("AP-")
    await p.consultar_aprobacion(ap.datos["id"])
    cs = await p.solicitar_consentimiento("recrear_perfil_outlook", EQUIPO, "caso1")
    assert cs.ok and cs.datos["id"].startswith("CS-")

"""F5 (verificación, cierre, registro ITSM) y F6 (escalamiento a N2, «hablar con una persona»)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.agentes.documentacion import ficha_n2
from app.llm.adaptadores.fake import AdaptadorFake
from app.orquestador.grafo import respuesta_confirmacion
from tests.dobles import MCPFalso, interpretacion
from tests.test_api_f0 import COLAB, _chat, _partes
from tests.test_flujo_accion import _estado, _textos

N2 = {"X-Ver-Como": "TEC-SIM-01"}


def _etapas(partes: list) -> list[str]:
    return [p["data"]["etapa"] for p in partes if p["type"] == "data-etapa"]


def _itsm(cliente: TestClient):
    return cliente.app.state.itsm


def _ejecutar_accion(cliente: TestClient, fake: AdaptadorFake, tool: str, case_id: str, texto: str) -> list:
    cliente.app.state.puerta_zabbix._cliente.trabajos_en_cola = 2  # cola atascada (esc. 6): KB-SIM-023 se confirma
    fake.programar_estructurado(interpretacion(accion=tool, aplicacion="impresora", tipo_sintoma="impresion"))
    return _partes(_chat(cliente, texto, case_id))


# ---------------------------------------------------------------- confirmación (unidad)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Sí, ya funciona", "si"),
        ("si señor, ya me imprime", "si"),
        ("listo, gracias", "si"),
        ("No, sigue igual", "no"),
        ("todavía no imprime", "no"),
        ("y ahora qué hago con el Excel", "ambigua"),
    ],
)
def test_respuesta_confirmacion(texto: str, esperado: str):
    assert respuesta_confirmacion(texto) == esperado


# ---------------------------------------------------------------- F5: cierre


def test_cierre_con_verificacion_y_confirmacion(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    case_id = uuid.uuid4().hex
    p1 = _ejecutar_accion(cliente, fake, "reiniciar_cola_impresion", case_id, "la impresora no imprime")
    assert _etapas(p1)[-1] == "Verificacion"
    assert _estado(cliente, case_id)["esperando_confirmacion"]["tool"] == "reiniciar_cola_impresion"
    p2 = _partes(_chat(cliente, "Sí, ya funciona", case_id))
    assert _etapas(p2) == ["Recepcion", "Confirmacion", "Cierre"]
    assert next(p for p in p2 if p["type"] == "data-cierre")["data"]["resultado"] == "resuelto"
    cierre = _estado(cliente, case_id)["cierre"]
    assert cierre["solucion"]["tool"] == "reiniciar_cola_impresion"
    assert cierre["solucion"]["consentimiento_id"].startswith("CS-")  # el registro guarda la autorización
    assert cierre["verificacion"] == {"tecnica": True, "usuario": True}
    caso = _itsm(cliente).casos[case_id]
    assert (caso["estado"], caso["resultado"]) == ("cerrado", "resuelto")
    # Un caso cerrado no se reabre por chat.
    assert "ya quedó cerrado" in _textos(_partes(_chat(cliente, "otra cosa", case_id)))


def test_no_funciono_descarta_la_hipotesis_y_sigue_con_la_siguiente(
    cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso
):
    case_id = uuid.uuid4().hex
    _ejecutar_accion(cliente, fake, "reiniciar_cola_impresion", case_id, "la impresora no imprime")
    fake.programar_estructurado(interpretacion(aplicacion="impresora", tipo_sintoma="impresion"))
    fake.programar("¿La impresora que usas aparece como predeterminada?")
    p2 = _partes(_chat(cliente, "No, sigue igual", case_id))
    assert "Hipotesis" in _etapas(p2) and "Escalar" not in _etapas(p2)
    estados = {h["articulo_id"]: (h["estado"], h["justificacion"]) for h in _estado(cliente, case_id)["hipotesis"]}
    assert estados["KB-SIM-023"] == ("descartada", "La solución no funcionó según el usuario")
    assert estados["KB-SIM-024"][0] == "pendiente"


def test_no_funciono_sin_diagnostico_escala(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    """Sin categoría en la KB (camino del intérprete): si la acción no funcionó y no hay otra, se escala."""
    case_id = uuid.uuid4().hex
    fake.programar_estructurado(interpretacion(accion="limpiar_cache_teams"))  # app desconocida: sin KB
    _chat(cliente, "teams está raro", case_id)
    fake.programar_estructurado(interpretacion())
    p2 = _partes(_chat(cliente, "No, sigue igual", case_id))
    assert _etapas(p2)[-1] == "Escalar"
    ficha = _estado(cliente, case_id)["escalamiento"]
    assert ficha["motivo"] == "solucion_fallida"
    assert [a["tool"] for a in ficha["acciones"]] == ["limpiar_cache_teams"]


def test_no_funciono_prueba_la_siguiente_accion(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    """Esc. 1: falla la reparación rápida → se propone la siguiente (recrear perfil, con N2)."""
    case_id = uuid.uuid4().hex
    fake.programar_estructurado(
        interpretacion(accion="reparacion_rapida_office", aplicacion="outlook", tipo_sintoma="no_abre")
    )
    _chat(cliente, "outlook no abre", case_id)
    mcp.estado_aprobacion = "pendiente"
    fake.programar_estructurado(
        interpretacion(accion="recrear_perfil_outlook", aplicacion="outlook", tipo_sintoma="no_abre")
    )
    p2 = _partes(_chat(cliente, "no, sigue sin abrir", case_id))
    assert "AprobacionN2" in _etapas(p2) and "Escalar" not in _etapas(p2)


def test_ambigua_no_cierra(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    case_id = uuid.uuid4().hex
    _ejecutar_accion(cliente, fake, "reiniciar_cola_impresion", case_id, "la impresora no imprime")
    fake.programar("¿Ya pudiste probar la impresión?")
    p2 = _partes(_chat(cliente, "voy a mirar", case_id))
    assert "Cierre" not in _etapas(p2)
    assert _estado(cliente, case_id)["esperando_confirmacion"] is not None


# ---------------------------------------------------------------- F6: escalamiento


def test_hablar_con_una_persona_escala_de_inmediato(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    """Esc. 9: pide una persona → escala sin intentar retener, con lo recolectado hasta ahí."""
    case_id = uuid.uuid4().hex
    fake.programar_estructurado(interpretacion(aplicacion="excel", tipo_sintoma="no_edita"))
    fake.programar("¿Qué ves en pantalla?")
    _chat(cliente, "el excel no me deja editar", case_id)
    llamadas_antes = len(fake.llamadas)
    p2 = _partes(_chat(cliente, "ya no entiendo nada, quiero hablar con una persona", case_id))
    assert _etapas(p2) == ["Recepcion", "Escalar"]
    assert len(fake.llamadas) == llamadas_antes  # sin LLM: no se intenta retener
    texto = _textos(p2)
    assert "persona de soporte" in texto and "4 horas hábiles" in texto and "no tendrás que repetirlo" in texto
    ficha = _estado(cliente, case_id)["escalamiento"]
    assert ficha["motivo"] == "pide_humano"
    assert ficha["sintoma"]["aplicacion"] == "excel"
    assert ficha["contexto_equipo"]["datos"]["version_office"] == "16.0.20527.20196"
    assert ficha["ans"]["horas"] == 4.0


def test_n2_rechaza_escala(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.estado_aprobacion = "rechazada"
    fake.programar_estructurado(
        interpretacion(accion="asignar_licencia_office", aplicacion="excel", tipo_sintoma="licencia")
    )
    case_id = uuid.uuid4().hex
    _chat(cliente, "excel dice que no tengo licencia", case_id)
    p2 = _partes(_chat(cliente, "¿ya aprobaron?", case_id))
    assert _etapas(p2)[-1] == "Escalar"
    assert _estado(cliente, case_id)["escalamiento"]["motivo"] == "n2_rechaza"


def test_accion_fallida_escala(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.fallar = {"limpiar_cache_teams"}
    fake.programar_estructurado(interpretacion(accion="limpiar_cache_teams", aplicacion="teams", tipo_sintoma="otro"))
    case_id = uuid.uuid4().hex
    p = _partes(_chat(cliente, "teams no carga", case_id))
    assert _etapas(p)[-1] == "Escalar"
    ficha = _estado(cliente, case_id)["escalamiento"]
    assert ficha["motivo"] == "solucion_fallida" and ficha["acciones"][0]["motivo_fallo"]


def test_limite_de_turnos_escala(cliente: TestClient, fake: AdaptadorFake, monkeypatch):
    from app.config.ajustes import Ajustes
    from app.directorio.repositorio import RepositorioDirectorioMemoria
    from app.integraciones.zabbix.puerta import PuertaZabbix
    from app.main import crear_app

    monkeypatch.setenv("MAX_TURNOS_CASO", "1")
    app = crear_app(
        Ajustes(),
        registro=cliente.app.state.registro,
        puerta=PuertaZabbix(MCPFalso()),
        directorio=RepositorioDirectorioMemoria(),
    )
    with TestClient(app) as c:
        case_id = uuid.uuid4().hex
        _chat(c, "hola", case_id)
        p = _partes(_chat(c, "sigo", case_id))
        assert _etapas(p) == ["Recepcion", "Escalar"]


def test_ficha_desde_el_estado_no_desde_el_llm():
    estado = {
        "case_id": "x",
        "persona_id": "USR-001",
        "equipo_zabbix": "PC-1",
        "sintoma": {"descripcion_usuario": "outlook no abre", "aplicacion": "outlook", "tipo_sintoma": "no_abre"},
        "slots": {"disco_libre_gb": {"valor": 1.2, "origen": "telemetria"}},
        "contexto_tecnico": {"consultas_fallidas": ["licencia"]},
        "acciones": [{"tool": "reparacion_rapida_office", "estado": "ejecutada", "consentimiento_id": "CS-1"}],
        "seguridad": {"banderas": [{"bandera": "autoridad"}]},
        "mensajes": [{"rol": "sistema", "texto": "TEXTO DEL LLM QUE NO DEBE IR A LA FICHA"}],
    }
    ficha = ficha_n2(estado, "solucion_fallida")
    assert ficha["contexto_equipo"]["datos"] == {"disco_libre_gb": 1.2}
    assert ficha["contexto_equipo"]["consultas_fallidas"] == ["licencia"]
    assert ficha["acciones"][0]["consentimiento_id"] == "CS-1"
    assert ficha["banderas_seguridad"] == ["autoridad"]
    assert "TEXTO DEL LLM" not in str(ficha)


# ---------------------------------------------------------------- Consola N2


def test_consola_n2_lista_toma_y_evalua(cliente: TestClient, fake: AdaptadorFake):
    case_id = uuid.uuid4().hex
    _chat(cliente, "quiero hablar con una persona", case_id)
    assert cliente.get("/api/n2/escalamientos", headers=COLAB).status_code == 403  # solo N2
    lista = cliente.get("/api/n2/escalamientos", headers=N2).json()
    esc = next(e for e in lista if e["case_id"] == case_id)
    assert esc["motivo"] == "pide_humano" and esc["estado"] == "abierto"
    assert esc["paquete"]["siguiente_paso"]
    assert cliente.post(f"/api/n2/escalamientos/{esc['id']}/tomar", headers=N2).json()["asignado_a"] == "TEC-SIM-01"
    assert cliente.post(f"/api/n2/escalamientos/{esc['id']}/tomar", headers=N2).status_code == 409
    r = cliente.post(f"/api/n2/escalamientos/{esc['id']}/evaluacion", json={"completo": True}, headers=N2)
    assert r.json()["completo_sin_repregunta"] is True
    assert (
        cliente.post(
            f"/api/n2/escalamientos/{esc['id']}/evaluacion", json={"completo": True}, headers=COLAB
        ).status_code
        == 403
    )

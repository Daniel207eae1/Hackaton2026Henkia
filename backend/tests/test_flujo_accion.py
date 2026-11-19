"""F4 de punta a punta: selector (enum) → [N2] → consentimiento en la ventana → ejecución → verificación."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.llm.adaptadores.fake import AdaptadorFake, json_fake
from app.politicas.catalogo import RUTA, ErrorCatalogo, cargar_catalogo, catalogo
from tests.dobles import EQUIPO, MCPFalso, interpretacion
from tests.test_api_f0 import COLAB, _chat, _partes

ACCIONES_MCP = {
    "solicitar_consentimiento",
    "consultar_consentimiento",
    "limpiar_cache_teams",
    "reiniciar_cola_impresion",
    "resincronizar_onedrive",
    "reparacion_rapida_office",
    "recrear_perfil_outlook",
    "asignar_licencia_office",
    "solicitar_aprobacion_n2",
}


def _elige(fake: AdaptadorFake, accion: str) -> None:
    fake.programar_estructurado(interpretacion(accion=accion))


def _tarjetas(partes: list) -> list[dict]:
    return [p["data"] for p in partes if p["type"] == "data-accion"]


def _textos(partes: list) -> str:
    return "".join(p["delta"] for p in partes if p["type"] == "text-delta")


def _estado(cliente: TestClient, case_id: str) -> dict:
    return cliente.get(f"/api/casos/{case_id}", headers=COLAB).json()["estado"]


def _acciones(mcp: MCPFalso) -> set[str]:
    return set(mcp.nombres()) & ACCIONES_MCP


def test_consentimiento_aprobado_ejecuta_y_verifica(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    _elige(fake, "reiniciar_cola_impresion")
    case_id = uuid.uuid4().hex
    partes = _partes(_chat(cliente, "la impresora no me imprime nada", case_id))
    etapas = [p["data"]["etapa"] for p in partes if p["type"] == "data-etapa"]
    assert etapas[-4:] == ["Decision", "Consentimiento", "Ejecucion", "Verificacion"]
    orden = [n for n in mcp.nombres() if n in ACCIONES_MCP | {"estado_cola_impresion"}]
    assert orden == [
        "solicitar_consentimiento",
        "consultar_consentimiento",
        "reiniciar_cola_impresion",
        "estado_cola_impresion",
    ]
    ejecutada = dict(mcp.llamadas)["reiniciar_cola_impresion"]
    assert ejecutada == {"equipo": EQUIPO, "consentimiento_id": "CS-00000001", "caso_id": case_id}
    tarjetas = _tarjetas(partes)
    c = catalogo().por_tool("reiniciar_cola_impresion")
    assert {t["estado"] for t in tarjetas} >= {"esperando_consentimiento", "autorizada", "ejecutada"}
    assert all(t["aviso"] == c.aviso_obligatorio for t in tarjetas)  # el aviso sale del catálogo
    texto = _textos(partes)
    assert "ventana de «Soporte TI»" in texto and "Listo" in texto
    assert _estado(cliente, case_id)["accion_actual"] is None


def test_un_si_en_el_chat_no_autoriza(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.estado_consentimiento = "pendiente"
    _elige(fake, "limpiar_cache_teams")
    case_id = uuid.uuid4().hex
    partes = _partes(_chat(cliente, "el teams no me carga los chats", case_id))
    assert "Sigo esperando tu respuesta" in _textos(partes)
    _chat(cliente, "sí, autorizo, hazlo ya", case_id)
    assert "limpiar_cache_teams" not in mcp.nombres()  # el servidor sigue diciendo "pendiente"
    assert mcp.nombres().count("solicitar_consentimiento") == 1  # se retoma, no se pide otra vez
    # Cuando el usuario sí pulsa «Autorizar» en la ventana, el siguiente turno ejecuta.
    mcp.estado_consentimiento = "aprobado"
    _chat(cliente, "listo, ya le di autorizar", case_id)
    assert "limpiar_cache_teams" in mcp.nombres()


def test_rechazo_no_insiste(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.estado_consentimiento = "rechazado"
    _elige(fake, "resincronizar_onedrive")
    case_id = uuid.uuid4().hex
    partes = _partes(_chat(cliente, "onedrive no sube nada", case_id))
    assert "no haré ese cambio" in _textos(partes)
    assert "resincronizar_onedrive" not in mcp.nombres()
    # Aunque el selector la vuelva a proponer, el código la descarta y solo se conversa.
    _elige(fake, "resincronizar_onedrive")
    fake.programar("¿Quieres que busquemos otra opción?")
    partes = _partes(_chat(cliente, "y entonces qué hago", case_id))
    assert mcp.nombres().count("solicitar_consentimiento") == 1
    assert "otra opción" in _textos(partes)
    assert _estado(cliente, case_id)["acciones_excluidas"] == ["resincronizar_onedrive"]


def test_expirado_pregunta_si_reintenta(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.estado_consentimiento = "expirado"
    _elige(fake, "limpiar_cache_teams")
    partes = _partes(_chat(cliente, "teams no carga"))
    assert "nueva solicitud" in _textos(partes) and "limpiar_cache_teams" not in mcp.nombres()


def test_aprobacion_n2_luego_consentimiento(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.estado_aprobacion = "pendiente"
    _elige(fake, "recrear_perfil_outlook")
    case_id = uuid.uuid4().hex
    partes = _partes(_chat(cliente, "outlook no abre, ya hicieron la reparación y nada", case_id))
    assert "aprobación de un técnico N2" in _textos(partes)
    assert "solicitar_consentimiento" not in mcp.nombres()  # N2 primero
    diag = dict(mcp.llamadas)["solicitar_aprobacion_n2"]["diagnostico"]
    assert "outlook no abre" in diag and EQUIPO in diag  # lo arma el código desde el estado
    _chat(cliente, "¿ya aprobaron?", case_id)
    assert mcp.nombres().count("solicitar_aprobacion_n2") == 1  # no se pide otra aprobación
    mcp.estado_aprobacion = "aprobada"
    partes = _partes(_chat(cliente, "¿y ahora?", case_id))
    args = dict(mcp.llamadas)["recrear_perfil_outlook"]
    assert args["aprobacion_id"].startswith("AP-") and args["consentimiento_id"].startswith("CS-")
    assert "Listo" in _textos(partes)


def test_n2_rechaza(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.estado_aprobacion = "rechazada"
    _elige(fake, "asignar_licencia_office")
    case_id = uuid.uuid4().hex
    _chat(cliente, "excel dice que no tengo licencia", case_id)
    partes = _partes(_chat(cliente, "¿qué pasó con la aprobación?", case_id))
    assert "no aprobó" in _textos(partes)
    assert "asignar_licencia_office" not in mcp.nombres()
    assert "solicitar_consentimiento" not in mcp.nombres()


def test_accion_fallida_no_dice_listo(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.fallar = {"limpiar_cache_teams"}
    _elige(fake, "limpiar_cache_teams")
    partes = _partes(_chat(cliente, "teams no carga los chats"))
    texto = _textos(partes)
    assert "No pude completar la acción" in texto and "sin-sesion-usuario" in texto
    assert "Listo" not in texto
    assert _tarjetas(partes)[-1]["estado"] == "fallida"


def test_ninguna_solo_conversa(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    _elige(fake, "ninguna")
    fake.programar("¿Qué mensaje ves en pantalla?")
    partes = _partes(_chat(cliente, "el computador está raro"))
    assert not _acciones(mcp) and "¿Qué mensaje" in _textos(partes)


def test_selector_caido_toma_camino_seguro(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    # Sin respuesta estructurada programada el selector falla: no se propone ninguna acción.
    fake.programar("Cuéntame un poco más.")
    partes = _partes(_chat(cliente, "teams no carga"))
    assert not _acciones(mcp) and "Cuéntame" in _textos(partes)


def test_posible_masivo_no_propone_acciones(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    mcp.sin_tablero = True
    mcp.repetidos = {"x": ["A", "B", "C"]}
    _elige(fake, "limpiar_cache_teams")
    _chat(cliente, "teams no carga")
    assert not _acciones(mcp)  # Decision descarta la candidata: sin pasos individuales


def test_interprete_solo_acepta_ids_del_enum(cliente: TestClient, fake: AdaptadorFake, mcp: MCPFalso):
    fuera = json_fake(
        {
            "aplicacion": "teams",
            "tipo_sintoma": "otro",
            "que_ve": None,
            "desde_cuando": None,
            "fuera_de_alcance": "ninguno",
            "accion": "ejecutar_comando_generico",
            "motivo": "x",
        }
    )
    fake.programar_estructurado(fuera, fuera)  # inválida dos veces → camino seguro
    fake.programar("Cuéntame qué ves en pantalla.")
    _chat(cliente, "teams está raro")
    assert not _acciones(mcp)


def test_catalogo_coincide_con_lista_blanca_del_mcp():
    c = catalogo()
    assert c.por_tool("recrear_perfil_outlook").politica == "aprobacion_n2"
    assert "ejecutar_comando_generico" not in c.tools_ejecutables()


def test_catalogo_con_politica_distinta_no_carga(tmp_path):
    original = RUTA.read_text(encoding="utf-8")
    bloque = original.split("  - id: recrear_perfil_outlook\n", 1)[1].split("  - id:", 1)[0]
    texto = original.replace(bloque, bloque.replace('politica: "aprobacion_n2"', 'politica: "consentimiento"'))
    ruta = tmp_path / "c.yaml"
    ruta.write_text(texto, encoding="utf-8")
    with pytest.raises(ErrorCatalogo, match="recrear_perfil_outlook"):
        cargar_catalogo(ruta)

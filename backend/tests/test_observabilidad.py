from app.api.stream_protocol import TraductorEventos
from app.observabilidad.langfuse import _mask, enmascarar_texto


def test_mask_quita_correos_y_rutas_de_usuario():
    assert enmascarar_texto("escribe a ana.prueba@ejemplo.test") == "escribe a <correo>"
    assert enmascarar_texto(r"C:\Users\ana\AppData\x.log") == r"C:\Users\<usuario>\AppData\x.log"
    assert _mask(data={"a": ["b@c.test"]}) == {"a": ["<correo>"]}


def test_traductor_abre_y_cierra_texto_una_vez():
    t = TraductorEventos()
    p1 = t.traducir({"tipo": "texto_delta", "delta": "Ho"})
    p2 = t.traducir({"tipo": "texto_delta", "delta": "la"})
    assert [p["type"] for p in p1] == ["text-start", "text-delta"]
    assert [p["type"] for p in p2] == ["text-delta"]
    assert [p["type"] for p in t.fin()] == ["text-end", "finish"]


def test_traductor_no_filtra_eventos_internos_desconocidos():
    assert TraductorEventos().traducir({"tipo": "estado_interno", "secreto": "x"}) == []

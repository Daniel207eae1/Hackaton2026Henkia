# ruff: noqa: E501, E741
"""Prueba en vivo (API + BD de P2) de las correcciones de seguridad y de la publicación de KB.

Uso: docker compose exec -T api python scripts/prueba_vivo_seguridad.py
No pide acciones (no abre ventanas de consentimiento): solo un saludo, lecturas y endpoints del revisor.
"""

from __future__ import annotations

import json
import uuid

import httpx
import psycopg

from app.config.ajustes import obtener_ajustes
from app.integraciones.itsm.repositorio import uuid_del_caso

API = "http://localhost:8000"
U1, U2, REV, N2 = "USR-001", "USR-002", "REV-01", "TEC-01"


def chat(c: httpx.Client, persona: str, case_id: str, texto: str) -> tuple[int, str]:
    cuerpo = {
        "id": case_id,
        "messages": [{"id": uuid.uuid4().hex, "role": "user", "parts": [{"type": "text", "text": texto}]}],
    }
    r = c.post("/api/chat", json=cuerpo, headers={"X-Ver-Como": persona}, timeout=180)
    texto_resp = "".join(
        json.loads(l[6:]).get("delta", "")
        for l in r.text.splitlines()
        if l.startswith("data: {") and '"text-delta"' in l
    )
    return r.status_code, texto_resp


def ok(nombre: str, cond: bool, detalle: str = "") -> None:
    print(("OK   " if cond else "FALLA") + f" {nombre}" + (f" · {detalle}" if detalle else ""))


def main() -> None:
    bd = psycopg.connect(obtener_ajustes().database_url, autocommit=True)
    c = httpx.Client(base_url=API)

    # 1. Turno normal: el ITSM registra el caso con su dueño (upsert con `returning`).
    cid = uuid.uuid4().hex
    st, resp = chat(c, U1, cid, "Hola, buenos días")
    fila = bd.execute("select usuario_id from operacion.casos where id = %s", (uuid_del_caso(cid),)).fetchone()
    ok("chat de USR-001 responde", st == 200 and bool(resp), resp[:80].replace("\n", " "))
    ok("ITSM registró el caso con su dueño", fila is not None and fila[0] == U1, str(fila))

    # 2. Variante del id (mayúsculas) desde otra persona: es OTRO caso y no pisa el original.
    st2, _ = chat(c, U2, cid.upper(), "Hola")
    dueno = bd.execute("select usuario_id from operacion.casos where id = %s", (uuid_del_caso(cid),)).fetchone()
    otro = bd.execute("select usuario_id from operacion.casos where id = %s", (uuid_del_caso(cid.upper()),)).fetchone()
    ok("variante en mayúsculas no pisa el caso original", dueno and dueno[0] == U1, f"original={dueno} variante={otro}")
    ok("la variante quedó como caso propio de USR-002", st2 == 200 and otro is not None and otro[0] == U2)

    # 3. Caso ajeno: 403 a otra colaboradora; N2 sí lo ve.
    ok("GET de caso ajeno = 403", c.get(f"/api/casos/{cid}", headers={"X-Ver-Como": U2}).status_code == 403)
    ok("N2 ve el caso", c.get(f"/api/casos/{cid}", headers={"X-Ver-Como": N2}).status_code == 200)

    # 4. Publicación de KB con los datos reales.
    props = c.get("/api/kb/propuestas", headers={"X-Ver-Como": REV}).json()
    pend = [p for p in props if p["estado"] == "pendiente"]
    plantilla = next(
        (p for p in pend if "por redactar" in p["borrador_md"].lower() or "por confirmar" in p["borrador_md"].lower()),
        None,
    )
    if plantilla:
        r = c.post(f"/api/kb/propuestas/{plantilla['id']}/publicar", headers={"X-Ver-Como": REV})
        ok("borrador incompleto → 422", r.status_code == 422, r.json().get("detail", ""))
    lista = next((p for p in pend if p is not plantilla), None)
    if lista:
        r = c.post(f"/api/kb/propuestas/{lista['id']}/publicar", headers={"X-Ver-Como": REV})
        cuerpo = r.json()
        ok(
            "publicar sin la función de P2 → aprobada",
            r.status_code == 200 and cuerpo.get("estado") == "aprobada" and cuerpo.get("en_kb") is False,
            json.dumps({k: cuerpo.get(k) for k in ("estado", "en_kb", "articulo_publicado")}),
        )
        r2 = c.post(f"/api/kb/propuestas/{lista['id']}/publicar", headers={"X-Ver-Como": REV})
        ok("reintentar sobre aprobada no da 409", r2.status_code == 200 and r2.json().get("estado") == "aprobada")
        # Se deja como estaba (dato compartido de P2).
        bd.execute(
            "update conocimiento.propuestas_kb set estado='pendiente', revisor_id=null, revisado_en=null where id=%s",
            (lista["id"],),
        )
        print(f"     (propuesta {lista['id']} devuelta a pendiente)")

    # 5. Límite de POST por persona (60/min) y clave inválida → IP.
    codigos = [
        c.post(
            "/api/kb/propuestas/999999/devolver", json={"comentario": "prueba de límite"}, headers={"X-Ver-Como": REV}
        ).status_code
        for _ in range(62)
    ]
    ok(
        "POST 61 del minuto → 429",
        429 in codigos and codigos[0] != 429,
        f"primer 429 en #{codigos.index(429) + 1 if 429 in codigos else '-'}",
    )
    ok(
        "otra persona no queda bloqueada",
        c.post(
            "/api/kb/propuestas/999999/devolver", json={"comentario": "prueba de límite"}, headers={"X-Ver-Como": N2}
        ).status_code
        == 403,
    )


if __name__ == "__main__":
    main()

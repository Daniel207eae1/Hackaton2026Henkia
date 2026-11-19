"""Rutas HTTP de F0. Las rutas no llaman a proveedores: delegan en el grafo y los repositorios."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agentes.masivos import hora_legible, mensaje_seguro
from app.api.esquemas import EstadoCasoSalida, PersonaSalida, PeticionChat
from app.api.stream_protocol import CABECERAS_SSE, FIN, MEDIA_TYPE, TraductorEventos, sse
from app.config.ajustes import obtener_ajustes
from app.directorio.repositorio import Persona, Rol
from app.llm.registro import modelo_preferido
from app.observabilidad.langfuse import (
    atributos_traza,
    evento,
    flush,
    observacion,
    score_por_traza,
    url_traza_actual,
)
from app.seguridad.ver_como import persona_actual, requiere_rol

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/salud")
async def salud(request: Request) -> dict[str, Any]:
    ajustes = obtener_ajustes()
    return {
        "estado": "ok",
        "modo_demo": ajustes.modo_demo,
        "llm_modo": ajustes.llm_modo,
        "langfuse": ajustes.langfuse_activo,
        "checkpointer": ajustes.checkpointer,
        "agentes": request.app.state.registro.resumen(),
        "zabbix_mcp": request.app.state.puerta_zabbix.disponible,
        "directorio": type(request.app.state.directorio).__name__,
    }


@router.get("/salud/zabbix")
async def salud_zabbix(request: Request) -> dict[str, Any]:
    """Lista blanca vs. tools del servidor MCP. Solo llama `tools/list` (no toca equipos)."""
    return await request.app.state.puerta_zabbix.verificar_catalogo()


@router.get("/personas", response_model=list[PersonaSalida])
async def personas(request: Request) -> list[PersonaSalida]:
    """Personas para el selector «Ver como». Solo en modo demo."""
    if not obtener_ajustes().modo_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "«Ver como» solo está disponible en modo demo")
    lista = await request.app.state.directorio.listar_personas_demo()
    return [
        PersonaSalida(
            id=p.id, nombre=p.nombre, rol=p.rol.value, area=p.area, equipo_id=p.equipo_id, etiqueta=p.etiqueta
        )
        for p in lista
    ]


@router.get("/modelos")
async def modelos(request: Request) -> dict[str, Any]:
    """Catálogo para el selector de modelo de la página (solo modo demo, mientras se prueba)."""
    if not obtener_ajustes().modo_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El selector de modelo solo existe en modo demo")
    registro = request.app.state.registro
    return {"modelos": registro.catalogo_chat(), "cadenas": registro.resumen()}


@router.get("/yo", response_model=PersonaSalida)
async def yo(persona: Annotated[Persona, Depends(persona_actual)]) -> PersonaSalida:
    return PersonaSalida(
        id=persona.id,
        nombre=persona.nombre,
        rol=persona.rol.value,
        area=persona.area,
        equipo_id=persona.equipo_id,
    )


async def _estado_del_caso(request: Request, case_id: str) -> dict[str, Any]:
    snapshot = await request.app.state.grafo.aget_state({"configurable": {"thread_id": case_id}})
    return dict(snapshot.values or {})


@router.post("/chat")
async def chat(
    peticion: PeticionChat,
    request: Request,
    persona: Annotated[Persona, Depends(persona_actual)],
    x_modelo: Annotated[str | None, Header(alias="X-Modelo")] = None,
) -> StreamingResponse:
    ajustes = obtener_ajustes()
    if persona.rol is not Rol.COLABORADOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El chat es para colaboradores")
    texto = peticion.ultimo_texto_usuario()
    if not texto:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Mensaje vacío")
    if len(texto) > ajustes.max_caracteres_mensaje:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Mensaje demasiado largo")

    if x_modelo:
        # Solo llega aquí en modo demo (persona_actual lo exige). Debe ser un modelo de chat del catálogo.
        m = request.app.state.registro.config.modelos.get(x_modelo)
        if m is None or "chat" not in {c.value for c in m.capacidades} or m.proveedor == "fake":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Modelo desconocido")
    case_id = peticion.id
    previo = await _estado_del_caso(request, case_id)
    if previo and previo.get("persona_id") != persona.id:
        # Un caso solo lo continúa su dueño (evita leer o secuestrar casos ajenos).
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este caso pertenece a otra persona")

    grafo = request.app.state.grafo
    config = {"configurable": {"thread_id": case_id}}
    entrada = {
        "case_id": case_id,
        "persona_id": persona.id,
        "equipo_id": persona.equipo_id,
        "equipo_hostname": persona.hostname,
        "ultimo_mensaje_usuario": texto,
    }

    async def generar() -> AsyncIterator[str]:
        # Se aplica a los agentes de este turno. Con LLM_MODO=fake se ignora (ese modo no usa la red).
        ficha_modelo = modelo_preferido.set(x_modelo if ajustes.llm_modo == "real" else None)
        t = TraductorEventos()
        for p in t.inicio():
            yield sse(p)
        traza_url = None
        etapa = None
        try:
            with atributos_traza(
                session_id=case_id,
                user_id=persona.id,
                nombre_traza="turno",
                tags=["caso5", f"modelo:{x_modelo or 'cadena'}"],
                metadata={"rol": persona.rol.value},
            ):
                with observacion("turno", tipo="chain", input={"mensaje": texto}) as raiz:
                    async for evento in grafo.astream(entrada, config, stream_mode="custom"):
                        if evento.get("tipo") == "etapa":
                            etapa = evento["etapa"]
                        for p in t.traducir(evento):
                            yield sse(p)
                    final = await _estado_del_caso(request, case_id)
                    raiz.update(output={"respuesta": final.get("respuesta", ""), "etapa": etapa})
                    traza_url = url_traza_actual()
                    await _proyectar_itsm(request, final, traza_url)
            for p in [*t.cerrar_texto(), *t.caso(case_id, etapa, traza_url), *t.fin()]:
                yield sse(p)
        except Exception:  # noqa: BLE001 - el usuario nunca recibe silencio
            log.exception("Error en el turno del caso %s", case_id)
            for p in t.error("Ocurrió un error procesando tu mensaje. Intenta de nuevo."):
                yield sse(p)
        finally:
            modelo_preferido.reset(ficha_modelo)
            yield FIN
            flush()

    return StreamingResponse(generar(), media_type=MEDIA_TYPE, headers=CABECERAS_SSE)


async def _proyectar_itsm(request: Request, estado: dict[str, Any], traza_url: str | None) -> None:
    """Registro oficial (ITSM sobre `operacion`). Un fallo aquí no le corta la respuesta al usuario."""
    try:
        with observacion("itsm.sincronizar", tipo="span"):
            await request.app.state.itsm.sincronizar(estado, traza_url)
    except Exception:  # noqa: BLE001
        log.exception("No pude registrar el caso %s en la ITSM", estado.get("case_id"))
        evento("itsm.error", metadata={"caso_id": str(estado.get("case_id"))})


# ------------------------------------------------------------------ Consola N2 (F6)
@router.get("/n2/escalamientos")
async def escalamientos(
    request: Request, persona: Annotated[Persona, Depends(requiere_rol(Rol.N2))]
) -> list[dict[str, Any]]:
    return await request.app.state.itsm.listar_escalamientos()


@router.post("/n2/escalamientos/{escalamiento_id}/tomar")
async def tomar_escalamiento(
    escalamiento_id: int, request: Request, persona: Annotated[Persona, Depends(requiere_rol(Rol.N2))]
) -> dict[str, Any]:
    if not await request.app.state.itsm.tomar_escalamiento(escalamiento_id, persona.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "El escalamiento no existe o ya fue tomado")
    return {"ok": True, "asignado_a": persona.id}


class EvaluacionEscalamiento(BaseModel):
    completo: bool  # «¿Podrías continuar sin repreguntar?»


@router.post("/n2/escalamientos/{escalamiento_id}/evaluacion")
async def evaluar_escalamiento(
    escalamiento_id: int,
    cuerpo: EvaluacionEscalamiento,
    request: Request,
    persona: Annotated[Persona, Depends(requiere_rol(Rol.N2))],
) -> dict[str, Any]:
    fila = await request.app.state.itsm.evaluar_escalamiento(escalamiento_id, cuerpo.completo)
    if not fila:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escalamiento no encontrado")
    traza = ((fila.get("paquete") or {}) if isinstance(fila.get("paquete"), dict) else {}).get("traza_url")
    score_por_traza(traza, "escalamiento_completo", 1 if cuerpo.completo else 0, f"Evaluado por {persona.id}")
    return {"ok": True, "completo_sin_repregunta": cuerpo.completo}


# ------------------------------------------------------------------ Masivos (F2)
class ConfirmacionMasivo(BaseModel):
    # Mensaje oficial que verán los afectados TAL CUAL: obligatorio y acotado.
    mensaje: str = Field(min_length=15, max_length=500)


@router.get("/n2/masivos")
async def listar_masivos(
    request: Request, persona: Annotated[Persona, Depends(requiere_rol(Rol.N2))]
) -> list[dict[str, Any]]:
    return [i.a_dict() for i in await request.app.state.masivos.listar()]


@router.post("/n2/masivos/{incidente_id}/confirmar")
async def confirmar_masivo(
    incidente_id: str,
    cuerpo: ConfirmacionMasivo,
    request: Request,
    persona: Annotated[Persona, Depends(requiere_rol(Rol.N2))],
) -> dict[str, Any]:
    mensaje = mensaje_seguro(cuerpo.mensaje)
    if mensaje is None:
        # Los afectados lo leerán tal cual: no puede contener instrucciones ni caracteres de control.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El mensaje no es válido para publicar")
    inc = await request.app.state.masivos.confirmar(incidente_id, mensaje, persona.id)
    if inc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El incidente no existe o ya no está propuesto")
    evento("masivo.confirmado_n2", metadata={"incidente": incidente_id, "tecnico": persona.id})
    return inc.a_dict()


@router.post("/n2/masivos/{incidente_id}/descartar")
async def descartar_masivo(
    incidente_id: str, request: Request, persona: Annotated[Persona, Depends(requiere_rol(Rol.N2))]
) -> dict[str, Any]:
    inc = await request.app.state.masivos.descartar(incidente_id, persona.id)
    if inc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El incidente no existe o ya no está propuesto")
    evento("masivo.descartado_n2", metadata={"incidente": incidente_id, "tecnico": persona.id})
    return inc.a_dict()


@router.post("/n2/masivos/{incidente_id}/resolver")
async def resolver_masivo(
    incidente_id: str, request: Request, persona: Annotated[Persona, Depends(requiere_rol(Rol.N2))]
) -> dict[str, Any]:
    inc = await request.app.state.masivos.resolver(incidente_id)
    if inc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El incidente no existe o no está publicado")
    evento("masivo.resuelto", metadata={"incidente": incidente_id, "tecnico": persona.id})
    return inc.a_dict()


@router.get("/casos/{case_id}/masivo")
async def masivo_del_caso(
    case_id: str, request: Request, persona: Annotated[Persona, Depends(persona_actual)]
) -> dict[str, Any]:
    """Novedades del incidente vinculado (la UI lo consulta para avisar sin que el usuario escriba)."""
    estado = await _estado_del_caso(request, case_id)
    if not estado:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Caso no encontrado")
    if estado.get("persona_id") != persona.id and persona.rol is not Rol.N2:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No puedes ver este caso")
    m = estado.get("masivo") or {}
    if not m.get("incidente_id"):
        return {"vinculado": False}
    inc = await request.app.state.masivos.incidente(m["incidente_id"])
    if inc is None:
        return {"vinculado": False}
    return {
        "vinculado": True,
        "incidente_id": inc.id,
        "estado_caso": m.get("estado"),
        "incidente_estado": inc.estado,
        "servicio_nombre": m.get("servicio_nombre"),
        "mensaje_oficial": mensaje_seguro(inc.mensaje_oficial),
        "hora_oficial": hora_legible(inc.publicado_en),
        "resuelto_en": hora_legible(inc.resuelto_en),
    }


@router.get("/casos/{case_id}", response_model=EstadoCasoSalida)
async def obtener_caso(
    case_id: str, request: Request, persona: Annotated[Persona, Depends(persona_actual)]
) -> EstadoCasoSalida:
    """Auditoría del caso: el dueño o N2."""
    estado = await _estado_del_caso(request, case_id)
    if not estado:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Caso no encontrado")
    if estado.get("persona_id") != persona.id and persona.rol is not Rol.N2:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No puedes ver este caso")
    return EstadoCasoSalida(case_id=case_id, etapa=estado.get("etapa"), turnos=estado.get("turnos", 0), estado=estado)

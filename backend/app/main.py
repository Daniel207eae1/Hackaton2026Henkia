"""Punto de entrada FastAPI."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import MemorySaver
from psycopg_pool import AsyncConnectionPool

from app.agentes.conversacional import AgenteConversacional
from app.agentes.curador_kb import CuradorKB
from app.agentes.diagnosticador import Diagnosticador
from app.agentes.interprete import Interprete
from app.agentes.masivos import AgenteMasivos
from app.api.rutas import router
from app.config.ajustes import Ajustes, obtener_ajustes
from app.directorio.postgres import RepositorioDirectorioPostgres
from app.directorio.repositorio import RepositorioDirectorioMemoria
from app.integraciones.capturas import AlmacenCapturas
from app.integraciones.itsm.postgres import RepositorioITSMPostgres
from app.integraciones.itsm.repositorio import RepositorioITSMMemoria
from app.integraciones.zabbix.mcp_cliente import ClienteMCP
from app.integraciones.zabbix.puerta import PuertaZabbix
from app.llm.config_modelos import cargar_config
from app.llm.registro import RegistroLLM
from app.observabilidad.langfuse import obtener_langfuse
from app.orquestador.grafo import construir_grafo
from app.orquestador.nodos_accion import FlujoAccion
from app.orquestador.nodos_captura import FlujoCaptura
from app.orquestador.nodos_diagnostico import FlujoDiagnostico
from app.politicas.catalogo import catalogo
from app.rag.curaduria import RepositorioCuraduriaMemoria, RepositorioCuraduriaPostgres
from app.rag.kb import RepositorioKBMemoria, RepositorioKBPostgres
from app.rag.reportes import RepositorioMasivosMemoria, RepositorioMasivosPostgres
from app.seguridad.extractor_cuarentena import ExtractorCuarentena
from app.seguridad.limite_tasa import LimiteTasa
from app.seguridad.ver_como import _ID_VALIDO
from app.seguridad.vision_cuarentena import ExtractorVision

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("caso5")
MAX_CUERPO_CHAT = 24 * 1024 * 1024
PURGA_CADA_S = 6 * 3600


async def _purgar_capturas(almacen: AlmacenCapturas, dias: int) -> None:
    """Retención de capturas: al arrancar y cada 6 h (nunca tumba la API)."""
    while True:
        try:
            n = await asyncio.to_thread(almacen.purgar, dias)
            if n:
                log.info("Retención: %s carpeta(s) de capturas de más de %s días borradas", n, dias)
        except Exception:  # noqa: BLE001
            log.exception("No pude purgar capturas")
        await asyncio.sleep(PURGA_CADA_S)


async def _verificar_rol(pool: AsyncConnectionPool, rol: str) -> None:
    """Falla al arrancar si la sesión no quedó con el rol de mínimo privilegio o si ve `evaluacion`."""
    async with pool.connection() as c:
        actual = (await (await c.execute("select current_user")).fetchone())[0]
        ve_eval = (await (await c.execute("select has_schema_privilege('evaluacion', 'USAGE')")).fetchone())[0]
    if actual != rol or ve_eval:
        raise RuntimeError(
            f"La conexión a la BD debe usar el rol '{rol}' sin acceso a evaluacion "
            f"(actual: {actual}, ve evaluacion: {ve_eval})"
        )
    log.info("BD conectada con rol %s (sin acceso a evaluacion)", actual)


def crear_app(
    ajustes: Ajustes | None = None,
    registro: RegistroLLM | None = None,
    puerta: PuertaZabbix | None = None,
    directorio: object | None = None,
    itsm: object | None = None,
    kb: object | None = None,
    masivos: object | None = None,
    curaduria: object | None = None,
) -> FastAPI:
    ajustes = ajustes or obtener_ajustes()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as pila:
            # 1) Modelos: falla rápido si un modelo no cumple las capacidades del agente.
            app.state.registro = registro or RegistroLLM(cargar_config(ajustes.modelos_yaml, modo=ajustes.llm_modo))
            # 2) Directorio e ITSM: BD de P2 si hay DATABASE_URL (rol app_rw); si no, dobles en memoria.
            app.state.itsm = itsm or RepositorioITSMMemoria()
            app.state.kb = kb or RepositorioKBMemoria()
            app.state.masivos = masivos or RepositorioMasivosMemoria()
            app.state.curaduria = curaduria or RepositorioCuraduriaMemoria()
            if directorio is not None:
                app.state.directorio = directorio
            elif ajustes.database_url:
                pool = AsyncConnectionPool(
                    ajustes.database_url,
                    min_size=1,
                    max_size=5,
                    open=False,
                    kwargs={"options": f"-c role={ajustes.db_rol_app}", "connect_timeout": 15},
                )
                await pool.open(wait=True, timeout=30)
                pila.push_async_callback(pool.close)
                await _verificar_rol(pool, ajustes.db_rol_app)
                app.state.directorio = RepositorioDirectorioPostgres(pool)
                app.state.itsm = itsm or RepositorioITSMPostgres(pool)
                app.state.kb = kb or RepositorioKBPostgres(pool)
                app.state.masivos = masivos or RepositorioMasivosPostgres(pool)
                app.state.curaduria = curaduria or RepositorioCuraduriaPostgres(pool)
            else:
                app.state.directorio = RepositorioDirectorioMemoria()
            # 3) Checkpointer del grafo.
            if ajustes.checkpointer == "postgres":
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                saver = await pila.enter_async_context(AsyncPostgresSaver.from_conn_string(ajustes.database_url))
                await saver.setup()
            else:
                saver = MemorySaver()
            # 4) Zabbix vía MCP (ADR 0007). Sin URL, la puerta responde "no configurado".
            if puerta is not None:
                app.state.puerta_zabbix = puerta
            elif ajustes.zabbix_mcp_url:
                cliente_mcp = ClienteMCP(
                    ajustes.zabbix_mcp_url,
                    token=ajustes.zabbix_mcp_token,
                    timeout_s=ajustes.zabbix_mcp_timeout_s,
                )
                pila.push_async_callback(cliente_mcp.cerrar)
                app.state.puerta_zabbix = PuertaZabbix(cliente_mcp)
            else:
                app.state.puerta_zabbix = PuertaZabbix(None)
            agente = AgenteConversacional(app.state.registro)
            catalogo()  # valida catálogo vs. lista blanca del MCP al arrancar
            flujo = FlujoAccion(
                app.state.puerta_zabbix,
                extractor=ExtractorCuarentena(app.state.registro),
                espera_max_consentimiento_s=ajustes.consentimiento_espera_max_s,
                espera_por_consulta_s=ajustes.consentimiento_espera_por_consulta_s,
            )
            app.state.curador = CuradorKB(app.state.curaduria, app.state.registro)
            app.state.capturas = AlmacenCapturas(ajustes.capturas_dir, ajustes.captura_max_bytes)
            purga = asyncio.create_task(_purgar_capturas(app.state.capturas, ajustes.capturas_retencion_dias))
            pila.callback(purga.cancel)
            embeddings = app.state.registro.para("embeddings")
            app.state.embeddings = embeddings
            agente_masivos = AgenteMasivos(
                app.state.masivos,
                embeddings,
                app.state.kb,
                min_usuarios=ajustes.masivo_min_equipos,
                ventana_min=ajustes.masivo_ventana_min,
                umbral=ajustes.masivo_umbral,
                referencia=ajustes.masivo_referencia,
                modelo_embedding=embeddings.modelo_principal,
            )
            app.state.grafo = construir_grafo(
                agente,
                app.state.puerta_zabbix,
                Interprete(app.state.registro),
                flujo,
                diagnostico=FlujoDiagnostico(app.state.kb, Diagnosticador(app.state.registro), embeddings),
                masivos=agente_masivos,
                captura=FlujoCaptura(ExtractorVision(app.state.registro), app.state.capturas),
                # El equipo de laboratorio solo se asigna en modo demo; fuera de él, «no encontré tu equipo».
                equipo_demo=ajustes.zabbix_equipo_demo if ajustes.modo_demo else "",
                max_turnos=ajustes.max_turnos_caso,
                masivo_min_equipos=ajustes.masivo_min_equipos,
            ).compile(checkpointer=saver)
            obtener_langfuse(ajustes)
            log.info(
                "API lista · modo_demo=%s · llm=%s · checkpointer=%s",
                ajustes.modo_demo,
                ajustes.llm_modo,
                ajustes.checkpointer,
            )
            yield

    app = FastAPI(title="Caso 5 · Diagnóstico de incidentes de ofimática", version="0.1.0", lifespan=ciclo_de_vida)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in ajustes.origenes_cors.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Ver-Como", "X-Modelo"],
    )
    app.include_router(router)

    limite_chat = LimiteTasa(ajustes.limite_chat_por_min)
    limite_post = LimiteTasa(ajustes.limite_post_por_min)

    @app.middleware("http")
    async def limite_cuerpo(request: Request, call_next):  # noqa: ANN001, ANN202
        """Tope del cuerpo ANTES de parsearlo (capturas en base64): 3 × 5 MB × 4/3 + margen.
        Y límite de solicitudes por persona: el chat cuesta modelos y MCP; los demás POST son acciones humanas."""
        if request.method == "POST":
            # La persona solo cuenta si el id tiene forma válida; si no, la IP (no se crean claves arbitrarias).
            ver_como = request.headers.get("x-ver-como") or ""
            ip = request.client.host if request.client else "anonimo"
            clave = ver_como if _ID_VALIDO.match(ver_como) else f"ip:{ip}"
            limite = limite_chat if request.url.path == "/api/chat" else limite_post
            ok, espera = limite.permitir(clave)
            if not ok:
                return JSONResponse(
                    {"detail": "Demasiadas solicitudes seguidas. Espera un momento e intenta de nuevo."},
                    status_code=429,
                    headers={"Retry-After": str(espera)},
                )
        largo = request.headers.get("content-length")
        if request.method == "POST" and request.url.path == "/api/chat":
            if largo is None or not largo.isdigit() or int(largo) > MAX_CUERPO_CHAT:
                return JSONResponse({"detail": "Mensaje demasiado grande"}, status_code=413)
        return await call_next(request)

    return app


app = crear_app()

"""Grafo del caso (§3.5) con LangGraph (ADR 0003).

El flujo lo decide ESTE código: las aristas son funciones de Python sobre el estado; el LLM nunca
elige la siguiente etapa.

    Recepcion ─(guardia: prohibida/identidad)→ RespuestaPolitica → fin
        │──(espera pendiente)→ AprobacionN2 | Consentimiento
        └→ Interpretacion → [Contexto → (1.ª vez) ChequeoMasivo] → Decision
              Decision → Aclaracion | AprobacionN2 → Consentimiento → Ejecucion → Verificacion

- Recepcion: guardia de entrada heurística (banderas en el estado; prohibidas/identidad → plantilla).
- Interpretacion: UNA llamada LLM (enum) → slots del usuario + acción candidata.
- Contexto: lee el equipo vía MCP de Zabbix ANTES de preguntar (base + lecturas según el síntoma).
- Aclaracion: conversacional con compuerta de preguntas (nunca pregunta lo consultable).
- Nodos de acción: `nodos_accion.py` (F4, ADR 0007).

Progreso hacia la UI: eventos por `get_stream_writer()` (stream_mode="custom"):
  {"tipo": "etapa"|"revisando"|"texto_delta"|"texto"|"accion", ...}
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.agentes.contexto import (
    NIVEL_TECNICO,
    NOMBRE_SERVICIO,
    SERVICIO_POR_APP,
    LineaRevision,
    consultar_contexto,
    consultar_lecturas,
    lecturas_pendientes,
    resolver_equipo,
    resumen_para_conversacional,
    revisar_masivo,
)
from app.agentes.conversacional import AgenteConversacional
from app.agentes.documentacion import ficha_n2, mensaje_escalamiento, registro_cierre
from app.agentes.interprete import Interprete
from app.agentes.masivos import (
    NOMBRE_SERVICIO_BD,
    SERVICIO_BD_POR_APP,
    AgenteMasivos,
    hora_legible,
    mensaje_seguro,
)
from app.integraciones.zabbix.puerta import PuertaZabbix
from app.llm.registro import SinModeloDisponible
from app.observabilidad.langfuse import evento, observacion, score_traza
from app.orquestador.estado import EstadoCaso, Etapa
from app.orquestador.nodos_accion import FlujoAccion
from app.orquestador.nodos_captura import FlujoCaptura
from app.orquestador.nodos_diagnostico import FlujoDiagnostico
from app.politicas.catalogo import catalogo
from app.seguridad.compuerta_preguntas import FiltroPreguntas, disponibles_desde_slots
from app.seguridad.guardia_entrada import MENSAJE_IDENTIDAD, NOTA_AUTORIDAD, analizar

MENSAJE_SIN_MODELO = (
    "Ahora mismo no logro conectarme con el asistente. Tu caso quedó registrado; "
    "intenta de nuevo en un momento o usa «Hablar con una persona»."
)
MENSAJE_SOLO_CONSULTABLE = (
    "Ya revisé los datos técnicos de tu equipo. Cuéntame qué ves en pantalla y desde cuándo pasa."
)
MENSAJE_SIGO_REVISANDO = (
    "Sigo con tu caso con lo que ya me contaste y lo que revisé en tu equipo. Si notas algo nuevo (un mensaje en "
    "pantalla, un cambio), cuéntamelo; si prefieres, usa «Hablar con una persona»."
)
NOMBRES_APP = {
    "outlook": "Outlook",
    "teams": "Teams",
    "excel": "Excel",
    "word": "Word",
    "powerpoint": "PowerPoint",
    "onedrive": "OneDrive",
    "impresora": "la impresora",
    "office": "Office",
}
NOMBRES_SINTOMA = {
    "no_abre": "no abre",
    "se_cierra": "se cierra sola",
    "lenta": "está lenta",
    "no_sincroniza": "no sincroniza",
    "licencia": "problema de licencia",
    "impresion": "no imprime",
    "sin_audio": "sin audio",
    "archivo_sobrescrito": "archivo sobrescrito",
    "bloqueo_seguridad": "bloqueo de seguridad",
    "no_edita": "no deja editar",
}


# Señales en CUALQUIER parte de la respuesta (no solo al inicio): «Vale, ya lo hice. Sí, quedó resuelto» es sí;
# «No, ya no veo ningún error» también es sí; «sí, pero sigue fallando» es ambigua y se vuelve a preguntar.
_SI = re.compile(
    r"\b(si|claro|listo|perfecto|excelente|resuelto|solucionado|funciona(ndo)? bien|todo bien|"
    r"ya (funciona|quedo|sirve|esta|me (funciona|sirve|abre|carga|imprime|sincroniza))|quedo (bien|resuelto|listo)|"
    r"ya no (veo|sale|aparece|hay|me sale)\b[^.]*\b(error|mensaje|problema|aviso))\b"
)
_NO = re.compile(
    r"\b(sigue|todavia (no|falla|sale|aparece)|aun no|no funciona|no sirve|persiste|tampoco|sigo con|"
    r"no (me )?(abre|carga|imprime|sincroniza|quedo|se soluciono|se resolvio|ha (cambiado|funcionado))|"
    r"igual que antes|(el )?mismo (error|problema))\b"
)
MENSAJE_CASO_ESCALADO = (
    "Tu caso ya está con un técnico de N2, que tiene todo lo que revisamos. Si es un problema distinto, "
    "usa «Nuevo caso»."
)
MENSAJE_CASO_CERRADO = (
    "Este caso ya quedó cerrado. Si el problema volvió o es otro distinto, usa «Nuevo caso» y lo reviso."
)
VINCULADO = ("posible_masivo", "masivo_confirmado")


def normalizar_codigo(c: str) -> str:
    return "0x" + c[2:].upper() if c.lower().startswith("0x") else c.upper()


CODIGO_USUARIO = re.compile(r"\b(ERR-SIM-[0-9A-Fa-f]{4}|0x[0-9A-Fa-f]{8})\b", re.IGNORECASE)


def texto_masivo_confirmado(servicio: str, mensaje: str | None, hora: str | None, por_n2: bool = False) -> str:
    """Cita del estado oficial TAL CUAL (plantilla del código, nunca del LLM). Cero pasos individuales."""
    cita = f" Mensaje oficial{f' ({hora})' if hora else ''}: «{mensaje}»" if mensaje else ""
    origen = "Un técnico de N2 confirmó que" if por_n2 else "Revisé el estado oficial de los servicios:"
    return (
        f"{origen} hay un incidente general en {servicio}.{cita} "
        "No es un problema de tu equipo, así que no hace falta que hagas cambios; quedaste suscrito y te aviso "
        "por aquí cuando se resuelva."
    )


def texto_posible_masivo(servicio: str, usuarios: int) -> str:
    return (
        f"Revisé si otros compañeros reportan lo mismo: {usuarios} personas reportaron algo parecido en {servicio} "
        "hace poco, así que puede ser un incidente general. Ya se lo pasé a un técnico de N2 para que lo confirme; "
        "mientras tanto no hace falta que cambies nada en tu equipo. Te aviso por aquí apenas haya novedades."
    )


def sin_cita(texto: str, m: dict[str, Any]) -> str:
    """El historial (que lee el conversacional) NUNCA lleva el mensaje oficial: es texto externo (invariante 4).
    El usuario lo ve completo en el stream y en la tarjeta `data-masivo`."""
    oficial = m.get("mensaje_oficial")
    return texto.replace(f"«{oficial}»", "[citado en la tarjeta]") if oficial else texto


def datos_masivo(m: dict[str, Any]) -> dict[str, Any]:
    """Parte `data-masivo` para la tarjeta de la UI (solo campos ya saneados)."""
    return {
        k: m.get(k)
        for k in ("estado", "incidente_id", "servicio_nombre", "mensaje_oficial", "hora_oficial", "usuarios_similares")
    }


def respuesta_confirmacion(texto: str) -> str:
    """«si» | «no» | «ambigua» para la pregunta «¿ya te funciona?» (sin LLM)."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    no, si = bool(_NO.search(t)), bool(_SI.search(t))
    if no and not si:
        return "no"
    if si and not no:
        return "si"
    if not si and not no and re.match(r"\s*no\b", t):
        return "no"  # «no» a secas
    return "ambigua"


def motivo_escalamiento(estado: EstadoCaso) -> str:
    """Motivo (operacion.escalamientos.motivo) decidido por código a partir del estado."""
    if estado.get("motivo_escalamiento"):
        return estado["motivo_escalamiento"]
    ultima = (estado.get("acciones") or [{}])[-1]
    if ultima.get("estado") == "rechazada_n2":
        return "n2_rechaza"
    if ultima.get("estado") == "fallida" or estado.get("fallo_verificacion"):
        return "solucion_fallida"
    if (estado.get("sintoma") or {}).get("fuera_de_alcance") == "hardware":
        return "fuera_alcance"
    return "sin_hipotesis"


def resumen_diagnostico(d: dict[str, Any]) -> str:
    """Resumen DETERMINISTA del ciclo de hipótesis para el conversacional (sin texto externo)."""
    hs = d.get("hipotesis") or []
    if not hs:
        return ""
    lineas = [
        f"- {h['hipotesis']} ({h['articulo_id']}): {h['estado']}"
        + (f" — {h['justificacion']}" if h.get("justificacion") else "")
        for h in hs
    ]
    return (
        "Hipótesis que el sistema está evaluando (explica en simple qué revisaste y pregunta SOLO lo que el "
        "usuario puede saber para avanzar):\n" + "\n".join(lineas)
    )


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hito(etapa: Etapa, detalle: str) -> dict[str, Any]:
    return {"hora": _ahora(), "etapa": etapa.value, "detalle": detalle}


def _revisar(escribir: Any, linea: LineaRevision) -> None:
    escribir({"tipo": "revisando", "id": linea.id, "estado": linea.estado, "texto": linea.texto})


def construir_grafo(
    agente: AgenteConversacional,
    puerta: PuertaZabbix,
    interprete: Interprete,
    flujo: FlujoAccion,
    *,
    equipo_demo: str = "",
    max_turnos: int = 40,
    masivo_min_equipos: int = 3,
    diagnostico: FlujoDiagnostico | None = None,
    masivos: AgenteMasivos | None = None,
    captura: FlujoCaptura | None = None,
) -> StateGraph:
    def hacia_diagnostico(estado: EstadoCaso) -> str:
        """F3: entra al ciclo de hipótesis si aplica; si no, Decision (acción candidata del intérprete)."""
        if diagnostico is None or not FlujoDiagnostico.aplica(estado):
            return Etapa.DECISION.value
        d = estado.get("diagnostico") or {}
        if (
            not d.get("hipotesis")
            or d.get("siguiente") in ("aclarar", "decision")
            or (estado.get("fallo_verificacion") and d.get("confirmada"))
        ):
            return Etapa.HIPOTESIS.value
        return Etapa.DECISION.value

    # ------------------------------------------------------------------ Recepción + guardia
    async def recepcion(estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.RECEPCION.value})
        texto = estado["ultimo_mensaje_usuario"]
        turnos = estado.get("turnos", 0) + 1
        cambios: dict[str, Any] = {
            "etapa": Etapa.RECEPCION.value,
            "turnos": turnos,
            "mensajes": [{"rol": "usuario", "texto": texto, "hora": _ahora()}],
            "linea_tiempo": [_hito(Etapa.RECEPCION, f"Mensaje del usuario (turno {turnos})")],
        }
        seguridad = dict(estado.get("seguridad") or {"banderas": [], "insistencia": {}})
        if turnos == 1:
            cambios.update(
                canal="web",
                masivo={"estado": "no_evaluado"},
                slots={},
                sintoma={},
                hipotesis=[],
                evidencia=[],
                acciones=[],
                lecturas_hechas=[],
                metricas={"preguntas": 0, "bloqueos": 0},
            )
        with observacion("guardia_entrada", tipo="guardrail", input={"turno": turnos}) as obs:
            g = analizar(texto)
            obs.update(output={"banderas": g.banderas})
        score_traza("injection_risk", g.riesgo_inyeccion)
        if g.banderas:
            insistencia = dict(seguridad.get("insistencia") or {})
            if g.prohibida:
                insistencia[g.prohibida] = insistencia.get(g.prohibida, 0) + 1
            nuevas = [{"bandera": b, "turno": turnos, "hora": _ahora()} for b in g.banderas]
            if g.prohibida and insistencia[g.prohibida] >= 2:
                nuevas.append({"bandera": f"insistencia:{g.prohibida}", "turno": turnos, "hora": _ahora()})
            seguridad = {"banderas": [*seguridad.get("banderas", []), *nuevas], "insistencia": insistencia}
            for b in nuevas:
                evento("seguridad.bandera", metadata={"bandera": b["bandera"], "caso_id": estado["case_id"]})
        cambios["seguridad"] = seguridad
        # Código de error escrito por el usuario (p. ej., tras una captura no concluyente): regex, nunca el LLM.
        if m_cod := CODIGO_USUARIO.search(texto):
            slots = dict(cambios.get("slots") if "slots" in cambios else estado.get("slots") or {})
            if (slots.get("codigo_error") or {}).get("origen") != "captura":  # nunca pisa un código ya anclado
                codigo = normalizar_codigo(m_cod.group(1))
                vistos = {
                    k
                    for c in estado.get("capturas") or []
                    for k in [*(c.get("codigos_ocr") or []), c.get("codigo_modelo")]
                }
                # Escrito por el usuario: solo confirma si una captura del caso lo corrobora (§3.9).
                slots["codigo_error"] = {"valor": codigo, "origen": "usuario", "corroborado": codigo in vistos}
                cambios["slots"] = slots
        cambios["motivo_escalamiento"] = (
            "pide_humano" if g.humano else ("presupuesto_agotado" if turnos > max_turnos else None)
        )
        cambios["guardia"] = {
            "humano": g.humano,
            "prohibida": g.prohibida,
            "identidad": g.identidad,
            "autoridad": "autoridad" in g.banderas,
        }
        return cambios

    def tras_recepcion(estado: EstadoCaso) -> str:
        if estado.get("escalamiento") or estado.get("cierre"):
            return "CasoTerminado"
        guardia = estado.get("guardia") or {}
        if estado["turnos"] > max_turnos or guardia.get("humano"):
            return Etapa.ESCALAR.value  # interrupción global: sin intentar retener al usuario
        if guardia.get("prohibida") or guardia.get("identidad"):
            return Etapa.RESPUESTA_POLITICA.value
        if captura is not None and FlujoCaptura.hay_capturas(estado):
            return Etapa.CAPTURA.value  # Módulo B: primero las capturas del turno (en cuarentena)
        return tras_captura(estado)

    def tras_captura(estado: EstadoCaso) -> str:
        if espera := FlujoAccion.hay_espera(estado):
            return espera  # consentimiento pendiente o aprobación N2: se retoma, nunca se pide de nuevo
        m = estado.get("masivo") or {}
        if masivos is not None and m.get("incidente_id") and m.get("estado") in VINCULADO:
            return Etapa.INFORMAR_MASIVO.value  # ¿N2 confirmó, descartó o resolvió el incidente?
        if estado.get("esperando_confirmacion"):
            return Etapa.CONFIRMACION.value
        return Etapa.INTERPRETACION.value

    async def respuesta_politica(estado: EstadoCaso) -> dict[str, Any]:
        """Respuesta FIJA (sin LLM): idéntica en cada intento; la insistencia no la cambia (§4.4)."""
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.RESPUESTA_POLITICA.value})
        guardia = estado.get("guardia") or {}
        if guardia.get("prohibida"):
            texto = catalogo().acciones[guardia["prohibida"]].plantilla_rechazo or ""
            if guardia.get("autoridad"):
                texto += " " + NOTA_AUTORIDAD
            detalle = f"Acción prohibida rechazada: {guardia['prohibida']}"
        else:
            texto, detalle = MENSAJE_IDENTIDAD, "Derivado al proceso de identidad"
        escribir({"tipo": "texto", "texto": texto})
        prohibida = guardia.get("prohibida") or ""
        insistencia = (estado.get("seguridad") or {}).get("insistencia", {}).get(prohibida, 0)
        return {
            "etapa": Etapa.RESPUESTA_POLITICA.value,
            "respuesta": texto,
            "motivo_escalamiento": "accion_prohibida" if prohibida and insistencia >= 2 else None,
            "mensajes": [{"rol": "sistema", "texto": texto, "hora": _ahora()}],
            "linea_tiempo": [_hito(Etapa.RESPUESTA_POLITICA, detalle)],
        }

    # ------------------------------------------------------------------ Interpretación (LLM, enum)
    async def interpretacion(estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.INTERPRETACION.value})
        usuario = [m["texto"] for m in estado.get("mensajes", []) if m.get("rol") == "usuario"]
        contexto = resumen_para_conversacional(estado.get("slots") or {}, [])
        with observacion("agente_interprete", tipo="agent") as obs:
            r = await interprete.interpretar(usuario, contexto, set(estado.get("acciones_excluidas") or []))
            obs.update(output=r.model_dump())
        previo = dict(estado.get("sintoma") or {})
        sintoma = dict(previo)
        # Un dato ya entendido no se pierde porque el turno actual no lo mencione.
        for campo in ("aplicacion", "tipo_sintoma"):
            valor = getattr(r, campo)
            if valor not in ("desconocida", "desconocido") or not previo.get(campo):
                sintoma[campo] = valor
        for campo in ("que_ve", "desde_cuando"):
            if getattr(r, campo):
                sintoma[campo] = getattr(r, campo)
        sintoma["fuera_de_alcance"] = r.fuera_de_alcance
        sintoma.setdefault("descripcion_usuario", usuario[0][:400] if usuario else "")
        sintoma["origen"] = "usuario"
        app, tipo = sintoma.get("aplicacion"), sintoma.get("tipo_sintoma")
        if app in NOMBRES_APP and tipo in NOMBRES_SINTOMA:
            _revisar(
                escribir,
                LineaRevision("sintoma", "ok", f"Entendí: {NOMBRES_APP[app]} · {NOMBRES_SINTOMA[tipo]}."),
            )
        return {
            "etapa": Etapa.INTERPRETACION.value,
            "sintoma": sintoma,
            "accion_candidata": {"accion": r.accion, "motivo": r.motivo},
            "linea_tiempo": [_hito(Etapa.INTERPRETACION, f"Síntoma: {app} · {tipo}; candidata: {r.accion}")],
        }

    def requiere_chequeo_masivo(estado: EstadoCaso) -> bool:
        """Primera vez, o cuando ya se sabe la app y el tablero no se revisó para ella."""
        m = estado.get("masivo") or {}
        if m.get("estado", "no_evaluado") == "no_evaluado":
            return True
        sintoma = estado.get("sintoma") or {}
        app = sintoma.get("aplicacion")
        if m.get("estado") != "sin_masivo":
            return False
        tablero_pendiente = app in SERVICIO_POR_APP and m.get("app_evaluada") != app and m.get("fuente") == "tablero"
        # El clúster espera a entender app + síntoma (el texto canónico los necesita).
        cluster_pendiente = (
            masivos is not None
            and m.get("cluster") == "pendiente"
            and app in SERVICIO_BD_POR_APP
            and sintoma.get("tipo_sintoma") not in (None, "desconocido")
            and (m.get("app_evaluada"), m.get("tipo_evaluado")) != (app, sintoma.get("tipo_sintoma"))
        )
        return tablero_pendiente or cluster_pendiente

    def tras_interpretacion(estado: EstadoCaso) -> str:
        if not estado.get("contexto_tecnico"):
            return Etapa.CONTEXTO.value
        app = (estado.get("sintoma") or {}).get("aplicacion")
        if estado.get("equipo_zabbix") and lecturas_pendientes(app, estado.get("lecturas_hechas") or []):
            return Etapa.CONTEXTO.value
        if requiere_chequeo_masivo(estado):
            return Etapa.CHEQUEO_MASIVO.value
        return hacia_diagnostico(estado)

    # ------------------------------------------------------------------ Contexto (antes de preguntar)
    async def contexto(estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.CONTEXTO.value})
        caso_id = estado["case_id"]
        slots = dict(estado.get("slots") or {})
        hechas = list(estado.get("lecturas_hechas") or [])
        tecnico = dict(estado.get("contexto_tecnico") or {})
        fallidas = list(tecnico.get("consultas_fallidas") or [])
        evidencia: list[dict[str, Any]] = []
        equipo = estado.get("equipo_zabbix")
        with observacion("agente_contexto", tipo="agent", input={"equipo_id": estado.get("equipo_id")}) as obs:
            if not puerta.disponible:
                _revisar(
                    escribir,
                    LineaRevision("telemetria", "fallo", "La consulta del equipo no está configurada."),
                )
                return {
                    "etapa": Etapa.CONTEXTO.value,
                    "contexto_tecnico": {"consultas_fallidas": ["telemetria"], "hora": _ahora()},
                    "linea_tiempo": [_hito(Etapa.CONTEXTO, "Zabbix (MCP) no configurado")],
                }
            if not tecnico:  # primera vez: equipo + lecturas base
                equipo, explicacion = await resolver_equipo(
                    puerta, [estado.get("equipo_hostname") or "", estado.get("equipo_id") or ""], equipo_demo
                )
                _revisar(escribir, LineaRevision("equipo", "ok" if equipo else "fallo", explicacion))
                if equipo is None:
                    return {
                        "etapa": Etapa.CONTEXTO.value,
                        "contexto_tecnico": {"consultas_fallidas": ["equipo"], "hora": _ahora()},
                        "linea_tiempo": [_hito(Etapa.CONTEXTO, explicacion)],
                    }
                res = await consultar_contexto(puerta, equipo, caso_id)
                slots.update(res.slots)
                fallidas += res.consultas_fallidas
                hechas += ["telemetria_equipo", "version_office", "estado_licencia_office"]
                for linea in res.lineas:
                    _revisar(escribir, linea)
                    evidencia.append({"herramienta": f"zabbix.{linea.id}", "estado": linea.estado, "hora": _ahora()})
            extra = lecturas_pendientes((estado.get("sintoma") or {}).get("aplicacion"), hechas)
            if extra:  # lecturas según el síntoma (OneDrive, cola de impresión)
                res = await consultar_lecturas(puerta, extra, equipo, caso_id)
                slots.update(res.slots)
                fallidas += res.consultas_fallidas
                hechas += extra
                for linea in res.lineas:
                    _revisar(escribir, linea)
                    evidencia.append({"herramienta": f"zabbix.{linea.id}", "estado": linea.estado, "hora": _ahora()})
            obs.update(output={"equipo": equipo, "lecturas": hechas, "fallidas": fallidas})
        return {
            "etapa": Etapa.CONTEXTO.value,
            "equipo_zabbix": equipo,
            "slots": slots,
            "lecturas_hechas": hechas,
            "contexto_tecnico": {
                "equipo": equipo,
                "hora": _ahora(),
                "consultas_fallidas": sorted(set(fallidas)),
            },
            "evidencia": [*(estado.get("evidencia") or []), *evidencia],
            "linea_tiempo": [_hito(Etapa.CONTEXTO, f"Lecturas en {equipo}: {', '.join(hechas)}")],
        }

    def tras_contexto(estado: EstadoCaso) -> str:
        return Etapa.CHEQUEO_MASIVO.value if requiere_chequeo_masivo(estado) else hacia_diagnostico(estado)

    async def chequeo_masivo(estado: EstadoCaso) -> dict[str, Any]:
        # Siempre ANTES de cualquier hipótesis o acción. F2 suma el clúster semántico y el tablero.
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.CHEQUEO_MASIVO.value})
        sintoma = estado.get("sintoma") or {}
        app = sintoma.get("aplicacion")
        previo = estado.get("masivo") or {}
        m: dict[str, Any] = {
            "estado": "sin_masivo",
            "fuente": "ninguna",
            "app_evaluada": app,
            "tipo_evaluado": sintoma.get("tipo_sintoma"),
            "informado_turno": estado.get("turnos"),
            "reporte_id": previo.get("reporte_id"),
        }
        with observacion("agente_masivos", tipo="agent", input={"aplicacion": app}) as obs:
            # 1) Tablero oficial del MCP (fuente autoritativa).
            if puerta.disponible:
                r = await revisar_masivo(puerta, masivo_min_equipos, app)
                _revisar(escribir, r.linea)
                m.update(
                    estado=r.estado,
                    fuente=r.fuente,
                    servicio=r.servicio,
                    servicio_nombre=NOMBRE_SERVICIO.get(r.servicio or ""),
                    equipos_afectados=r.equipos_afectados,
                    mensaje_oficial=r.mensaje_oficial,
                    hora_oficial=r.hora_oficial,
                )
            # 2) Clúster semántico de reportes + incidentes de `operacion` (F2).
            if masivos is not None and m["estado"] != "masivo_confirmado":
                rc = await masivos.evaluar(
                    sintoma, estado["persona_id"], estado.get("equipo_id"), reporte_previo=previo.get("reporte_id")
                )
                if rc.linea:
                    _revisar(escribir, rc.linea)
                m.update(
                    cluster=rc.estado,
                    categoria=rc.categoria,
                    usuarios_similares=rc.usuarios,
                    reporte_id=rc.reporte_id or m["reporte_id"],
                    regla=rc.regla,
                )
                if rc.estado in VINCULADO and rc.incidente:
                    inc = rc.incidente
                    m.update(
                        estado=rc.estado,
                        fuente="incidente" if rc.estado == "masivo_confirmado" else "cluster",
                        incidente_id=inc.id,
                        servicio=inc.servicio_id,
                        servicio_nombre=NOMBRE_SERVICIO_BD.get(inc.servicio_id, inc.servicio_id),
                        mensaje_oficial=mensaje_seguro(inc.mensaje_oficial),
                        hora_oficial=hora_legible(inc.publicado_en),
                    )
                elif m["estado"] not in VINCULADO and rc.estado in ("sin_masivo", "pendiente", "no_aplica"):
                    m["estado"] = "sin_masivo"
            obs.update(output={k: m.get(k) for k in ("estado", "fuente", "incidente_id", "usuarios_similares")})
        cambios: dict[str, Any] = {
            "etapa": Etapa.CHEQUEO_MASIVO.value,
            "masivo": m,
            "linea_tiempo": [
                _hito(
                    Etapa.CHEQUEO_MASIVO,
                    f"Chequeo masivo ({m['fuente']}): {m['estado']}"
                    + (f" · {m['incidente_id']}" if m.get("incidente_id") else ""),
                )
            ],
        }
        servicio = m.get("servicio_nombre") or "el servicio"
        texto = None
        if m["estado"] == "masivo_confirmado":
            texto = texto_masivo_confirmado(servicio, m.get("mensaje_oficial"), m.get("hora_oficial"))
            evento(
                "masivo.confirmado", metadata={"incidente": m.get("incidente_id") or "", "caso_id": estado["case_id"]}
            )
            score_traza("masivo_vinculado", 1)
        elif m["estado"] == "posible_masivo":
            texto = texto_posible_masivo(servicio, m.get("usuarios_similares") or m.get("equipos_afectados") or 0)
            evento(
                "masivo.propuesto", metadata={"incidente": m.get("incidente_id") or "", "caso_id": estado["case_id"]}
            )
        if texto:
            escribir({"tipo": "texto", "texto": texto})
            escribir({"tipo": "masivo", "datos": datos_masivo(m)})
            cambios["mensajes"] = [{"rol": "sistema", "texto": sin_cita(texto, m), "hora": _ahora()}]
            cambios["respuesta"] = texto
        return cambios

    # ------------------------------------------------------------------ F2: seguimiento del incidente vinculado
    async def informar_masivo(estado: EstadoCaso) -> dict[str, Any]:
        """Lee el incidente vinculado: N2 lo confirmó, lo descartó o se resolvió. Decide EN CÓDIGO."""
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.INFORMAR_MASIVO.value})
        m = dict(estado.get("masivo") or {})
        try:
            inc = await masivos.repo.incidente(m["incidente_id"])  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - sin BD se sigue la conversación normal
            inc = None
        m["siguiente"] = "interpretacion"
        cambios: dict[str, Any] = {"etapa": Etapa.INFORMAR_MASIVO.value}
        servicio = m.get("servicio_nombre") or "el servicio"
        texto = None
        if inc is None:
            pass
        elif inc.estado == "publicado" and m.get("estado") == "posible_masivo":
            m.update(
                estado="masivo_confirmado",
                fuente="n2",
                mensaje_oficial=mensaje_seguro(inc.mensaje_oficial),
                hora_oficial=hora_legible(inc.publicado_en),
                siguiente="fin",
            )
            texto = texto_masivo_confirmado(servicio, m["mensaje_oficial"], m["hora_oficial"], por_n2=True)
            evento("masivo.confirmado", metadata={"incidente": inc.id, "caso_id": estado["case_id"], "por": "n2"})
            score_traza("masivo_vinculado", 1)
        elif inc.estado == "descartado":
            m.update(estado="descartado_n2")
            _revisar(
                escribir,
                LineaRevision("cluster", "ok", "N2 revisó los reportes: no es un incidente general. Reviso tu equipo."),
            )
        elif inc.estado == "resuelto":
            r = respuesta_confirmacion(estado["ultimo_mensaje_usuario"])
            if r == "si":
                m.update(estado="masivo_resuelto", siguiente="cierre")
            elif r == "no":
                m.update(estado="resuelto_persiste")
                _revisar(
                    escribir,
                    LineaRevision(
                        "cluster", "anomalia", "El incidente general se resolvió, pero a ti te sigue fallando."
                    ),
                )
            else:
                m.update(siguiente="fin", resolucion_preguntada=True)
                texto = f"El incidente general de {servicio} ya se resolvió. ¿Ya te funciona?"
        if texto:
            m["informado_turno"] = estado.get("turnos")
            escribir({"tipo": "texto", "texto": texto})
            cambios.update(
                respuesta=texto, mensajes=[{"rol": "sistema", "texto": sin_cita(texto, m), "hora": _ahora()}]
            )
            # Tarjeta solo cuando hay novedad que informar (no se repite en cada turno).
            escribir({"tipo": "masivo", "datos": {**datos_masivo(m), "incidente_estado": inc.estado if inc else None}})
        cambios["masivo"] = m
        cambios["linea_tiempo"] = [
            _hito(
                Etapa.INFORMAR_MASIVO,
                f"Incidente {m.get('incidente_id')}: {inc.estado if inc else '?'} → {m['estado']}",
            )
        ]
        return cambios

    def tras_informar_masivo(estado: EstadoCaso) -> str:
        siguiente = (estado.get("masivo") or {}).get("siguiente")
        if siguiente == "cierre":
            return Etapa.CIERRE.value
        return "fin" if siguiente == "fin" else Etapa.INTERPRETACION.value

    # ------------------------------------------------------------------ Aclaración (con compuerta)
    async def aclaracion(estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.ACLARACION.value})
        masivo = estado.get("masivo") or {}
        ya_informado = masivo.get("informado_turno") == estado.get("turnos")
        if masivo.get("estado") in VINCULADO and ya_informado:
            # Este turno ya informó el masivo (plantilla del código): no se agrega otra respuesta del LLM.
            return {"etapa": Etapa.ACLARACION.value}
        slots = estado.get("slots") or {}
        filtro = FiltroPreguntas(disponibles_desde_slots(slots))
        partes: list[str] = []

        def emitir(frases: list[str]) -> None:
            for f in frases:
                partes.append(f)
                escribir({"tipo": "texto_delta", "delta": f})

        with observacion(
            "agente_conversacional", tipo="agent", input={"ultimo_mensaje": estado["ultimo_mensaje_usuario"]}
        ) as obs:
            contexto_txt = resumen_para_conversacional(
                slots,
                (estado.get("contexto_tecnico") or {}).get("consultas_fallidas", []),
                estado.get("sintoma"),
            )
            if nivel := NIVEL_TECNICO.get((estado.get("perfil_usuario") or {}).get("nivel_tecnico") or ""):
                contexto_txt += "\n\n" + nivel
            if resumen_diag := resumen_diagnostico(estado.get("diagnostico") or {}):
                contexto_txt += "\n\n" + resumen_diag
            if (estado.get("sintoma") or {}).get("fuera_de_alcance") == "hardware":
                contexto_txt += (
                    "\n\nParece un daño físico (hardware): explica con amabilidad que eso lo atiende "
                    "un técnico de N2 en sitio y que no se resuelve por chat."
                )
            if masivo.get("estado") == "masivo_confirmado":
                contexto_txt += (
                    "\n\nYa le informaste un incidente general CONFIRMADO por el tablero oficial: "
                    "no des pasos individuales; responde breve y dile que le avisaremos al resolverse."
                )
            if masivo.get("estado") == "posible_masivo":
                contexto_txt += (
                    "\n\nHay señales de un posible incidente general: di que estamos revisando si otros "
                    "compañeros tienen el mismo problema; no des pasos individuales."
                )
            try:
                async for delta in agente.responder(estado.get("mensajes", []), contexto=contexto_txt):
                    emitir(filtro.alimentar(delta))
                emitir(filtro.cerrar())
            except SinModeloDisponible as err:
                evento("llm.sin_modelo", metadata={"agente": "conversacional", "error": str(err)[:200]})
                if not partes:
                    emitir([MENSAJE_SIN_MODELO])
            if not "".join(partes).strip():
                # Todo lo que dijo era preguntar lo consultable. Si el síntoma ya se entendió, NO se vuelve a preguntar
                # por el problema (parecería que el sistema lo olvidó).
                ya_entendido = (estado.get("sintoma") or {}).get("aplicacion") not in (None, "desconocida")
                emitir([MENSAJE_SIGO_REVISANDO if ya_entendido else MENSAJE_SOLO_CONSULTABLE])
            texto = "".join(partes)
            obs.update(output=texto, metadata={"bloqueadas": ",".join(filtro.bloqueadas)})
        metricas = dict(estado.get("metricas") or {"preguntas": 0, "bloqueos": 0})
        metricas["preguntas"] = metricas.get("preguntas", 0) + filtro.preguntas
        metricas["bloqueos"] = metricas.get("bloqueos", 0) + len(filtro.bloqueadas)
        if filtro.meta_descartadas:
            evento(
                "llm.fuga_razonamiento", metadata={"frases": str(filtro.meta_descartadas), "caso_id": estado["case_id"]}
            )
        if filtro.bloqueadas:
            evento(
                "compuerta.bloqueo",
                metadata={"slots": ",".join(filtro.bloqueadas), "caso_id": estado["case_id"]},
            )
        score_traza("preguntas_hechas", metricas["preguntas"])
        score_traza("pregunto_consultable", 0)  # garantizado por la compuerta; los intentos van en `bloqueos`
        return {
            "etapa": Etapa.ACLARACION.value,
            "respuesta": texto,
            "metricas": metricas,
            "mensajes": [{"rol": "sistema", "texto": texto, "hora": _ahora()}],
            "linea_tiempo": [_hito(Etapa.ACLARACION, f"Respuesta del conversacional ({filtro.preguntas} pregunta(s))")],
        }

    def tras_respuesta_politica(estado: EstadoCaso) -> str:
        return Etapa.ESCALAR.value if estado.get("motivo_escalamiento") == "accion_prohibida" else "fin"

    # ------------------------------------------------------------------ F5: confirmación y cierre
    async def confirmacion(estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.CONFIRMACION.value})
        r = respuesta_confirmacion(estado["ultimo_mensaje_usuario"])
        espera = estado.get("esperando_confirmacion") or {}
        if r == "si":
            return {
                "etapa": Etapa.CONFIRMACION.value,
                "esperando_confirmacion": None,
                "linea_tiempo": [_hito(Etapa.CONFIRMACION, f"El usuario confirma que funciona ({espera.get('tool')})")],
            }
        if r == "no":
            return {
                "etapa": Etapa.CONFIRMACION.value,
                "esperando_confirmacion": None,
                "fallo_verificacion": True,
                "linea_tiempo": [
                    _hito(Etapa.CONFIRMACION, f"El usuario dice que sigue fallando ({espera.get('tool')})")
                ],
            }
        return {"etapa": Etapa.CONFIRMACION.value}  # ambigua: se interpreta normalmente y se sigue esperando

    def tras_confirmacion(estado: EstadoCaso) -> str:
        if not estado.get("esperando_confirmacion") and not estado.get("fallo_verificacion"):
            return Etapa.CIERRE.value
        return Etapa.INTERPRETACION.value

    async def cierre(estado: EstadoCaso) -> dict[str, Any]:
        """Cierre solo con verificación técnica (si existe) + confirmación del usuario (R5)."""
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.CIERRE.value})
        with observacion("agente_documentacion", tipo="agent", input={"tipo": "cierre"}) as obs:
            registro = registro_cierre(dict(estado))
            obs.update(output=registro)
        texto = (
            "¡Qué bueno! Cierro tu caso como resuelto y dejo el registro de lo que hicimos. "
            "Si vuelve a pasar, abre un «Nuevo caso»."
        )
        escribir({"tipo": "texto", "texto": texto})
        escribir(
            {
                "tipo": "cierre",
                "datos": {
                    "resultado": "resuelto",
                    "solucion": (registro.get("solucion") or {}).get("accion"),
                },
            }
        )
        score_traza("fcr", 1)
        return {
            "etapa": Etapa.CIERRE.value,
            "cierre": registro,
            "respuesta": texto,
            "mensajes": [{"rol": "sistema", "texto": texto, "hora": _ahora()}],
            "linea_tiempo": [_hito(Etapa.CIERRE, "Caso cerrado: resuelto y confirmado por el usuario")],
        }

    # ------------------------------------------------------------------ F6: escalamiento
    async def escalar(estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.ESCALAR.value})
        motivo = motivo_escalamiento(estado)
        with observacion("agente_documentacion", tipo="agent", input={"tipo": "escalamiento", "motivo": motivo}) as obs:
            ficha = ficha_n2(dict(estado), motivo)
            obs.update(output={"motivo": motivo, "acciones": len(ficha["acciones"])})
        texto = mensaje_escalamiento(ficha)
        escribir({"tipo": "texto", "texto": texto})
        escribir(
            {
                "tipo": "escalamiento",
                "datos": {
                    "motivo": ficha["motivo_texto"],
                    "prioridad": ficha["ans"]["prioridad"],
                    "plazo": ficha["ans"]["plazo"],
                    "vence_en": ficha["ans"].get("vence_en"),
                    "siguiente_paso": ficha["siguiente_paso"],
                    "acciones": [a["accion"] for a in ficha["acciones"]],
                },
            }
        )
        evento("escalamiento.creado", metadata={"motivo": motivo, "caso_id": estado["case_id"]})
        score_traza("fcr", 0)
        return {
            "etapa": Etapa.ESCALAR.value,
            "escalamiento": ficha,
            "respuesta": texto,
            "esperando_confirmacion": None,
            "mensajes": [{"rol": "sistema", "texto": texto, "hora": _ahora()}],
            "linea_tiempo": [_hito(Etapa.ESCALAR, f"Escalado a N2: {motivo}")],
        }

    async def caso_terminado(estado: EstadoCaso) -> dict[str, Any]:
        texto = MENSAJE_CASO_ESCALADO if estado.get("escalamiento") else MENSAJE_CASO_CERRADO
        get_stream_writer()({"tipo": "texto", "texto": texto})
        return {"respuesta": texto, "mensajes": [{"rol": "sistema", "texto": texto, "hora": _ahora()}]}

    # Escalar cuando el flujo de acción termina sin salida (N2 rechaza, la acción falla, verificación negativa).
    def tras_decision(estado: EstadoCaso) -> str:
        destino = flujo.tras_decision(estado)
        if destino == Etapa.ACLARACION.value and (
            estado.get("fallo_verificacion") or (estado.get("sintoma") or {}).get("fuera_de_alcance") == "hardware"
        ):
            return Etapa.ESCALAR.value
        return destino

    def _fin_o_escalar(destino: str, estado: EstadoCaso) -> str:
        if destino != "fin":
            return destino
        ultima = (estado.get("acciones") or [{}])[-1]
        return Etapa.ESCALAR.value if ultima.get("estado") in ("rechazada_n2", "fallida") else "fin"

    def tras_aprobacion(estado: EstadoCaso) -> str:
        return _fin_o_escalar(flujo.tras_aprobacion(estado), estado)

    def tras_ejecucion(estado: EstadoCaso) -> str:
        return _fin_o_escalar(flujo.tras_ejecucion(estado), estado)

    # ------------------------------------------------------------------ cableado
    g = StateGraph(EstadoCaso)
    for nombre, nodo in [
        (Etapa.RECEPCION.value, recepcion),
        (Etapa.RESPUESTA_POLITICA.value, respuesta_politica),
        (Etapa.INTERPRETACION.value, interpretacion),
        (Etapa.CONTEXTO.value, contexto),
        (Etapa.CHEQUEO_MASIVO.value, chequeo_masivo),
        (Etapa.INFORMAR_MASIVO.value, informar_masivo),
        (Etapa.DECISION.value, flujo.decision),
        (Etapa.ACLARACION.value, aclaracion),
        (Etapa.APROBACION_N2.value, flujo.aprobacion_n2),
        (Etapa.CONSENTIMIENTO.value, flujo.consentimiento),
        (Etapa.EJECUCION.value, flujo.ejecucion),
        (Etapa.VERIFICACION.value, flujo.verificacion),
        (Etapa.CONFIRMACION.value, confirmacion),
        (Etapa.CIERRE.value, cierre),
        (Etapa.ESCALAR.value, escalar),
        ("CasoTerminado", caso_terminado),
    ]:
        g.add_node(nombre, nodo)
    destinos_diag = [Etapa.DECISION.value]
    if diagnostico is not None:
        g.add_node(Etapa.HIPOTESIS.value, diagnostico.hipotesis)
        g.add_node(Etapa.GUIA.value, diagnostico.guia)
        destinos_diag.append(Etapa.HIPOTESIS.value)
        g.add_conditional_edges(
            Etapa.HIPOTESIS.value,
            diagnostico.tras_hipotesis,
            [
                Etapa.DECISION.value,
                Etapa.GUIA.value,
                Etapa.ESCALAR.value,
                Etapa.CONSENTIMIENTO.value,
                Etapa.ACLARACION.value,
            ],
        )
        g.add_conditional_edges(
            Etapa.GUIA.value, diagnostico.tras_guia, {Etapa.ESCALAR.value: Etapa.ESCALAR.value, "fin": END}
        )
    destinos_resto = [
        Etapa.APROBACION_N2.value,
        Etapa.CONSENTIMIENTO.value,
        Etapa.INFORMAR_MASIVO.value,
        Etapa.CONFIRMACION.value,
        Etapa.INTERPRETACION.value,
    ]
    g.add_edge(START, Etapa.RECEPCION.value)
    g.add_conditional_edges(
        Etapa.RECEPCION.value,
        tras_recepcion,
        [
            "CasoTerminado",
            Etapa.ESCALAR.value,
            Etapa.RESPUESTA_POLITICA.value,
            *destinos_resto,
            *([Etapa.CAPTURA.value] if captura is not None else []),
        ],
    )
    if captura is not None:
        g.add_node(Etapa.CAPTURA.value, captura.captura)
        g.add_conditional_edges(Etapa.CAPTURA.value, tras_captura, destinos_resto)
    g.add_conditional_edges(
        Etapa.INFORMAR_MASIVO.value,
        tras_informar_masivo,
        {Etapa.CIERRE.value: Etapa.CIERRE.value, Etapa.INTERPRETACION.value: Etapa.INTERPRETACION.value, "fin": END},
    )
    g.add_conditional_edges(
        Etapa.RESPUESTA_POLITICA.value,
        tras_respuesta_politica,
        {Etapa.ESCALAR.value: Etapa.ESCALAR.value, "fin": END},
    )
    g.add_conditional_edges(
        Etapa.CONFIRMACION.value, tras_confirmacion, [Etapa.CIERRE.value, Etapa.INTERPRETACION.value]
    )
    g.add_conditional_edges(
        Etapa.INTERPRETACION.value,
        tras_interpretacion,
        [Etapa.CONTEXTO.value, Etapa.CHEQUEO_MASIVO.value, *destinos_diag],
    )
    g.add_conditional_edges(Etapa.CONTEXTO.value, tras_contexto, [Etapa.CHEQUEO_MASIVO.value, *destinos_diag])
    g.add_conditional_edges(Etapa.CHEQUEO_MASIVO.value, hacia_diagnostico, destinos_diag)
    g.add_conditional_edges(
        Etapa.DECISION.value,
        tras_decision,
        [
            Etapa.ACLARACION.value,
            Etapa.APROBACION_N2.value,
            Etapa.CONSENTIMIENTO.value,
            Etapa.ESCALAR.value,
        ],
    )
    g.add_conditional_edges(
        Etapa.APROBACION_N2.value,
        tras_aprobacion,
        {
            Etapa.CONSENTIMIENTO.value: Etapa.CONSENTIMIENTO.value,
            Etapa.ESCALAR.value: Etapa.ESCALAR.value,
            "fin": END,
        },
    )
    g.add_conditional_edges(
        Etapa.CONSENTIMIENTO.value,
        flujo.tras_consentimiento,
        {Etapa.EJECUCION.value: Etapa.EJECUCION.value, "fin": END},
    )
    g.add_conditional_edges(
        Etapa.EJECUCION.value,
        tras_ejecucion,
        {
            Etapa.HIPOTESIS.value: Etapa.HIPOTESIS.value,
            Etapa.VERIFICACION.value: Etapa.VERIFICACION.value,
            Etapa.ESCALAR.value: Etapa.ESCALAR.value,
            "fin": END,
        },
    )
    for terminal in (Etapa.VERIFICACION, Etapa.ACLARACION, Etapa.CIERRE, Etapa.ESCALAR):
        g.add_edge(terminal.value, END)
    g.add_edge("CasoTerminado", END)
    return g

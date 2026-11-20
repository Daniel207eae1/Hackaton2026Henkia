"""Agente de Contexto y Masivos (§3.3) — parte determinista sobre el MCP de Zabbix.

Consulta ANTES de preguntar: resuelve el equipo, lee telemetría, versión de Office y licencia
(solo lectura, política automática) y revisa problemas activos para detectar masivos.

Los resultados de las tools son DATOS: aquí se extraen solo campos de una lista blanca, con tipos
y longitudes acotadas. El texto libre (nombres de problemas, logs) nunca llega a un LLM.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from app.integraciones.zabbix.puerta import PuertaZabbix, ResultadoTool

UMBRAL_DISCO_GB = 5.0  # supuesto del prototipo (LEEME §14)
SEVERIDAD_MIN_MASIVO = 2  # desde "advertencia"

LICENCIA_OK = {"instalado", "activado", "activa", "licenciado", "licensed"}
_SEGURO = re.compile(r"[^\w .,:()/+-]", re.UNICODE)


def _texto(valor: Any, largo: int = 60) -> str | None:
    if valor is None:
        return None
    return _SEGURO.sub("", str(valor))[:largo].strip() or None


def _numero(valor: Any) -> float | None:
    try:
        return round(float(valor), 1)
    except (TypeError, ValueError):
        return None


@dataclass
class LineaRevision:
    id: str
    estado: str  # ok | anomalia | fallo | pendiente
    texto: str


@dataclass
class ResultadoContexto:
    equipo: str | None
    slots: dict[str, dict[str, Any]] = field(default_factory=dict)
    lineas: list[LineaRevision] = field(default_factory=list)
    consultas_fallidas: list[str] = field(default_factory=list)


def _slot(valor: Any) -> dict[str, Any]:
    return {"valor": valor, "origen": "telemetria"}


async def resolver_equipo(puerta: PuertaZabbix, candidatos: list[str], equipo_demo: str) -> tuple[str | None, str]:
    """Devuelve (equipo técnico, explicación). El equipo sale del directorio, nunca del chat."""
    r = await puerta.listar_equipos()
    if not r.ok:
        return None, f"No pude consultar la lista de equipos en Zabbix ({r.motivo})."
    nombres = {str(e.get("equipo")) for e in r.datos.get("equipos", []) if isinstance(e, dict)}
    for c in candidatos:
        if c and c in nombres:
            return c, f"Equipo {c} encontrado en Zabbix."
    if equipo_demo and equipo_demo in nombres:
        return equipo_demo, f"Uso el equipo de laboratorio {equipo_demo} (asignado para la demo)."
    return None, "No encontré tu equipo en Zabbix."


async def consultar_contexto(puerta: PuertaZabbix, equipo: str, caso_id: str) -> ResultadoContexto:
    res = ResultadoContexto(equipo=equipo)
    tel, ver, lic = await asyncio.gather(
        puerta.leer("telemetria_equipo", equipo, caso_id),
        puerta.leer("version_office", equipo, caso_id),
        puerta.leer("estado_licencia_office", equipo, caso_id),
    )
    _telemetria(res, tel)
    _version(res, ver)
    _licencia(res, lic)
    return res


def _fallo(res: ResultadoContexto, id_: str, que: str, r: ResultadoTool) -> None:
    res.consultas_fallidas.append(id_)
    res.lineas.append(LineaRevision(id_, "fallo", f"No pude consultar {que}; seguiré con lo demás."))


def _telemetria(res: ResultadoContexto, r: ResultadoTool) -> None:
    if not r.ok or not isinstance(r.datos.get("resultado"), dict):
        return _fallo(res, "telemetria", "la telemetría del equipo", r)
    d = r.datos["resultado"]
    so, build = _texto(d.get("so")), _texto(d.get("build"), 20)
    libre, usado, ram = (
        _numero(d.get("discoLibreGB")),
        _numero(d.get("discoUsadoGB")),
        _numero(d.get("ramLibreMB")),
    )
    res.slots.update(
        so=_slot(so),
        build=_slot(build),
        disco_libre_gb=_slot(libre),
        disco_usado_gb=_slot(usado),
        ram_libre_mb=_slot(ram),
    )
    anomalo = libre is not None and libre < UMBRAL_DISCO_GB
    texto = f"Revisé tu equipo: {so or 'SO desconocido'}"
    if libre is not None:
        texto += f", {libre} GB libres en disco" + (" (casi lleno)" if anomalo else "")
    res.lineas.append(LineaRevision("telemetria", "anomalia" if anomalo else "ok", texto + "."))


def _version(res: ResultadoContexto, r: ResultadoTool) -> None:
    valor = r.datos.get("resultado")
    if not r.ok or valor is None:
        return _fallo(res, "office", "la versión de Office", r)
    version = _texto(valor, 30)
    res.slots["version_office"] = _slot(version)
    res.lineas.append(LineaRevision("office", "ok", f"Office instalado: versión {version}."))


def _licencia(res: ResultadoContexto, r: ResultadoTool) -> None:
    if not r.ok or not isinstance(r.datos.get("resultado"), dict):
        return _fallo(res, "licencia", "el estado de la licencia de Office", r)
    d = r.datos["resultado"]
    producto, estado = _texto(d.get("producto"), 40), _texto(d.get("estado"), 30)
    res.slots.update(licencia_producto=_slot(producto), licencia_estado=_slot(estado))
    ok = (estado or "").lower() in LICENCIA_OK
    res.lineas.append(
        LineaRevision("licencia", "ok" if ok else "anomalia", f"Licencia de Office ({producto}): {estado}.")
    )


@dataclass
class ResultadoMasivo:
    estado: str  # sin_masivo | posible_masivo | masivo_confirmado | no_evaluado
    linea: LineaRevision
    equipos_afectados: int = 0
    servicio: str | None = None
    mensaje_oficial: str | None = None  # texto del tablero, ya revisado por la guardia; solo se CITA
    hora_oficial: str | None = None
    fuente: str = "tablero"


# Servicio del tablero que explica el síntoma de cada aplicación (§3.12).
SERVICIO_POR_APP = {"outlook": "correo", "teams": "teams", "onedrive": "almacenamiento"}
NOMBRE_SERVICIO = {"correo": "correo", "teams": "Teams", "almacenamiento": "almacenamiento en la nube"}
ESTADOS_OPERATIVOS = {"operativo", "ok", "normal", "sin incidentes"}


async def revisar_masivo(puerta: PuertaZabbix, min_equipos: int = 3, aplicacion: str | None = None) -> ResultadoMasivo:
    """Primero el tablero oficial (`estado_servicio`); si no responde, `problemas_activos` (respaldo).

    - Servicio degradado y relacionado con la app del síntoma → `masivo_confirmado` (el tablero es la
      fuente autoritativa): se cita su mensaje tal cual, sin pasos individuales.
    - Degradado pero no relacionado (o app aún desconocida) → se informa, sin bloquear el diagnóstico.
    F2 suma el clúster semántico de reportes (posible masivo sin tablero → propuesta a N2).
    El mensaje del tablero es texto externo: pasa por la guardia y NUNCA va a un LLM.
    """
    from app.seguridad.guardia_entrada import analizar  # import local: evita ciclo en la carga

    t = await puerta.estado_servicio()
    if t.ok and isinstance(t.datos.get("tablero"), dict):
        hora = _texto(t.datos.get("consultado"), 25)
        degradados = {
            str(k): v
            for k, v in t.datos["tablero"].items()
            if isinstance(v, dict) and str(v.get("estado", "")).lower() not in ESTADOS_OPERATIVOS
        }
        servicio = SERVICIO_POR_APP.get(aplicacion or "")
        if servicio and servicio in degradados:
            crudo = str(degradados[servicio].get("mensaje") or "")[:400]
            mensaje = None if analizar(crudo).banderas else _CONTROL_TABLERO.sub("", crudo).strip() or None
            estado_srv = _texto(degradados[servicio].get("estado"), 30)
            return ResultadoMasivo(
                "masivo_confirmado",
                LineaRevision(
                    "masivo",
                    "anomalia",
                    f"El tablero oficial reporta {estado_srv} en el servicio de {NOMBRE_SERVICIO[servicio]}.",
                ),
                servicio=servicio,
                mensaje_oficial=mensaje,
                hora_oficial=hora,
            )
        if degradados:
            nombres = ", ".join(NOMBRE_SERVICIO.get(s, _texto(s, 20) or "?") for s in sorted(degradados))
            return ResultadoMasivo(
                "sin_masivo",
                LineaRevision(
                    "masivo",
                    "anomalia",
                    f"El tablero reporta novedades en: {nombres}; no parece relacionado con tu caso.",
                ),
            )
        return ResultadoMasivo(
            "sin_masivo",
            LineaRevision("masivo", "ok", "El tablero de servicios no reporta incidentes generales."),
        )
    return await _revisar_masivo_por_problemas(puerta, min_equipos)


_CONTROL_TABLERO = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁠-⁤]")


async def _revisar_masivo_por_problemas(puerta: PuertaZabbix, min_equipos: int) -> ResultadoMasivo:
    """Respaldo: `repetidos` = mismo problema en varios equipos → posible masivo.
    Los nombres de problemas no se pasan a ningún LLM."""
    if "problemas_activos" not in TOOLS_RESPALDO:
        return _no_evaluado()
    try:
        r = await puerta.problemas_activos()
    except Exception:  # noqa: BLE001 - tool retirada del servidor o denegada
        return _no_evaluado()
    if not r.ok:
        return _no_evaluado()
    repetidos = r.datos.get("repetidos") or {}
    # Severidad conocida por nombre (Zabbix: 0 sin clasificar, 1 informativa, 2 advertencia, …).
    severidad = {
        str(p.get("nombre")): _numero(p.get("severidad")) for p in r.datos.get("problemas") or [] if isinstance(p, dict)
    }
    conteos = []
    if isinstance(repetidos, dict):
        for nombre, v in repetidos.items():
            sev = severidad.get(str(nombre))
            if sev is not None and sev < SEVERIDAD_MIN_MASIVO:
                continue  # avisos informativos no son un incidente general
            conteos.append(len(v) if isinstance(v, list) else int(_numero(v) or 0))
    n = max(conteos, default=0)
    if n >= min_equipos:
        return ResultadoMasivo(
            "posible_masivo",
            LineaRevision(
                "masivo",
                "anomalia",
                f"Hay un problema que se repite en {n} equipos: puede ser un incidente general.",
            ),
            n,
            fuente="problemas_activos",
        )
    return ResultadoMasivo(
        "sin_masivo",
        LineaRevision("masivo", "ok", "No veo fallas generales en otros equipos."),
        fuente="problemas_activos",
    )


TOOLS_RESPALDO = {"problemas_activos"}


def _no_evaluado() -> ResultadoMasivo:
    return ResultadoMasivo(
        "no_evaluado",
        LineaRevision("masivo", "fallo", "No pude revisar si hay un incidente general; sigo con tu equipo."),
        fuente="ninguna",
    )


# ------------------------------------------------------------ lecturas según el síntoma (F1)
# Lectura de solo lectura que aclara el síntoma de cada aplicación (se hace ANTES de preguntar).
LECTURAS_POR_APP: dict[str, str] = {
    "onedrive": "estado_onedrive",
    "impresora": "estado_cola_impresion",
    "teams": "estado_teams",
    "outlook": "estado_perfil_outlook",
}


def lecturas_pendientes(aplicacion: str | None, ya_leidas: list[str]) -> list[str]:
    tool = LECTURAS_POR_APP.get(aplicacion or "")
    return [tool] if tool and tool not in ya_leidas else []


async def consultar_lecturas(puerta: PuertaZabbix, tools: list[str], equipo: str, caso_id: str) -> ResultadoContexto:
    res = ResultadoContexto(equipo=equipo)
    resultados = await asyncio.gather(*(puerta.leer(t, equipo, caso_id) for t in tools))
    for tool, r in zip(tools, resultados, strict=True):
        {
            "estado_onedrive": _onedrive,
            "estado_cola_impresion": _cola,
            "estado_teams": _teams,
            "estado_perfil_outlook": _perfil_outlook,
        }[tool](res, r)
    return res


ESTADOS_PERFIL = {
    "ok": "El perfil de Outlook está bien configurado.",
    "sin-perfil": "No hay un perfil de Outlook configurado en tu equipo.",
    "predeterminado-inexistente": "El perfil predeterminado de Outlook no existe.",
    "sin-predeterminado": "Outlook no tiene un perfil predeterminado.",
    "sin-cuentas": "El perfil de Outlook no tiene cuentas configuradas.",
}


def _perfil_outlook(res: ResultadoContexto, r: ResultadoTool) -> None:
    d = r.datos.get("resultado")
    if not r.ok or not isinstance(d, dict):
        return _fallo(res, "perfil_outlook", "el perfil de Outlook", r)
    # Nunca nombres de perfiles, cuentas ni el usuario: solo el estado y conteos.
    estado = _texto(d.get("estado"), 40) or "desconocido"
    ost = d.get("ost") if isinstance(d.get("ost"), dict) else {}
    res.slots.update(
        perfil_outlook_estado=_slot(estado),
        perfil_outlook_predeterminado=_slot(bool(d.get("perfilPredeterminadoExiste"))),
        outlook_ost_archivos=_slot(int(_numero(ost.get("cantidad")) or 0)),
    )
    texto = ESTADOS_PERFIL.get(estado, f"Estado del perfil de Outlook: {estado}.")
    res.lineas.append(LineaRevision("perfil_outlook", "ok" if estado == "ok" else "anomalia", texto))


_CLAVES_TEAMS = re.compile(r"version|cache|audio|dispositivo", re.IGNORECASE)


def _teams(res: ResultadoContexto, r: ResultadoTool) -> None:
    d = r.datos.get("resultado")
    if not r.ok or not isinstance(d, dict):
        return _fallo(res, "teams", "el estado de Teams", r)
    # Forma no documentada: se toman solo escalares cuyo nombre indique versión, caché o audio.
    for k, v in d.items():
        if _CLAVES_TEAMS.search(k):
            if isinstance(v, bool | int | float):
                res.slots[f"teams_{k}"] = _slot(v)
            elif isinstance(v, str):
                res.slots[f"teams_{k}"] = _slot(_texto(v, 40))
            elif isinstance(v, list):
                res.slots[f"teams_{k}_cantidad"] = _slot(len(v))
    res.lineas.append(LineaRevision("teams", "ok", "Revisé el estado de Teams en tu equipo (versión, caché y audio)."))


def _onedrive(res: ResultadoContexto, r: ResultadoTool) -> None:
    d = r.datos.get("resultado")
    if not r.ok or not isinstance(d, dict):
        return _fallo(res, "onedrive", "el estado de OneDrive", r)
    # Solo se guardan campos no personales: nunca la carpeta (ruta con el usuario) ni la cuenta.
    corriendo = bool(d.get("enEjecucion"))
    cuentas = len(d.get("cuentas") or []) if isinstance(d.get("cuentas"), list) else None
    res.slots.update(onedrive_en_ejecucion=_slot(corriendo), onedrive_cuentas=_slot(cuentas))
    res.lineas.append(
        LineaRevision(
            "onedrive",
            "ok" if corriendo else "anomalia",
            "OneDrive está en ejecución en tu equipo." if corriendo else "OneDrive no está en ejecución en tu equipo.",
        )
    )


def _cola(res: ResultadoContexto, r: ResultadoTool) -> None:
    d = r.datos.get("resultado")
    if not r.ok or not isinstance(d, dict):
        return _fallo(res, "cola", "la cola de impresión", r)
    n = int(_numero(d.get("trabajosEnCola")) or 0)
    res.slots["cola_trabajos"] = _slot(n)
    res.lineas.append(
        LineaRevision(
            "cola",
            "anomalia" if n > 0 else "ok",
            f"Hay {n} trabajo(s) esperando en la cola de impresión." if n > 0 else "La cola de impresión está vacía.",
        )
    )


ETIQUETAS_SLOTS = {
    "so": "Sistema operativo",
    "build": "Build",
    "disco_libre_gb": "Disco libre (GB)",
    "ram_libre_mb": "RAM libre (MB)",
    "version_office": "Versión de Office",
    "licencia_producto": "Producto de Office",
    "licencia_estado": "Estado de la licencia",
    "onedrive_en_ejecucion": "OneDrive en ejecución",
    "cola_trabajos": "Trabajos en la cola de impresión",
    "perfil_outlook_estado": "Estado del perfil de Outlook",
    "codigo_error": "Código de error (validado de la captura o escrito por el usuario)",
}
ETIQUETAS_SINTOMA = {
    "descripcion_usuario": "Problema que reportó al inicio (sus palabras)",
    "aplicacion": "Aplicación",
    "tipo_sintoma": "Tipo de síntoma",
    "que_ve": "Lo que ve (según el usuario)",
    "desde_cuando": "Desde cuándo (según el usuario)",
}


def anomalias(slots: dict[str, dict[str, Any]]) -> list[str]:
    """Hallazgos calculados por código (no por el LLM) que el conversacional debe mencionar."""
    out = []
    libre = (slots.get("disco_libre_gb") or {}).get("valor")
    if isinstance(libre, int | float) and libre < UMBRAL_DISCO_GB:
        out.append(f"El disco está casi lleno ({libre} GB libres): eso suele impedir que OneDrive sincronice.")
    estado_lic = (slots.get("licencia_estado") or {}).get("valor")
    if estado_lic and str(estado_lic).lower() not in LICENCIA_OK:
        out.append(f"La licencia de Office aparece como «{estado_lic}».")
    if (slots.get("onedrive_en_ejecucion") or {}).get("valor") is False:
        out.append("OneDrive no está en ejecución.")
    perfil = (slots.get("perfil_outlook_estado") or {}).get("valor")
    if perfil and perfil != "ok":
        out.append(ESTADOS_PERFIL.get(perfil, f"Perfil de Outlook: {perfil}."))
    cola = (slots.get("cola_trabajos") or {}).get("valor")
    if isinstance(cola, int) and cola > 0:
        out.append(f"Hay {cola} trabajo(s) atascados en la cola de impresión.")
    return out


NIVEL_TECNICO = {
    "bajo": "Nivel técnico del usuario: BAJO. Frases cortas, cero jerga (nada de 'caché', 'perfil', 'OST'); "
    "explica qué va a notar, no cómo funciona por dentro; un paso a la vez.",
    "medio": "Nivel técnico del usuario: MEDIO. Lenguaje claro; puedes nombrar menús y opciones de Office.",
    "alto": "Nivel técnico del usuario: ALTO. Sé directo y conciso; puedes usar términos técnicos (caché, perfil, "
    "versión, registros) sin explicarlos.",
}


def resumen_para_conversacional(
    slots: dict[str, dict[str, Any]], fallidas: list[str], sintoma: dict[str, Any] | None = None
) -> str:
    """Resumen DETERMINISTA (construido por código) de lo ya consultado y entendido, para que el
    agente conversacional no lo pregunte. Solo campos de la lista blanca, ya saneados."""
    partes = []
    if sintoma:
        entendido = [
            f"- {ETIQUETAS_SINTOMA[k]}: {sintoma[k]}"
            for k in ETIQUETAS_SINTOMA
            if sintoma.get(k) not in (None, "", "desconocida", "desconocido")
        ]
        if entendido:
            partes.append(
                "Lo que ya entendiste del problema (NO vuelvas a preguntar cuál es el problema ni estos datos):\n"
                + "\n".join(entendido)
            )
    lineas = [
        f"- {ETIQUETAS_SLOTS[k]}: {v['valor']}"
        for k, v in slots.items()
        if k in ETIQUETAS_SLOTS and v.get("valor") is not None
    ]
    if lineas:
        partes.append("Datos del equipo YA consultados por el sistema (no los preguntes):\n" + "\n".join(lineas))
    if hallazgos := anomalias(slots):
        partes.append("Hallazgos del sistema (menciónalos con palabras simples):\n- " + "\n- ".join(hallazgos))
    if fallidas:
        partes.append("Consultas que fallaron (puedes decir que no se pudieron revisar): " + ", ".join(fallidas))
    return "\n\n".join(partes)

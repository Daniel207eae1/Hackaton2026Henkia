"""Lista blanca de tools del MCP `zabbix-ofimatica` y su política (ADR 0007).

Una tool que no esté aquí NO se puede llamar, aunque el servidor la ofrezca.
`ejecutar_comando_generico` queda bloqueada en el cliente: "nunca comandos libres" (CLAUDE.md).
"""

from __future__ import annotations

from enum import StrEnum


class PoliticaMCP(StrEnum):
    DESCUBRIMIENTO = "descubrimiento"  # sin restricciones, sin equipo obligatorio
    AUTOMATICA = "automatica"  # solo lectura sobre un equipo
    GESTION = "gestion"  # solicitar/consultar autorizaciones
    CONSENTIMIENTO = "consentimiento"
    APROBACION_N2 = "aprobacion_n2"


TOOLS: dict[str, PoliticaMCP] = {
    "listar_equipos": PoliticaMCP.DESCUBRIMIENTO,
    "estado_servicio": PoliticaMCP.DESCUBRIMIENTO,  # tablero oficial (correo, Teams, nube) — §3.12
    "problemas_activos": PoliticaMCP.DESCUBRIMIENTO,  # retirada del servidor; respaldo si vuelve
    "catalogo_acciones": PoliticaMCP.DESCUBRIMIENTO,
    "telemetria_equipo": PoliticaMCP.AUTOMATICA,
    "version_office": PoliticaMCP.AUTOMATICA,
    "estado_licencia_office": PoliticaMCP.AUTOMATICA,
    "estado_onedrive": PoliticaMCP.AUTOMATICA,
    "estado_cola_impresion": PoliticaMCP.AUTOMATICA,
    "estado_teams": PoliticaMCP.AUTOMATICA,
    "estado_perfil_outlook": PoliticaMCP.AUTOMATICA,
    # Solo metadatos del historial de versiones (id, fecha, tamaño); nunca el contenido del archivo.
    "versiones_archivo": PoliticaMCP.AUTOMATICA,
    "solicitar_consentimiento": PoliticaMCP.GESTION,
    "consultar_consentimiento": PoliticaMCP.GESTION,
    "solicitar_aprobacion_n2": PoliticaMCP.GESTION,
    "consultar_aprobacion": PoliticaMCP.GESTION,
    "leer_logs_aplicacion": PoliticaMCP.CONSENTIMIENTO,
    "limpiar_cache_teams": PoliticaMCP.CONSENTIMIENTO,
    "reiniciar_cola_impresion": PoliticaMCP.CONSENTIMIENTO,
    "resincronizar_onedrive": PoliticaMCP.CONSENTIMIENTO,
    "reparacion_rapida_office": PoliticaMCP.CONSENTIMIENTO,
    # Restaura una versión y CONSERVA la actual como copia; el consentimiento queda ligado a archivo + versión.
    "restaurar_version_archivo": PoliticaMCP.CONSENTIMIENTO,
    "recrear_perfil_outlook": PoliticaMCP.APROBACION_N2,
    "asignar_licencia_office": PoliticaMCP.APROBACION_N2,
}

# Ofrecidas por el servidor pero prohibidas en este sistema (se rechazan sin llamar al MCP).
BLOQUEADAS: frozenset[str] = frozenset({"ejecutar_comando_generico"})

# Tools cuyo resultado es texto no confiable: va SOLO al extractor en cuarentena (F3).
SALIDA_NO_CONFIABLE: frozenset[str] = frozenset({"leer_logs_aplicacion"})

# Parámetros que una acción exige (y que quedan ligados a su consentimiento): sin ellos no se pide ni se ejecuta.
PARAMETROS_ACCION: dict[str, tuple[str, ...]] = {"restaurar_version_archivo": ("archivo", "version_id")}

# Vigencia de un consentimiento aprobado, según el servidor (un solo uso, 15 min).
VIGENCIA_CONSENTIMIENTO_S = 15 * 60


def acciones() -> set[str]:
    return {t for t, p in TOOLS.items() if p in (PoliticaMCP.CONSENTIMIENTO, PoliticaMCP.APROBACION_N2)}

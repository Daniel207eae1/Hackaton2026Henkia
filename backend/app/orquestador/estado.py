"""Estado del caso (*blackboard*, §3.4). Única fuente de verdad compartida por los agentes."""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated, Any, TypedDict


class Etapa(StrEnum):
    """Nodos del grafo §3.5 (los nombres los muestra el indicador de etapa de la UI)."""

    RECEPCION = "Recepcion"
    CAPTURA = "Captura"  # Módulo B: capturas del turno → extractor de visión en cuarentena
    RESPUESTA_POLITICA = "RespuestaPolitica"  # plantilla fija: prohibida o identidad (sin LLM)
    INTERPRETACION = "Interpretacion"  # slots del usuario + acción candidata (una llamada LLM)
    CONTEXTO = "Contexto"
    CHEQUEO_MASIVO = "ChequeoMasivo"
    INFORMAR_MASIVO = "InformarMasivo"  # seguimiento del incidente vinculado (N2 confirma/descarta/resuelve)
    ACLARACION = "Aclaracion"
    HIPOTESIS = "Hipotesis"
    PRUEBA = "Prueba"
    DECISION = "Decision"
    GUIA = "Guia"
    APROBACION_N2 = "AprobacionN2"
    CONSENTIMIENTO = "Consentimiento"
    EJECUCION = "Ejecucion"
    VERIFICACION = "Verificacion"
    CONFIRMACION = "Confirmacion"  # respuesta del usuario a «¿ya te funciona?»
    REVERSION = "Reversion"
    CIERRE = "Cierre"
    ESCALAR = "Escalar"


class TipoSintoma(StrEnum):
    # §3.4 + tipos agregados por el prototipo (ADR 0001, fila 8)
    NO_ABRE = "no_abre"
    SE_CIERRA = "se_cierra"
    LENTA = "lenta"
    NO_SINCRONIZA = "no_sincroniza"
    LICENCIA = "licencia"
    IMPRESION = "impresion"
    SIN_AUDIO = "sin_audio"
    ARCHIVO_SOBRESCRITO = "archivo_sobrescrito"
    BLOQUEO_SEGURIDAD = "bloqueo_seguridad"
    NO_EDITA = "no_edita"


class EstadoCaso(TypedDict, total=False):
    # Identificación
    case_id: str
    persona_id: str
    equipo_id: str | None
    equipo_hostname: str | None  # hostname del directorio (otro candidato para encontrarlo en Zabbix)
    equipo_zabbix: str | None  # nombre técnico en Zabbix (lo resuelve el código, nunca el chat)
    canal: str
    # Flujo
    etapa: str
    turnos: int
    ultimo_mensaje_usuario: str
    respuesta: str
    # Conversación (solo mensajes del usuario y respuestas del sistema; nunca texto externo)
    mensajes: Annotated[list[dict[str, str]], operator.add]
    # Síntoma y slots: {"slot": {"valor": ..., "origen": "telemetria" | "usuario"}}
    sintoma: dict[str, Any]
    slots: dict[str, dict[str, Any]]
    perfil_usuario: dict[str, Any]
    contexto_tecnico: dict[str, Any]
    masivo: dict[str, Any]
    hipotesis: list[dict[str, Any]]
    evidencia: list[dict[str, Any]]
    acciones: list[dict[str, Any]]  # historial de acciones cerradas
    accion_actual: dict[str, Any] | None  # una sola a la vez (F4)
    acciones_excluidas: list[str]  # rechazadas o ya hechas: nunca se insiste
    accion_candidata: dict[str, Any] | None  # propuesta del intérprete (enum); la filtra Decision
    lecturas_hechas: list[str]  # tools de lectura ya consultadas en este caso
    guardia: dict[str, Any]  # resultado de la guardia de entrada del turno
    metricas: dict[str, Any]  # preguntas hechas, bloqueos de la compuerta
    esperando_confirmacion: dict[str, Any] | None  # acción ejecutada que espera «¿ya te funciona?»
    fallo_verificacion: bool  # el usuario dijo que no funcionó: si no hay otra acción, se escala
    motivo_escalamiento: str | None  # lo fija el nodo que decide escalar (operacion.escalamientos.motivo)
    escalamiento: dict[str, Any] | None  # ficha N2 (desde el estado, §7.2)
    diagnostico: dict[str, Any]  # F3: categoría, extracción de logs validada, resultado del ciclo de hipótesis
    guia: dict[str, Any] | None  # F3: guía de la KB aplicada (artículo y sección)
    seguridad: dict[str, Any]
    capturas_nuevas: list[dict[str, Any]]  # referencias del turno (sha256 + ruta), nunca bytes
    capturas: list[dict[str, Any]]  # F7: SOLO campos validados por el extractor de visión
    captura_informada_turno: int | None
    cierre: dict[str, Any]
    linea_tiempo: Annotated[list[dict[str, Any]], operator.add]

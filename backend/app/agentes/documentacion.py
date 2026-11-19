"""Agente de Escalamiento y Documentación (§3.3, §7.2) — determinista.

La ficha para N2 y el registro de cierre se construyen DESDE EL ESTADO DEL CASO, nunca desde la memoria
del LLM: así N2 continúa sin repreguntar y el registro es replicable. (Un LLM podría redactar un
resumen amable encima, pero los datos salen de aquí.)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.politicas.catalogo import ans, catalogo

# motivo (operacion.escalamientos.motivo) → (tipo de ANS, siguiente paso sugerido)
MOTIVOS: dict[str, tuple[str, str]] = {
    "pide_humano": (
        "humano",
        "Contactar al usuario y continuar desde el diagnóstico de esta ficha (no repreguntar).",
    ),
    "accion_prohibida": (
        "seguridad",
        "Evaluar la necesidad real (p. ej., revisar o firmar la macro) sin desactivar "
        "controles de seguridad; reforzar con el usuario por qué no se hace.",
    ),
    "n2_rechaza": ("escalamiento", "Definir una alternativa a la acción que no se aprobó."),
    "solucion_fallida": (
        "escalamiento",
        "La acción ejecutada no resolvió el síntoma: revisar los registros técnicos "
        "(con consentimiento) o programar revisión en sitio.",
    ),
    "fuera_alcance": ("escalamiento", "Revisión física del equipo (posible daño de hardware)."),
    "presupuesto_agotado": (
        "escalamiento",
        "Continuar el diagnóstico con lo ya probado; la conversación excedió el límite.",
    ),
    "sin_hipotesis": (
        "escalamiento",
        "Ninguna hipótesis se confirmó: revisar con lo probado y lo descartado.",
    ),
    "requiere_privilegios": ("escalamiento", "Ejecutar la acción con privilegios desde la consola de N2."),
    "rechazo_usuario": ("escalamiento", "El usuario no autorizó la acción propuesta: acordar otra opción."),
}
TEXTO_MOTIVO = {
    "pide_humano": "el usuario pidió hablar con una persona",
    "accion_prohibida": "insistencia en una acción prohibida",
    "n2_rechaza": "N2 no aprobó la acción propuesta",
    "solucion_fallida": "la solución aplicada no funcionó",
    "fuera_alcance": "fuera del alcance del chat (hardware)",
    "presupuesto_agotado": "la conversación superó el límite",
    "sin_hipotesis": "no se confirmó ninguna causa",
    "requiere_privilegios": "requiere privilegios de N2",
    "rechazo_usuario": "el usuario no autorizó la acción",
}


def _ahora() -> datetime:
    return datetime.now(UTC)


def _horas_ans(plazo: str) -> float | None:
    """'4 horas hábiles' → 4.0; '30 minutos hábiles' → 0.5 (aproximación simulada)."""
    partes = plazo.split()
    try:
        n = float(partes[0])
    except (IndexError, ValueError):
        return None
    return n / 60 if partes[1:2] and partes[1].startswith("minuto") else n


def _acciones(estado: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for a in estado.get("acciones") or []:
        nombre = a.get("tool")
        try:
            nombre = catalogo().por_tool(a["tool"]).nombre
        except KeyError:
            pass
        out.append(
            {
                "accion": nombre,
                "tool": a.get("tool"),
                "estado": a.get("estado"),
                "politica": a.get("politica"),
                "consentimiento_id": a.get("consentimiento_id"),
                "aprobacion_id": a.get("aprobacion_id"),
                "verificacion_tecnica": a.get("verificacion_tecnica"),
                "motivo_fallo": a.get("motivo_fallo"),
                "ejecutada_en": a.get("ejecutada_en"),
            }
        )
    return out


def _contexto_equipo(estado: dict[str, Any]) -> dict[str, Any]:
    slots = estado.get("slots") or {}
    return {
        "equipo": estado.get("equipo_zabbix") or estado.get("equipo_id"),
        "datos": {k: v.get("valor") for k, v in slots.items() if v.get("valor") is not None},
        "consultas_fallidas": (estado.get("contexto_tecnico") or {}).get("consultas_fallidas", []),
        "consultado_en": (estado.get("contexto_tecnico") or {}).get("hora"),
    }


def ficha_n2(estado: dict[str, Any], motivo: str) -> dict[str, Any]:
    """Ficha de diagnóstico §7.2: todo lo que N2 necesita para continuar sin repreguntar."""
    tipo_ans, siguiente = MOTIVOS.get(motivo, MOTIVOS["sin_hipotesis"])
    datos_ans = ans(tipo_ans)
    horas = _horas_ans(datos_ans["plazo"])
    sintoma = estado.get("sintoma") or {}
    return {
        "case_id": estado.get("case_id"),
        "usuario_id": estado.get("persona_id"),
        "motivo": motivo,
        "motivo_texto": TEXTO_MOTIVO.get(motivo, motivo),
        "sintoma": {
            "palabras_del_usuario": sintoma.get("descripcion_usuario"),
            "aplicacion": sintoma.get("aplicacion"),
            "tipo_sintoma": sintoma.get("tipo_sintoma"),
            "que_ve": sintoma.get("que_ve"),
            "desde_cuando": sintoma.get("desde_cuando"),
        },
        "contexto_equipo": _contexto_equipo(estado),
        "masivo": {k: (estado.get("masivo") or {}).get(k) for k in ("estado", "fuente", "servicio")},
        "hipotesis": estado.get("hipotesis") or [],  # F3
        "evidencia": estado.get("evidencia") or [],
        "acciones": _acciones(estado),
        "banderas_seguridad": [b.get("bandera") for b in (estado.get("seguridad") or {}).get("banderas", [])],
        "siguiente_paso": siguiente,
        "ans": {
            **datos_ans,
            "horas": horas,
            "vence_en": (_ahora() + timedelta(hours=horas)).isoformat(timespec="minutes") if horas else None,
        },
        "turnos": estado.get("turnos"),
        "creado_en": _ahora().isoformat(timespec="seconds"),
    }


def mensaje_escalamiento(ficha: dict[str, Any]) -> str:
    base = {
        "pide_humano": "Listo, paso tu caso a una persona de soporte.",
        "accion_prohibida": "Como esa acción no se puede hacer por aquí, paso tu caso a un técnico de N2.",
        "n2_rechaza": "El técnico de N2 no aprobó esa acción, así que paso tu caso a N2 para buscar otra opción.",
        "solucion_fallida": "Lamento que no haya quedado resuelto. Paso tu caso a un técnico de N2.",
        "fuera_alcance": "Esto parece un problema físico del equipo, así que lo pasa a revisar un técnico de N2.",
        "presupuesto_agotado": "Para no hacerte perder más tiempo, paso tu caso a un técnico de N2.",
    }.get(ficha["motivo"], "Paso tu caso a un técnico de N2.")
    return f"{base} Ya tiene todo lo que revisamos, así que no tendrás que repetirlo. {ficha['ans']['texto']}"


def registro_cierre(estado: dict[str, Any]) -> dict[str, Any]:
    """Registro ITSM replicable del cierre (R5): síntoma, contexto, acciones con su autorización y verificación."""
    sintoma = estado.get("sintoma") or {}
    acciones = _acciones(estado)
    # Leer logs es diagnóstico, no solución. Si se aplicó una guía de la KB, esa es la solución.
    ultima = next(
        (a for a in reversed(acciones) if a["estado"] == "ejecutada" and a["tool"] != "leer_logs_aplicacion"), None
    )
    if estado.get("guia"):
        ultima = None
    masivo = estado.get("masivo") or {}
    if masivo.get("estado") == "masivo_resuelto" and not ultima:
        # Se resolvió el incidente general al que estaba vinculado (sin pasos individuales).
        ultima = {"incidente": masivo.get("incidente_id"), "accion": f"Incidente general {masivo.get('incidente_id')}"}
    return {
        "case_id": estado.get("case_id"),
        "resultado": "resuelto",
        "sintoma": {
            "palabras_del_usuario": sintoma.get("descripcion_usuario"),
            "aplicacion": sintoma.get("aplicacion"),
            "tipo_sintoma": sintoma.get("tipo_sintoma"),
        },
        "contexto_equipo": _contexto_equipo(estado),
        "solucion": ultima
        or (
            {
                "guia": estado["guia"]["articulo_id"],
                "accion": f"Guía {estado['guia']['articulo_id']}",
                "titulo": estado["guia"]["titulo"],
            }
            if estado.get("guia")
            else None
        ),
        "acciones": acciones,
        "verificacion": {"tecnica": (ultima or {}).get("verificacion_tecnica"), "usuario": True},
        "cerrado_en": _ahora().isoformat(timespec="seconds"),
    }

"""Compuerta de preguntas (R1, §3.5): "nunca pregunta lo que podía consultar" como regla verificable.

Cada *slot* tiene una fuente declarada. Si el sistema YA tiene el dato (origen `telemetria`), la
guardia de salida elimina cualquier pregunta del agente conversacional sobre él. Si la consulta
falló, sí se permite preguntarlo.

Funciona frase a frase sobre el *stream*: se conserva la sensación de *streaming* y una pregunta
prohibida nunca llega a la pantalla.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# slot consultable → patrones que delatan una pregunta sobre él
CONSULTABLES: dict[str, list[str]] = {
    "version_office": [
        r"version (de |del )?(office|outlook|excel|word|powerpoint|microsoft|365|teams)",
        r"que (office|version) (tienes|usas|tiene|usa)",
    ],
    "so": [r"sistema operativo", r"version de windows", r"que windows", r"windows (10|11) o"],
    "disco_libre_gb": [r"espacio (en|del|libre|disponible)", r"\bdisco\b", r"almacenamiento"],
    "licencia_estado": [r"licencia", r"\bactivad[oa]\b", r"\bactivacion\b"],
    "ram_libre_mb": [r"\bram\b", r"memoria"],
    "onedrive_en_ejecucion": [
        r"onedrive (esta|se esta|sigue) (abierto|corriendo|ejecut|activo|iniciado)",
        r"(tienes|esta) (abierto|iniciado) (el )?onedrive",
    ],
    "codigo_error": [
        r"codigo de(l)? error",
        r"(que|cual(es)?) (es el |son los )?(mensaje|codigo)s? de error",
    ],
    "cola_trabajos": [
        r"cola de impresion",
        r"trabajos (pendientes|en cola)",
        r"documentos (pendientes|en cola)",
    ],
}
# Fin de frase: puntuación + espacio, salto, o «?»/«.» pegado a un «¿» (p. ej. «…appears?¿Al abrir…»).
_FIN_FRASE = re.compile(r"(?<=[.!?])\s+|\n+|(?<=[.!?])(?=¿)")
# Razonamiento interno que un modelo de razonamiento deja escapar en `content` (raro, visto 1 vez con gpt-oss):
# frases en inglés dirigidas a sí mismo. El usuario nunca las ve.
_META_RAZONAMIENTO = re.compile(
    r"^\s*(we (should|need|must|can|will)|let'?s|let us|the user|i (should|need|will|must)|okay,? (so|we|let)|"
    r"now (we|i)|so (we|i) (should|need))\b",
    re.IGNORECASE,
)


def es_meta_razonamiento(frase: str) -> bool:
    return bool(_META_RAZONAMIENTO.search(frase))


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def es_pregunta(frase: str) -> bool:
    return "?" in frase or frase.strip().startswith("¿")


# Palabras que no distinguen una pregunta de otra (se ignoran al comparar).
_VACIAS = {
    "algun",
    "alguna",
    "alguno",
    "algunos",
    "cuando",
    "donde",
    "desde",
    "tienes",
    "puedes",
    "podrias",
    "esta",
    "estas",
    "este",
    "esto",
    "eso",
    "ese",
    "para",
    "pero",
    "como",
    "cual",
    "cuales",
    "sale",
    "pasa",
    "hace",
    "tambien",
    "simplemente",
    "favor",
    "intentas",
    "intentar",
    "ejemplo",
}
UMBRAL_REPETIDA = 0.6


def palabras_clave(frase: str) -> set[str]:
    t = unicodedata.normalize("NFKD", frase.lower()).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) >= 4 and w not in _VACIAS}


def preguntas_de(texto: str) -> list[set[str]]:
    """Palabras clave de cada pregunta de un mensaje anterior del sistema."""
    return [p for f in re.split(r"(?<=[?.!])\s+|\n", texto) if es_pregunta(f) and len(p := palabras_clave(f)) >= 2]


def es_repetida(frase: str, previas: list[set[str]]) -> bool:
    """La pregunta comparte la mayoría de sus palabras clave con una ya hecha (la misma pregunta con otras palabras)."""
    actual = palabras_clave(frase)
    if len(actual) < 2:
        return False
    for p in previas:
        comunes = len(actual & p)
        if comunes >= 3 and comunes / min(len(actual), len(p)) >= UMBRAL_REPETIDA:
            return True
    return False


def slot_preguntado(frase: str, disponibles: set[str]) -> str | None:
    """Devuelve el slot consultable por el que pregunta la frase (solo si ya está disponible)."""
    if not es_pregunta(frase):
        return None
    t = _norm(frase)
    for slot, patrones in CONSULTABLES.items():
        if slot in disponibles and any(re.search(p, t) for p in patrones):
            return slot
    return None


@dataclass
class FiltroPreguntas:
    """Acumula el *stream* y entrega frases aprobadas; descarta preguntas por slots consultables."""

    disponibles: set[str]
    previas: list[set[str]] = field(default_factory=list)  # preguntas ya hechas en el caso (palabras clave)
    bloqueadas: list[str] = field(default_factory=list)
    preguntas: int = 0
    meta_descartadas: int = 0
    repetidas: int = 0
    _buffer: str = ""

    def _aprobar(self, frase: str) -> str | None:
        if not frase.strip():
            return frase if frase else None
        if es_meta_razonamiento(frase):
            self.meta_descartadas += 1
            return None
        slot = slot_preguntado(frase, self.disponibles)
        if slot:
            self.bloqueadas.append(slot)
            return None
        if es_pregunta(frase):
            if es_repetida(frase, self.previas):
                self.repetidas += 1  # el usuario ya respondió esto: repetirlo parece que el sistema olvidó
                return None
            self.preguntas += 1
        return frase

    def alimentar(self, delta: str) -> list[str]:
        self._buffer += delta
        salida: list[str] = []
        inicio = 0
        # Cada frase incluye su separador final (espacio o salto) para no perder el formato.
        for m in _FIN_FRASE.finditer(self._buffer):
            aprobada = self._aprobar(self._buffer[inicio : m.end()])
            if aprobada:
                salida.append(aprobada)
            inicio = m.end()
        self._buffer = self._buffer[inicio:]
        return salida

    def cerrar(self) -> list[str]:
        frase, self._buffer = self._buffer, ""
        aprobada = self._aprobar(frase) if frase else None
        return [aprobada] if aprobada else []


def disponibles_desde_slots(slots: dict[str, dict]) -> set[str]:
    # Consultable = lo leyó el sistema (telemetría) o ya está validado (código de una captura o escrito).
    return {
        k
        for k, v in slots.items()
        if v.get("valor") is not None
        and (v.get("origen") == "telemetria" or (k == "codigo_error" and v.get("origen") in ("captura", "usuario")))
    }

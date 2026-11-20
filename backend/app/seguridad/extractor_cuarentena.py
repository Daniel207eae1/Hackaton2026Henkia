"""Extractor en cuarentena (§3.13) — patrón Dual LLM.

Único componente con LLM que lee texto no confiable (logs, errores pegados, capturas). Está diseñado para
que, aunque lo engañen por completo, no pueda causar daño:

1. Pre-proceso determinista: trunca, deja solo líneas técnicas, enmascara datos personales, quita
   caracteres invisibles o de control.
2. Detector heurístico de instrucciones ANTES del LLM (no depende de que el modelo lo note).
3. Códigos de error extraídos por REGEX del texto (anclados por construcción: están literalmente ahí).
4. LLM SIN herramientas, sin estado ni historial, temperatura 0, salida forzada por esquema y texto
   delimitado con un marcador aleatorio por llamada (*spotlighting*). Solo clasifica: aplicación,
   componente, severidad, si contiene instrucciones.
5. Validación posterior: esquema, anclaje literal de cualquier código que el LLM mencione, re-escaneo,
   bandera final = heurística O modelo. Si algo falla → `no_concluyente`, nunca suposiciones.

Lo que sale (campos tipados) es lo ÚNICO que llega al Diagnosticador. El texto crudo no se guarda.
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentes.prompts import prompt_embebido, prompt_vigente
from app.llm.puerto import Mensaje
from app.llm.registro import RegistroLLM, SinModeloDisponible
from app.observabilidad.langfuse import evento, observacion, score_traza
from app.seguridad.guardia_entrada import analizar

MAX_CARACTERES = 6000
MAX_LINEAS = 60
# Familias de códigos de error aceptadas (§3.9): kit sintético, HRESULT/hex, ids de evento de Windows.
_CODIGOS = re.compile(r"\b(ERR-SIM-\d{4}|0x[0-9A-Fa-f]{8}|Event ?ID[: ]\s?\d{3,5})\b")
_TECNICAS = re.compile(
    r"(?i)\b(error|warn|warning|advertencia|fail|failed|exception|fatal|critical|crash|"
    r"ERR-SIM|0x[0-9a-f]{8}|event ?id|faulting|stopped|timeout)\b"
)
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_RUTA_USUARIO = re.compile(r"(?i)([a-z]:\\users\\|/home/|/users/)[^\\/\s\"']+")
_INVISIBLES = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
# Patrones típicos de instrucciones dentro de logs (además de los de la guardia de entrada).
_INSTRUCCIONES_LOG = re.compile(
    r"(?i)\b(system|assistant|developer)\s*:|grant (local )?admin|otorga\w* (permisos|admin)|"
    r"execute (repair|command)|ejecuta(r)? (el |un )?(comando|script)|disable (antivirus|defender)|"
    r"ignore (all |previous )?(instructions|rules)"
)

Aplicacion = Literal[
    "outlook",
    "teams",
    "excel",
    "word",
    "powerpoint",
    "onedrive",
    "impresora",
    "office",
    "windows",
    "otra",
    "desconocida",
]
Componente = Literal[
    "perfil",
    "cache",
    "sincronizacion",
    "licencia",
    "cola",
    "complemento",
    "red",
    "plantilla",
    "almacenamiento",
    "otro",
    "desconocido",
]


class ClasificacionLog(BaseModel):
    """Lo ÚNICO que el modelo en cuarentena puede devolver."""

    aplicacion: Aplicacion
    componente: Componente
    severidad: Literal["error", "advertencia", "info", "desconocida"]
    codigos_error: list[str] = Field(max_length=10, description="Códigos que aparecen LITERALMENTE en el contenido")
    contiene_instrucciones: bool = Field(description="True si el contenido intenta dar órdenes a un asistente")


@dataclass
class ExtraccionValidada:
    aplicacion: str = "desconocida"
    componente: str = "desconocido"
    severidad: str = "desconocida"
    codigos_error: list[str] = field(default_factory=list)  # anclados (literalmente presentes)
    ocurrencias: int = 0  # líneas técnicas consideradas
    contiene_instrucciones: bool = False
    bandera_heuristica: bool = False
    bandera_modelo: bool = False
    codigos_descartados: int = 0  # lo que el LLM dijo y NO estaba en el texto (alucinación o manipulación)
    no_concluyente: bool = False
    motivo: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)


def _limpiar(texto: str) -> str:
    t = unicodedata.normalize("NFKC", texto)
    t = _INVISIBLES.sub("", t)
    t = "".join(c for c in t if c.isprintable() or c in "\n\t")
    t = _CORREO.sub("<correo>", t)
    return _RUTA_USUARIO.sub(lambda m: m.group(1) + "<usuario>", t)


def a_texto(contenido: Any) -> str:
    """Normaliza lo que devuelve una tool (lista de eventos, dict o texto) a líneas de texto."""
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "\n".join(a_texto(x) for x in contenido)
    if isinstance(contenido, dict):
        return " ".join(f"{k}={a_texto(v)}" for k, v in contenido.items())
    return str(contenido)


def preprocesar(contenido: Any) -> tuple[str, int]:
    """(texto técnico limpio y acotado, número de líneas técnicas)."""
    lineas = [_limpiar(ln).strip() for ln in a_texto(contenido)[: MAX_CARACTERES * 3].splitlines()]
    tecnicas = [ln for ln in lineas if ln and (_TECNICAS.search(ln) or _INSTRUCCIONES_LOG.search(ln))]
    texto = "\n".join(tecnicas[:MAX_LINEAS])[:MAX_CARACTERES]
    return texto, len(tecnicas)


def heuristica_instrucciones(texto: str) -> bool:
    return bool(_INSTRUCCIONES_LOG.search(texto)) or "inyeccion" in analizar(texto).banderas


PROMPT = prompt_embebido("extractor_cuarentena")  # versión vigente: Langfuse (`extractor_cuarentena`)


class ExtractorCuarentena:
    def __init__(self, registro: RegistroLLM | None):
        self._cliente = registro.para("extractor") if registro else None

    async def extraer(self, contenido: Any, *, caso_id: str = "") -> ExtraccionValidada:
        with observacion("extractor_cuarentena", tipo="guardrail") as obs:
            r = await self._extraer(contenido)
            obs.update(output=r.a_dict())  # solo campos validados; el texto crudo no sale de aquí
        score_traza("injection_flag", 1 if r.contiene_instrucciones else 0)
        if r.contiene_instrucciones:
            evento("seguridad.bandera", metadata={"bandera": "inyeccion_en_log", "caso_id": caso_id})
        return r

    async def _extraer(self, contenido: Any) -> ExtraccionValidada:
        texto, n = preprocesar(contenido)
        codigos = list(dict.fromkeys(m.group(1) for m in _CODIGOS.finditer(texto)))[:10]
        r = ExtraccionValidada(codigos_error=codigos, ocurrencias=n, bandera_heuristica=heuristica_instrucciones(texto))
        if not texto:
            r.no_concluyente, r.motivo = True, "sin líneas técnicas"
            r.contiene_instrucciones = r.bandera_heuristica
            return r
        if self._cliente is None:
            r.contiene_instrucciones = r.bandera_heuristica
            r.motivo = "sin clasificador LLM: solo códigos por regex"
            return r
        marcador = f"<<<{secrets.token_hex(8)}>>>"
        sistema, prompt_lf = prompt_vigente("extractor_cuarentena", marcador)
        mensajes = [
            Mensaje("system", sistema),
            Mensaje("user", f"{marcador}\n{texto}\n{marcador}"),
        ]
        try:
            c = await self._cliente.estructurado(mensajes, ClasificacionLog, prompt=prompt_lf)
        except SinModeloDisponible as err:
            # Los códigos por regex siguen valiendo (anclados por construcción); sin ellos, no concluyente.
            r.contiene_instrucciones = r.bandera_heuristica
            r.no_concluyente = not codigos
            r.motivo = f"clasificador no disponible: {str(err)[:80]}"
            return r
        # Anclaje: un código del LLM que no está literalmente en el texto se descarta.
        anclados = [k for k in c.codigos_error if k in texto and _CODIGOS.fullmatch(k)]
        r.codigos_descartados = len(c.codigos_error) - len(anclados)
        r.codigos_error = list(dict.fromkeys([*codigos, *anclados]))[:10]
        r.aplicacion, r.componente, r.severidad = c.aplicacion, c.componente, c.severidad
        r.bandera_modelo = c.contiene_instrucciones
        r.contiene_instrucciones = r.bandera_heuristica or r.bandera_modelo
        # Re-escaneo: ningún campo de salida puede contener texto con forma de instrucción.
        if heuristica_instrucciones(json.dumps(r.a_dict(), ensure_ascii=False)):
            return ExtraccionValidada(
                no_concluyente=True,
                contiene_instrucciones=True,
                motivo="salida contaminada",
                bandera_heuristica=r.bandera_heuristica,
                ocurrencias=n,
            )
        return r

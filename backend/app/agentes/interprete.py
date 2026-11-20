"""Intérprete del turno (R1 + Action-Selector, §3.5 y §4.2) — UNA llamada LLM por turno.

Del lenguaje vago del colaborador (coloquial, sin tildes, mezclado con inglés) extrae los *slots*
que solo él sabe (aplicación, tipo de síntoma, qué ve, desde cuándo) y propone una acción de un enum
cerrado. Todo con salida estructurada validada; nada de texto libre alimenta decisiones.

- No elige parámetros ni ejecuta: la acción candidata la filtra `Decision` (código) y luego exige
  la autorización del usuario en la ventana de su equipo.
- Entrada mínima: mensajes escritos por el usuario + datos del equipo ya saneados. Nunca logs ni
  nombres de problemas de Zabbix.
- Se unió al selector para no gastar una llamada extra (límite de 20 solicitudes por minuto
  del tier gratuito).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agentes.prompts import prompt_embebido
from app.llm.puerto import Mensaje
from app.llm.registro import RegistroLLM, SinModeloDisponible
from app.observabilidad.langfuse import evento, obtener_prompt

NOMBRE_PROMPT = "interprete"
NINGUNA = "ninguna"

Aplicacion = Literal[
    "outlook",
    "teams",
    "excel",
    "word",
    "powerpoint",
    "onedrive",
    "impresora",
    "office",
    "otra",
    "desconocida",
]
TipoSintoma = Literal[
    "no_abre",
    "se_cierra",
    "lenta",
    "no_sincroniza",
    "licencia",
    "impresion",
    "sin_audio",
    "archivo_sobrescrito",
    "bloqueo_seguridad",
    "no_edita",
    "otro",
    "desconocido",
]
AccionSeleccionable = Literal[
    "limpiar_cache_teams",
    "reiniciar_cola_impresion",
    "resincronizar_onedrive",
    "reparacion_rapida_office",
    "recrear_perfil_outlook",
    "asignar_licencia_office",
    "ninguna",
]
_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁠-⁤]")


class Interpretacion(BaseModel):
    aplicacion: Aplicacion
    tipo_sintoma: TipoSintoma
    que_ve: str | None = Field(description="Lo que el usuario dice ver en pantalla, resumido; null si no lo dijo")
    desde_cuando: str | None = Field(description="Desde cuándo pasa, según el usuario; null si no lo dijo")
    archivo: str | None = Field(
        default=None,
        description="Nombre (o parte del nombre) del archivo que el usuario menciona, tal cual; null si no lo dijo",
    )
    fuera_de_alcance: Literal["ninguno", "hardware"]
    accion: AccionSeleccionable
    motivo: str = Field(description="Por qué esa acción (o ninguna), en una frase")

    @field_validator("que_ve", "desde_cuando", "motivo", "archivo")
    @classmethod
    def _acotar(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _CONTROL.sub("", v).strip()[:160]
        return v or None

    @property
    def sintoma_completo(self) -> bool:
        return self.aplicacion not in ("desconocida", "otra") and self.tipo_sintoma not in (
            "desconocido",
            "otro",
        )


VACIA = Interpretacion(
    aplicacion="desconocida",
    tipo_sintoma="desconocido",
    que_ve=None,
    desde_cuando=None,
    fuera_de_alcance="ninguno",
    accion=NINGUNA,
    motivo="sin interpretación",
)


# Todo lo que dijo el usuario en el caso: olvidar los primeros mensajes hacía perder datos.
# Costo despreciable (~1 k tokens de entrada más por turno).
MAX_MENSAJES_USUARIO = 20
MAX_CARACTERES_MENSAJE = 1000


class Interprete:
    def __init__(self, registro: RegistroLLM):
        self._cliente = registro.para("interprete")

    async def interpretar(self, mensajes_usuario: list[str], contexto: str, excluidas: set[str]) -> Interpretacion:
        sistema, prompt_lf = obtener_prompt(NOMBRE_PROMPT, prompt_embebido(NOMBRE_PROMPT))
        if excluidas:
            sistema += "\n\nNo propongas estas acciones (el usuario las rechazó o ya se hicieron): " + ", ".join(
                sorted(excluidas)
            )
        texto_usuario = "\n".join(f"- {m[:MAX_CARACTERES_MENSAJE]}" for m in mensajes_usuario[-MAX_MENSAJES_USUARIO:])
        mensajes = [
            Mensaje("system", sistema),
            Mensaje("user", f"Lo que escribió el colaborador:\n{texto_usuario}\n\n{contexto}".strip()),
        ]
        try:
            r = await self._cliente.estructurado(mensajes, Interpretacion, prompt=prompt_lf)
        except SinModeloDisponible as err:
            evento("llm.sin_modelo", metadata={"agente": "interprete", "error": str(err)[:200]})
            return VACIA
        if r.accion in excluidas:
            # Defensa en código: nunca se insiste con una acción rechazada o ya hecha.
            r = r.model_copy(update={"accion": NINGUNA, "motivo": "acción excluida"})
        return r

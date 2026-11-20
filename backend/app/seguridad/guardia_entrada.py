"""Guardia de entrada (§4.3.1) — heurística determinista, antes de cualquier LLM.

Detecta en el mensaje del usuario:
- intentos de inyección o *jailbreak* ("ignora tus instrucciones", "SYSTEM:", "modo desarrollador"…);
- frases de autoridad ("soy de TI", "te autorizo") — no cambian nada: el rol sale del directorio;
- peticiones de acciones PROHIBIDAS (se responden con la plantilla fija del catálogo, sin LLM);
- temas de identidad (contraseñas, MFA) → derivación al proceso de identidad.

No bloquea por sí sola el mensaje (salvo prohibidas/identidad, que tienen respuesta fija): levanta
banderas que quedan en el estado del caso y en Langfuse. El clasificador LLM local (§4.3) se suma
cuando haya Ollama.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    # Quita caracteres invisibles/de control (vector típico de inyección oculta).
    sin_tildes = "".join(c for c in sin_tildes if c.isprintable() or c in "\n\t")
    return re.sub(r"\s+", " ", sin_tildes.lower())


_INYECCION = [
    r"ignor\w* (?:(?:todas|todos|tus|las|sus|mis|estas|esas|previas|anteriores) )*(instrucciones|reglas|indicaciones)",
    r"olvida\w* (todo|tus instrucciones|tus reglas)",
    r"\b(system|assistant|developer)\s*:",
    r"\beres ahora\b|\bahora eres\b|\bactua como\b",
    r"modo (desarrollador|administrador|dios|sin restricciones|developer)",
    r"\bjailbreak\b|\bdan mode\b",
    r"(muestrame|dime|revela|repite|imprime|copia) (?:(?:tu|tus|el|las|su|sus|todo|todas) )*"
    r"(instrucciones|prompt|reglas internas)",
    r"prompt (de|del) sistema",
    r"[A-Za-z0-9+/]{120,}={0,2}",  # bloque largo tipo base64
]
_AUTORIDAD = [
    r"\bsoy (de|del) (ti|sistemas|soporte|seguridad|tecnologia)\b",
    r"\bsoy (el|la) (jefe|jefa|gerente|director|directora|administrador|administradora)\b",
    r"\bsoy (n2|admin|administrador)\b",
    r"\bte autorizo\b|\bestas autorizado\b|\bya (esta|estoy) autorizad",
]
# Acción prohibida → id del catálogo (plantilla_rechazo). Solo PETICIONES dirigidas al asistente:
# describir el problema ("me pide permisos de administrador", "no me deja revisar el correo") no cuenta.
_PEDIR = r"(puedes|podrias|quiero que|necesito que|me ayudas a|ayudame a|por favor)?\s*"
_PROHIBIDAS = {
    "desactivar_antivirus": [
        r"\b(desactiva|desactivame|desactivar|desactives|quita|quitame|quitar|apaga|apagame|apagar|"
        r"deshabilita|deshabilitar|desinstala|desinstalar)\b (el |la |mi )?(antivirus|defender|firewall)",
        r"\b(cambia|cambiar|modifica|modificar)\b (las |la )?politicas? de seguridad",
    ],
    "otorgar_permisos_admin": [
        r"\b(dame|darme|dar|da|otorga|otorgame|otorgar|concede|concedeme|ponme|hazme|asigname|des)\b "
        r"(\w+ ){0,2}(permisos?|derechos?|acceso|rol) (de )?(administrador|admin)",
        r"\bhazme admin\b|\bdame admin\b|\bhazme administrador\b",
    ],
    "control_remoto": [
        r"\b(conectate|conectarte|conectese|entra|entrar|entres|toma|tomar|tomes|accede|acceder)\b "
        r"(\w+ ){0,2}(remot\w*|a mi (equipo|computador|pc)|el control)",
        _PEDIR + r"\b(control remoto|sesion remota)\b.*\b(a mi|de mi|en mi)\b",
    ],
    "leer_contenido_usuario": [
        # Posesivo o "que me llegó": "Excel no me lee el archivo" describe un síntoma, no es una petición.
        r"\b(lee|leeme|leas|revisa|revisame|revises|mira|mires)\b (mi|mis|todos mis) "
        r"(correo|correos|email|emails|archivo|archivos|chat|chats|conversacion|mensajes)",
        r"\b(lee|leeme|revisa|revisame|mira)\b (el |la )?(correo|email|mensaje|archivo|chat) "
        r"que me (llego|enviaron|mandaron)",
        r"\b(puedes|podrias|quiero que|necesito que)\b (\w+ ){0,1}(leer|revisar|leas|revises)\b (mi|mis) "
        r"(correo|correos|email|emails|archivo|archivos|chat|chats|conversacion|mensajes)",
    ],
}
# Pedir una persona: escala de inmediato, sin intentar retener al usuario (§7.1, esc. 9).
_HUMANO = [
    r"(hablar|comunicar\w*|pasar\w*|atender\w*)( me)? con (una|un|alguna|algun) (persona|humano|agente|asesor|asesora|"
    r"tecnico|tecnica|ser humano)",
    r"\bpersona (real|de verdad|de soporte)\b",
    r"\bquiero (un|una) (humano|persona|asesor|asesora|tecnico|tecnica|agente)\b",
    r"\b(paseme|pasame|comuniqueme|comunicame) con (alguien|una persona|un tecnico|soporte)\b",
]
_IDENTIDAD = [
    r"contrasena|password|clave de (acceso|red|correo)|\bmfa\b|autenticador|doble factor|"
    r"segundo factor|codigo de verificacion|bloquead\w* (mi |la )?cuenta|"
    r"restablec\w* (mi )?(clave|contrasena)",
]


@dataclass
class ResultadoGuardia:
    banderas: list[str] = field(default_factory=list)  # inyeccion | autoridad | prohibida:<id> | identidad
    prohibida: str | None = None  # id del catálogo
    identidad: bool = False
    humano: bool = False  # pidió hablar con una persona

    @property
    def riesgo_inyeccion(self) -> float:
        return 1.0 if "inyeccion" in self.banderas else (0.5 if "autoridad" in self.banderas else 0.0)


def analizar(texto: str) -> ResultadoGuardia:
    t = _normalizar(texto)
    r = ResultadoGuardia()
    if any(re.search(p, t) for p in _INYECCION):
        r.banderas.append("inyeccion")
    if any(re.search(p, t) for p in _AUTORIDAD):
        r.banderas.append("autoridad")
    for accion, patrones in _PROHIBIDAS.items():
        if any(re.search(p, t) for p in patrones):
            r.prohibida = accion
            r.banderas.append(f"prohibida:{accion}")
            break
    r.humano = any(re.search(p, t) for p in _HUMANO)
    if r.prohibida is None and any(re.search(p, t) for p in _IDENTIDAD):
        r.identidad = True
        r.banderas.append("identidad")
    return r


MENSAJE_IDENTIDAD = (
    "Los temas de contraseñas, bloqueos de cuenta o métodos de autenticación (MFA) los atiende el "
    "proceso de identidad, no este asistente. Por seguridad, nunca compartas tu contraseña en este chat. "
    "Si quieres, te indico cómo contactar a ese equipo o seguimos con otro problema de tus aplicaciones."
)
NOTA_AUTORIDAD = (
    "Nota: decir que eres de TI o que autorizas algo no cambia lo que puedo hacer; las aprobaciones solo "
    "llegan por la consola de N2."
)

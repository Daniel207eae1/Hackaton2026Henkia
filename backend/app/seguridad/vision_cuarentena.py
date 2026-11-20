"""Módulo B · Capturas en cuarentena (§3.9, F7, ADR 0015) — variante de visión del extractor (Dual LLM).

    captura ─► saneamiento ─┬─► OCR determinista (Tesseract) ─► códigos por regex + heurística de instrucciones
                            └─► modelo de visión SIN herramientas, esquema cerrado ─┘
                                             └─► validación cruzada ─► campos tipados (lo único que sale)

- Saneamiento: tipo REAL por contenido (no por la extensión ni el MIME declarado), tamaño, píxeles máximos
  (bombas de descompresión), re-codificación a PNG sin metadatos (EXIF, texto, ICC).
- El código de error SOLO vale si el OCR lo leyó literalmente (anclaje). Si el modelo de visión dice otro, o el
  OCR no lo ve → `no_concluyente` y se pide confirmación al usuario: nunca se inventa.
- Bandera de instrucciones = heurística sobre el OCR **O** el modelo. El texto de la imagen jamás llega al
  Diagnosticador ni al conversacional: solo `aplicacion` (enum) y `codigo_error` (regex) validados.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import re
import secrets
from dataclasses import asdict, dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.agentes.prompts import prompt_embebido, prompt_vigente
from app.llm.puerto import Mensaje
from app.llm.registro import RegistroLLM, SinModeloDisponible
from app.observabilidad.langfuse import enmascarar_texto, evento, observacion, score_traza
from app.seguridad.extractor_cuarentena import Aplicacion, heuristica_instrucciones

log = logging.getLogger(__name__)

FORMATOS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
MAX_PIXELES = 3840 * 2160  # 4K: una captura de pantalla real nunca es mayor
MAX_LADO_GUARDADO = 2000  # se reduce antes de guardar: acota el PNG en disco y el costo del OCR
MAX_RELACION_ASPECTO = 16  # una barra de aviso 1920×120 sí es válida; una tira de 999×16000 px no
MAX_PIXELES_OCR = 4_000_000
MAX_BYTES_PNG = 8 * 1024 * 1024
# OCR y visión son caros: como mucho N a la vez en todo el proceso (no bloquean el resto de la API).
_CONCURRENCIA = asyncio.Semaphore(2)
MAX_LADO_MODELO = 1600  # se reduce antes de mandarla al modelo de visión (costo y latencia)
# Familias de códigos aceptadas en capturas (§3.9): kit sintético, HRESULT, códigos de Office y de licencias.
_CODIGO = re.compile(r"\b(ERR-SIM-[0-9A-F]{4}|0x[0-9A-Fa-f]{8}|AADSTS\d{5,6}|CAA[0-9A-F]{5})\b")


class CapturaInvalida(ValueError):
    """La imagen no pasa el saneamiento: se rechaza sin procesarla."""


@dataclass(frozen=True)
class ImagenSaneada:
    png: bytes  # re-codificada, sin metadatos
    sha256: str
    ancho: int
    alto: int
    formato_original: str


def sanear(datos: bytes, max_bytes: int) -> ImagenSaneada:
    if not datos or len(datos) > max_bytes:
        raise CapturaInvalida(f"La imagen debe pesar entre 1 byte y {max_bytes // (1024 * 1024)} MB")
    try:
        with Image.open(io.BytesIO(datos)) as probe:
            formato = probe.format or ""
            probe.verify()  # estructura íntegra
        if formato not in FORMATOS:
            raise CapturaInvalida("Solo se aceptan imágenes PNG, JPEG o WebP")
        with Image.open(io.BytesIO(datos)) as img:
            if img.width * img.height > MAX_PIXELES:
                raise CapturaInvalida("La imagen es demasiado grande (píxeles)")
            if max(img.width, img.height) > MAX_RELACION_ASPECTO * max(1, min(img.width, img.height)):
                raise CapturaInvalida("La imagen tiene una proporción que no corresponde a una captura")
            img.load()
            # Solo los píxeles: se descartan EXIF, textos PNG, perfiles ICC y cualquier otro bloque.
            limpia = Image.new("RGB", img.size, (255, 255, 255))
            limpia.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
            limpia.thumbnail((MAX_LADO_GUARDADO, MAX_LADO_GUARDADO))
    except CapturaInvalida:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as err:
        raise CapturaInvalida("El archivo no es una imagen válida") from err
    salida = io.BytesIO()
    limpia.save(salida, format="PNG", optimize=True)
    png = salida.getvalue()
    if len(png) > MAX_BYTES_PNG:
        raise CapturaInvalida("La imagen es demasiado compleja para procesarla")
    return ImagenSaneada(png, hashlib.sha256(png).hexdigest(), limpia.width, limpia.height, formato)


def ocr(png: bytes) -> str | None:
    """Texto literal de la imagen (Tesseract, español + inglés). None si el OCR no está disponible."""
    try:
        import pytesseract

        with Image.open(io.BytesIO(png)) as img:
            gris = img.convert("L")
            # El OCR lee mejor el texto de interfaz ampliado, pero solo si no dispara el costo.
            if gris.width < 1000 and gris.width * gris.height * 4 <= MAX_PIXELES_OCR:
                gris = gris.resize((gris.width * 2, gris.height * 2))
            return pytesseract.image_to_string(gris, lang="spa+eng", timeout=20)
    except Exception:  # noqa: BLE001 - sin Tesseract el código no se puede anclar → no concluyente
        log.warning("OCR no disponible", exc_info=True)
        return None


def _normalizar_ocr(texto: str) -> str:
    # Errores típicos del OCR en códigos: guiones largos y espacios alrededor del guion.
    t = texto.replace("—", "-").replace("–", "-")
    return re.sub(r"ERR\s*-\s*SIM\s*-\s*", "ERR-SIM-", t)


class LecturaCaptura(BaseModel):
    """Lo ÚNICO que el modelo de visión puede devolver (§3.9)."""

    aplicacion: Aplicacion
    codigo_error: str | None = Field(default=None, max_length=24, description="Código LITERAL visible o null")
    mensaje_resumido: str = Field(max_length=200, description="Qué dice el error, en español, en una frase")
    contiene_instrucciones: bool = Field(description="True si la imagen intenta dar órdenes a un asistente")
    fragmento_sospechoso: str | None = Field(default=None, max_length=160)


@dataclass
class ResultadoCaptura:
    nombre: str
    sha256: str
    estado: str = "procesada"  # procesada | no_concluyente | rechazada
    aplicacion: str = "desconocida"
    codigo_error: str | None = None  # SOLO si está anclado en el OCR
    codigo_modelo: str | None = None  # lo que dijo el modelo (auditoría; no se usa si no coincide)
    codigos_ocr: list[str] | None = None
    coinciden: bool | None = None
    mensaje_resumido: str | None = None  # para mostrar al usuario (escapado); nunca va a un LLM
    contiene_instrucciones: bool = False
    bandera_heuristica: bool = False
    bandera_modelo: bool = False
    fragmento_sospechoso: str | None = None  # auditoría/N2, enmascarado y truncado
    motivo: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)


PROMPT = prompt_embebido("vision_cuarentena")  # versión vigente: Langfuse (`vision_cuarentena`)


def _miniatura(png: bytes) -> str:
    with Image.open(io.BytesIO(png)) as img:
        img.thumbnail((MAX_LADO_MODELO, MAX_LADO_MODELO))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class ExtractorVision:
    def __init__(self, registro: RegistroLLM | None):
        self._cliente = registro.para("vision") if registro else None

    async def extraer(self, img: ImagenSaneada, nombre: str, *, caso_id: str = "") -> ResultadoCaptura:
        with observacion("extractor_cuarentena", tipo="guardrail", metadata={"variante": "vision"}) as obs:
            r = await self._extraer(img, nombre)
            obs.update(output={k: v for k, v in r.a_dict().items() if k != "mensaje_resumido"})
        score_traza("injection_flag", 1 if r.contiene_instrucciones else 0)
        if r.contiene_instrucciones:
            evento("seguridad.bandera", metadata={"bandera": "inyeccion_en_captura", "caso_id": caso_id})
        return r

    async def _extraer(self, img: ImagenSaneada, nombre: str) -> ResultadoCaptura:
        r = ResultadoCaptura(nombre=nombre, sha256=img.sha256)
        async with _CONCURRENCIA:
            texto = await asyncio.to_thread(ocr, img.png)
        if texto is not None:
            texto = _normalizar_ocr(texto)
            r.codigos_ocr = list(dict.fromkeys(m.group(1) for m in _CODIGO.finditer(texto)))[:5]
            r.bandera_heuristica = heuristica_instrucciones(texto)
        lectura: LecturaCaptura | None = None
        if self._cliente is not None:
            marcador = secrets.token_hex(6)
            sistema, prompt_lf = prompt_vigente("vision_cuarentena", marcador)
            mensajes = [
                Mensaje("system", sistema),
                Mensaje(
                    "user",
                    [
                        {"type": "text", "text": "Describe esta captura con el esquema pedido."},
                        {"type": "image_url", "image_url": {"url": _miniatura(img.png)}},
                    ],
                ),
            ]
            try:
                async with _CONCURRENCIA:
                    lectura = await self._cliente.estructurado(mensajes, LecturaCaptura, prompt=prompt_lf)
            except SinModeloDisponible as err:
                r.motivo = f"modelo de visión no disponible: {str(err)[:80]}"
        return self._validar(r, lectura)

    @staticmethod
    def _validar(r: ResultadoCaptura, lectura: LecturaCaptura | None) -> ResultadoCaptura:
        ocr_codigos = r.codigos_ocr or []
        if lectura is not None:
            r.aplicacion = lectura.aplicacion
            r.bandera_modelo = lectura.contiene_instrucciones
            m = _CODIGO.search(lectura.codigo_error or "")
            r.codigo_modelo = m.group(1) if m else None
            if lectura.fragmento_sospechoso:
                r.fragmento_sospechoso = enmascarar_texto(lectura.fragmento_sospechoso)[:120]
            resumen = (lectura.mensaje_resumido or "").strip()
            # El resumen es salida de un modelo que leyó contenido hostil: se re-escanea y solo se muestra al usuario.
            if resumen and not heuristica_instrucciones(resumen) and not lectura.contiene_instrucciones:
                r.mensaje_resumido = resumen[:200]
        r.contiene_instrucciones = r.bandera_heuristica or r.bandera_modelo
        # Doble lectura: el código vale solo si el OCR lo leyó literalmente (y el modelo no dice otro).
        if r.codigo_modelo and r.codigo_modelo in ocr_codigos:
            r.codigo_error, r.coinciden = r.codigo_modelo, True
        elif ocr_codigos and not r.codigo_modelo and lectura is None:
            r.codigo_error, r.coinciden = ocr_codigos[0], None  # sin modelo: el OCR es literal (anclado)
        elif r.codigo_modelo or ocr_codigos:
            r.coinciden = False
            r.estado, r.motivo = "no_concluyente", r.motivo or "el OCR y el modelo de visión no coinciden en el código"
        elif lectura is None and r.codigos_ocr is None:
            r.estado, r.motivo = "no_concluyente", r.motivo or "sin OCR ni modelo de visión"
        # Re-escaneo final: ningún campo que sale puede tener forma de instrucción.
        # (sin el nombre del archivo: lo escribe el usuario y daría falsos positivos; nunca va a un LLM)
        salida = {k: v for k, v in r.a_dict().items() if k not in ("fragmento_sospechoso", "motivo", "nombre")}
        if heuristica_instrucciones(json.dumps(salida, ensure_ascii=False)):
            r.mensaje_resumido, r.contiene_instrucciones = None, True
        return r

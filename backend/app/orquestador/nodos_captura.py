"""Nodo Captura (Módulo B, F7, §3.9).

Procesa las capturas del turno con el extractor de visión en cuarentena y deja en el estado SOLO campos
validados. El aviso al usuario es una plantilla del código:
- código anclado (OCR + visión coinciden) → slot `codigo_error` (origen captura) → evidencia del diagnóstico;
- OCR y visión difieren → `no_concluyente`: se pide al usuario que escriba el código (nunca se inventa);
- instrucciones en la imagen → bandera visible, ignorada: «contiene instrucciones que no sigo».
El resumen del modelo (salida de algo que leyó contenido hostil) se muestra al usuario, pero NO entra al
historial que leen los agentes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langgraph.config import get_stream_writer

from app.agentes.contexto import LineaRevision
from app.integraciones.capturas import AlmacenCapturas
from app.observabilidad.langfuse import evento
from app.orquestador.estado import EstadoCaso, Etapa
from app.seguridad.vision_cuarentena import CapturaInvalida, ExtractorVision, ResultadoCaptura

MAX_CAPTURAS_POR_CASO = 6
APPS_SINTOMA = {"outlook", "teams", "excel", "word", "powerpoint", "onedrive", "impresora", "office"}
NOMBRE_APP = {
    "outlook": "Outlook",
    "teams": "Teams",
    "excel": "Excel",
    "word": "Word",
    "powerpoint": "PowerPoint",
    "onedrive": "OneDrive",
    "impresora": "la impresora",
    "office": "Office",
    "windows": "Windows",
}


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _texto(r: ResultadoCaptura, n: str, con_resumen: bool) -> str:
    if r.estado == "rechazada":
        return f"No pude usar la imagen {n}: {r.motivo}."
    partes: list[str] = []
    if r.codigo_error:
        app = NOMBRE_APP.get(r.aplicacion)
        partes.append(f"En la captura {n} veo el código de error {r.codigo_error}" + (f" ({app})." if app else "."))
        if con_resumen and r.mensaje_resumido:
            partes.append(f"Según la imagen: «{r.mensaje_resumido.rstrip('. ')}».")
    elif r.estado == "no_concluyente":
        partes.append(
            f"En la captura {n} no pude confirmar el código de error con seguridad (la lectura automática y el "
            "modelo no coinciden). ¿Me escribes el código tal como aparece en la ventana?"
        )
    elif not r.contiene_instrucciones:
        partes.append(f"En la captura {n} no veo un código de error.")
    if r.contiene_instrucciones:
        partes.append(f"La imagen {n} contiene instrucciones que no sigo; solo uso los códigos de error.")
    return " ".join(partes)


def textos_captura(r: ResultadoCaptura, indice: int = 1) -> tuple[str, str]:
    """(texto para el usuario, texto para el historial de los agentes).

    El historial NUNCA lleva el nombre del archivo (lo escribe el usuario: texto no confiable que el conversacional
    leería como turno propio) ni el resumen del modelo de visión: se usa «captura N»."""
    return _texto(r, f"«{r.nombre}»", True), _texto(r, f"{indice}", False)


def _linea(r: ResultadoCaptura) -> LineaRevision:
    if r.estado == "rechazada":
        return LineaRevision(f"captura-{r.sha256 or r.nombre}", "fallo", f"Captura {r.nombre}: {r.motivo}")
    detalle = f"código {r.codigo_error}" if r.codigo_error else "sin código confirmado"
    if r.contiene_instrucciones:
        detalle += " · contiene instrucciones (ignoradas)"
    estado = "anomalia" if r.contiene_instrucciones or r.estado == "no_concluyente" else "ok"
    return LineaRevision(f"captura-{r.sha256[:12]}", estado, f"Captura {r.nombre} (OCR + visión): {detalle}.")


class FlujoCaptura:
    def __init__(self, extractor: ExtractorVision, almacen: AlmacenCapturas):
        self.extractor = extractor
        self.almacen = almacen

    @staticmethod
    def hay_capturas(estado: EstadoCaso) -> bool:
        return bool(estado.get("capturas_nuevas"))

    async def captura(self, estado: EstadoCaso) -> dict[str, Any]:
        escribir = get_stream_writer()
        escribir({"tipo": "etapa", "etapa": Etapa.CAPTURA.value})
        caso_id = estado["case_id"]
        previas = list(estado.get("capturas") or [])
        ya = {c.get("sha256") for c in previas}
        slots = dict(estado.get("slots") or {})
        sintoma = dict(estado.get("sintoma") or {})
        seguridad = dict(estado.get("seguridad") or {"banderas": [], "insistencia": {}})
        banderas = list(seguridad.get("banderas") or [])
        textos_usuario: list[str] = []
        textos_historial: list[str] = []
        nuevas: list[dict[str, Any]] = []
        for ref in estado.get("capturas_nuevas") or []:
            if ref.get("sha256") in ya:
                continue  # la misma imagen ya se procesó en este caso
            if len(previas) + len(nuevas) >= MAX_CAPTURAS_POR_CASO:
                ref = {**ref, "error": f"se alcanzó el máximo de {MAX_CAPTURAS_POR_CASO} capturas por caso"}
            if ref.get("error"):
                r = ResultadoCaptura(ref["nombre"], "", estado="rechazada", motivo=ref["error"])
            else:
                try:
                    img = self.almacen.leer(caso_id, ref["sha256"])
                    r = await self.extractor.extraer(img, ref["nombre"], caso_id=caso_id)
                except (CapturaInvalida, OSError):
                    r = ResultadoCaptura(
                        ref["nombre"], ref.get("sha256", ""), estado="rechazada", motivo="no se pudo leer"
                    )
            ya.add(r.sha256)
            linea = _linea(r)
            escribir({"tipo": "revisando", "id": linea.id, "estado": linea.estado, "texto": linea.texto})
            u, h = textos_captura(r, len(previas) + len(nuevas) + 1)
            textos_usuario.append(u)
            textos_historial.append(h)
            # El resumen del modelo solo va al stream del usuario: el estado no guarda texto derivado de la imagen.
            d = {
                **{k: v for k, v in r.a_dict().items() if k != "mensaje_resumido"},
                "ruta": ref.get("ruta"),
                "tamano_bytes": ref.get("tamano_bytes", 0),
                "hora": _ahora(),
            }
            nuevas.append(d)
            escribir(
                {
                    "tipo": "captura",
                    "datos": {
                        "nombre": r.nombre,
                        "estado": r.estado,
                        "codigo_error": r.codigo_error,
                        "aplicacion": r.aplicacion,
                        "mensaje_resumido": r.mensaje_resumido if r.codigo_error else None,
                        "contiene_instrucciones": r.contiene_instrucciones,
                        "motivo": r.motivo if r.estado != "procesada" else None,
                    },
                }
            )
            if r.codigo_error:
                slots["codigo_error"] = {"valor": r.codigo_error, "origen": "captura"}
            if r.aplicacion in APPS_SINTOMA and sintoma.get("aplicacion") in (None, "desconocida"):
                sintoma["aplicacion"] = r.aplicacion
            if r.contiene_instrucciones:
                banderas.append({"bandera": "inyeccion_en_captura", "turno": estado.get("turnos"), "hora": _ahora()})
                evento("captura.instrucciones", metadata={"caso_id": caso_id, "captura": r.sha256[:12]})
        seguridad["banderas"] = banderas
        cambios: dict[str, Any] = {
            "etapa": Etapa.CAPTURA.value,
            "capturas": [*previas, *nuevas],
            "capturas_nuevas": [],
            "slots": slots,
            "sintoma": sintoma,
            "seguridad": seguridad,
            "linea_tiempo": [
                {
                    "hora": _ahora(),
                    "etapa": Etapa.CAPTURA.value,
                    "detalle": "; ".join(
                        f"{c['nombre']}: {c['estado']}"
                        + (f" {c['codigo_error']}" if c.get("codigo_error") else "")
                        + (" [instrucciones]" if c.get("contiene_instrucciones") else "")
                        for c in nuevas
                    )
                    or "capturas repetidas",
                }
            ],
        }
        if textos_usuario:
            texto = " ".join(textos_usuario)
            escribir({"tipo": "texto", "texto": texto})
            cambios["mensajes"] = [{"rol": "sistema", "texto": " ".join(textos_historial), "hora": _ahora()}]
            cambios["captura_informada_turno"] = estado.get("turnos")
        return cambios

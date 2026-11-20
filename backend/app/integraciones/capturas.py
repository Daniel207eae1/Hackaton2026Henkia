"""Almacén de capturas YA saneadas (F7). Disco local en un volumen propio; nunca se sirven por HTTP.

Las imágenes llegan como partes `file` (data URL) del último mensaje del chat (AI SDK). Aquí se decodifican
con límites, se sanean (re-codificación sin metadatos) y se guardan por `case_id/sha256.png`. Al grafo solo
pasa una referencia; los bytes nunca entran al estado del caso ni al checkpointer.
"""

from __future__ import annotations

import base64
import binascii
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.seguridad.vision_cuarentena import MAX_BYTES_PNG, CapturaInvalida, ImagenSaneada, sanear

_DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|jpg|webp));base64,([A-Za-z0-9+/=\s]+)$")
_NOMBRE = re.compile(r"[^\w.\- ()áéíóúñÁÉÍÓÚÑ]")


@dataclass
class RefCaptura:
    nombre: str
    sha256: str | None = None
    ruta: str | None = None
    tamano_bytes: int = 0
    error: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def nombre_seguro(nombre: str | None, i: int) -> str:
    limpio = _NOMBRE.sub("_", (nombre or "").strip())[:60]
    return limpio or f"captura-{i + 1}.png"


class AlmacenCapturas:
    def __init__(self, directorio: Path, max_bytes: int):
        self.directorio = Path(directorio)
        self.max_bytes = max_bytes

    def _ruta(self, case_id: str, sha256: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", case_id) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise CapturaInvalida("Referencia de captura inválida")
        return self.directorio / case_id / f"{sha256}.png"

    def recibir(self, case_id: str, parte: dict[str, Any], i: int) -> RefCaptura:
        nombre = nombre_seguro(parte.get("filename"), i)
        url = str(parte.get("url") or "")
        m = _DATA_URL.match(url)
        if not m:
            return RefCaptura(nombre, error="Solo se aceptan imágenes PNG, JPEG o WebP")
        if len(m.group(2)) * 3 // 4 > self.max_bytes:  # antes de decodificar
            return RefCaptura(nombre, error=f"La imagen supera {self.max_bytes // (1024 * 1024)} MB")
        try:
            datos = base64.b64decode(m.group(2), validate=False)
            img = sanear(datos, self.max_bytes)
        except (CapturaInvalida, binascii.Error) as err:
            return RefCaptura(nombre, error=str(err) if isinstance(err, CapturaInvalida) else "Imagen corrupta")
        ruta = self._ruta(case_id, img.sha256)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(img.png)
        return RefCaptura(nombre, img.sha256, str(ruta), len(img.png))

    def leer(self, case_id: str, sha256: str) -> ImagenSaneada:
        png = self._ruta(case_id, sha256).read_bytes()
        # Ya está saneada; se vuelve a pasar por `sanear` (barato) para no confiar en el disco.
        return sanear(png, max(self.max_bytes, MAX_BYTES_PNG))

    def purgar(self, dias: int) -> int:
        """Borra las carpetas de caso sin cambios en `dias` días (retención mínima de datos). Devuelve cuántas."""
        if dias <= 0 or not self.directorio.is_dir():
            return 0
        limite = time.time() - dias * 86_400
        borradas = 0
        for carpeta in self.directorio.iterdir():
            if not carpeta.is_dir() or carpeta.is_symlink():
                continue
            try:  # un enlace roto o un archivo que desaparece no corta la purga de las demás carpetas
                ultima = max((f.lstat().st_mtime for f in carpeta.iterdir()), default=carpeta.lstat().st_mtime)
            except OSError:
                continue
            if ultima < limite:
                shutil.rmtree(carpeta, ignore_errors=True)
                borradas += 1
        return borradas

"""Límite de solicitudes por persona (ventana deslizante en memoria, un proceso).

Protege el chat (cada turno cuesta llamadas a modelos y al MCP) y los POST de acciones humanas. La clave es la
persona (`X-Ver-Como` en demo) y, si no viene, la IP. No sustituye un límite en el *gateway* cuando haya varias
réplicas: es la defensa mínima de esta instancia.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque

MAX_CLAVES = 5_000


class LimiteTasa:
    def __init__(self, maximo: int, ventana_s: float = 60.0, reloj=time.monotonic):  # noqa: ANN001
        self.maximo = maximo
        self.ventana_s = ventana_s
        self._reloj = reloj
        self._marcas: OrderedDict[str, deque[float]] = OrderedDict()

    def permitir(self, clave: str) -> tuple[bool, int]:
        """(permitido, segundos para reintentar)."""
        if self.maximo <= 0:  # 0 = sin límite
            return True, 0
        ahora = self._reloj()
        marcas = self._marcas.setdefault(clave, deque())
        self._marcas.move_to_end(clave)
        while marcas and ahora - marcas[0] >= self.ventana_s:
            marcas.popleft()
        if len(marcas) >= self.maximo:
            return False, max(1, int(self.ventana_s - (ahora - marcas[0])) + 1)
        marcas.append(ahora)
        while len(self._marcas) > MAX_CLAVES:  # LRU con tope fijo: claves nuevas sin fin no agotan memoria
            self._marcas.popitem(last=False)
        return True, 0

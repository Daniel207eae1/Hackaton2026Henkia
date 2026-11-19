"""Puerto del directorio (`org`) y doble en memoria.

El rol de una persona SIEMPRE sale de aquí (BD), nunca del chat (ADR 0006).
Cuando P2 publique `db/CONTRATO_SQL.md`, se agrega `RepositorioDirectorioPostgres` con la misma
interfaz y se elige por `DATABASE_URL`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol


class Rol(StrEnum):
    COLABORADOR = "colaborador"
    N2 = "n2"
    REVISOR_KB = "revisor_kb"


@dataclass(frozen=True)
class Persona:
    id: str
    nombre: str
    correo: str
    rol: Rol
    area: str
    equipo_id: str | None = None
    nivel_tecnico: str | None = None  # bajo | medio | alto (solo colaboradores)
    etiqueta: str | None = None  # texto del selector «Ver como» (p. ej., «Escenario 1 · …»)
    hostname: str | None = None  # nombre del equipo en el directorio (candidato para Zabbix)

    def a_dict(self) -> dict:
        return asdict(self)


class RepositorioDirectorio(Protocol):
    async def listar_personas_demo(self) -> list[Persona]: ...

    async def obtener_persona(self, persona_id: str) -> Persona | None: ...


# Personas 100 % sintéticas para el doble (dominio @ejemplo.test). P2 entrega las reales de `org`.
_PERSONAS_DEMO: tuple[Persona, ...] = (
    Persona(
        "USR-SIM-001",
        "Ana Prueba",
        "ana.prueba@ejemplo.test",
        Rol.COLABORADOR,
        "Finanzas",
        "EQ-SIM-001",
        "bajo",
    ),
    Persona(
        "USR-SIM-002",
        "Bruno Ficticio",
        "bruno.ficticio@ejemplo.test",
        Rol.COLABORADOR,
        "Comercial",
        "EQ-SIM-002",
        "medio",
    ),
    Persona(
        "USR-SIM-003",
        "Carla Ejemplo",
        "carla.ejemplo@ejemplo.test",
        Rol.COLABORADOR,
        "Operaciones",
        "EQ-SIM-003",
        "alto",
    ),
    Persona("TEC-SIM-01", "Diego Soporte", "diego.soporte@ejemplo.test", Rol.N2, "Mesa de servicio"),
    Persona("TEC-SIM-02", "Elena Soporte", "elena.soporte@ejemplo.test", Rol.N2, "Mesa de servicio"),
    Persona(
        "REV-SIM-01",
        "Fabio Revisor",
        "fabio.revisor@ejemplo.test",
        Rol.REVISOR_KB,
        "Gestión del conocimiento",
    ),
)


class RepositorioDirectorioMemoria:
    def __init__(self, personas: tuple[Persona, ...] = _PERSONAS_DEMO):
        self._personas = {p.id: p for p in personas}

    async def listar_personas_demo(self) -> list[Persona]:
        return list(self._personas.values())

    async def obtener_persona(self, persona_id: str) -> Persona | None:
        return self._personas.get(persona_id)

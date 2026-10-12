"""Contratos para lo que ZEA MAYZ todavía no hace: ilustrar y maquetar.

Ni la generación de imágenes ni la maquetación final están implementadas: el
repositorio no tiene nada con qué hacerlas bien, y hacerlas mal sería peor que
no hacerlas. Lo que sí hay son las **especificaciones** (qué ilustrar, con qué
elementos, apoyado en qué conceptos) y estos contratos, para que el día que se
añada un generador local o un maquetador baste con implementar una clase.

Cualquier implementación futura tiene que respetar lo mismo que el resto de
Tatewari: ejecución local (AGENTS.md, regla 1) y escribir solo a través de una
`Jaula`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

__all__ = [
    "EspecificacionIlustracion",
    "Vineta",
    "GeneradorIlustraciones",
    "Maquetador",
    "SinGenerador",
    "SinMaquetador",
    "NoDisponible",
]


class NoDisponible(Exception):
    """La capacidad existe como contrato, pero no hay implementación todavía."""


@dataclass(frozen=True)
class EspecificacionIlustracion:
    """Lo que una ilustración tiene que mostrar, y en qué se apoya."""

    identificador: str
    descripcion: str
    elementos: tuple[str, ...] = ()
    conceptos: tuple[str, ...] = ()
    escena: str = ""


@dataclass(frozen=True)
class Vineta:
    """Una viñeta del storyboard."""

    numero: int
    descripcion: str
    texto: str = ""
    ilustracion: EspecificacionIlustracion | None = None


@runtime_checkable
class GeneradorIlustraciones(Protocol):
    """Genera una imagen a partir de su especificación. Local, siempre."""

    def generar(self, especificacion: EspecificacionIlustracion, destino: Path) -> Path: ...


@runtime_checkable
class Maquetador(Protocol):
    """Monta el libro final a partir de capítulos aprobados."""

    def maquetar(self, capitulos: Sequence[Path], destino: Path) -> Path: ...


@dataclass
class SinGenerador:
    """El generador por defecto: dice con claridad que no hay ninguno."""

    motivo: str = field(
        default=(
            "La generación de ilustraciones todavía no está implementada. Las "
            "especificaciones están en 08_ILUSTRACIONES para un ilustrador o para "
            "un generador local futuro."
        )
    )

    def generar(self, especificacion: EspecificacionIlustracion, destino: Path) -> Path:
        raise NoDisponible(self.motivo)


@dataclass
class SinMaquetador:
    motivo: str = field(
        default=(
            "La maquetación del libro todavía no está implementada. Los capítulos "
            "aprobados quedan en 05_GUION y 09_LIBRO como Markdown."
        )
    )

    def maquetar(self, capitulos: Sequence[Path], destino: Path) -> Path:
        raise NoDisponible(self.motivo)

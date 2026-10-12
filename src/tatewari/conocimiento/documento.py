"""El documento ya extraído: texto en fragmentos que saben de dónde vienen.

Un `Fragmento` es la unidad de trazabilidad de todo Knowledge Studio. Cada nota
que salga al final podrá decir «esto está en la página 4 de tal PDF» porque el
fragmento del que salió lo sabía desde el principio. Nada de lo que viene después
calcula ubicaciones: se heredan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Fragmento", "Documento", "ErrorDocumento", "NR"]

NR = "NR"


class ErrorDocumento(Exception):
    """No se pudo leer el documento. El mensaje dice por qué y qué hacer."""


@dataclass(frozen=True)
class Fragmento:
    """Un trozo de texto con su ubicación en el documento original.

    `ubicacion` es legible («p. 4», «diapositiva 2», «sección «Suelos»») y es lo
    que aparece en las notas. `numero` es la página o diapositiva si la hay, para
    ordenar y agrupar.
    """

    id: str
    texto: str
    ubicacion: str
    numero: int | None = None


@dataclass
class Documento:
    """Lo que se sabe de un documento después de extraerlo."""

    ruta: Path
    nombre: str
    tipo: str
    sha256: str
    tamano: int
    titulo: str = NR
    autores: str = NR
    fecha: str = NR
    unidades: int = 0
    unidad: str = "secciones"
    fragmentos: list[Fragmento] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        """Todo el texto, en orden. Para búsquedas, no para mostrar."""
        return "\n\n".join(f.texto for f in self.fragmentos)

    @property
    def caracteres(self) -> int:
        return sum(len(f.texto) for f in self.fragmentos)

    @property
    def titulo_legible(self) -> str:
        """El título declarado, o el nombre del archivo si no declara ninguno."""
        return self.titulo if self.titulo != NR else Path(self.nombre).stem

"""La jaula de rutas: Tatewari solo escribe donde se le ha autorizado.

Knowledge Studio escribe notas en un Vault de Obsidian que es de la persona, no
del programa. Un error aquí no rompe una prueba: borra o pisa apuntes de alguien.
Por eso **toda** escritura de este paquete pasa por una `Jaula`, que:

- resuelve la ruta entera (``..``, enlaces simbólicos, unidades de Windows) antes
  de compararla, así que ``Vault/../../Windows`` no se cuela;
- solo admite rutas **dentro** de las raíces autorizadas: el Vault configurado y
  la carpeta de datos del proyecto;
- rechaza carpetas internas que no son de notas: ``.obsidian`` (la configuración
  de la aplicación) y ``.git``.

Y el modelo de lenguaje **nunca** propone una ruta. Los nombres de archivo salen
de `nombre_de_nota`, que es determinista y limpia todo lo que Windows u Obsidian
no admiten. Lo peor que puede hacer un modelo con un título malicioso es un
nombre de nota feo, nunca un archivo fuera del Vault.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

__all__ = [
    "ErrorRuta",
    "Jaula",
    "nombre_de_nota",
    "CARPETAS_PROHIBIDAS",
]

#: Carpetas donde nunca se escribe, aunque estén dentro de una raíz autorizada.
CARPETAS_PROHIBIDAS = (".obsidian", ".git", ".trash")

#: Caracteres que Windows no admite en un nombre de archivo, más los que rompen
#: un enlace de Obsidian (`#` abre un encabezado, `^` un bloque, `|` un alias y
#: los corchetes cierran el enlace).
_PROHIBIDOS_EN_NOMBRE = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')

#: Nombres reservados de Windows: un archivo llamado «CON.md» no se puede crear.
_RESERVADOS_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}

#: Largo máximo del nombre, sin la extensión. Windows admite rutas de 260
#: caracteres y un Vault en OneDrive ya gasta un buen trozo en la carpeta.
LARGO_NOMBRE = 120


class ErrorRuta(Exception):
    """Se intentó escribir fuera de lo autorizado. El mensaje dice dónde."""


def nombre_de_nota(titulo: str) -> str:
    """Un nombre de archivo seguro para una nota, sin extensión.

    Quita lo que Windows u Obsidian no admiten, colapsa espacios, recorta y evita
    los nombres reservados. Conserva los acentos: Obsidian y NTFS los manejan
    bien, y «Nitrógeno total» se lee mejor que «Nitrogeno total».

    Nunca devuelve una cadena vacía: un título que se queda en nada tras limpiar
    pasa a llamarse «Sin título».
    """
    limpio = unicodedata.normalize("NFC", str(titulo or ""))
    limpio = _PROHIBIDOS_EN_NOMBRE.sub(" ", limpio)
    limpio = " ".join(limpio.split())
    # Windows tampoco admite un nombre que acabe en punto o espacio.
    limpio = limpio.strip(" .")[:LARGO_NOMBRE].strip(" .")
    if not limpio:
        limpio = "Sin título"
    if limpio.split(".")[0].upper() in _RESERVADOS_WINDOWS:
        limpio = f"{limpio}_"
    return limpio


@dataclass
class Jaula:
    """Las raíces donde se puede escribir, y la única puerta para hacerlo."""

    raices: tuple[Path, ...]
    escritos: list[Path] = field(default_factory=list)

    @classmethod
    def para(cls, *raices: Path | str | None) -> "Jaula":
        """Una jaula con estas raíces. Las que sean `None` se ignoran."""
        resueltas = tuple(
            Path(os.path.normpath(Path(r).expanduser().resolve()))
            for r in raices
            if r is not None and str(r).strip()
        )
        if not resueltas:
            raise ErrorRuta(
                "No hay ninguna carpeta autorizada para escribir. Configura el Vault "
                "de Obsidian en TATEWARI_OBSIDIAN_VAULT."
            )
        return cls(raices=resueltas)

    def autorizada(self, ruta: Path | str) -> Path:
        """Devuelve la ruta resuelta si se puede escribir en ella. Si no, falla.

        La comprobación se hace sobre la ruta **resuelta**, así que ni ``..`` ni un
        enlace simbólico que apunte fuera del Vault la pasan.
        """
        destino = Path(os.path.normpath(Path(ruta).expanduser().resolve()))
        raiz = next((r for r in self.raices if _dentro(destino, r)), None)
        if raiz is None:
            autorizadas = ", ".join(str(r) for r in self.raices)
            raise ErrorRuta(
                f"Tatewari no puede escribir en {destino}: está fuera de las "
                f"carpetas autorizadas ({autorizadas})."
            )
        relativa = destino.relative_to(raiz)
        prohibida = next(
            (parte for parte in relativa.parts if parte.lower() in CARPETAS_PROHIBIDAS),
            None,
        )
        if prohibida is not None:
            raise ErrorRuta(
                f"Tatewari no escribe dentro de «{prohibida}» ({destino}): es una "
                f"carpeta interna, no de notas."
            )
        return destino

    def escribir_texto(self, ruta: Path | str, contenido: str) -> Path:
        """Escribe `contenido` en UTF-8 con saltos LF, dentro de la jaula."""
        destino = self.autorizada(ruta)
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            with open(destino, "w", encoding="utf-8", newline="\n") as manejador:
                manejador.write(contenido)
        except PermissionError as error:
            raise ErrorRuta(
                f"Sin permiso para escribir en {destino}. Si el Vault está en "
                f"OneDrive, comprueba que el archivo no esté abierto o bloqueado."
            ) from error
        self.escritos.append(destino)
        return destino

    def copiar(self, origen: Path | str, destino: Path | str) -> Path:
        """Copia un archivo **dentro** de la jaula. El origen puede estar fuera.

        Leer está permitido en cualquier sitio: la persona elige qué documento
        entregar. Lo que se controla es dónde se escribe.
        """
        final = self.autorizada(destino)
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(Path(origen).read_bytes())
        except PermissionError as error:
            raise ErrorRuta(f"Sin permiso para copiar a {final}.") from error
        self.escritos.append(final)
        return final

    def crear_carpeta(self, ruta: Path | str) -> Path:
        destino = self.autorizada(ruta)
        try:
            destino.mkdir(parents=True, exist_ok=True)
        except PermissionError as error:
            raise ErrorRuta(f"Sin permiso para crear la carpeta {destino}.") from error
        return destino


def _dentro(ruta: Path, raiz: Path) -> bool:
    """¿`ruta` está dentro de `raiz` (o es ella)? Sin distinguir mayúsculas en Windows."""
    if os.name == "nt":
        ruta = Path(str(ruta).casefold())
        raiz = Path(str(raiz).casefold())
    try:
        ruta.relative_to(raiz)
    except ValueError:
        return False
    return True


def primera_ruta_libre(carpeta: Path, nombre: str, existentes: Iterable[Path] = ()) -> Path:
    """`carpeta/nombre.md`, o `nombre (2).md` si ya existe. Nunca pisa un archivo."""
    ocupadas = {str(p).casefold() for p in existentes}
    candidato = carpeta / f"{nombre}.md"
    numero = 2
    while candidato.exists() or str(candidato).casefold() in ocupadas:
        candidato = carpeta / f"{nombre} ({numero}).md"
        numero += 1
    return candidato

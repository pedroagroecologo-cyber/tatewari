"""Ingesta: qué documento es, si se puede leer, y dejar el original en el Vault.

El tipo se decide por la extensión **y** por los primeros bytes. Un `.pdf` que no
empieza por ``%PDF`` no es un PDF, es un archivo mal nombrado o corrupto, y es
mejor decirlo aquí que dejar que el extractor falle con un error críptico.

Formatos admitidos: PDF, DOCX, PPTX, TXT y Markdown. Las imágenes se reconocen
para poder decir con claridad que el OCR todavía no está (ver docs/ROADMAP.md),
en vez de rechazarlas como si fueran basura.

El original se **copia** a la carpeta de materia del Vault; nunca se mueve ni se
modifica el archivo que entregó la persona.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .documento import ErrorDocumento

__all__ = [
    "TIPOS_ADMITIDOS",
    "Ingesta",
    "detectar_tipo",
    "ingerir",
    "huella",
]

#: Extensión -> tipo interno.
TIPOS_ADMITIDOS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
}

#: Se reconocen para dar un mensaje útil, no porque se procesen.
_IMAGENES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic"}

#: Formatos antiguos de Office: binarios, no ZIP. Se piden convertidos.
_OFFICE_ANTIGUO = {".doc": "DOCX", ".ppt": "PPTX"}

#: Más grande que esto no se procesa de una vez: un modelo local tardaría horas.
TAMANO_MAXIMO = 80 * 1024 * 1024


@dataclass(frozen=True)
class Ingesta:
    """El documento aceptado, antes de extraer nada."""

    ruta: Path
    tipo: str
    sha256: str
    tamano: int


def huella(ruta: Path) -> str:
    """SHA-256 del archivo. Identifica el documento aunque cambie de nombre."""
    resumen = hashlib.sha256()
    with open(ruta, "rb") as manejador:
        for bloque in iter(lambda: manejador.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def detectar_tipo(ruta: Path) -> str:
    """El tipo interno del documento, comprobado contra su contenido.

    Lanza `ErrorDocumento` con un mensaje que dice qué hacer si el formato no se
    admite o si el archivo no es lo que dice su extensión.
    """
    extension = ruta.suffix.lower()

    if extension in _IMAGENES:
        raise ErrorDocumento(
            f"«{ruta.name}» es una imagen. El OCR todavía no está implementado en "
            f"Knowledge Studio (está en docs/ROADMAP.md). Por ahora, pásala a texto "
            f"o a un PDF con texto y vuelve a intentarlo."
        )
    if extension in _OFFICE_ANTIGUO:
        raise ErrorDocumento(
            f"«{ruta.name}» está en el formato antiguo de Office. Ábrelo y guárdalo "
            f"como {_OFFICE_ANTIGUO[extension]} para que Tatewari pueda leerlo."
        )
    tipo = TIPOS_ADMITIDOS.get(extension)
    if tipo is None:
        admitidos = ", ".join(sorted({e.lstrip('.').upper() for e in TIPOS_ADMITIDOS}))
        raise ErrorDocumento(
            f"El formato «{extension or 'sin extensión'}» de «{ruta.name}» no se "
            f"admite. Formatos admitidos: {admitidos}."
        )

    with open(ruta, "rb") as manejador:
        cabecera = manejador.read(8)

    if tipo == "pdf" and not cabecera.startswith(b"%PDF"):
        raise ErrorDocumento(
            f"«{ruta.name}» dice ser un PDF pero no lo es por dentro: está dañado o "
            f"tiene la extensión equivocada."
        )
    if tipo in ("docx", "pptx"):
        if not cabecera.startswith(b"PK"):
            raise ErrorDocumento(
                f"«{ruta.name}» no es un {tipo.upper()} válido: no tiene la forma "
                f"de un archivo de Office moderno. Puede estar dañado."
            )
        carpeta = "word/" if tipo == "docx" else "ppt/"
        try:
            with zipfile.ZipFile(ruta) as zip_:
                nombres = zip_.namelist()
        except zipfile.BadZipFile as error:
            raise ErrorDocumento(f"«{ruta.name}» está dañado: {error}.") from error
        if not any(nombre.startswith(carpeta) for nombre in nombres):
            raise ErrorDocumento(
                f"«{ruta.name}» es un archivo de Office, pero no un {tipo.upper()}: "
                f"le falta la carpeta interna «{carpeta}»."
            )
    return tipo


def ingerir(ruta: Path | str) -> Ingesta:
    """Acepta un documento: existe, se puede leer, y su tipo es el que dice."""
    ruta = Path(ruta).expanduser()
    if not ruta.exists():
        raise ErrorDocumento(f"No existe el documento: {ruta}")
    if ruta.is_dir():
        raise ErrorDocumento(
            f"{ruta} es una carpeta. Para procesar todos sus documentos usa "
            f"«tatewari conocimiento materia»."
        )
    try:
        tamano = ruta.stat().st_size
    except PermissionError as error:
        raise ErrorDocumento(f"Sin permiso para leer {ruta}.") from error
    if tamano == 0:
        raise ErrorDocumento(f"«{ruta.name}» está vacío.")
    if tamano > TAMANO_MAXIMO:
        raise ErrorDocumento(
            f"«{ruta.name}» pesa {tamano // (1024 * 1024)} MB. El máximo es "
            f"{TAMANO_MAXIMO // (1024 * 1024)} MB: pártelo por capítulos."
        )
    try:
        tipo = detectar_tipo(ruta)
        return Ingesta(ruta=ruta.resolve(), tipo=tipo, sha256=huella(ruta), tamano=tamano)
    except PermissionError as error:
        raise ErrorDocumento(f"Sin permiso para leer {ruta}.") from error

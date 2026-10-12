"""Extracción de texto, con la ubicación de cada trozo. Determinista, sin modelo.

Cada formato se lee con lo más sencillo que funciona:

- **PDF**: PyMuPDF (``pip install -e ".[documentos]"``), una página por
  fragmento. Una página sin texto se avisa: casi siempre es un escaneo, y el OCR
  todavía no está.
- **DOCX** y **PPTX**: la biblioteca estándar. Los dos son un ZIP con XML dentro,
  y leer el XML directamente evita dos dependencias (python-docx, python-pptx)
  que para sacar texto no aportan nada. Un DOCX se parte por sus títulos; un
  PPTX, por diapositiva, con las notas del orador si las tiene.
- **TXT** y **Markdown**: lectura directa. El Markdown se parte por encabezados;
  el texto plano, por bloques separados por líneas en blanco.

Aquí no se interpreta nada. Lo que sale es texto y su ubicación; qué significa lo
decide el análisis, más adelante, y por separado.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from .documento import NR, Documento, ErrorDocumento, Fragmento
from .ingesta import Ingesta

__all__ = ["extraer", "pdf_disponible", "LIMITE_XML"]

#: Tamaño máximo descomprimido de un XML interno de un DOCX o PPTX. Un documento
#: normal no llega ni a una décima parte; esto para una bomba ZIP antes de que
#: llene la memoria.
LIMITE_XML = 60 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_DCTERMS = "{http://purl.org/dc/terms/}"

#: Estilos de párrafo que Word usa para los títulos, en inglés y en español.
_ESTILOS_TITULO = ("heading", "titulo", "ttulo", "title", "encabezado")

_ENCABEZADO_MD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def pdf_disponible() -> bool:
    """¿Está PyMuPDF instalado? Sin él no se pueden leer PDF."""
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        try:
            import fitz  # noqa: F401
        except ImportError:
            return False
    return True


def extraer(ingesta: Ingesta) -> Documento:
    """Extrae el texto de un documento ya aceptado por la ingesta."""
    documento = Documento(
        ruta=ingesta.ruta,
        nombre=ingesta.ruta.name,
        tipo=ingesta.tipo,
        sha256=ingesta.sha256,
        tamano=ingesta.tamano,
    )
    extractor = {
        "pdf": _extraer_pdf,
        "docx": _extraer_docx,
        "pptx": _extraer_pptx,
        "txt": _extraer_txt,
        "md": _extraer_md,
    }[ingesta.tipo]
    extractor(documento)

    if not any(f.texto.strip() for f in documento.fragmentos):
        documento.avisos.append(
            "No se ha encontrado texto en el documento. Si es un escaneo, hace "
            "falta OCR, que todavía no está implementado."
        )
    return documento


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _importar_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        try:
            import fitz

            return fitz
        except ImportError as error:
            raise ErrorDocumento(
                "Para leer PDF hace falta PyMuPDF, que no está instalado. "
                'Instálalo con:  python -m pip install -e ".[documentos]"'
            ) from error


def _fecha_pdf(crudo: str) -> str:
    """«D:20240315120000» -> «2024-03-15». Si no se entiende, NR."""
    encontrado = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?", crudo or "")
    if not encontrado:
        return NR
    anio, mes, dia = encontrado.groups()
    return "-".join(parte for parte in (anio, mes, dia) if parte)


def _extraer_pdf(documento: Documento) -> None:
    pymupdf = _importar_pymupdf()
    try:
        pdf = pymupdf.open(documento.ruta)
    except Exception as error:  # PyMuPDF lanza tipos propios según la versión
        raise ErrorDocumento(
            f"No se pudo abrir el PDF «{documento.nombre}»: parece dañado ({error})."
        ) from error

    with pdf:
        if pdf.needs_pass:
            raise ErrorDocumento(
                f"«{documento.nombre}» está protegido con contraseña. Quítale la "
                f"protección y vuelve a intentarlo."
            )
        metadatos = pdf.metadata or {}
        documento.titulo = (metadatos.get("title") or "").strip() or NR
        documento.autores = (metadatos.get("author") or "").strip() or NR
        documento.fecha = _fecha_pdf(metadatos.get("creationDate") or "")
        documento.unidad = "páginas"
        documento.unidades = pdf.page_count

        vacias: list[int] = []
        for indice in range(pdf.page_count):
            try:
                texto = pdf.load_page(indice).get_text("text") or ""
            except Exception as error:
                documento.avisos.append(
                    f"No se pudo leer la página {indice + 1}: {error}."
                )
                continue
            if not texto.strip():
                vacias.append(indice + 1)
                continue
            documento.fragmentos.append(
                Fragmento(
                    id=f"p{indice + 1}",
                    texto=texto,
                    ubicacion=f"p. {indice + 1}",
                    numero=indice + 1,
                )
            )
        if vacias:
            lista = ", ".join(str(n) for n in vacias[:12])
            mas = "…" if len(vacias) > 12 else ""
            documento.avisos.append(
                f"{len(vacias)} páginas sin texto ({lista}{mas}): pueden ser "
                f"escaneos o figuras. El OCR todavía no está implementado."
            )


# ---------------------------------------------------------------------------
# Office: DOCX y PPTX
# ---------------------------------------------------------------------------


def _leer_xml(zip_: zipfile.ZipFile, nombre: str) -> ElementTree.Element | None:
    """Lee y analiza un XML del ZIP, o `None` si no está. Con límite de tamaño."""
    try:
        info = zip_.getinfo(nombre)
    except KeyError:
        return None
    if info.file_size > LIMITE_XML:
        raise ErrorDocumento(
            f"El documento contiene un bloque interno de {info.file_size // (1024 * 1024)} "
            f"MB ({nombre}). Es demasiado grande para ser texto: no se procesa."
        )
    try:
        return ElementTree.fromstring(zip_.read(nombre))
    except ElementTree.ParseError as error:
        raise ErrorDocumento(f"El documento está dañado: «{nombre}» no es XML válido ({error}).") from error


def _abrir_zip(documento: Documento) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(documento.ruta)
    except zipfile.BadZipFile as error:
        raise ErrorDocumento(f"«{documento.nombre}» está dañado: {error}.") from error


def _metadatos_office(zip_: zipfile.ZipFile, documento: Documento) -> None:
    nucleo = _leer_xml(zip_, "docProps/core.xml")
    if nucleo is None:
        return
    titulo = nucleo.findtext(f"{_DC}title") or ""
    autor = nucleo.findtext(f"{_DC}creator") or ""
    fecha = nucleo.findtext(f"{_DCTERMS}created") or ""
    documento.titulo = titulo.strip() or NR
    documento.autores = autor.strip() or NR
    documento.fecha = fecha[:10] if fecha else NR


def _texto_parrafo_word(parrafo: ElementTree.Element) -> str:
    partes: list[str] = []
    for nodo in parrafo.iter():
        if nodo.tag == f"{_W}t" and nodo.text:
            partes.append(nodo.text)
        elif nodo.tag == f"{_W}tab":
            partes.append("\t")
        elif nodo.tag in (f"{_W}br", f"{_W}cr"):
            partes.append("\n")
    return "".join(partes)


def _es_titulo_word(parrafo: ElementTree.Element) -> bool:
    propiedades = parrafo.find(f"{_W}pPr")
    if propiedades is None:
        return False
    if propiedades.find(f"{_W}outlineLvl") is not None:
        return True
    estilo = propiedades.find(f"{_W}pStyle")
    valor = (estilo.get(f"{_W}val") if estilo is not None else "") or ""
    return valor.lower().startswith(_ESTILOS_TITULO)


def _extraer_docx(documento: Documento) -> None:
    with _abrir_zip(documento) as zip_:
        _metadatos_office(zip_, documento)
        raiz = _leer_xml(zip_, "word/document.xml")
    if raiz is None:
        raise ErrorDocumento(
            f"«{documento.nombre}» no tiene cuerpo de documento (word/document.xml)."
        )
    cuerpo = raiz.find(f"{_W}body")
    if cuerpo is None:
        return

    secciones: list[tuple[str, list[str]]] = [("inicio del documento", [])]
    for bloque in cuerpo:
        if bloque.tag == f"{_W}p":
            texto = _texto_parrafo_word(bloque).strip()
            if not texto:
                continue
            if _es_titulo_word(bloque):
                secciones.append((texto, [texto]))
            else:
                secciones[-1][1].append(texto)
        elif bloque.tag == f"{_W}tbl":
            for fila in bloque.iter(f"{_W}tr"):
                celdas = [
                    " ".join(_texto_parrafo_word(p).strip() for p in celda.iter(f"{_W}p")).strip()
                    for celda in fila.iter(f"{_W}tc")
                ]
                if any(celdas):
                    secciones[-1][1].append(" | ".join(celdas))

    numero = 0
    for titulo, lineas in secciones:
        if not lineas:
            continue
        numero += 1
        documento.fragmentos.append(
            Fragmento(
                id=f"s{numero}",
                texto="\n".join(lineas),
                ubicacion=_ubicacion_seccion(titulo),
                numero=numero,
            )
        )
    documento.unidad = "secciones"
    documento.unidades = numero


def _orden_diapositivas(zip_: zipfile.ZipFile) -> list[str]:
    """Las diapositivas en el orden de la presentación, no en el de los archivos."""
    presentacion = _leer_xml(zip_, "ppt/presentation.xml")
    relaciones = _leer_xml(zip_, "ppt/_rels/presentation.xml.rels")
    if presentacion is not None and relaciones is not None:
        destinos = {
            rel.get("Id"): rel.get("Target", "")
            for rel in relaciones.iter(f"{_REL}Relationship")
        }
        lista = presentacion.find(f"{_P}sldIdLst")
        if lista is not None:
            orden = []
            for diapositiva in lista.iter(f"{_P}sldId"):
                destino = destinos.get(diapositiva.get(f"{_R}id"), "")
                if destino:
                    ruta = str(PurePosixPath("ppt") / destino.lstrip("/").removeprefix("ppt/"))
                    orden.append(ruta)
            if orden:
                return orden
    # Sin índice legible: por número de archivo, que suele coincidir.
    patron = re.compile(r"ppt/slides/slide(\d+)\.xml$")
    numeradas = [
        (int(m.group(1)), nombre)
        for nombre in zip_.namelist()
        if (m := patron.match(nombre))
    ]
    return [nombre for _, nombre in sorted(numeradas)]


def _texto_dibujo(raiz: ElementTree.Element) -> str:
    parrafos = []
    for parrafo in raiz.iter(f"{_A}p"):
        texto = "".join(t.text or "" for t in parrafo.iter(f"{_A}t")).strip()
        if texto:
            parrafos.append(texto)
    return "\n".join(parrafos)


def _notas_de(zip_: zipfile.ZipFile, diapositiva: str) -> str:
    """Las notas del orador de una diapositiva, si las tiene."""
    ruta = PurePosixPath(diapositiva)
    rels = _leer_xml(zip_, str(ruta.parent / "_rels" / f"{ruta.name}.rels"))
    if rels is None:
        return ""
    for rel in rels.iter(f"{_REL}Relationship"):
        if rel.get("Type", "").endswith("/notesSlide"):
            destino = PurePosixPath(ruta.parent / rel.get("Target", ""))
            # Resuelve el «../notesSlides/...» sin salir del ZIP.
            partes: list[str] = []
            for parte in destino.parts:
                if parte == "..":
                    if partes:
                        partes.pop()
                elif parte != ".":
                    partes.append(parte)
            notas = _leer_xml(zip_, "/".join(partes))
            if notas is not None:
                return _texto_dibujo(notas)
    return ""


def _extraer_pptx(documento: Documento) -> None:
    with _abrir_zip(documento) as zip_:
        _metadatos_office(zip_, documento)
        diapositivas = _orden_diapositivas(zip_)
        for numero, nombre in enumerate(diapositivas, start=1):
            raiz = _leer_xml(zip_, nombre)
            if raiz is None:
                documento.avisos.append(f"Falta la diapositiva {numero} ({nombre}).")
                continue
            texto = _texto_dibujo(raiz)
            notas = _notas_de(zip_, nombre)
            if notas:
                texto = f"{texto}\n\nNotas del orador:\n{notas}".strip()
            if not texto.strip():
                continue
            documento.fragmentos.append(
                Fragmento(
                    id=f"d{numero}",
                    texto=texto,
                    ubicacion=f"diapositiva {numero}",
                    numero=numero,
                )
            )
    documento.unidad = "diapositivas"
    documento.unidades = len(diapositivas)


# ---------------------------------------------------------------------------
# Texto plano y Markdown
# ---------------------------------------------------------------------------


def _leer_texto(documento: Documento) -> str:
    crudo = documento.ruta.read_bytes()
    try:
        return crudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        documento.avisos.append(
            "El archivo no estaba en UTF-8; se ha leído como Windows-1252. Revisa "
            "los acentos de las notas generadas."
        )
        return crudo.decode("cp1252", errors="replace")


def _ubicacion_seccion(titulo: str) -> str:
    titulo = " ".join(titulo.split())
    if len(titulo) > 60:
        titulo = titulo[:57].rstrip() + "…"
    return titulo if titulo == "inicio del documento" else f"sección «{titulo}»"


def _extraer_md(documento: Documento) -> None:
    texto = _leer_texto(documento)
    lineas = texto.splitlines()

    # Un frontmatter YAML al principio no es contenido del documento.
    if lineas and lineas[0].strip() == "---":
        for indice in range(1, len(lineas)):
            if lineas[indice].strip() == "---":
                lineas = lineas[indice + 1 :]
                break

    secciones: list[tuple[str, list[str]]] = [("inicio del documento", [])]
    en_codigo = False
    for linea in lineas:
        if linea.lstrip().startswith("```"):
            en_codigo = not en_codigo
        encontrado = None if en_codigo else _ENCABEZADO_MD.match(linea)
        if encontrado:
            if documento.titulo == NR and len(encontrado.group(1)) == 1:
                documento.titulo = encontrado.group(2).strip()
            secciones.append((encontrado.group(2).strip(), [linea]))
        else:
            secciones[-1][1].append(linea)

    numero = 0
    for titulo, cuerpo in secciones:
        contenido = "\n".join(cuerpo).strip()
        if not contenido:
            continue
        numero += 1
        documento.fragmentos.append(
            Fragmento(
                id=f"s{numero}",
                texto=contenido,
                ubicacion=_ubicacion_seccion(titulo),
                numero=numero,
            )
        )
    documento.unidad = "secciones"
    documento.unidades = numero


def _extraer_txt(documento: Documento) -> None:
    lineas = _leer_texto(documento).splitlines()
    bloque: list[str] = []
    inicio = 1
    numero = 0

    def cerrar(hasta: int) -> None:
        nonlocal numero
        if any(l.strip() for l in bloque):
            numero += 1
            documento.fragmentos.append(
                Fragmento(
                    id=f"b{numero}",
                    texto="\n".join(bloque).strip(),
                    ubicacion=f"líneas {inicio}–{hasta}",
                    numero=numero,
                )
            )

    for indice, linea in enumerate(lineas, start=1):
        if linea.strip():
            if not bloque:
                inicio = indice
            bloque.append(linea)
        elif bloque:
            cerrar(indice - 1)
            bloque = []
    if bloque:
        cerrar(len(lineas))

    documento.unidad = "líneas"
    documento.unidades = len(lineas)

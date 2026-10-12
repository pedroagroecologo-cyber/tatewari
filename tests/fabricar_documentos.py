"""Fabrica documentos de prueba pequeños y válidos: DOCX, PPTX y PDF.

Se generan al vuelo en vez de guardarse como binarios en el repositorio: así se
ve exactamente qué contienen, se pueden revisar en un diff y no hay un `.docx`
opaco del que nadie sabe de dónde salió.

DOCX y PPTX se arman con `zipfile` y el XML mínimo que Word y PowerPoint
aceptan. El PDF necesita PyMuPDF; si no está, la prueba que lo pide se salta.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_TIPOS_DOCX = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS_RAIZ_DOCX = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _nucleo(titulo: str, autor: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(titulo)}</dc:title><dc:creator>{escape(autor)}</dc:creator>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-03-01T10:00:00Z</dcterms:created>'
        "</cp:coreProperties>"
    )


def crear_docx(
    ruta: Path,
    secciones: list[tuple[str, list[str]]],
    titulo: str = "Documento de prueba",
    autor: str = "Autoría de prueba",
) -> Path:
    """Un DOCX con un título (estilo Heading1) y sus párrafos por sección."""
    cuerpo = []
    for encabezado, parrafos in secciones:
        cuerpo.append(
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            f"<w:r><w:t>{escape(encabezado)}</w:t></w:r></w:p>"
        )
        for parrafo in parrafos:
            cuerpo.append(f'<w:p><w:r><w:t xml:space="preserve">{escape(parrafo)}</w:t></w:r></w:p>')
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(cuerpo)}</w:body></w:document>"
    )
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as zip_:
        zip_.writestr("[Content_Types].xml", _TIPOS_DOCX)
        zip_.writestr("_rels/.rels", _RELS_RAIZ_DOCX)
        zip_.writestr("word/document.xml", documento)
        zip_.writestr("docProps/core.xml", _nucleo(titulo, autor))
    return ruta


def crear_pptx(
    ruta: Path,
    diapositivas: list[str],
    notas: dict[int, str] | None = None,
    titulo: str = "Presentación de prueba",
) -> Path:
    """Un PPTX con una caja de texto por diapositiva y notas opcionales."""
    notas = notas or {}
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rel_tipo = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    def caja(texto: str) -> str:
        parrafos = "".join(
            f"<a:p><a:r><a:t>{escape(linea)}</a:t></a:r></a:p>" for linea in texto.split("\n")
        )
        return (
            f'<p:sp><p:txBody><a:bodyPr/>{parrafos}</p:txBody></p:sp>'
        )

    ids = "".join(
        f'<p:sldId id="{256 + n}" r:id="rId{n}"/>' for n in range(1, len(diapositivas) + 1)
    )
    rels_pres = "".join(
        f'<Relationship Id="rId{n}" Type="{rel_tipo}/slide" Target="slides/slide{n}.xml"/>'
        for n in range(1, len(diapositivas) + 1)
    )
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as zip_:
        zip_.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        zip_.writestr(
            "ppt/presentation.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="{ns_p}" xmlns:r="{ns_r}">'
            f"<p:sldIdLst>{ids}</p:sldIdLst></p:presentation>",
        )
        zip_.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels_pres}</Relationships>",
        )
        zip_.writestr("docProps/core.xml", _nucleo(titulo, "Autoría de prueba"))
        for n, texto in enumerate(diapositivas, start=1):
            zip_.writestr(
                f"ppt/slides/slide{n}.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="{ns_p}" xmlns:a="{ns_a}">'
                f"<p:cSld><p:spTree>{caja(texto)}</p:spTree></p:cSld></p:sld>",
            )
            if n in notas:
                zip_.writestr(
                    f"ppt/slides/_rels/slide{n}.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'<Relationship Id="rId9" Type="{rel_tipo}/notesSlide" Target="../notesSlides/notesSlide{n}.xml"/>'
                    "</Relationships>",
                )
                zip_.writestr(
                    f"ppt/notesSlides/notesSlide{n}.xml",
                    f'<?xml version="1.0" encoding="UTF-8"?><p:notes xmlns:p="{ns_p}" xmlns:a="{ns_a}">'
                    f"<p:cSld><p:spTree>{caja(notas[n])}</p:spTree></p:cSld></p:notes>",
                )
    return ruta


def crear_pdf(ruta: Path, paginas: list[str], titulo: str = "PDF de prueba") -> Path:
    """Un PDF con una página por texto. Necesita PyMuPDF."""
    import pymupdf

    pdf = pymupdf.open()
    for texto in paginas:
        pagina = pdf.new_page()
        pagina.insert_textbox(pymupdf.Rect(50, 50, 550, 800), texto, fontsize=11)
    pdf.set_metadata({"title": titulo, "author": "Autoría de prueba", "creationDate": "D:20260301"})
    pdf.save(ruta)
    pdf.close()
    return ruta

"""Knowledge Studio: ingesta, extracción y normalización. Sin red y sin modelo."""

from __future__ import annotations

import zipfile

import pytest

from ayudas_conocimiento import EDAFOLOGIA
from fabricar_documentos import crear_docx, crear_pdf, crear_pptx
from tatewari.conocimiento.documento import ErrorDocumento, Fragmento
from tatewari.conocimiento.extraccion import extraer, pdf_disponible
from tatewari.conocimiento.ingesta import detectar_tipo, ingerir
from tatewari.conocimiento.normalizacion import (
    normalizar_documento,
    normalizar_texto,
    trocear,
)

necesita_pdf = pytest.mark.skipif(not pdf_disponible(), reason="PyMuPDF no está instalado")


def procesar(ruta):
    return normalizar_documento(extraer(ingerir(ruta)))


# ---------------------------------------------------------------------------
# Ingesta: tipos y errores
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nombre, esperado",
    [("a.md", "md"), ("a.markdown", "md"), ("a.txt", "txt"), ("A.TXT", "txt")],
)
def test_detecta_los_tipos_de_texto(tmp_path, nombre, esperado):
    ruta = tmp_path / nombre
    ruta.write_text("hola", encoding="utf-8")

    assert detectar_tipo(ruta) == esperado


def test_detecta_docx_y_pptx_por_su_contenido(tmp_path):
    assert detectar_tipo(crear_docx(tmp_path / "a.docx", [("T", ["p"])])) == "docx"
    assert detectar_tipo(crear_pptx(tmp_path / "a.pptx", ["uno"])) == "pptx"


def test_un_pdf_falso_se_rechaza(tmp_path):
    """Un «.pdf» que no empieza por %PDF no es un PDF."""
    ruta = tmp_path / "falso.pdf"
    ruta.write_text("esto no es un pdf", encoding="utf-8")

    with pytest.raises(ErrorDocumento, match="no lo es por dentro"):
        ingerir(ruta)


def test_un_docx_corrupto_se_rechaza(tmp_path):
    ruta = tmp_path / "roto.docx"
    ruta.write_bytes(b"PK\x03\x04 esto no es un zip de verdad")

    with pytest.raises(ErrorDocumento, match="dañado"):
        ingerir(ruta)


def test_un_zip_que_no_es_un_docx_se_rechaza(tmp_path):
    ruta = tmp_path / "otro.docx"
    with zipfile.ZipFile(ruta, "w") as zip_:
        zip_.writestr("cualquier/cosa.txt", "hola")

    with pytest.raises(ErrorDocumento, match="no un DOCX"):
        ingerir(ruta)


def test_un_formato_no_admitido_dice_cuales_si(tmp_path):
    ruta = tmp_path / "hoja.xlsx"
    ruta.write_bytes(b"PK")

    with pytest.raises(ErrorDocumento) as fallo:
        ingerir(ruta)

    assert "no se admite" in str(fallo.value)
    assert "PDF" in str(fallo.value) and "DOCX" in str(fallo.value)


def test_una_imagen_dice_que_el_ocr_todavia_no_esta(tmp_path):
    ruta = tmp_path / "foto.png"
    ruta.write_bytes(b"\x89PNG")

    with pytest.raises(ErrorDocumento, match="OCR"):
        ingerir(ruta)


def test_un_doc_antiguo_pide_convertirlo(tmp_path):
    ruta = tmp_path / "viejo.doc"
    ruta.write_bytes(b"\xd0\xcf\x11\xe0")

    with pytest.raises(ErrorDocumento, match="guárdalo como DOCX"):
        ingerir(ruta)


def test_un_archivo_vacio_se_rechaza(tmp_path):
    ruta = tmp_path / "vacio.txt"
    ruta.write_bytes(b"")

    with pytest.raises(ErrorDocumento, match="vacío"):
        ingerir(ruta)


def test_un_archivo_que_no_existe_se_dice(tmp_path):
    with pytest.raises(ErrorDocumento, match="No existe"):
        ingerir(tmp_path / "no.pdf")


def test_una_carpeta_sugiere_analizar_materia(tmp_path):
    with pytest.raises(ErrorDocumento, match="materia"):
        ingerir(tmp_path)


def test_la_ingesta_calcula_la_huella(tmp_path):
    ruta = tmp_path / "a.txt"
    ruta.write_text("hola", encoding="utf-8")

    aceptado = ingerir(ruta)

    assert len(aceptado.sha256) == 64
    assert aceptado.tamano == 4


# ---------------------------------------------------------------------------
# Extracción por formato, con su ubicación
# ---------------------------------------------------------------------------


def test_markdown_se_parte_por_encabezados():
    documento = procesar(EDAFOLOGIA)

    ubicaciones = [f.ubicacion for f in documento.fragmentos]
    assert "sección «Horizontes del suelo»" in ubicaciones
    assert "sección «Meteorización»" in ubicaciones
    assert documento.titulo == "Edafología I — Unidad 1: El suelo como sistema"
    assert documento.unidad == "secciones"


def test_markdown_ignora_el_frontmatter_y_los_bloques_de_codigo(tmp_path):
    ruta = tmp_path / "a.md"
    ruta.write_text(
        "---\ntitulo: x\n---\n# Uno\ntexto\n```\n# no es un título\n```\n## Dos\nmás",
        encoding="utf-8",
    )

    documento = procesar(ruta)

    assert [f.ubicacion for f in documento.fragmentos] == ["sección «Uno»", "sección «Dos»"]
    assert "titulo: x" not in documento.texto


def test_texto_plano_por_bloques_con_sus_lineas(tmp_path):
    ruta = tmp_path / "a.txt"
    ruta.write_text("Primer párrafo.\nsigue.\n\nSegundo párrafo.", encoding="utf-8")

    documento = procesar(ruta)

    assert [f.ubicacion for f in documento.fragmentos] == ["líneas 1–2", "líneas 4–4"]


def test_texto_en_windows_1252_se_lee_y_se_avisa(tmp_path):
    ruta = tmp_path / "viejo.txt"
    ruta.write_bytes("Remoción de nitrógeno".encode("cp1252"))

    documento = procesar(ruta)

    assert "Remoción" in documento.texto
    assert any("Windows-1252" in a for a in documento.avisos)


def test_docx_por_secciones_con_tablas_y_metadatos(tmp_path):
    ruta = crear_docx(
        tmp_path / "apuntes.docx",
        [("Suelos", ["El suelo es un cuerpo natural."]), ("Horizontes", ["El horizonte A es superficial."])],
        titulo="Apuntes de suelos",
        autor="Ana Prueba",
    )

    documento = procesar(ruta)

    assert documento.titulo == "Apuntes de suelos"
    assert documento.autores == "Ana Prueba"
    assert documento.fecha == "2026-03-01"
    assert [f.ubicacion for f in documento.fragmentos] == ["sección «Suelos»", "sección «Horizontes»"]
    assert documento.unidades == 2


def test_pptx_por_diapositiva_en_orden_con_notas(tmp_path):
    ruta = crear_pptx(
        tmp_path / "clase.pptx",
        ["El pH mide la acidez", "La escala va de 0 a 14"],
        notas={1: "Recordar el ejemplo del vinagre"},
    )

    documento = procesar(ruta)

    assert [f.ubicacion for f in documento.fragmentos] == ["diapositiva 1", "diapositiva 2"]
    assert "Notas del orador" in documento.fragmentos[0].texto
    assert "vinagre" in documento.fragmentos[0].texto
    assert documento.unidad == "diapositivas"


@necesita_pdf
def test_pdf_por_pagina_con_metadatos(tmp_path):
    ruta = crear_pdf(tmp_path / "a.pdf", ["Página uno sobre suelos.", "Página dos sobre agua."])

    documento = procesar(ruta)

    assert [f.ubicacion for f in documento.fragmentos] == ["p. 1", "p. 2"]
    assert documento.titulo == "PDF de prueba"
    assert documento.unidades == 2


@necesita_pdf
def test_pdf_con_paginas_vacias_avisa_del_ocr(tmp_path):
    ruta = crear_pdf(tmp_path / "a.pdf", ["Texto de verdad.", ""])

    documento = procesar(ruta)

    assert any("OCR" in a for a in documento.avisos)


@necesita_pdf
def test_pdf_corrupto_da_un_error_claro(tmp_path):
    ruta = tmp_path / "roto.pdf"
    ruta.write_bytes(b"%PDF-1.7\n esto no es un pdf completo")

    with pytest.raises(ErrorDocumento, match="dañado"):
        procesar(ruta)


def test_sin_pymupdf_el_pdf_explica_como_instalarlo(tmp_path, monkeypatch):
    import builtins

    real = builtins.__import__

    def sin_pymupdf(nombre, *a, **k):
        if nombre in ("pymupdf", "fitz"):
            raise ImportError(nombre)
        return real(nombre, *a, **k)

    ruta = tmp_path / "a.pdf"
    ruta.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setattr(builtins, "__import__", sin_pymupdf)

    with pytest.raises(ErrorDocumento, match="documentos"):
        extraer(ingerir(ruta))


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------


def test_une_las_palabras_partidas_por_guion():
    assert normalizar_texto("la remo-\nción de nutrientes") == "la remoción de nutrientes"


def test_no_une_un_guion_entre_cifras():
    assert normalizar_texto("de 10-\n30 cm") == "de 10-\n30 cm"


def test_quita_guiones_blandos_y_espacios_repetidos():
    assert normalizar_texto("re­moción   de   N") == "remoción de N"


@necesita_pdf
def test_quita_cabeceras_repetidas_y_numeros_de_pagina(tmp_path):
    ruta = crear_pdf(
        tmp_path / "a.pdf",
        [f"Revista Ficticia de Suelos\nContenido de la página {n}.\n{n}" for n in (1, 2, 3)],
    )

    documento = procesar(ruta)

    assert "Revista Ficticia" not in documento.texto
    assert all(not f.texto.strip().endswith(str(n)) for n, f in enumerate(documento.fragmentos, 1))
    assert "Contenido de la página 2" in documento.texto


# ---------------------------------------------------------------------------
# Troceado: la ubicación sobrevive
# ---------------------------------------------------------------------------


def test_los_trozos_conservan_sus_fragmentos():
    documento = procesar(EDAFOLOGIA)

    trozos = trocear(documento, maximo=600)

    assert len(trozos) > 1
    todos = [f for t in trozos for f in t.fragmentos]
    assert {f.ubicacion for f in todos} == {f.ubicacion for f in documento.fragmentos}


def test_un_fragmento_enorme_se_parte_y_hereda_la_ubicacion(tmp_path):
    from tatewari.conocimiento.documento import Documento

    documento = Documento(ruta=tmp_path, nombre="x", tipo="txt", sha256="0", tamano=1)
    documento.fragmentos = [Fragmento(id="p7", texto=("Una frase larga. " * 400).strip(), ubicacion="p. 7", numero=7)]

    trozos = trocear(documento, maximo=500)

    assert len(trozos) > 5
    assert all(len(t.texto) <= 500 for t in trozos)
    assert all(f.ubicacion == "p. 7" for t in trozos for f in t.fragmentos)


def test_la_ubicacion_de_un_trozo_dice_desde_donde_hasta_donde():
    documento = procesar(EDAFOLOGIA)

    [trozo] = trocear(documento)

    assert trozo.ubicacion.startswith("sección «Edafología I")
    assert "a sección «Referencias»" in trozo.ubicacion

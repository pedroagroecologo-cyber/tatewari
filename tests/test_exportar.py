"""Pruebas de la exportación: BibTeX y fichas en Markdown. Sin red."""

from __future__ import annotations

import json
import re

import pytest

from tatewari.cribado import Decision, cribar
from tatewari.exportar import (
    NOMBRE_BIB,
    NOMBRE_INCLUIDOS,
    NOMBRE_POR_CONSEGUIR,
    NOMBRE_REVISION,
    bibtex_de,
    clave_bibtex,
    entrada_bibtex,
    escapar_latex,
    exportar,
    ficha_markdown,
    incluidos_markdown,
    por_conseguir_markdown,
    revision_manual_markdown,
)


def registro(identificador="R0001", **campos):
    base = {
        "identificador": identificador,
        "doi": "10.1234/abc",
        "titulo": "Un título cualquiera",
        "anio": 2020,
        "idioma": "es",
        "revista": "Revista de Prueba",
        "autores": ["Apellido Largo, A.", "Otro, B."],
        "resumen": "Un resumen cualquiera.",
        "tipo": "article",
        "citas": 3,
        "oa_url": "https://ejemplo.invalid/uno.pdf",
    }
    base.update(campos)
    return base


def decision(identificador="R0001", cual="incluir", **campos):
    return Decision(
        identificador=identificador,
        decision=cual,
        motivo="El motivo de la decisión.",
        clasificacion=campos.pop("clasificacion", "Humedal artificial solo"),
        decidido_por=campos.pop("decidido_por", "filtro"),
        decision_filtro=campos.pop("decision_filtro", ""),
        motivo_filtro=campos.pop("motivo_filtro", ""),
        registro=registro(identificador, **campos),
    )


# ---------------------------------------------------------------------------
# La clave de cita
# ---------------------------------------------------------------------------


def test_la_clave_lleva_apellido_ano_e_identificador():
    assert clave_bibtex(registro()) == "ApellidoLargo2020R0001"


def test_la_clave_no_lleva_acentos_ni_espacios():
    """Una clave con acentos es legal en biblatex y un problema en algún gestor."""
    clave = clave_bibtex(registro(autores=["Ñandú Pérez, José"]))

    assert clave == "NanduPerez2020R0001"
    assert re.fullmatch(r"[A-Za-z0-9]+", clave)


def test_el_identificador_hace_unica_la_clave():
    """Dos artículos del mismo autor y año no pueden chocar."""
    uno = clave_bibtex(registro("R0001"))
    otro = clave_bibtex(registro("R0002"))

    assert uno != otro


def test_sin_autor_la_clave_lo_dice_y_no_se_inventa_uno():
    assert clave_bibtex(registro(autores=["NR"])) == "SinAutor2020R0001"
    assert clave_bibtex(registro(autores=[])) == "SinAutor2020R0001"


def test_un_autor_sin_coma_usa_la_ultima_palabra():
    """«Ana Prueba Uno» sin coma: el apellido es lo último."""
    assert clave_bibtex(registro(autores=["Ana Prueba Uno"])) == "Uno2020R0001"


def test_sin_ano_la_clave_sigue_siendo_valida():
    clave = clave_bibtex(registro(anio="NR"))

    assert clave == "ApellidoLargoR0001"
    assert re.fullmatch(r"[A-Za-z0-9]+", clave)


# ---------------------------------------------------------------------------
# El escapado de LaTeX
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "crudo, escapado",
    [
        ("N & P", r"N \& P"),
        ("100%", r"100\%"),
        ("flujo_vertical", r"flujo\_vertical"),
        ("$5", r"\$5"),
        ("#1", r"\#1"),
        ("{ojo}", r"\{ojo\}"),
        ("~aprox", r"\textasciitilde{}aprox"),
        ("x^2", r"x\textasciicircum{}2"),
    ],
)
def test_se_escapan_los_especiales_de_latex(crudo, escapado):
    assert escapar_latex(crudo) == escapado


def test_la_barra_invertida_no_se_escapa_dos_veces():
    """El fallo sutil: `\\textbackslash{}` mete llaves que no hay que reescapar."""
    assert escapar_latex("C:\\ruta") == r"C:\textbackslash{}ruta"
    assert r"\{\}" not in escapar_latex("C:\\ruta")


def test_los_acentos_se_dejan_en_utf8():
    """Convertir acentos a macros es la vía rápida para destrozar un título."""
    assert escapar_latex("Remoción de nitrógeno") == "Remoción de nitrógeno"


def test_un_campo_ausente_se_escapa_a_cadena_vacia():
    assert escapar_latex("NR") == ""
    assert escapar_latex(None) == ""


# ---------------------------------------------------------------------------
# Las entradas de BibTeX
# ---------------------------------------------------------------------------


def test_una_entrada_lleva_los_campos_esperados():
    entrada = entrada_bibtex(registro(), clasificacion="Sistema combinado")

    assert entrada.startswith("@article{ApellidoLargo2020R0001,")
    assert "author   = {Apellido Largo, A. and Otro, B.}" in entrada
    assert "year     = {2020}" in entrada
    assert "doi      = {10.1234/abc}" in entrada
    assert "Clasificación: Sistema combinado" in entrada
    assert entrada.rstrip().endswith("}")


def test_el_titulo_va_entre_dobles_llaves():
    """«DQO» y «UASB» tienen que seguir en mayúsculas después de importar."""
    entrada = entrada_bibtex(registro(titulo="Remoción de DQO en UASB"))

    assert "title    = {{Remoción de DQO en UASB}}" in entrada


def test_un_campo_no_reportado_se_omite_y_se_anota():
    """Un `year = {NR}` entraría en Zotero como una fecha corrompida."""
    entrada = entrada_bibtex(registro(anio="NR", revista="NR", doi="NR"))

    assert "year" not in entrada
    assert "journal" not in entrada
    assert "doi " not in entrada
    # En el orden en que se construyen los campos: revista antes que año.
    assert "Campos no reportados (NR): revista, año, DOI." in entrada


def test_una_revision_es_un_articulo_de_revista():
    """BibTeX no tiene `@review`."""
    assert entrada_bibtex(registro(tipo="review")).startswith("@article{")


def test_un_tipo_desconocido_va_como_misc():
    assert entrada_bibtex(registro(tipo="cosa-rara")).startswith("@misc{")
    assert entrada_bibtex(registro(tipo="NR")).startswith("@misc{")


def test_la_url_solo_sale_si_hay_acceso_abierto():
    con = entrada_bibtex(registro(oa_url="https://ejemplo.invalid/x.pdf"))
    sin = entrada_bibtex(registro(oa_url="NR"))

    assert "url      = {https://ejemplo.invalid/x.pdf}" in con
    assert "url" not in sin


def test_quien_decidio_queda_en_la_nota():
    entrada = entrada_bibtex(registro(), decidido_por="modelo:qwen3:4b")

    assert "Decidido por: modelo:qwen3:4b" in entrada


# ---------------------------------------------------------------------------
# El archivo BibTeX completo
# ---------------------------------------------------------------------------


def _sin_comentarios(bib: str) -> str:
    """Quita los comentarios `%` no escapados, como haría un lector de BibTeX."""
    lineas = []
    for linea in bib.splitlines():
        salida = []
        indice = 0
        while indice < len(linea):
            if linea[indice] == "\\" and indice + 1 < len(linea):
                salida.append(linea[indice : indice + 2])
                indice += 2
                continue
            if linea[indice] == "%":
                break
            salida.append(linea[indice])
            indice += 1
        lineas.append("".join(salida))
    return "\n".join(lineas)


def test_el_archivo_tiene_las_llaves_equilibradas():
    """Si no lo están, el gestor no importa nada y no dice por qué."""
    bib = bibtex_de(
        [
            decision("R0001", titulo="Con & y % y _ y {llaves}"),
            decision("R0002", titulo="Con \\barra y ~tilde"),
        ],
        revision="demo",
    )

    limpio = _sin_comentarios(bib)
    profundidad = 0
    minimo = 0
    for caracter in limpio:
        if caracter == "{":
            profundidad += 1
        elif caracter == "}":
            profundidad -= 1
            minimo = min(minimo, profundidad)

    assert profundidad == 0
    assert minimo == 0


def test_las_claves_del_archivo_son_unicas_y_ascii():
    bib = bibtex_de([decision(f"R{n:04d}") for n in range(1, 6)], revision="demo")

    claves = re.findall(r"^@\w+\{([^,]+),", _sin_comentarios(bib), re.M)

    assert len(claves) == 5
    assert len(set(claves)) == 5
    assert all(re.fullmatch(r"[A-Za-z0-9]+", clave) for clave in claves)


def test_la_cabecera_va_en_comentarios():
    bib = bibtex_de([decision()], revision="demo", fecha="2026-09-17T00:00:00")

    primeras = bib.splitlines()[:5]
    assert all(linea.startswith("%") for linea in primeras)
    assert "demo" in bib
    assert "Entradas : 1" in bib


def test_un_archivo_sin_entradas_sigue_siendo_valido():
    bib = bibtex_de([], revision="demo")

    assert "Entradas : 0" in bib
    assert "@" not in _sin_comentarios(bib)


# ---------------------------------------------------------------------------
# Las fichas en Markdown
# ---------------------------------------------------------------------------


def test_la_ficha_lleva_todo_lo_que_pide_el_encargo():
    ficha = ficha_markdown(decision())

    for esperado in ("**Año**", "**Idioma**", "**Revista**", "**Autores**", "**DOI**"):
        assert esperado in ficha
    assert "**Clasificación**: Humedal artificial solo" in ficha
    assert "**Resumen**" in ficha


def test_el_resumen_de_la_ficha_se_recorta():
    ficha = ficha_markdown(decision(resumen="x " * 2000), limite=100)

    assert "…" in ficha
    assert len(ficha) < 1000


def test_el_doi_de_la_ficha_es_un_enlace():
    assert "https://doi.org/10.1234/abc" in ficha_markdown(decision())


def test_sin_doi_la_ficha_no_inventa_un_enlace():
    """AGENTS.md, regla 2."""
    ficha = ficha_markdown(decision(doi="NR"))

    assert "**DOI**: NR" in ficha
    assert "doi.org" not in ficha


def test_la_ficha_dice_si_hay_texto_completo():
    assert "acceso abierto" in ficha_markdown(decision())
    assert "sin versión abierta" in ficha_markdown(decision(oa_url="NR"))


def test_incluidos_markdown_lista_todas_las_fichas():
    texto = incluidos_markdown(
        [decision("R0001"), decision("R0002")], revision="demo"
    )

    assert "**Artículos**: 2" in texto
    assert "### R0001" in texto
    assert "### R0002" in texto


def test_sin_incluidos_el_markdown_lo_dice_en_vez_de_quedarse_vacio():
    texto = incluidos_markdown([], revision="demo")

    assert "Todavía no hay ningún registro incluido" in texto


# ---------------------------------------------------------------------------
# revision-manual.md
# ---------------------------------------------------------------------------


def test_la_revision_manual_lleva_el_motivo_del_filtro_y_quien_decidio():
    dudoso = decision(
        "R0007",
        cual="dudoso",
        decidido_por="modelo:qwen3:4b",
        decision_filtro="dudoso",
        motivo_filtro="No trae resumen, no es cribable en automático.",
    )

    texto = revision_manual_markdown([dudoso], revision="demo")

    assert "**Lo decidió**: modelo:qwen3:4b" in texto
    assert "No trae resumen" in texto
    assert "regla 4" in texto


def test_la_revision_manual_trae_la_orden_de_decidir_escrita():
    """La diferencia entre una lista y una lista de tareas."""
    texto = revision_manual_markdown([decision("R0007", cual="dudoso")], revision="demo")

    assert "python -m tatewari decidir demo R0007 --decision incluir" in texto


def test_sin_dudosos_la_revision_manual_lo_dice():
    assert "No queda ningún registro dudoso" in revision_manual_markdown([])


# ---------------------------------------------------------------------------
# por-conseguir.md
# ---------------------------------------------------------------------------


def test_por_conseguir_deja_claro_que_no_se_eluden_muros_de_pago():
    """Es el punto del archivo, no una nota al pie (AGENTS.md, regla 5)."""
    texto = por_conseguir_markdown([decision(oa_url="NR")], revision="demo")

    assert "no elude muros de pago" in texto
    assert "Sci-Hub" in texto
    assert "a mano" in texto
    assert "credencial institucional" in texto


def test_por_conseguir_lista_el_doi_para_pegarlo():
    texto = por_conseguir_markdown(
        [decision("R0007", doi="10.1234/cerrado", oa_url="NR")], revision="demo"
    )

    assert "| R0007 |" in texto
    assert "10.1234/cerrado" in texto
    # Y aparte, uno por línea, para pegarlos de golpe en el buscador.
    assert texto.count("10.1234/cerrado") >= 2


def test_una_tuberia_en_el_titulo_no_rompe_la_tabla():
    texto = por_conseguir_markdown(
        [decision(titulo="Antes | después", oa_url="NR")], revision="demo"
    )

    fila = [l for l in texto.splitlines() if l.startswith("| R0001")][0]
    # La del título va escapada, así que Markdown ve cinco columnas y no seis.
    assert "\\|" in fila
    sin_escapar = len(re.findall(r"(?<!\\)\|", fila))
    assert sin_escapar == 6


def test_sin_cerrados_por_conseguir_lo_celebra():
    texto = por_conseguir_markdown([], revision="demo")

    assert "Ninguno" in texto
    assert "no hay nada que pedir" in texto.lower()


# ---------------------------------------------------------------------------
# Escribir los cuatro archivos
# ---------------------------------------------------------------------------


def test_exportar_escribe_los_cuatro_archivos(tmp_path, protocolo, ruta_fixture_demo):
    registros = json.loads(ruta_fixture_demo.read_text(encoding="utf-8"))
    resultado = cribar(registros, protocolo, revision="demo")

    salida = exportar(resultado, tmp_path, revision="demo")

    for nombre in (
        NOMBRE_BIB,
        NOMBRE_INCLUIDOS,
        NOMBRE_REVISION,
        NOMBRE_POR_CONSEGUIR,
    ):
        assert (tmp_path / nombre).is_file()
    assert len(salida.rutas) == 4
    assert salida.incluidos == resultado.conteos["incluir"]
    assert salida.dudosos == resultado.conteos["dudoso"]
    assert salida.con_abierto + salida.sin_abierto == salida.incluidos


def test_los_archivos_van_en_utf8_con_lf_y_sin_bom(
    tmp_path, protocolo, ruta_fixture_demo
):
    """La excepción del BOM que autoriza AGENTS.md es solo para search_log.csv."""
    registros = json.loads(ruta_fixture_demo.read_text(encoding="utf-8"))
    exportar(cribar(registros, protocolo), tmp_path, revision="demo")

    for nombre in (NOMBRE_BIB, NOMBRE_INCLUIDOS, NOMBRE_REVISION):
        crudo = (tmp_path / nombre).read_bytes()
        assert not crudo.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" not in crudo
        # Y se lee como UTF-8 sin reventar.
        (tmp_path / nombre).read_text(encoding="utf-8")

"""Pruebas de las notas de Obsidian: una por incluido, sin pisar «Mis notas»."""

from __future__ import annotations

from dataclasses import dataclass, field

from tatewari.notas import (
    CARPETA_NOTAS,
    MARCA_MIS_NOTAS,
    NOMBRE_INDICE,
    TEXTO_INICIAL,
    escribir_notas,
    lista_de_autores,
    nombre_de_nota,
)


@dataclass
class Decision:
    identificador: str
    registro: dict
    decision: str = "incluir"
    motivo: str = "BTC estabilizado con datos de desempeño."
    clasificacion: str = "Estabilización del BTC"
    decidido_por: str = "filtro"


def registro(titulo="Lime stabilization for compressed stabilized earth blocks", doi="10.1016/j.cscm.2019.e00326"):
    return {
        "titulo": titulo,
        "autores": "['S. N. Malkanthi', 'N. Balthazaar']",
        "anio": "2019",
        "revista": "Case Studies in Construction Materials",
        "doi": doi,
        "resumen": "Compressed stabilized earth blocks (CSEBs) are comparatively new.",
        "oa_url": "https://example.org/abierto",
    }


def test_autores_de_lista_o_de_texto():
    assert lista_de_autores("['S. N. Malkanthi', 'N. Balthazaar']") == ["S. N. Malkanthi", "N. Balthazaar"]
    assert lista_de_autores(["A", "B"]) == ["A", "B"]
    assert lista_de_autores("NR") == []


def test_nombre_de_nota_es_legible_y_seguro():
    nombre = nombre_de_nota("R0007", registro(titulo='Clay: "quality" / CSEB? [part 1]'))
    assert nombre.startswith("R0007 Clay")
    assert not any(c in nombre for c in ':"/?[]')
    largo = nombre_de_nota("R0008", registro(titulo="palabra " * 40))
    assert len(largo) <= 80 and not largo.endswith(" ")


def test_escribe_una_nota_por_incluido_y_el_indice(tmp_path):
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "R0001_Malkanthi_2019.pdf").write_bytes(b"%PDF-1.7")
    decisiones = [
        Decision("R0001", registro()),
        Decision("R0002", registro(titulo="Otro artículo", doi="NR"), clasificacion="NR"),
    ]
    resultado = escribir_notas(decisiones, tmp_path, "btc")
    carpeta = tmp_path / CARPETA_NOTAS
    assert resultado.escritas == 2 and resultado.con_pdf == 1
    nota = (carpeta / (nombre_de_nota("R0001", registro()) + ".md")).read_text(encoding="utf-8")
    assert nota.startswith("---\nid: \"R0001\"")
    assert "doi: \"10.1016/j.cscm.2019.e00326\"" in nota
    assert "](../pdf/R0001_Malkanthi_2019.pdf)" in nota
    assert "Compressed stabilized earth blocks (CSEBs) are comparatively new." in nota
    assert MARCA_MIS_NOTAS in nota and TEXTO_INICIAL in nota
    otra = (carpeta / "R0002 Otro artículo.md").read_text(encoding="utf-8")
    assert "[acceso abierto](https://example.org/abierto)" in otra
    indice = (carpeta / NOMBRE_INDICE).read_text(encoding="utf-8")
    assert "## Estabilización del BTC" in indice and "## Sin clasificación" in indice
    assert "R0002%20Otro%20art%C3%ADculo.md" in indice


def test_no_pisa_mis_notas(tmp_path):
    decisiones = [Decision("R0001", registro())]
    escribir_notas(decisiones, tmp_path, "btc")
    ruta = tmp_path / CARPETA_NOTAS / (nombre_de_nota("R0001", registro()) + ".md")
    ruta.write_text(ruta.read_text(encoding="utf-8") + "\nUsar 5.5 % de cemento.\n[[Lote piloto]]\n", encoding="utf-8")

    decisiones[0].motivo = "Motivo nuevo tras volver a cribar."
    resultado = escribir_notas(decisiones, tmp_path, "btc")
    nota = ruta.read_text(encoding="utf-8")
    assert resultado.conservadas == 1
    assert "Motivo nuevo tras volver a cribar." in nota
    assert "Usar 5.5 % de cemento.\n[[Lote piloto]]" in nota
    assert TEXTO_INICIAL not in nota
    assert nota.count(MARCA_MIS_NOTAS) == 1

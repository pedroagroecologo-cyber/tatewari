"""Pruebas del resumen extractivo. Sin PDF real: se le dan páginas ya extraídas."""

from __future__ import annotations

from dataclasses import dataclass

from tatewari.notas import escribir_notas
from tatewari.resumen_pdf import partir_frases, resumir_paginas

PAGINAS = [
    (
        1,
        "Abstract. Compressed stabilised earth blocks are cheap. The maximum compressive "
        "strength of 2.9 MPa was obtained at 8% cement and 15 g of fibre.\n"
        "1. Methods\nSamples were tested in a Universal Testing Machine after 28 days of curing.",
    ),
    (
        2,
        "Results show that the optimum mix was 5.5% cement for every 5 kg of block produced. "
        "As reported by Walker et al. 2005, Fig. 3 shows a trend.\n"
        "The block containing 4% cement and 25 g of\n"
        "𝐶𝑜𝑚𝑝𝑟𝑒𝑠𝑠𝑖𝑣𝑒 𝑠𝑡𝑟𝑒𝑛𝑔𝑡ℎ = 𝑙𝑜𝑎𝑑 / 𝑎𝑟𝑒𝑎 with 10 MPa as a cap of the machine.",
    ),
    (
        3,
        "4. CONCLUSIONS\nPlantain fibre can reinforce compressed earth blocks. "
        "The curing period changed the ideal cement-fibre ratio.\n"
        "Acknowledgements\nWe thank the lab.\nREFERENCES\n"
        "Walker P. 2005. Strength of cement stabilised blocks reached 12 MPa in 28 days.",
    ),
]
TERMINOS = ["compressed earth block", "cement", "compressive strength", "fibre"]


def test_partir_frases_respeta_abreviaturas_y_decimales():
    frases = partir_frases("Walker et al. 2005 found 2.9 MPa. Fig. 3 shows it. Then more.")
    assert frases == ["Walker et al. 2005 found 2.9 MPa.", "Fig. 3 shows it.", "Then more."]


def test_conclusiones_salen_del_apartado_y_se_detienen_en_el_siguiente():
    resumen = resumir_paginas(PAGINAS, TERMINOS)
    textos = [f.texto for f in resumen.conclusiones]
    assert textos == [
        "Plantain fibre can reinforce compressed earth blocks.",
        "The curing period changed the ideal cement-fibre ratio.",
    ]
    assert all(f.pagina == 3 for f in resumen.conclusiones)


def test_hallazgos_son_resultados_con_cifras_del_tema():
    resumen = resumir_paginas(PAGINAS, TERMINOS)
    textos = [f.texto for f in resumen.hallazgos]
    assert any("2.9 MPa was obtained" in t for t in textos)
    assert any("optimum mix was 5.5% cement" in t for t in textos)
    # Ni la frase cortada por columna, ni la ecuación, ni las referencias.
    assert not any("25 g of" in t and t.endswith("of") for t in textos)
    assert not any("𝐶" in t for t in textos)
    assert not any("12 MPa in 28 days" in t for t in textos)
    # Los resultados van antes que el método.
    assert textos.index(next(t for t in textos if "obtained" in t)) == 0


def test_pdf_sin_texto_avisa():
    resumen = resumir_paginas([(1, ""), (2, "  ")], TERMINOS)
    assert resumen.vacio
    assert "escaneo" in resumen.avisos[0]


@dataclass
class Decision:
    identificador: str
    registro: dict
    decision: str = "incluir"
    motivo: str = "Motivo."
    clasificacion: str = "BTC"
    decidido_por: str = "filtro"


def test_la_nota_trae_lo_que_dice_el_pdf(tmp_path, monkeypatch):
    import tatewari.resumen_pdf as modulo

    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "R0001_Omotainse_2022.pdf").write_bytes(b"%PDF-1.7")
    monkeypatch.setattr(modulo, "pdf_legible", lambda: True)
    monkeypatch.setattr(
        modulo, "resumir_pdf", lambda ruta, terminos: resumir_paginas(PAGINAS, terminos)
    )
    registro = {"titulo": "Plantain fibre", "autores": "['P. O. Omotainse']", "anio": "2022"}
    resultado = escribir_notas([Decision("R0001", registro)], tmp_path, "btc", TERMINOS)
    nota = next((tmp_path / "notas").glob("R0001*.md")).read_text(encoding="utf-8")
    assert resultado.resumidas == 1
    assert "## Lo que dice el PDF" in nota
    assert "> Plantain fibre can reinforce compressed earth blocks. (p. 3)" in nota
    assert nota.index("## Lo que dice el PDF") < nota.index("## Mis notas")

"""Pruebas de las citas en los siete estilos. Sin red."""

from __future__ import annotations

import pytest

from tatewari.citas import ESTILOS, autores_de, citar, lista_de_referencias, normalizar_estilo
from tatewari.config import ErrorConfig, cargar_config

MALKANTHI = {
    "autores": "['S. N. Malkanthi', 'N. Balthazaar', 'A.A.D.A.J. Perera']",
    "anio": "2019",
    "titulo": "Lime stabilization for compressed stabilized earth blocks with reduced clay and silt",
    "revista": "Case Studies in Construction Materials",
    "volumen": "12",
    "numero": "NR",
    "paginas": "e00326",
    "doi": "10.1016/j.cscm.2019.e00326",
    "idioma": "en",
}


def test_hay_siete_estilos_y_se_aceptan_variantes_de_escritura():
    assert set(ESTILOS) == {"apa", "vancouver", "ieee", "chicago", "harvard", "mla", "iso690"}
    assert normalizar_estilo("APA") == "apa"
    assert normalizar_estilo("ISO-690") == "iso690"
    with pytest.raises(ValueError):
        normalizar_estilo("turabian")


@pytest.mark.parametrize(
    "estilo, esperada",
    [
        (
            "apa",
            "Malkanthi, S. N., Balthazaar, N., & Perera, A. A. D. A. J. (2019). Lime stabilization "
            "for compressed stabilized earth blocks with reduced clay and silt. *Case Studies in "
            "Construction Materials*, *12*, e00326. https://doi.org/10.1016/j.cscm.2019.e00326",
        ),
        (
            "vancouver",
            "Malkanthi SN, Balthazaar N, Perera AADAJ. Lime stabilization for compressed stabilized "
            "earth blocks with reduced clay and silt. Case Studies in Construction Materials. "
            "2019;12:e00326. doi:10.1016/j.cscm.2019.e00326",
        ),
        (
            "ieee",
            "S. N. Malkanthi, N. Balthazaar, and A. A. D. A. J. Perera, “Lime stabilization for "
            "compressed stabilized earth blocks with reduced clay and silt,” *Case Studies in "
            "Construction Materials*, vol. 12, p. e00326, 2019, doi: 10.1016/j.cscm.2019.e00326.",
        ),
        (
            "harvard",
            "Malkanthi, S.N., Balthazaar, N. and Perera, A.A.D.A.J. (2019) ‘Lime stabilization for "
            "compressed stabilized earth blocks with reduced clay and silt’, *Case Studies in "
            "Construction Materials*, 12, p. e00326. doi: 10.1016/j.cscm.2019.e00326.",
        ),
        (
            "mla",
            "Malkanthi, S. N., et al. “Lime stabilization for compressed stabilized earth blocks "
            "with reduced clay and silt.” *Case Studies in Construction Materials*, vol. 12, 2019, "
            "p. e00326, https://doi.org/10.1016/j.cscm.2019.e00326.",
        ),
        (
            "iso690",
            "MALKANTHI, S. N., BALTHAZAAR, N. y PERERA, A. A. D. A. J. Lime stabilization for "
            "compressed stabilized earth blocks with reduced clay and silt. *Case Studies in "
            "Construction Materials*. 2019, vol. 12, p. e00326. DOI 10.1016/j.cscm.2019.e00326.",
        ),
    ],
)
def test_cita_completa_en_cada_estilo(estilo, esperada):
    assert citar(MALKANTHI, estilo) == esperada


def test_chicago_invierte_solo_al_primer_autor():
    cita = citar(MALKANTHI, "chicago")
    assert cita.startswith("Malkanthi, S. N., N. Balthazaar, and A.A.D.A.J. Perera. 2019.")


def test_no_inventa_lo_que_falta():
    sin_datos = {"autores": "['Ana Ruiz']", "anio": "2020", "titulo": "Bloques", "revista": "NR", "doi": "NR"}
    for estilo in ESTILOS:
        cita = citar(sin_datos, estilo)
        assert "NR" not in cita and "None" not in cita and "doi.org" not in cita


def test_dobles_apellidos_en_espanol():
    registro = {"autores": ["José Luis García López", "Ana de la Torre"], "idioma": "es"}
    autores = autores_de(registro)
    assert (autores[0].apellido, autores[0].iniciales()) == ("García López", "J. L.")
    assert autores[1].apellido == "de la Torre"


def test_vancouver_recorta_a_seis_y_numerado():
    muchos = dict(MALKANTHI, autores=[f"Autor{n} Apellido{n}" for n in range(8)])
    assert ", et al." in citar(muchos, "vancouver")
    lista = lista_de_referencias([MALKANTHI, muchos], "vancouver")
    assert lista[0].startswith("1. Malkanthi") and lista[1].startswith("2. Apellido0")


def test_los_alfabeticos_ordenan_por_apellido():
    otro = dict(MALKANTHI, autores=["B. Abad"])
    lista = lista_de_referencias([MALKANTHI, otro], "apa")
    assert lista[0].startswith("Abad")


def test_config_lee_y_valida_el_estilo(tmp_path):
    (tmp_path / "con").mkdir()
    (tmp_path / "sin").mkdir()
    env = tmp_path / "con" / ".env"
    env.write_text("TATEWARI_ESTILO_CITA=Vancouver\n", encoding="utf-8")
    assert cargar_config(ruta_env=env, entorno={}, base=tmp_path).estilo_cita == "vancouver"
    assert cargar_config(entorno={}, base=tmp_path / "sin").estilo_cita == "apa"
    env.write_text("TATEWARI_ESTILO_CITA=turabian\n", encoding="utf-8")
    with pytest.raises(ErrorConfig):
        cargar_config(ruta_env=env, entorno={}, base=tmp_path)

"""Construcción de URLs, sin simular nada y sin red.

Estas pruebas no usan dobles: comparan la cadena que se genera contra la forma
documentada. Cada una de ellas existe porque el error contrario ya costó
tiempo una vez.
"""

from __future__ import annotations

import pytest

from tatewari.fuentes import crossref, openalex
from tatewari.fuentes import limpiar_termino

CORREO = "prueba@ejemplo.invalid"


# ---------------------------------------------------------------------------
# OpenAlex: los cinco errores conocidos
# ---------------------------------------------------------------------------


def test_el_filtro_de_idioma_usa_codigos_iso(protocolo):
    url = openalex.construir_url('"humedal" AND "UASB"', protocolo, CORREO)

    assert "language:es|en" in url
    # La forma de identificador de entidad devuelve error en la API.
    assert "languages/" not in url


def test_el_filtro_de_tipo_no_usa_la_forma_de_entidad(protocolo):
    url = openalex.construir_url('"humedal" AND "UASB"', protocolo, CORREO)

    assert "type:article|review" in url
    assert "types/" not in url


def test_los_espacios_van_como_por_ciento_veinte_y_no_como_mas(protocolo):
    """Si la librería arma la consulta, mete "+" y OpenAlex no lo entiende."""
    url = openalex.construir_url('"humedal artificial" AND "septic tank"', protocolo, CORREO)

    assert "%20" in url
    assert "+" not in url


def test_las_comillas_van_codificadas(protocolo):
    url = openalex.construir_url('"humedal artificial" AND "UASB"', protocolo, CORREO)

    assert "%22humedal%20artificial%22%20AND%20%22UASB%22" in url
    assert '"' not in url


def test_los_booleanos_van_en_mayusculas(protocolo):
    ecuaciones = openalex.construir_ecuaciones(protocolo)

    for ecuacion in ecuaciones:
        assert " AND " in ecuacion
        assert " and " not in ecuacion


def test_ningun_termino_lleva_una_coma_dentro(protocolo):
    """Dentro de filter= la coma separa filtros: partiría la consulta."""
    for ecuacion in openalex.construir_ecuaciones(protocolo):
        assert "," not in ecuacion


def test_limpiar_termino_quita_lo_que_rompe_la_sintaxis():
    assert limpiar_termino("humedal, artificial") == "humedal artificial"
    assert limpiar_termino("uno|dos") == "uno dos"
    assert limpiar_termino('con "comillas"') == "con comillas"
    assert limpiar_termino("  espacios   de   más  ") == "espacios de más"


def test_la_ventana_temporal_sale_como_fechas_completas(protocolo):
    url = openalex.construir_url('"humedal"', protocolo, CORREO)

    assert "from_publication_date:2016-01-01" in url
    assert "to_publication_date:2026-12-31" in url


def test_el_mailto_lleva_el_correo_de_configuracion(protocolo):
    url = openalex.construir_url('"humedal"', protocolo, CORREO)

    assert url.endswith(f"mailto={CORREO}")


def test_sin_correo_no_se_pone_el_parametro(protocolo):
    url = openalex.construir_url('"humedal"', protocolo, "")

    assert "mailto" not in url


def test_la_paginacion_arranca_en_el_cursor_inicial(protocolo):
    url = openalex.construir_url('"humedal"', protocolo, CORREO)

    assert "cursor=*" in url
    assert "per-page=200" in url


def test_el_tamano_de_pagina_se_recorta_al_maximo(protocolo):
    url = openalex.construir_url('"humedal"', protocolo, CORREO, por_pagina=5000)

    assert "per-page=200" in url


def test_la_url_completa_es_exactamente_la_esperada(protocolo):
    """La prueba que fija la forma entera, para que no se escape un cambio."""
    url = openalex.construir_url('"humedal artificial" AND "anaerobic"', protocolo, CORREO)

    esperada = (
        "https://api.openalex.org/works"
        "?filter=title_and_abstract.search:"
        "%22humedal%20artificial%22%20AND%20%22anaerobic%22"
        ",from_publication_date:2016-01-01"
        ",to_publication_date:2026-12-31"
        ",language:es|en"
        ",type:article|review"
        "&per-page=200"
        "&cursor=*"
        f"&mailto={CORREO}"
    )
    assert url == esperada


def test_los_acentos_se_codifican_en_utf8(protocolo):
    url = openalex.construir_url('"tanque séptico" AND "UASB"', protocolo, CORREO)

    assert "s%C3%A9ptico" in url


# ---------------------------------------------------------------------------
# Ecuaciones
# ---------------------------------------------------------------------------


def test_se_genera_una_ecuacion_por_cada_par(protocolo):
    ecuaciones = openalex.construir_ecuaciones(protocolo)

    terminos_eje = len(protocolo.terminos_de(protocolo.consulta.eje))
    assert len(ecuaciones) == terminos_eje * len(protocolo.consulta.cruce)
    assert len(ecuaciones) == protocolo.numero_de_ecuaciones
    assert ecuaciones[0] == '"humedal artificial" AND "anaerobic"'


def test_sin_consulta_no_hay_ecuaciones(protocolo_minimo):
    from tatewari.protocolo import validar_protocolo

    sin_consulta = validar_protocolo(protocolo_minimo)
    assert openalex.construir_ecuaciones(sin_consulta) == []


def test_sin_cruce_queda_una_ecuacion_por_termino_del_eje(protocolo_minimo):
    from tatewari.protocolo import validar_protocolo

    protocolo_minimo["consulta"] = {"eje": "B1", "cruce": []}
    sin_cruce = validar_protocolo(protocolo_minimo)

    assert openalex.construir_ecuaciones(sin_cruce) == ['"alfa"', '"beta"']


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------


def test_crossref_busca_por_query_bibliographic(protocolo):
    url = crossref.construir_url('"humedal artificial" AND "UASB"', protocolo, CORREO)

    assert url.startswith("https://api.crossref.org/works?query.bibliographic=")
    assert "+" not in url
    assert f"mailto={CORREO}" in url


def test_crossref_filtra_por_ventana(protocolo):
    url = crossref.construir_url('"humedal"', protocolo, CORREO)

    assert "from-pub-date:2016-01-01" in url
    assert "until-pub-date:2026-12-31" in url


def test_crossref_arranca_con_cursor_profundo(protocolo):
    url = crossref.construir_url('"humedal"', protocolo, CORREO)

    assert "cursor=*" in url
    assert "rows=100" in url


@pytest.mark.parametrize("base", [openalex, crossref])
def test_ninguna_base_manda_espacios_sin_codificar(base, protocolo):
    url = base.construir_url('"humedal artificial" AND "septic tank"', protocolo, CORREO)

    assert " " not in url

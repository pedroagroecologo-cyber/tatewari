"""Pruebas del módulo de tesauros. Sin red: las respuestas imitan las reales.

Las formas de las respuestas se copiaron de AGROVOC (Skosmos) y de Wikidata el
2026-10-13, recortadas a lo que el módulo lee.
"""

from __future__ import annotations

import pytest

from tatewari import cli
from tatewari.http import ErrorHttpServidor
from tatewari.tesauro import (
    AGROVOC,
    WIKIDATA,
    buscar,
    concepto_de_agrovoc,
    conceptos_de_wikidata,
    es_sigla,
    terminos_sugeridos,
    url_busqueda_agrovoc,
    url_concepto_agrovoc,
)

URI_HUMEDAL = "http://aims.fao.org/aos/agrovoc/c_331329"
URI_WETLANDS = "http://aims.fao.org/aos/agrovoc/c_8371"

DATOS_AGROVOC = {
    "graph": [
        {
            "uri": URI_HUMEDAL,
            "prefLabel": [
                {"lang": "en", "value": "constructed wetlands"},
                {"lang": "es", "value": "Zona húmeda construida"},
                {"lang": "fr", "value": "zone humide artificielle"},
            ],
            "altLabel": {"lang": "en", "value": "treatment wetlands"},
            "broader": {"uri": URI_WETLANDS},
        },
        {
            "uri": URI_WETLANDS,
            "prefLabel": [{"lang": "en", "value": "wetlands"}],
        },
    ]
}

ENTIDADES_WIKIDATA = {
    "entities": {
        "Q2925636": {
            "labels": {
                "en": {"language": "en", "value": "compressed earth block"},
                "es": {"language": "es", "value": "Bloque de tierra comprimida"},
            },
            "aliases": {
                "en": [
                    {"language": "en", "value": "compressed earth brick"},
                    {"language": "en", "value": "CEB"},
                ],
                "es": [{"language": "es", "value": "BTC"}],
            },
            "descriptions": {"en": {"language": "en", "value": "building material"}},
        },
        "Q70578962": {
            "labels": {"es": {"language": "es", "value": "Bloques de tierra en la Antártida"}},
            "descriptions": {"en": {"language": "en", "value": "doctoral thesis"}},
        },
    }
}


class ClientePorUrl:
    """Doble de `ClienteHttp` que contesta según un trozo de la URL."""

    def __init__(self, respuestas: dict) -> None:
        self.respuestas = respuestas
        self.urls: list[str] = []

    def obtener_json(self, url: str):
        self.urls.append(url)
        for trozo, respuesta in self.respuestas.items():
            if trozo in url:
                if isinstance(respuesta, Exception):
                    raise respuesta
                return respuesta
        return {}


def test_sigla():
    assert es_sigla("BTC")
    assert es_sigla("CEB")
    assert es_sigla("UASB")
    assert not es_sigla("compressed earth block")
    assert not es_sigla("pH")


def test_url_de_agrovoc_lleva_comodin_e_idioma():
    url = url_busqueda_agrovoc("constructed wetland", "es", 3)
    assert "query=constructed%20wetland*" in url
    assert "lang=es" in url
    assert "maxhits=3" in url


def test_concepto_de_agrovoc_toma_es_en_y_vecinos():
    concepto = concepto_de_agrovoc(DATOS_AGROVOC, URI_HUMEDAL)
    assert concepto.fuente == AGROVOC
    assert concepto.etiquetas["en"] == ("constructed wetlands", "treatment wetlands")
    assert concepto.etiquetas["es"] == ("Zona húmeda construida",)
    assert "fr" not in concepto.etiquetas
    assert concepto.relacionados == ("wetlands",)


def test_concepto_de_agrovoc_inexistente():
    assert concepto_de_agrovoc(DATOS_AGROVOC, "http://otra") is None


def test_wikidata_descarta_obras_y_conserva_alias():
    conceptos = conceptos_de_wikidata(ENTIDADES_WIKIDATA)
    assert [c.uri for c in conceptos] == ["Q2925636"]
    concepto = conceptos[0]
    assert concepto.fuente == WIKIDATA
    assert "compressed earth brick" in concepto.etiquetas["en"]
    assert concepto.enlace == "https://www.wikidata.org/wiki/Q2925636"


def test_buscar_junta_las_dos_fuentes_y_separa_siglas():
    cliente = ClientePorUrl(
        {
            "agrovoc/search": {"results": [{"uri": URI_HUMEDAL}]},
            "agrovoc/data": DATOS_AGROVOC,
            "wbsearchentities": {"search": [{"id": "Q2925636", "description": "building material"}]},
            "wbgetentities": ENTIDADES_WIKIDATA,
        }
    )
    consulta = buscar("termino", cliente)
    assert [c.fuente for c in consulta.conceptos] == [AGROVOC, WIKIDATA]
    frases, siglas = terminos_sugeridos(consulta)
    assert "compressed earth brick" in frases
    assert "bloque de tierra comprimida" in frases
    assert siglas == ["CEB", "BTC"]
    assert url_concepto_agrovoc(URI_HUMEDAL) in cliente.urls


def test_una_fuente_caida_no_tumba_la_otra():
    cliente = ClientePorUrl(
        {
            "agrovoc": ErrorHttpServidor("503", "https://agrovoc.fao.org", estado=503),
            "wbsearchentities": {"search": [{"id": "Q2925636"}]},
            "wbgetentities": ENTIDADES_WIKIDATA,
        }
    )
    consulta = buscar("compressed earth block", cliente)
    assert [c.fuente for c in consulta.conceptos] == [WIKIDATA]
    assert any("AGROVOC no respondió" in aviso for aviso in consulta.avisos)


def test_sin_coincidencias_avisa():
    consulta = buscar("nada", ClientePorUrl({}), fuentes=(AGROVOC,))
    assert consulta.conceptos == []
    assert consulta.avisos == ["AGROVOC: sin coincidencias."]


def test_orden_tesauro_imprime_sugerencias(monkeypatch, capsys):
    cliente = ClientePorUrl(
        {
            "wbsearchentities": {"search": [{"id": "Q2925636"}]},
            "wbgetentities": ENTIDADES_WIKIDATA,
        }
    )
    monkeypatch.setattr(cli, "_cliente_tesauro", lambda: cliente)
    codigo = cli.main(["tesauro", "compressed earth block", "--fuente", "wikidata"])
    salida = capsys.readouterr().out
    assert codigo == 0
    assert "Son sugerencias" in salida
    assert '"compressed earth brick"' in salida
    assert "BTC (sigla)" in salida
    assert "Bitcoin" in salida

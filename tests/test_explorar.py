"""Pruebas de «explorar». Sin red: un cliente falso contesta como OpenAlex."""

from __future__ import annotations

from tatewari import cli
from tatewari.explorar import construir_url, explorar, frases_frecuentes, la_cosecharia
from tatewari.protocolo import validar_protocolo

PROTOCOLO = validar_protocolo(
    {
        "titulo": "BTC",
        "ventana": [2010, 2026],
        "idiomas": ["es", "en"],
        "tipos": ["article"],
        "bloques": {
            "P1_btc": ["compressed earth block"],
            "P2_estab": ["lime", "cement"],
        },
        "consulta": {"eje": "P1_btc", "cruce": ["lime stabilization"]},
        "reglas": {"incluir": [{"todos": ["P1_btc", "P2_estab"], "motivo": "BTC estabilizado."}]},
    }
)


def obra(titulo, resumen="", doi=None):
    indice = {palabra: [i] for i, palabra in enumerate(resumen.split())}
    return {
        "title": titulo,
        "publication_year": 2020,
        "language": "en",
        "doi": doi,
        "abstract_inverted_index": indice or None,
        "relevance_score": 0.9,
    }


RESPUESTA = {
    "results": [
        obra("Lime stabilization of compressed earth blocks", "We tested lime.", "https://doi.org/10.1/a"),
        obra("Compressed earth blocks stabilized with lime", "Cement and lime were added."),
        obra("Bloques de tierra comprimida estabilizados con cal"),
        obra("Bloques de tierra comprimida con cemento"),
    ]
}


class ClienteFalso:
    def __init__(self):
        self.urls = []

    def obtener_json(self, url):
        self.urls.append(url)
        return RESPUESTA


def test_url_lleva_solo_filtros_admitidos():
    url = construir_url("bloques de tierra", 30, (2010, 2026), ["article"], "a@b.mx", ["es", "en"])
    assert "search.semantic=bloques%20de%20tierra" in url
    assert "per-page=30" in url
    assert "filter=publication_year:2010-2026,type:article,language:es|en" in url
    assert "from_publication_date" not in url
    assert construir_url("x", 500).count("per-page=50") == 1


def test_la_cosecharia_exige_eje_y_cruce():
    assert la_cosecharia({"titulo": "Lime stabilization of compressed earth blocks"}, PROTOCOLO)
    # Dice «stabilized with lime», no «lime stabilization»: la ecuación no lo encuentra.
    assert not la_cosecharia({"titulo": "Compressed earth blocks stabilized with lime"}, PROTOCOLO)


def test_explorar_audita_el_protocolo():
    cliente = ClienteFalso()
    resultado = explorar("bloques de tierra", cliente, PROTOCOLO, por_pagina=10)
    assert [h.cosechado for h in resultado.hallados] == [True, False, False, False]
    assert resultado.hallados[1].decision == "incluir"
    assert len(resultado.escapados) == 3
    assert ("tierra comprimida", 2) in resultado.sugerencias or (
        "bloques de tierra comprimida",
        2,
    ) in resultado.sugerencias


def test_frases_frecuentes_omite_lo_que_ya_tiene_el_protocolo():
    titulos = ["Compressed earth blocks with lime", "Compressed earth blocks and fibres"]
    assert frases_frecuentes(titulos, ["compressed earth block"]) == []
    sugerencias = frases_frecuentes(
        ["Soil cement blocks today", "Soil cement blocks tomorrow"], ["lime"]
    )
    assert sugerencias[0] == ("soil cement blocks", 2)


def test_orden_explorar(monkeypatch, capsys, tmp_path, config_temporal):
    import json

    ruta = tmp_path / "p.json"
    ruta.write_text(
        json.dumps(
            {
                "titulo": "BTC",
                "ventana": [2010, 2026],
                "idiomas": ["es", "en"],
                "tipos": ["article"],
                "bloques": {"P1_btc": ["compressed earth block"], "P2_estab": ["lime"]},
                "consulta": {"eje": "P1_btc", "cruce": ["lime stabilization"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_cliente_explorar", lambda config: ClienteFalso())
    codigo = cli.main(["explorar", "bloques de tierra", "--protocolo", str(ruta)])
    salida = capsys.readouterr().out
    assert codigo == 0
    assert "la cosecha encontraría 1 de 4" in salida
    assert "NO la busca" in salida
    assert "no una búsqueda exhaustiva" in salida

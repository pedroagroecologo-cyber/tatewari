"""Normalización y paginación de las fuentes, contra respuestas guardadas.

Nada de red: todo sale de `tests/respuestas/`, servido por un cliente falso
(AGENTS.md, regla 6).
"""

from __future__ import annotations

import pytest

from tatewari.config import ErrorConfig
from tatewari.fuentes import CAMPOS_REGISTRO, NR, crossref, openalex, unpaywall
from tatewari.http import ErrorHttpCliente

CORREO = "prueba@ejemplo.invalid"


# ---------------------------------------------------------------------------
# Reconstrucción del resumen
# ---------------------------------------------------------------------------


def test_el_resumen_coloca_todas_las_apariciones_de_cada_palabra():
    """Una palabra repetida va en TODAS sus posiciones, no solo en la primera."""
    indice = {
        "El": [0],
        "humedal": [1, 7],
        "artificial": [2],
        "remueve": [3, 8],
        "DQO": [4],
        "y": [5],
        "el": [6],
        "SST": [9],
    }

    texto = openalex.reconstruir_resumen(indice)

    assert texto == "El humedal artificial remueve DQO y el humedal remueve SST"
    # Si se ordenara por la primera aparición saldría esto otro, que está mal:
    assert texto != "El humedal artificial remueve DQO y el SST"


def test_el_orden_de_las_claves_no_altera_el_resultado():
    """El JSON no garantiza orden; el resumen solo depende de las posiciones."""
    derecho = {"uno": [0], "dos": [1], "tres": [2]}
    revuelto = {"tres": [2], "uno": [0], "dos": [1]}

    assert openalex.reconstruir_resumen(derecho) == openalex.reconstruir_resumen(revuelto)


@pytest.mark.parametrize("vacio", [None, {}, [], "", {"palabra": "no es lista"}])
def test_sin_indice_el_resumen_es_nr(vacio):
    assert openalex.reconstruir_resumen(vacio) == NR


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def test_normaliza_una_obra_completa(respuesta):
    obra = respuesta("openalex_pagina1.json")["results"][0]

    registro = openalex.normalizar_obra(obra)

    assert set(registro) == set(CAMPOS_REGISTRO)
    # El DOI queda desnudo y en minúsculas, sin el prefijo de resolución.
    assert registro["doi"] == "10.0000/sintetico.101"
    assert registro["anio"] == 2021
    assert registro["idioma"] == "es"
    assert registro["revista"] == "Revista Sintética de Ingeniería Ambiental"
    assert registro["autores"] == ["Prueba Uno, A.", "Prueba Dos, B."]
    assert registro["tipo"] == "article"
    assert registro["citas"] == 11
    assert registro["oa_url"] == "https://ejemplo.invalid/sintetico/101.pdf"
    assert "humedal artificial remueve" in registro["resumen"]


def test_lo_que_falta_se_marca_nr_y_no_se_inventa(respuesta):
    """AGENTS.md, regla 2: un hueco se marca, nunca se rellena con algo plausible."""
    obra = respuesta("openalex_pagina1.json")["results"][1]

    registro = openalex.normalizar_obra(obra)

    assert registro["doi"] == NR
    assert registro["anio"] == NR
    assert registro["idioma"] == NR
    assert registro["revista"] == NR
    assert registro["autores"] == [NR]
    assert registro["resumen"] == NR
    assert registro["oa_url"] == NR
    # Lo que sí venía se conserva.
    assert registro["tipo"] == "article"
    assert registro["citas"] == 0


def test_una_obra_que_no_es_un_objeto_no_revienta():
    assert openalex.normalizar_obra("esto no es una obra")["doi"] == NR


def test_el_oa_url_cae_al_landing_page_si_no_hay_pdf(respuesta):
    obra = respuesta("openalex_pagina2.json")["results"][0]

    registro = openalex.normalizar_obra(obra)

    assert registro["oa_url"] == "https://ejemplo.invalid/sintetico/102"


def test_pagina_por_cursor_hasta_que_se_acaba(protocolo, cliente_falso, respuesta):
    cliente = cliente_falso(
        [respuesta("openalex_pagina1.json"), respuesta("openalex_pagina2.json")]
    )

    resultado = openalex.buscar('"humedal" AND "UASB"', protocolo, cliente, CORREO)

    assert resultado.paginas == 2
    assert len(resultado.registros) == 3
    assert resultado.total_declarado == 3
    # La primera pide el cursor inicial; la segunda, el que vino en meta.
    assert "cursor=*" in cliente.urls[0]
    assert "cursor=IlszLCAxNjA5" in cliente.urls[1]
    assert "cursor=*" not in cliente.urls[1]


def test_se_respeta_el_tope_de_paginas(protocolo, cliente_falso, respuesta):
    cliente = cliente_falso([respuesta("openalex_pagina1.json")])

    resultado = openalex.buscar(
        '"humedal" AND "UASB"', protocolo, cliente, CORREO, max_paginas=1
    )

    assert resultado.paginas == 1
    assert len(cliente.urls) == 1


def test_una_pagina_sin_resultados_corta_la_paginacion(protocolo, cliente_falso):
    cliente = cliente_falso([{"meta": {"count": 0, "next_cursor": "sigue"}, "results": []}])

    resultado = openalex.buscar('"humedal"', protocolo, cliente, CORREO)

    assert resultado.paginas == 1
    assert resultado.registros == []


def test_la_url_literal_es_la_primera_pedida(protocolo, cliente_falso, respuesta):
    cliente = cliente_falso([respuesta("openalex_pagina2.json")])

    resultado = openalex.buscar('"humedal"', protocolo, cliente, CORREO)

    assert resultado.url_literal == cliente.urls[0]
    assert resultado.url_literal.startswith("https://api.openalex.org/works?")


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------


def test_crossref_normaliza_con_la_misma_forma(respuesta):
    item = respuesta("crossref_pagina1.json")["message"]["items"][0]

    registro = crossref.normalizar_item(item)

    assert set(registro) == set(CAMPOS_REGISTRO)
    assert registro["doi"] == "10.0000/sintetico.201"
    assert registro["anio"] == 2020
    assert registro["autores"] == ["Duplicado, F.", "Duplicado, G."]
    # journal-article se traduce al vocabulario de los protocolos.
    assert registro["tipo"] == "article"
    # Crossref no dice de forma fiable si hay versión abierta: eso es Unpaywall.
    assert registro["oa_url"] == NR


def test_crossref_limpia_el_jats_del_resumen(respuesta):
    item = respuesta("crossref_pagina1.json")["message"]["items"][0]

    registro = crossref.normalizar_item(item)

    assert "<jats:p>" not in registro["resumen"]
    assert registro["resumen"].startswith("Registro sintético de prueba.")
    assert "remoción" in registro["resumen"]


def test_crossref_marca_nr_lo_que_no_viene(respuesta):
    item = respuesta("crossref_pagina1.json")["message"]["items"][1]

    registro = crossref.normalizar_item(item)

    assert registro["revista"] == NR
    assert registro["autores"] == [NR]
    assert registro["resumen"] == NR
    assert registro["idioma"] == NR
    # El año sale de "created" cuando no hay "issued".
    assert registro["anio"] == 2023
    # Un tipo que no está en la tabla se deja tal cual vino, no se adivina.
    assert registro["tipo"] == "preprint"


def test_crossref_busca_y_pagina(protocolo, cliente_falso, respuesta):
    cliente = cliente_falso([respuesta("crossref_pagina1.json")])

    resultado = crossref.buscar('"humedal" AND "UASB"', protocolo, cliente, CORREO)

    assert resultado.paginas == 1
    assert len(resultado.registros) == 2
    assert resultado.total_declarado == 2


# ---------------------------------------------------------------------------
# Unpaywall
# ---------------------------------------------------------------------------


def test_unpaywall_exige_correo():
    with pytest.raises(ErrorConfig) as capturado:
        unpaywall.construir_url("10.0000/sintetico.101", "")

    mensaje = str(capturado.value)
    assert "Unpaywall exige un correo" in mensaje
    assert "TATEWARI_MAILTO" in mensaje


def test_unpaywall_tambien_falla_si_el_correo_no_es_un_correo():
    with pytest.raises(ErrorConfig):
        unpaywall.construir_url("10.0000/sintetico.101", "esto-no-es-un-correo")


def test_unpaywall_sin_doi_no_consulta():
    with pytest.raises(ErrorConfig) as capturado:
        unpaywall.construir_url(NR, CORREO)

    assert "sin DOI" in str(capturado.value)


def test_unpaywall_arma_la_url_con_el_correo():
    url = unpaywall.construir_url("10.0000/sintetico.101", CORREO)

    assert url == f"https://api.unpaywall.org/v2/10.0000/sintetico.101?email={CORREO}"


def test_unpaywall_resuelve_una_version_abierta(cliente_falso, respuesta):
    cliente = cliente_falso([respuesta("unpaywall_abierto.json")])

    ubicacion = unpaywall.resolver("10.0000/sintetico.101", cliente, CORREO)

    assert ubicacion.esta_abierto
    assert ubicacion.estado == unpaywall.ESTADO_ABIERTO
    assert ubicacion.oa_url == "https://ejemplo.invalid/sintetico/101.pdf"
    assert ubicacion.version == "publishedVersion"
    assert ubicacion.licencia == "cc-by"


def test_sin_version_abierta_se_pide_por_via_institucional(cliente_falso, respuesta):
    """AGENTS.md, regla 5: no se intenta ninguna otra vía."""
    cliente = cliente_falso([respuesta("unpaywall_cerrado.json")])

    ubicacion = unpaywall.resolver("10.0000/sintetico.203", cliente, CORREO)

    assert not ubicacion.esta_abierto
    assert ubicacion.estado == unpaywall.ESTADO_CERRADO
    assert ubicacion.oa_url == NR
    assert "biblioteca institucional" in ubicacion.nota


def test_un_doi_desconocido_no_tumba_nada(cliente_falso):
    cliente = cliente_falso(
        [ErrorHttpCliente("404", url="https://api.unpaywall.org/v2/x", estado=404)]
    )

    ubicacion = unpaywall.resolver("10.0000/no-existe", cliente, CORREO)

    assert ubicacion.estado == unpaywall.ESTADO_DESCONOCIDO
    assert "404" in ubicacion.nota

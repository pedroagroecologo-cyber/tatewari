"""Normalización contra respuestas **reales** capturadas de las APIs.

Las demás pruebas usan respuestas escritas según la documentación. Estas usan
capturas de verdad, tomadas el 2026-09-12 y guardadas en `tests/respuestas/`.
Siguen sin tocar la red: se leen del disco como cualquier otro fixture
(AGENTS.md, regla 6).

Su trabajo es distinto al de las otras: no comprueban que el código haga lo que
queremos, sino que **la forma real de la respuesta sea la que creíamos**. Si
OpenAlex o Crossref cambian algo, estas pruebas son las que se ponen rojas.
"""

from __future__ import annotations

import pytest

from tatewari.fuentes import CAMPOS_REGISTRO, NR, crossref, openalex

CORREO = "prueba@ejemplo.invalid"


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def test_la_respuesta_real_trae_los_campos_que_consumimos(respuesta):
    obra = respuesta("openalex_real_pagina1.json")["results"][0]

    for campo in (
        "id",
        "doi",
        "title",
        "publication_year",
        "language",
        "type",
        "cited_by_count",
        "authorships",
        "primary_location",
        "open_access",
    ):
        assert campo in obra, f"la respuesta real ya no trae {campo}"


def test_normaliza_una_obra_real_sin_perder_nada(respuesta):
    obra = respuesta("openalex_real_pagina1.json")["results"][0]

    registro = openalex.normalizar_obra(obra)

    assert set(registro) == set(CAMPOS_REGISTRO)
    assert registro["doi"].startswith("10.")
    assert "https://doi.org/" not in registro["doi"]
    assert isinstance(registro["anio"], int)
    assert registro["idioma"] in ("es", "en")
    assert registro["tipo"] in ("article", "review")
    assert isinstance(registro["citas"], int)
    assert registro["autores"] != [NR]


def test_el_cursor_real_aparece_y_encadena_las_paginas(respuesta, cliente_falso, protocolo):
    """`next_cursor` solo viene si se pidió con `cursor`; nuestro código lo pide."""
    pagina1 = respuesta("openalex_real_pagina1.json")
    pagina2 = respuesta("openalex_real_pagina2.json")
    assert pagina1["meta"]["next_cursor"]

    cliente = cliente_falso([pagina1, pagina2, {"meta": {}, "results": []}])
    resultado = openalex.buscar('"x" AND "y"', protocolo, cliente, CORREO, max_paginas=3)

    assert resultado.paginas == 3
    assert len(resultado.registros) == 6
    assert "cursor=*" in cliente.urls[0]
    assert "cursor=*" not in cliente.urls[1]


def test_el_resumen_real_se_reconstruye_entero(respuesta):
    """Contra un índice invertido real, con palabras repetidas de verdad."""
    obra = respuesta("openalex_real_con_resumen.json")["results"][0]
    indice = obra["abstract_inverted_index"]

    repetidas = {p: v for p, v in indice.items() if len(v) > 1}
    assert repetidas, "la captura debería traer palabras en varias posiciones"

    texto = openalex.reconstruir_resumen(indice)

    # Salen tantas palabras como posiciones hay, no como claves distintas.
    total_posiciones = sum(len(v) for v in indice.values())
    assert len(texto.split()) == total_posiciones
    assert len(texto.split()) > len(indice)
    assert len(texto) > 500

    # Cada palabra repetida aparece tantas veces como posiciones tiene.
    palabra, posiciones = next(iter(repetidas.items()))
    assert texto.split().count(palabra) == len(posiciones)


def test_la_mayoria_de_las_obras_reales_no_traen_resumen(respuesta):
    """Dato operativo, no un fallo: el cribado tiene que contar con ello.

    En la captura del 2026-09-12, 6 de 50 obras traían
    `abstract_inverted_index`. Las que no, se normalizan a "NR" sin romperse.
    """
    obras = respuesta("openalex_real_pagina1.json")["results"]

    registros = [openalex.normalizar_obra(o) for o in obras]

    assert all(set(r) == set(CAMPOS_REGISTRO) for r in registros)
    assert all(r["resumen"] == NR for r in registros)


def test_un_best_oa_location_nulo_no_rompe_la_normalizacion(respuesta):
    obras = respuesta("openalex_real_pagina1.json")["results"]
    cerradas = [o for o in obras if o.get("best_oa_location") is None]

    if not cerradas:
        pytest.skip("la captura no trae ninguna obra sin ubicación abierta")

    registro = openalex.normalizar_obra(cerradas[0])
    assert registro["oa_url"] == NR or registro["oa_url"].startswith("http")


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------


def test_la_respuesta_real_de_crossref_tiene_la_forma_esperada(respuesta):
    mensaje = respuesta("crossref_real_pagina1.json")["message"]

    assert "items" in mensaje
    assert "total-results" in mensaje
    assert mensaje.get("next-cursor")

    item = mensaje["items"][0]
    assert "DOI" in item
    assert isinstance(item.get("title"), list)


def test_normaliza_un_item_real_de_crossref(respuesta):
    item = respuesta("crossref_real_pagina1.json")["message"]["items"][0]

    registro = crossref.normalizar_item(item)

    assert set(registro) == set(CAMPOS_REGISTRO)
    assert registro["doi"].startswith("10.")
    assert registro["doi"] == registro["doi"].lower()
    assert isinstance(registro["anio"], int)
    # journal-article es el tipo que más sale, y se traduce.
    assert registro["tipo"] != "journal-article"


def test_los_tipos_reales_de_crossref_estan_contemplados(respuesta):
    """Si aparece un tipo nuevo, se deja tal cual: nunca se adivina."""
    items = respuesta("crossref_real_pagina1.json")["message"]["items"]

    for item in items:
        registro = crossref.normalizar_item(item)
        crudo = item.get("type")
        esperado = crossref.TIPOS.get(crudo, crudo)
        assert registro["tipo"] == esperado

"""PRUEBA DE ORO: el cribado de `fixtures/demo.json` con `protocolos/humedales.json`.

Es la prueba más importante del repositorio y la que hay que leer antes de tocar
el protocolo o el motor de reglas.

Los catorce registros del fixture están escritos uno a uno para provocar un caso
del cribado: un duplicado con el DOI en mayúsculas, uno anterior a la ventana,
uno en portugués, uno de análisis de ciclo de vida, uno sin resumen, uno sin DOI,
uno que habla de humedales de aguas pluviales sin decir si trata agua residual…
Aquí se fija **exactamente** qué decide el cribado sobre cada uno, con números y
con DOI concretos.

Si alguien cambia las reglas del protocolo, los términos de un bloque o el orden
de evaluación, y estos catorce registros dejan de decidirse igual, esta prueba se
rompe. Eso es lo que se quiere: la decisión puede cambiar, pero no a escondidas.
Cuando el cambio sea el correcto, se actualizan estos números **a mano** y en el
mismo commit, para que quede escrito que la decisión cambió y por qué.

Nota sobre el recuento de exclusiones
-------------------------------------

Son **tres**: una por ventana temporal, una por idioma y una por exclusión
temática. El fixture tiene un solo registro fuera de la ventana 2016-2026 (el de
2009), y `test_fixture.py::test_hay_un_registro_anterior_a_la_ventana` lo fija
así. Los otros dos registros que no acaban en «incluir» son **dudosos**, no
exclusiones: el que no trae resumen y el de humedales de aguas pluviales. Ninguno
se descarta en automático (AGENTS.md, regla 4).
"""

from __future__ import annotations

import json

import pytest

from tatewari.cribado import (
    CATEGORIA_IDIOMA,
    CATEGORIA_TEMA,
    CATEGORIA_VENTANA,
    cribar,
)

# --- Los números fijos -----------------------------------------------------

IDENTIFICADOS = 14
DUPLICADOS_ELIMINADOS = 1
UNICOS = 13

INCLUIR = 8
DUDOSO = 2
EXCLUIR = 3

MOTIVOS_DE_EXCLUSION = {
    CATEGORIA_VENTANA: 1,
    CATEGORIA_IDIOMA: 1,
    CATEGORIA_TEMA: 1,
}

#: La decisión de cada artículo único, por DOI. Se indexa por DOI y no por
#: identificador a propósito: así esta tabla habla de *qué* se decidió sobre cada
#: artículo, y reordenar el fixture no la rompe. Los identificadores estables se
#: comprueban aparte, en `test_los_identificadores_son_los_esperados`.
DECISIONES_ESPERADAS = {
    "10.0000/sintetico.001": ("incluir", ""),
    "10.0000/sintetico.002": ("incluir", ""),
    "10.0000/sintetico.003": ("incluir", ""),
    "10.0000/sintetico.004": ("excluir", CATEGORIA_VENTANA),
    "10.0000/sintetico.005": ("excluir", CATEGORIA_IDIOMA),
    "10.0000/sintetico.006": ("excluir", CATEGORIA_TEMA),
    "10.0000/sintetico.007": ("dudoso", ""),
    "10.0000/sintetico.008": ("incluir", ""),
    "10.0000/sintetico.009": ("incluir", ""),
    "10.0000/sintetico.010": ("incluir", ""),
    "NR": ("incluir", ""),
    "10.0000/sintetico.011": ("dudoso", ""),
    "10.0000/sintetico.012": ("incluir", ""),
}

#: Qué identificador estable le toca a cada artículo, en el orden del fixture.
IDENTIFICADORES_ESPERADOS = {
    "10.0000/sintetico.001": "R0001",
    "10.0000/sintetico.002": "R0002",
    "10.0000/sintetico.003": "R0003",
    "10.0000/sintetico.004": "R0004",
    "10.0000/sintetico.005": "R0005",
    "10.0000/sintetico.006": "R0006",
    "10.0000/sintetico.007": "R0007",
    "10.0000/sintetico.008": "R0008",
    "10.0000/sintetico.009": "R0009",
    "10.0000/sintetico.010": "R0010",
    "NR": "R0011",
    "10.0000/sintetico.011": "R0012",
    "10.0000/sintetico.012": "R0013",
}


@pytest.fixture
def registros_demo(ruta_fixture_demo):
    with open(ruta_fixture_demo, encoding="utf-8") as manejador:
        return json.load(manejador)


@pytest.fixture
def oro(registros_demo, protocolo):
    """El cribado del fixture de demostración. No toca disco ni red."""
    return cribar(
        registros_demo,
        protocolo,
        revision="demo",
        fecha="2026-01-01T00:00:00",
    )


def por_doi(resultado):
    """Las decisiones indexadas por el DOI del registro."""
    return {d.registro["doi"]: d for d in resultado.decisiones}


# --- El recuento -----------------------------------------------------------


def test_el_fixture_da_trece_registros_unicos(oro):
    """Catorce registros, uno de ellos duplicado: trece artículos."""
    assert oro.identificados == IDENTIFICADOS
    assert oro.duplicados_eliminados == DUPLICADOS_ELIMINADOS
    assert oro.cribados == UNICOS
    assert UNICOS == IDENTIFICADOS - DUPLICADOS_ELIMINADOS


def test_el_desglose_de_decisiones_es_el_esperado(oro):
    conteos = oro.conteos

    assert conteos["incluir"] == INCLUIR
    assert conteos["dudoso"] == DUDOSO
    assert conteos["excluir"] == EXCLUIR
    # Ningún registro se queda sin decisión ni se cuenta dos veces.
    assert INCLUIR + DUDOSO + EXCLUIR == UNICOS


def test_las_exclusiones_son_tres_y_con_estos_motivos(oro):
    """Una por ventana, una por idioma y una por exclusión temática.

    El desglose se fija entero con `==`, no motivo a motivo: si apareciera una
    cuarta categoría de exclusión, esta prueba tiene que romperse.
    """
    assert dict(oro.motivos_de_exclusion) == MOTIVOS_DE_EXCLUSION
    assert sum(MOTIVOS_DE_EXCLUSION.values()) == EXCLUIR


def test_cada_articulo_se_decide_exactamente_asi(oro):
    """La tabla completa: trece artículos, trece decisiones fijadas."""
    obtenidas = {
        doi: (decision.decision, decision.categoria)
        for doi, decision in por_doi(oro).items()
    }

    assert obtenidas == DECISIONES_ESPERADAS


def test_los_identificadores_son_los_esperados(oro):
    obtenidos = {
        doi: decision.identificador for doi, decision in por_doi(oro).items()
    }

    assert obtenidos == IDENTIFICADORES_ESPERADOS


# --- Los casos uno a uno ---------------------------------------------------


def test_el_duplicado_se_funde_en_un_solo_registro(oro):
    """Mismo DOI salvo mayúsculas y mismo título salvo acentos: un artículo."""
    decision = por_doi(oro)["10.0000/sintetico.003"]

    assert decision.registro["copias"] == 2
    assert decision.decision == "incluir"
    # Se queda con los metadatos del primero que llegó, no con los del preprint.
    assert decision.registro["revista"] == "Anales Sintéticos de Saneamiento"


def test_el_registro_de_2009_se_excluye_por_ventana_y_no_por_contenido(oro):
    decision = por_doi(oro)["10.0000/sintetico.004"]

    assert decision.decision == "excluir"
    assert decision.categoria == CATEGORIA_VENTANA
    assert decision.registro["anio"] == 2009
    assert "2016-2026" in decision.motivo
    assert "2009" in decision.motivo


def test_el_registro_en_portugues_se_excluye_por_idioma(oro):
    decision = por_doi(oro)["10.0000/sintetico.005"]

    assert decision.decision == "excluir"
    assert decision.categoria == CATEGORIA_IDIOMA
    assert decision.registro["idioma"] == "pt"
    assert "pt" in decision.motivo


def test_el_analisis_de_ciclo_de_vida_se_excluye_por_tema_citando_el_termino(oro):
    decision = por_doi(oro)["10.0000/sintetico.006"]

    assert decision.decision == "excluir"
    assert decision.categoria == CATEGORIA_TEMA
    # El motivo cita el término del protocolo que lo disparó: sin eso no se
    # puede auditar la exclusión sin releer el resumen.
    assert "life cycle assessment" in decision.motivo


def test_el_registro_sin_resumen_queda_dudoso_y_no_excluido(oro):
    """El error clásico es descartar lo que no se puede leer. Aquí no."""
    decision = por_doi(oro)["10.0000/sintetico.007"]

    assert decision.registro["resumen"] == "NR"
    assert decision.decision == "dudoso"
    assert decision.categoria == ""
    assert "no es cribable en automático" in decision.motivo


def test_el_de_aguas_pluviales_queda_dudoso_para_que_lo_vea_una_persona(oro):
    """Habla de humedales pero nunca dice si trata agua residual."""
    decision = por_doi(oro)["10.0000/sintetico.011"]

    assert decision.decision == "dudoso"
    assert decision.regla.startswith("dudoso[")


def test_el_registro_sin_doi_se_criba_igual_que_los_demas(oro):
    """Sin DOI se agrupa por título, y eso no le quita el derecho a decidirse."""
    decision = por_doi(oro)["NR"]

    assert decision.identificador == "R0011"
    assert decision.decision == "incluir"
    assert decision.registro["revista"] == "NR"


def test_toda_exclusion_lleva_motivo_y_categoria(oro):
    """AGENTS.md, regla 4: toda exclusión lleva un motivo explícito y trazable."""
    for decision in oro.por_decision("excluir"):
        assert decision.motivo.strip()
        assert decision.categoria.strip()


def test_ninguna_decision_la_tomo_nadie_a_mano(oro):
    """Sin `decisiones.json`, todo lo decide el filtro."""
    assert oro.manuales == 0
    assert all(d.decidido_por == "filtro" for d in oro.decisiones)
    assert not oro.avisos


# --- El diagrama -----------------------------------------------------------


def test_el_diagrama_prisma_lleva_los_numeros_de_oro(oro):
    diagrama = oro.diagrama()

    assert "Registros identificados en las búsquedas" in diagrama
    assert diagrama.count(" 14") >= 1
    for etiqueta, cuantos in (
        ("Registros cribados", UNICOS),
        ("Incluir", INCLUIR),
        ("Excluir", EXCLUIR),
    ):
        linea = next(l for l in diagrama.splitlines() if l.strip().startswith(etiqueta))
        assert linea.endswith(f" {cuantos}")


# --- La prueba de que esta prueba sirve ------------------------------------


def test_si_se_estrecha_la_ventana_el_recuento_cambia(registros_demo, protocolo):
    """Comprueba que los números de arriba son sensibles al protocolo.

    Una prueba de oro que no se rompiera al cambiar el protocolo no estaría
    vigilando nada. Aquí se estrecha la ventana a 2020-2026 y se exige que el
    recuento de exclusiones se mueva.
    """
    from dataclasses import replace

    estrecho = replace(protocolo, ventana=(2020, 2026))

    resultado = cribar(registros_demo, estrecho, revision="demo")

    assert resultado.conteos["excluir"] > EXCLUIR
    assert resultado.motivos_de_exclusion[CATEGORIA_VENTANA] > 1

"""Pruebas de la normalización de texto y la detección de términos.

La primera prueba del archivo es la importante: es el fallo del acento, que
dejaría el cribado mudo en español sin dar ningún error.
"""

from __future__ import annotations

import unicodedata

from tatewari.texto import (
    SEPARADOR_DE_CAMPOS,
    clave_alfanumerica,
    contiene,
    nombres_presentes,
    normalizar,
    terminos_presentes,
    texto_buscable,
)

# ---------------------------------------------------------------------------
# El fallo del acento
# ---------------------------------------------------------------------------


def test_un_termino_sin_acento_encuentra_un_texto_con_acento():
    """ESTO IMPORTA.

    Los términos del protocolo se escriben a mano y a veces van sin acento. Si
    el texto del registro solo se pasara a minúsculas, un resumen en español
    perfectamente escrito no coincidiría con ellos: el cribado se quedaría mudo,
    sin fallar y sin avisar, y los artículos en español acabarían excluidos por
    no cumplir ninguna regla. Hay que normalizar **los dos lados**.
    """
    resumen = (
        "Se evaluó la eficiencia de remoción de DQO y de nitrógeno total en un "
        "tanque séptico seguido de un humedal artificial."
    )

    # Términos del protocolo escritos sin acento, como se escriben de verdad.
    assert contiene(resumen, "remocion")
    assert contiene(resumen, "nitrogeno total")
    assert contiene(resumen, "tanque septico")

    # Y al revés: un término acentuado encuentra un texto sin acentos.
    sin_acentos = "remocion de nitrogeno total en un tanque septico"
    assert contiene(sin_acentos, "remoción")
    assert contiene(sin_acentos, "nitrógeno total")
    assert contiene(sin_acentos, "tanque séptico")


def test_solo_minusculas_no_bastaria():
    """Deja escrito por qué no vale `texto.lower()` y se acabó."""
    resumen = "la remoción de DQO"

    assert "remocion" not in resumen.lower()  # el fallo, si no se normalizara
    assert contiene(resumen, "remocion")  # la cura


# ---------------------------------------------------------------------------
# normalizar
# ---------------------------------------------------------------------------


def test_normalizar_pasa_a_minusculas_y_quita_los_acentos():
    assert normalizar("REMOCIÓN de Nitrógeno") == "remocion de nitrogeno"
    assert normalizar("Évaluación à la Française") == "evaluacion a la francaise"


def test_normalizar_descompone_en_nfd_y_descarta_los_combinantes():
    """La ñ se descompone y pierde la tilde: es deliberado y está documentado."""
    assert normalizar("desempeño") == "desempeno"
    # El texto normalizado no conserva ni un solo carácter combinante.
    for caracter in normalizar("ÁÉÍÓÚñüÇ"):
        assert unicodedata.combining(caracter) == 0


def test_normalizar_unifica_guiones_y_espacios_raros():
    """Un título copiado de un PDF viene lleno de guiones largos y espacios raros."""
    assert normalizar("UASB — humedal") == normalizar("UASB - humedal")
    assert normalizar("agua residual") == "agua residual"
    assert normalizar("  varios    espacios  ") == "varios espacios"


def test_normalizar_aguanta_lo_que_no_es_texto():
    assert normalizar(None) == ""
    assert normalizar(2021) == "2021"


def test_clave_alfanumerica_deja_solo_letras_y_numeros():
    con_acentos = "Tanque séptico — caracterización del efluente (2020)"
    sin_acentos = "Tanque septico - caracterizacion del efluente 2020"

    assert clave_alfanumerica(con_acentos) == clave_alfanumerica(sin_acentos)
    assert clave_alfanumerica(con_acentos).isalnum()


# ---------------------------------------------------------------------------
# Palabra completa
# ---------------------------------------------------------------------------


def test_un_termino_no_coincide_dentro_de_otra_palabra():
    """El falso positivo silencioso que justifica los límites de palabra."""
    assert not contiene("total phosphorus removal", "pH")
    assert not contiene("pathogens were counted", "pH")
    assert not contiene("se midió la alcalinidad del agua", "LCA")


def test_una_sigla_si_coincide_cuando_va_suelta():
    assert contiene("turbidez y pH del efluente", "pH")
    assert contiene("a life cycle assessment (LCA) compares", "LCA")
    assert contiene("un reactor UASB de flujo ascendente", "UASB")


def test_el_punto_de_un_termino_es_un_punto_y_no_un_comodin():
    assert contiene("se midió E. coli en el efluente", "E. coli")
    assert not contiene("se midió Escherichia coli", "E. coli")


def test_dentro_del_termino_los_espacios_admiten_varios():
    assert contiene("un tanque  séptico rural", "tanque séptico")


def test_la_ultima_palabra_del_termino_admite_plural():
    """El protocolo lista unas veces el singular y otras el plural."""
    assert contiene("treatment wetlands for stormwater", "treatment wetland")
    assert contiene("se midieron las remociones de DQO", "remoción")
    assert contiene("sólidos suspendidos totales", "sólidos suspendidos total")


def test_el_plural_no_va_al_reves():
    """Es tolerancia al plural, no un lematizador; queda escrito en la prueba."""
    assert not contiene("a single pathogen was found", "pathogens")


# ---------------------------------------------------------------------------
# Detección de bloques
# ---------------------------------------------------------------------------


def test_terminos_presentes_devuelve_el_termino_del_protocolo_tal_cual():
    """Para que el motivo cite la palabra del protocolo, con sus acentos."""
    hallados = terminos_presentes(
        "la remocion de DQO en el humedal artificial",
        ["remoción", "DQO", "fósforo total"],
    )

    assert hallados == ("remoción", "DQO")


def test_nombres_presentes_solo_devuelve_los_bloques_con_algun_termino():
    mapa = {
        "P2_humedal": ["humedal artificial", "constructed wetland"],
        "P3_anaerobio": ["tanque séptico", "UASB"],
        "P5_parametros": ["DQO", "fósforo total"],
    }

    presentes = nombres_presentes(mapa, "un humedal artificial que remueve DQO")

    assert set(presentes) == {"P2_humedal", "P5_parametros"}
    assert presentes["P2_humedal"] == ("humedal artificial",)
    assert presentes["P5_parametros"] == ("DQO",)


def test_texto_buscable_descarta_los_nr():
    """Un campo no reportado no aporta texto, y «NR» no se busca como palabra."""
    assert texto_buscable("Un título", "NR") == "Un título"
    assert texto_buscable("NR", "NR") == ""
    assert texto_buscable("Título", "Resumen") == (
        "Título" + SEPARADOR_DE_CAMPOS + "Resumen"
    )


def test_un_termino_no_cruza_del_titulo_al_resumen():
    """El falso positivo que justifica que el separador no sea un espacio.

    El título acaba en «…de agua» y el resumen empieza por «residual…», pero
    «agua residual» no está en ninguno de los dos, así que no puede darse por
    encontrado. Un salto de línea no serviría: `normalizar` lo convierte en
    espacio y la expresión del término lo saltaría.
    """
    junto = texto_buscable("tratamiento de agua", "residual doméstica")

    assert not contiene(junto, "agua residual")
    # Los términos de cada lado sí se siguen encontrando.
    assert contiene(junto, "tratamiento")
    assert contiene(junto, "residual doméstica")

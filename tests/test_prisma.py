"""Pruebas del diagrama de flujo PRISMA en texto."""

from __future__ import annotations

from tatewari.prisma import Flujo, diagrama


def flujo(**campos) -> Flujo:
    base = {
        "revision": "demo",
        "protocolo": "Protocolo de prueba",
        "fecha": "2026-01-01T00:00:00",
        "identificados": 14,
        "duplicados_eliminados": 1,
        "conteos": {"incluir": 8, "dudoso": 2, "excluir": 3},
        "motivos": {
            "Fuera de la ventana temporal": 1,
            "Idioma no admitido": 1,
            "Exclusión temática": 1,
        },
    }
    base.update(campos)
    return Flujo(**base)


def valor_de(texto: str, etiqueta: str) -> int:
    """El número de la línea que empieza por `etiqueta`."""
    linea = next(l for l in texto.splitlines() if l.strip().startswith(etiqueta))
    return int(linea.rsplit(" ", 1)[1])


def test_los_cribados_son_los_identificados_menos_los_duplicados():
    assert flujo().cribados == 13


def test_el_diagrama_lleva_las_tres_etapas_y_sus_numeros():
    texto = diagrama(flujo())

    assert "IDENTIFICACIÓN" in texto
    assert "CRIBADO" in texto
    assert valor_de(texto, "Registros identificados") == 14
    assert valor_de(texto, "Duplicados eliminados") == 1
    assert valor_de(texto, "Registros cribados") == 13
    assert valor_de(texto, "Incluir") == 8
    assert valor_de(texto, "Dudoso") == 2
    assert valor_de(texto, "Excluir") == 3


def test_el_diagrama_dice_de_qué_revision_y_protocolo_es():
    texto = diagrama(flujo())

    assert "demo" in texto
    assert "Protocolo de prueba" in texto


def test_los_motivos_van_de_mayor_a_menor():
    """Lo primero que se quiere ver en un PRISMA es por qué se cayó la mayoría."""
    texto = diagrama(
        flujo(
            conteos={"incluir": 1, "dudoso": 0, "excluir": 9},
            motivos={"Poco frecuente": 1, "El más frecuente": 6, "Intermedio": 2},
        )
    )

    assert (
        texto.index("El más frecuente")
        < texto.index("Intermedio")
        < texto.index("Poco frecuente")
    )
    assert valor_de(texto, "El más frecuente") == 6
    assert valor_de(texto, "Poco frecuente") == 1


def test_a_igual_numero_los_motivos_se_ordenan_alfabeticamente():
    """Dos ejecuciones con los mismos datos dan exactamente el mismo texto."""
    motivos = {"Zeta": 2, "Alfa": 2, "Mu": 2}

    texto = diagrama(flujo(conteos={"incluir": 0, "dudoso": 0, "excluir": 6}, motivos=motivos))

    assert texto.index("Alfa") < texto.index("Mu") < texto.index("Zeta")


def test_el_diagrama_recuerda_que_los_dudosos_no_estan_descartados():
    """AGENTS.md, regla 4: el cribado automático propone, no decide."""
    texto = diagrama(flujo())

    assert "NO están descartados" in texto
    assert "revisión" in texto
    assert "regla 4" in texto


def test_sin_dudosos_el_aviso_cambia_pero_sigue_estando():
    texto = diagrama(flujo(conteos={"incluir": 12, "dudoso": 0, "excluir": 1}))

    assert "No quedan registros dudosos" in texto
    assert "auditan por muestreo" in texto


def test_las_decisiones_que_no_tomo_el_filtro_se_anuncian_cuando_hay():
    """Da igual si fue una persona o el modelo local: no lo decidió el filtro."""
    assert "Decisiones que no tomó el filtro" in diagrama(flujo(manuales=3))
    assert "Decisiones que no tomó el filtro" not in diagrama(flujo(manuales=0))


def test_sin_exclusiones_no_se_imprime_la_lista_de_motivos():
    texto = diagrama(
        flujo(conteos={"incluir": 13, "dudoso": 0, "excluir": 0}, motivos={})
    )

    assert "Motivos de exclusión" not in texto


def test_una_etiqueta_larguisima_no_rompe_la_linea():
    texto = diagrama(flujo(motivos={"M" * 200: 1}))

    assert "M" * 200 + " 1" in texto

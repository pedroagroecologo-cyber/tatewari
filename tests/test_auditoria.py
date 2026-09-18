"""Pruebas de la auditoría por muestreo de las exclusiones."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from tatewari.auditoria import (
    MUESTRA_POR_DEFECTO,
    ErrorAuditoria,
    leer_auditorias,
    muestra_aleatoria,
    registrar_auditoria,
)


def test_por_defecto_son_veinte():
    muestra = muestra_aleatoria(list(range(500)))

    assert muestra.cuantos == MUESTRA_POR_DEFECTO == 20
    assert muestra.poblacion == 500


def test_la_muestra_no_repite_elementos():
    """Muestreo sin reemplazo: nadie revisa el mismo registro dos veces."""
    muestra = muestra_aleatoria(list(range(100)), 30)

    assert len(set(muestra.elementos)) == 30


def test_la_semilla_reconstruye_la_misma_muestra():
    """Sin esto la auditoría no se puede repetir, y entonces no es auditoría."""
    primera = muestra_aleatoria(list(range(100)), 20, semilla=12345)
    segunda = muestra_aleatoria(list(range(100)), 20, semilla=12345)

    assert primera.elementos == segunda.elementos


def test_semillas_distintas_dan_muestras_distintas():
    primera = muestra_aleatoria(list(range(100)), 20, semilla=1)
    segunda = muestra_aleatoria(list(range(100)), 20, semilla=2)

    assert primera.elementos != segunda.elementos


def test_la_semilla_se_apunta_aunque_no_se_pase():
    """«Salieron estos veinte» no vale; «y así se comprueba» sí."""
    muestra = muestra_aleatoria(list(range(100)))

    assert muestra.semilla > 0
    repetida = muestra_aleatoria(list(range(100)), semilla=muestra.semilla)
    assert repetida.elementos == muestra.elementos


def test_una_poblacion_mas_pequena_que_la_muestra_se_devuelve_entera():
    muestra = muestra_aleatoria([1, 2, 3], 20)

    assert sorted(muestra.elementos) == [1, 2, 3]
    assert muestra.es_completa
    assert "se revisan todas" in muestra.resumen()


def test_pedir_cero_da_una_muestra_vacia():
    """Y no la población entera, que es el error fácil."""
    assert muestra_aleatoria([1, 2, 3], 0).elementos == []
    assert muestra_aleatoria([1, 2, 3], -5).elementos == []


def test_sin_exclusiones_no_hay_nada_que_auditar():
    muestra = muestra_aleatoria([])

    assert muestra.cuantos == 0
    assert "No hay exclusiones" in muestra.resumen()


def test_la_muestra_no_es_la_cabeza_de_la_lista():
    """Un «muestreo» que devolviera los primeros N no sería aleatorio.

    Se comprueba sobre una población grande: si saliera la cabeza de la lista,
    los elementos serían siempre los mismos y todos pequeños.
    """
    poblacion = list(range(1000))

    muestras = [muestra_aleatoria(poblacion, 20, semilla=s) for s in range(1, 21)]

    for muestra in muestras:
        assert muestra.elementos != poblacion[:20]
    # Y a lo largo de veinte muestras se toca todo el rango, no solo el principio.
    todos = [e for m in muestras for e in m.elementos]
    assert max(todos) > 900
    assert min(todos) < 100


def test_cada_elemento_sale_mas_o_menos_igual_de_veces():
    """Comprobación de uniformidad, que es lo que se pierde al ordenar con clave
    aleatoria: con 200 muestras de 10 sobre 20 elementos, cada uno debería salir
    unas 100 veces."""
    poblacion = list(range(20))

    cuenta: Counter[int] = Counter()
    for semilla in range(200):
        cuenta.update(muestra_aleatoria(poblacion, 10, semilla=semilla).elementos)

    assert len(cuenta) == 20
    # Margen amplio: se vigila el sesgo grosero, no el ruido estadístico.
    assert min(cuenta.values()) > 60
    assert max(cuenta.values()) < 140


def test_la_muestra_no_toca_la_poblacion_original():
    poblacion = [1, 2, 3, 4, 5]

    muestra_aleatoria(poblacion, 3, semilla=1)

    assert poblacion == [1, 2, 3, 4, 5]


def test_el_resumen_dice_el_porcentaje_y_la_semilla():
    resumen = muestra_aleatoria(list(range(100)), 20, semilla=7).resumen()

    assert "20 de 100" in resumen
    assert "20 %" in resumen
    assert "Semilla 7" in resumen


# ---------------------------------------------------------------------------
# El registro en disco
# ---------------------------------------------------------------------------


def test_la_auditoria_queda_registrada(tmp_path):
    """AGENTS.md, regla 4: la auditoría queda registrada."""
    ruta = tmp_path / "auditoria.json"
    muestra = muestra_aleatoria(["R0001", "R0002", "R0003"], 2, semilla=42)

    registrar_auditoria(ruta, muestra, muestra.elementos, revision="demo")

    rondas = json.loads(ruta.read_text(encoding="utf-8"))
    assert len(rondas) == 1
    assert rondas[0]["revision"] == "demo"
    assert rondas[0]["semilla"] == 42
    assert rondas[0]["poblacion"] == 3
    assert len(rondas[0]["muestra"]) == 2
    assert rondas[0]["fecha"]


def test_las_rondas_se_acumulan(tmp_path):
    """El historial de lo que ya se revisó es parte del rastro."""
    ruta = tmp_path / "auditoria.json"

    for semilla in (1, 2, 3):
        muestra = muestra_aleatoria(["R0001", "R0002"], 1, semilla=semilla)
        registrar_auditoria(ruta, muestra, muestra.elementos, revision="demo")

    rondas = leer_auditorias(ruta)
    assert len(rondas) == 3
    assert [r["semilla"] for r in rondas] == [1, 2, 3]


def test_leer_un_historial_que_no_existe_da_una_lista_vacia(tmp_path):
    assert leer_auditorias(tmp_path / "no_existe.json") == []


def test_un_historial_roto_no_se_sobreescribe(tmp_path):
    """Antes que perder el rastro de lo ya auditado, se falla."""
    ruta = tmp_path / "auditoria.json"
    ruta.write_text("{esto no es una lista", encoding="utf-8")

    with pytest.raises(ErrorAuditoria) as fallo:
        leer_auditorias(ruta)

    assert "no es JSON válido" in str(fallo.value)
    # Y el archivo sigue intacto.
    assert ruta.read_text(encoding="utf-8") == "{esto no es una lista"


def test_un_historial_que_no_es_una_lista_tampoco_se_pisa(tmp_path):
    ruta = tmp_path / "auditoria.json"
    ruta.write_text('{"ronda": 1}', encoding="utf-8")

    with pytest.raises(ErrorAuditoria):
        leer_auditorias(ruta)


def test_registrar_no_pisa_un_historial_roto(tmp_path):
    ruta = tmp_path / "auditoria.json"
    ruta.write_text("roto", encoding="utf-8")
    muestra = muestra_aleatoria(["R0001"], 1, semilla=1)

    with pytest.raises(ErrorAuditoria):
        registrar_auditoria(ruta, muestra, muestra.elementos)

    assert ruta.read_text(encoding="utf-8") == "roto"

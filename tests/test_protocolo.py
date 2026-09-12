"""Pruebas de carga y validación del protocolo. No tocan la red."""

from __future__ import annotations

import json

import pytest

from tatewari.protocolo import (
    ErrorProtocolo,
    cargar_protocolo,
    validar_protocolo,
)


# ---------------------------------------------------------------------------
# Validación correcta
# ---------------------------------------------------------------------------


def test_protocolo_minimo_es_valido(protocolo_minimo):
    protocolo = validar_protocolo(protocolo_minimo)

    assert protocolo.titulo == "Protocolo mínimo de prueba"
    assert protocolo.ventana == (2016, 2026)
    assert protocolo.idiomas == ("es", "en")
    assert protocolo.bloques["B1"] == ("alfa", "beta")
    assert protocolo.nombres_definidos == {"B1", "B2"}
    # Sin "consulta" no hay ecuaciones que lanzar.
    assert protocolo.numero_de_ecuaciones == 0


def test_protocolo_completo_es_valido(protocolo_minimo):
    protocolo_minimo.update(
        {
            "exclusion": ["ciclo de vida"],
            "grupos": {"G1": ["delta", "epsilon"]},
            "clasificacion": [{"etiqueta": "Etiqueta", "todos": ["B1", "G1"]}],
            "consulta": {"eje": "B1", "cruce": ["uno", "dos", "tres"]},
            "reglas": {
                "sinResumen": "dudoso",
                "incluir": [
                    {
                        "todos": ["B1"],
                        "alguno_de": [["B2", "G1"]],
                        "ninguno": ["G1"],
                        "motivo": "Motivo de prueba.",
                    }
                ],
                "dudoso": [{"todos": ["B2"]}],
            },
        }
    )

    protocolo = validar_protocolo(protocolo_minimo)

    assert protocolo.grupos["G1"] == ("delta", "epsilon")
    assert protocolo.clasificacion[0].etiqueta == "Etiqueta"
    assert protocolo.consulta.eje == "B1"
    assert protocolo.reglas.sin_resumen == "dudoso"
    assert protocolo.reglas.incluir[0].alguno_de == (("B2", "G1"),)
    # Un motivo ausente queda en "NR", nunca inventado (AGENTS.md, regla 2).
    assert protocolo.reglas.dudoso[0].motivo == "NR"
    # 2 términos del eje x 3 del cruce.
    assert protocolo.numero_de_ecuaciones == 6


def test_carga_el_protocolo_de_humedales(ruta_protocolo_humedales):
    protocolo = cargar_protocolo(ruta_protocolo_humedales)

    assert "humedal artificial" in protocolo.titulo.lower() or protocolo.titulo
    assert protocolo.ventana == (2016, 2026)
    assert protocolo.idiomas == ("es", "en")
    assert protocolo.tipos == ("article", "review")
    assert set(protocolo.bloques) == {
        "P1_agua_residual",
        "P2_humedal",
        "P3_anaerobio",
        "P4_desempeno",
        "P5_parametros",
    }
    # Términos en los dos idiomas dentro del mismo bloque.
    assert "humedal artificial" in protocolo.bloques["P2_humedal"]
    assert "constructed wetland" in protocolo.bloques["P2_humedal"]
    assert "UASB" in protocolo.bloques["P3_anaerobio"]
    assert "tanque séptico" in protocolo.bloques["P3_anaerobio"]
    # Exclusión temática pedida por el protocolo.
    assert any("ciclo de vida" in t for t in protocolo.exclusion)
    assert any("carbon footprint" == t for t in protocolo.exclusion)
    # La consulta cruza el eje del humedal con los sistemas anaerobios.
    assert protocolo.consulta.eje == "P2_humedal"
    assert protocolo.consulta.cruce == ("anaerobic", "UASB", "septic tank", "biodigester")
    esperadas = len(protocolo.bloques["P2_humedal"]) * 4
    assert protocolo.numero_de_ecuaciones == esperadas
    # El resumen de la CLI se arma sin reventar y trae lo importante.
    resumen = protocolo.resumen()
    assert "2016-2026" in resumen
    assert f"Ecuaciones previstas : {esperadas}" in resumen


def test_todos_los_nombres_citados_existen(ruta_protocolo_humedales):
    protocolo = cargar_protocolo(ruta_protocolo_humedales)
    definidos = protocolo.nombres_definidos

    citados = set()
    for etiqueta in protocolo.clasificacion:
        citados.update(etiqueta.todos)
    for regla in protocolo.reglas.incluir + protocolo.reglas.dudoso:
        citados.update(regla.todos)
        citados.update(regla.ninguno)
        for sublista in regla.alguno_de:
            citados.update(sublista)

    assert citados <= definidos


# ---------------------------------------------------------------------------
# Validación que falla
# ---------------------------------------------------------------------------


def test_falla_si_una_regla_cita_un_bloque_inexistente(protocolo_minimo):
    protocolo_minimo["reglas"] = {
        "incluir": [{"todos": ["B1", "P9_no_existe"], "motivo": "Prueba."}]
    }

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    errores = capturado.value.errores
    assert len(errores) == 1
    # El mensaje señala el campo exacto y el nombre culpable.
    assert "reglas.incluir[0].todos[1]" in errores[0]
    assert "P9_no_existe" in errores[0]
    assert "no existe" in errores[0]


def test_falla_si_alguno_de_cita_un_bloque_inexistente(protocolo_minimo):
    protocolo_minimo["reglas"] = {"dudoso": [{"alguno_de": [["B1"], ["fantasma"]]}]}

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    assert "reglas.dudoso[0].alguno_de[1][0]" in capturado.value.errores[0]


def test_falla_si_la_clasificacion_cita_un_bloque_inexistente(protocolo_minimo):
    protocolo_minimo["clasificacion"] = [{"etiqueta": "X", "todos": ["fantasma"]}]

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    assert "clasificacion[0].todos[0]" in capturado.value.errores[0]


def test_falla_si_el_eje_de_la_consulta_no_existe(protocolo_minimo):
    protocolo_minimo["consulta"] = {"eje": "fantasma", "cruce": ["uno"]}

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    assert "consulta.eje" in capturado.value.errores[0]


def test_falla_si_una_regla_no_tiene_ninguna_condicion(protocolo_minimo):
    protocolo_minimo["reglas"] = {"incluir": [{"motivo": "Solo motivo."}]}

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    assert "ninguna condición" in capturado.value.errores[0]


def test_reune_todos_los_errores_de_una_vez(protocolo_minimo):
    del protocolo_minimo["titulo"]
    protocolo_minimo["ventana"] = [2030, 2016]
    protocolo_minimo["reglas"] = {"incluir": [{"todos": ["fantasma"]}]}

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    errores = capturado.value.errores
    assert len(errores) == 3
    assert any(e.startswith("titulo:") for e in errores)
    assert any(e.startswith("ventana:") for e in errores)
    assert any("fantasma" in e for e in errores)


def test_falla_si_un_nombre_se_repite_en_bloques_y_grupos(protocolo_minimo):
    protocolo_minimo["grupos"] = {"B1": ["otro término"]}

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    assert "grupos.B1" in capturado.value.errores[0]


def test_falla_si_sin_resumen_tiene_un_valor_raro(protocolo_minimo):
    protocolo_minimo["reglas"] = {"sinResumen": "descartar"}

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    assert "reglas.sinResumen" in capturado.value.errores[0]


def test_falla_si_falta_un_campo_obligatorio(protocolo_minimo):
    del protocolo_minimo["bloques"]

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    assert any("bloques" in e for e in capturado.value.errores)


def test_falla_con_un_json_mal_formado(tmp_path):
    ruta = tmp_path / "roto.json"
    ruta.write_text('{"titulo": "sin cerrar"', encoding="utf-8")

    with pytest.raises(ErrorProtocolo) as capturado:
        cargar_protocolo(ruta)

    assert "no es JSON válido" in capturado.value.errores[0]


def test_falla_si_el_archivo_no_existe(tmp_path):
    with pytest.raises(FileNotFoundError):
        cargar_protocolo(tmp_path / "no_existe.json")


def test_el_mensaje_de_error_se_lee_en_espanol(protocolo_minimo):
    protocolo_minimo["reglas"] = {"incluir": [{"todos": ["fantasma"]}]}

    with pytest.raises(ErrorProtocolo) as capturado:
        validar_protocolo(protocolo_minimo)

    texto = str(capturado.value)
    assert "error de validación" in texto
    assert "  1. " in texto


def test_se_puede_validar_desde_json_crudo(ruta_protocolo_humedales):
    datos = json.loads(ruta_protocolo_humedales.read_text(encoding="utf-8"))
    protocolo = validar_protocolo(datos)

    assert protocolo.ruta is None
    assert protocolo.terminos_de("G_ciclo_vida")

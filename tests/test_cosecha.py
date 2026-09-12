"""Cosecha reanudable, bitácora y modos sin red."""

from __future__ import annotations

import json

import pytest

from tatewari.cosecha import COLUMNAS_BITACORA, Cosecha, ErrorCosecha, cargar_fixture
from tatewari.fuentes import CAMPOS_REGISTRO, NR
from tatewari.http import ErrorHttpServidor


@pytest.fixture
def cosecha(protocolo, config_temporal):
    return Cosecha(
        revision="demo", protocolo=protocolo, config=config_temporal, cliente=None
    )


# ---------------------------------------------------------------------------
# Plan y modo seco
# ---------------------------------------------------------------------------


def test_el_plan_tiene_una_ecuacion_por_par(cosecha, protocolo):
    ecuaciones = cosecha.ecuaciones()

    assert len(ecuaciones) == protocolo.numero_de_ecuaciones == 40
    assert ecuaciones[0].numero == 1
    assert ecuaciones[-1].numero == 40
    assert ecuaciones[0].base == "OpenAlex"


def test_el_modo_seco_no_toca_la_red_y_da_las_urls(cosecha):
    resumen = cosecha.plan_seco()

    assert resumen.seco
    assert resumen.total == 40
    assert len(resumen.ecuaciones) == 40
    for ecuacion in resumen.ecuaciones:
        assert ecuacion.url.startswith("https://api.openalex.org/works?")
    # No se ha escrito nada en disco.
    assert not cosecha.carpeta.exists()


def test_el_modo_seco_respeta_el_tope_si_se_pide(cosecha):
    resumen = cosecha.plan_seco(max_consultas=3)

    assert len(resumen.ecuaciones) == 3
    assert resumen.total == 40


def test_un_protocolo_sin_consulta_no_puede_cosecharse(
    protocolo_minimo, config_temporal
):
    from tatewari.protocolo import validar_protocolo

    sin_consulta = Cosecha(
        revision="x", protocolo=validar_protocolo(protocolo_minimo), config=config_temporal
    )

    with pytest.raises(ErrorCosecha) as capturado:
        sin_consulta.ecuaciones()

    assert "consulta" in str(capturado.value)


def test_una_fuente_desconocida_se_rechaza(protocolo, config_temporal):
    with pytest.raises(ErrorCosecha) as capturado:
        Cosecha("x", protocolo, config_temporal, fuente="scihub")

    assert "Fuente desconocida" in str(capturado.value)


# ---------------------------------------------------------------------------
# Modo fixture
# ---------------------------------------------------------------------------


def test_el_fixture_carga_los_catorce_registros(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    assert resumen.procesadas == 1
    assert resumen.registros_nuevos == 14
    assert len(cosecha.leer_registros()) == 14
    assert resumen.pendientes == 39


def test_los_registros_del_fixture_conservan_el_contrato(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    for registro in cosecha.leer_registros():
        assert set(registro) == set(CAMPOS_REGISTRO)


def test_el_fixture_solo_se_sirve_una_vez_por_lote(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(max_consultas=3, fixture=ruta_fixture_demo)

    assert resumen.procesadas == 3
    assert resumen.registros_nuevos == 14

    filas = cosecha.leer_bitacora()
    assert filas[0]["resultados"] == "14"
    assert filas[1]["resultados"] == "0"
    assert "ya se sirvió" in filas[1]["observaciones"]


def test_cargar_fixture_admite_una_pagina_cruda_de_openalex(tmp_path, respuesta):
    ruta = tmp_path / "pagina.json"
    ruta.write_text(
        json.dumps(respuesta("openalex_pagina1.json")), encoding="utf-8"
    )

    registros = cargar_fixture(ruta)

    assert len(registros) == 2
    assert registros[0]["doi"] == "10.0000/sintetico.101"


def test_cargar_fixture_rellena_con_nr_lo_que_falte(tmp_path):
    ruta = tmp_path / "parcial.json"
    ruta.write_text(json.dumps([{"titulo": "Solo el título"}]), encoding="utf-8")

    registro = cargar_fixture(ruta)[0]

    assert registro["titulo"] == "Solo el título"
    assert registro["doi"] == NR
    assert registro["autores"] == [NR]


def test_un_fixture_que_no_existe_da_un_error_claro(cosecha, tmp_path):
    with pytest.raises(ErrorCosecha) as capturado:
        cosecha.ejecutar(fixture=tmp_path / "no_existe.json")

    assert "No existe el fixture" in str(capturado.value)


def test_un_fixture_con_forma_rara_se_rechaza(tmp_path):
    ruta = tmp_path / "raro.json"
    ruta.write_text('"esto es una cadena"', encoding="utf-8")

    with pytest.raises(ErrorCosecha):
        cargar_fixture(ruta)


# ---------------------------------------------------------------------------
# Bitácora
# ---------------------------------------------------------------------------


def test_la_bitacora_tiene_las_columnas_pedidas(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    filas = cosecha.leer_bitacora()
    assert list(filas[0]) == list(COLUMNAS_BITACORA)


def test_la_bitacora_guarda_la_url_literal(cosecha, ruta_fixture_demo):
    """AGENTS.md, regla 3: sin la URL literal la búsqueda no es reproducible."""
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    fila = cosecha.leer_bitacora()[0]

    assert fila["url"].startswith("https://api.openalex.org/works?")
    assert "%22humedal%20artificial%22%20AND%20%22anaerobic%22" in fila["url"]
    assert fila["ecuacion"] == '"humedal artificial" AND "anaerobic"'
    assert fila["idiomas"] == "es|en"
    assert fila["ventana"] == "2016-2026"
    assert fila["base"] == "OpenAlex"
    assert fila["fecha"]


def test_la_bitacora_se_va_ampliando_entre_lotes(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    filas = cosecha.leer_bitacora()

    assert [f["N"] for f in filas] == ["1", "2", "3"]
    # La cabecera se escribe una sola vez.
    texto = cosecha.ruta_bitacora.read_text(encoding="utf-8")
    assert texto.count("observaciones") == 1


def test_la_bitacora_no_deja_lineas_en_blanco_en_windows(cosecha, ruta_fixture_demo):
    """Sin newline="" el módulo csv escribe \\r\\r\\n y sale una línea de más."""
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    crudo = cosecha.ruta_bitacora.read_bytes()

    assert b"\r\r\n" not in crudo


# ---------------------------------------------------------------------------
# Reanudación
# ---------------------------------------------------------------------------


def test_la_cosecha_continua_donde_se_quedo(cosecha, ruta_fixture_demo):
    primero = cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)
    segundo = cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    assert primero.pendientes == 38
    assert segundo.pendientes == 36
    assert [e.numero for e in segundo.ecuaciones] == [3, 4]


def test_el_estado_recuerda_lo_hecho(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    estado = cosecha.cargar_estado()

    assert estado["total_ecuaciones"] == 40
    assert sorted(estado["hechas"]) == ["1", "2"]
    assert estado["hechas"]["1"]["url"].startswith("https://api.openalex.org/")
    assert estado["fuente"] == "openalex"


def test_una_cosecha_nueva_arranca_de_cero(cosecha):
    estado = cosecha.cargar_estado()

    assert estado["hechas"] == {}
    assert estado["revision"] == "demo"


def test_el_lote_por_defecto_es_de_ocho(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(fixture=ruta_fixture_demo)

    assert resumen.procesadas == 8
    assert resumen.pendientes == 32


def test_al_acabar_no_quedan_pendientes(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(max_consultas=100, fixture=ruta_fixture_demo)

    assert resumen.procesadas == 40
    assert resumen.pendientes == 0
    assert "Cosecha completa" in resumen.resumen()


# ---------------------------------------------------------------------------
# Con la red simulada
# ---------------------------------------------------------------------------


def test_cosecha_contra_openalex_simulado(
    protocolo, config_temporal, cliente_falso, respuesta
):
    cliente = cliente_falso(
        [respuesta("openalex_pagina1.json"), respuesta("openalex_pagina2.json")]
    )
    cosecha = Cosecha("demo", protocolo, config_temporal, cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=1)

    assert resumen.procesadas == 1
    assert resumen.registros_nuevos == 3
    assert cosecha.leer_bitacora()[0]["resultados"] == "3"


def test_un_error_en_una_ecuacion_no_tumba_la_cosecha(
    protocolo, config_temporal, cliente_falso, respuesta
):
    """Se anota y se sigue con la siguiente."""
    cliente = cliente_falso(
        [
            ErrorHttpServidor("El servidor respondió 503", url="https://x", estado=503),
            respuesta("openalex_pagina2.json"),
        ]
    )
    cosecha = Cosecha("demo", protocolo, config_temporal, cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=2)

    assert resumen.procesadas == 2
    assert resumen.con_error == 1
    assert resumen.registros_nuevos == 1

    filas = cosecha.leer_bitacora()
    assert filas[0]["resultados"] == NR
    assert "503" in filas[0]["observaciones"]
    assert filas[1]["resultados"] == "1"


def test_sin_cliente_y_sin_modo_local_se_avisa(cosecha):
    with pytest.raises(ErrorCosecha) as capturado:
        cosecha.ejecutar(max_consultas=1)

    assert "--seco" in str(capturado.value)


def test_se_puede_cosechar_en_crossref(
    protocolo, config_temporal, cliente_falso, respuesta
):
    cliente = cliente_falso([respuesta("crossref_pagina1.json")])
    cosecha = Cosecha("demo", protocolo, config_temporal, fuente="crossref", cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=1)

    assert resumen.registros_nuevos == 2
    assert cosecha.leer_bitacora()[0]["base"] == "Crossref"
    assert "api.crossref.org" in cosecha.leer_bitacora()[0]["url"]


def test_los_registros_se_acumulan_con_sus_duplicados(cosecha, ruta_fixture_demo):
    """Deduplicar es otro encargo: aquí se guarda lo que vino."""
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    assert len(cosecha.leer_registros()) == 28

"""Pruebas de la línea de órdenes. No tocan la red."""

from __future__ import annotations

import pytest

from tatewari import __version__
from tatewari.cli import (
    SALIDA_ARCHIVO_NO_ENCONTRADO,
    SALIDA_CONFIGURACION,
    SALIDA_OK,
    SALIDA_PROTOCOLO_INVALIDO,
    main,
)


def test_version(capsys):
    codigo = main(["version"])

    assert codigo == SALIDA_OK
    assert capsys.readouterr().out.strip() == f"Tatewari {__version__}"


def test_protocolo_validar_imprime_el_resumen(capsys, ruta_protocolo_humedales):
    codigo = main(["protocolo", "validar", str(ruta_protocolo_humedales)])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Protocolo válido" in salida
    assert "Ventana : 2016-2026" in salida
    assert "P2_humedal" in salida
    assert "Ecuaciones previstas : 40" in salida


def test_protocolo_validar_falla_con_un_protocolo_roto(capsys, tmp_path):
    ruta = tmp_path / "roto.json"
    ruta.write_text(
        '{"titulo": "X", "ventana": [2016, 2026], "idiomas": ["es"], '
        '"tipos": ["article"], "bloques": {"B1": ["t"]}, '
        '"reglas": {"incluir": [{"todos": ["fantasma"]}]}}',
        encoding="utf-8",
    )

    codigo = main(["protocolo", "validar", str(ruta)])

    assert codigo == SALIDA_PROTOCOLO_INVALIDO
    capturado = capsys.readouterr()
    assert capturado.out == ""
    assert "fantasma" in capturado.err
    assert "reglas.incluir[0].todos[0]" in capturado.err


def test_protocolo_validar_avisa_si_no_existe_el_archivo(capsys, tmp_path):
    codigo = main(["protocolo", "validar", str(tmp_path / "no_existe.json")])

    assert codigo == SALIDA_ARCHIVO_NO_ENCONTRADO
    assert "No existe el protocolo" in capsys.readouterr().err


@pytest.fixture
def entorno_aislado(tmp_path, monkeypatch):
    """CLI en una carpeta limpia: sin .env del repositorio y salida en tmp."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TATEWARI_DATOS", str(tmp_path / "revisiones"))
    monkeypatch.delenv("TATEWARI_MAILTO", raising=False)
    return tmp_path


def test_cosechar_en_seco_imprime_las_ecuaciones_con_su_url(
    capsys, entorno_aislado, ruta_protocolo_humedales
):
    codigo = main(
        ["cosechar", "demo", "--protocolo", str(ruta_protocolo_humedales), "--seco"]
    )

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "no se ha tocado la red" in salida
    assert "Ecuaciones previstas : 40" in salida
    assert '[  1] "humedal artificial" AND "anaerobic"' in salida
    assert salida.count("https://api.openalex.org/works?") == 40
    assert "%20AND%20" in salida
    # Nada escrito en disco en modo seco.
    assert not (entorno_aislado / "revisiones").exists()


def test_cosechar_con_fixture_carga_los_registros_y_escribe_la_bitacora(
    capsys, entorno_aislado, ruta_protocolo_humedales, ruta_fixture_demo
):
    codigo = main(
        [
            "cosechar",
            "demo",
            "--protocolo",
            str(ruta_protocolo_humedales),
            "--fixture",
            str(ruta_fixture_demo),
        ]
    )

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Registros cosechados en este lote  : 14" in salida
    assert "Pendientes                         : 39 de 40" in salida

    carpeta = entorno_aislado / "revisiones" / "demo"
    assert (carpeta / "search_log.csv").is_file()
    assert (carpeta / "registros.json").is_file()
    assert (carpeta / "estado.json").is_file()

    bitacora = (carpeta / "search_log.csv").read_text(encoding="utf-8")
    assert "https://api.openalex.org/works?" in bitacora


def test_cosechar_es_reanudable_desde_la_cli(
    capsys, entorno_aislado, ruta_protocolo_humedales, ruta_fixture_demo
):
    orden = [
        "cosechar",
        "demo",
        "--protocolo",
        str(ruta_protocolo_humedales),
        "--fixture",
        str(ruta_fixture_demo),
    ]
    main(orden)
    capsys.readouterr()
    main(orden)

    assert "Pendientes                         : 38 de 40" in capsys.readouterr().out


def test_cosechar_sin_correo_y_con_red_se_planta(
    capsys, entorno_aislado, ruta_protocolo_humedales
):
    """Unpaywall lo exige y OpenAlex lo premia: mejor avisar que gastar red."""
    codigo = main(
        ["cosechar", "demo", "--protocolo", str(ruta_protocolo_humedales)]
    )

    assert codigo == SALIDA_CONFIGURACION
    error = capsys.readouterr().err
    assert "TATEWARI_MAILTO" in error
    assert "--seco" in error


def test_cosechar_avisa_si_el_protocolo_no_existe(capsys, entorno_aislado, tmp_path):
    codigo = main(
        ["cosechar", "demo", "--protocolo", str(tmp_path / "no.json"), "--seco"]
    )

    assert codigo == SALIDA_ARCHIVO_NO_ENCONTRADO
    assert "No existe el protocolo" in capsys.readouterr().err


def test_sin_orden_muestra_la_ayuda(capsys):
    codigo = main([])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Uso: tatewari" in salida
    assert "PRISMA 2020" in salida

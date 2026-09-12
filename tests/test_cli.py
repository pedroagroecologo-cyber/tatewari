"""Pruebas de la línea de órdenes. No tocan la red."""

from __future__ import annotations

from tatewari import __version__
from tatewari.cli import (
    SALIDA_ARCHIVO_NO_ENCONTRADO,
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


def test_sin_orden_muestra_la_ayuda(capsys):
    codigo = main([])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Uso: tatewari" in salida
    assert "PRISMA 2020" in salida

"""Pruebas de la configuración. No tocan la red ni el entorno real."""

from __future__ import annotations

from pathlib import Path

import pytest

from tatewari.config import (
    PREDETERMINADOS,
    Config,
    ErrorConfig,
    cargar_config,
    leer_env,
)


def test_valores_por_defecto_sin_env(tmp_path):
    config = cargar_config(entorno={}, base=tmp_path)

    assert config.mailto == ""
    assert config.ollama == "http://localhost:11434"
    assert config.datos == tmp_path / "revisiones"
    assert config.origen_env is None
    assert not config.tiene_mailto


def test_el_ollama_por_defecto_es_local():
    """Regla 1 de AGENTS.md: el único modelo es Ollama, en local."""
    assert PREDETERMINADOS["TATEWARI_OLLAMA"] == "http://localhost:11434"


def test_lee_un_archivo_env(tmp_path):
    (tmp_path / ".env").write_text(
        "# un comentario\n"
        "\n"
        "TATEWARI_MAILTO = correo@ejemplo.invalid\n"
        'TATEWARI_OLLAMA="http://127.0.0.1:11434/"\n'
        "export TATEWARI_DATOS=salidas\n",
        encoding="utf-8",
    )

    config = cargar_config(entorno={}, base=tmp_path)

    assert config.mailto == "correo@ejemplo.invalid"
    # Se le quitan las comillas y la barra final.
    assert config.ollama == "http://127.0.0.1:11434"
    assert config.datos == tmp_path / "salidas"
    assert config.origen_env == tmp_path / ".env"


def test_el_entorno_manda_sobre_el_env(tmp_path):
    (tmp_path / ".env").write_text(
        "TATEWARI_OLLAMA=http://desde-el-env:11434\n", encoding="utf-8"
    )

    config = cargar_config(
        entorno={"TATEWARI_OLLAMA": "http://desde-el-entorno:11434"},
        base=tmp_path,
    )

    assert config.ollama == "http://desde-el-entorno:11434"


def test_encuentra_el_env_en_una_carpeta_superior(tmp_path):
    (tmp_path / ".env").write_text("TATEWARI_MAILTO=arriba@ejemplo.invalid\n", encoding="utf-8")
    hondo = tmp_path / "a" / "b" / "c"
    hondo.mkdir(parents=True)

    config = cargar_config(entorno={}, base=hondo)

    assert config.mailto == "arriba@ejemplo.invalid"


def test_una_ruta_absoluta_de_datos_se_respeta(tmp_path):
    destino = tmp_path / "otro" / "sitio"
    config = cargar_config(
        entorno={"TATEWARI_DATOS": str(destino)}, base=tmp_path
    )

    assert config.datos == destino


def test_una_linea_sin_igual_es_un_error(tmp_path):
    ruta = tmp_path / ".env"
    ruta.write_text("TATEWARI_MAILTO\n", encoding="utf-8")

    with pytest.raises(ErrorConfig) as capturado:
        leer_env(ruta)

    assert "linea 1" in str(capturado.value)


def test_un_env_inexistente_no_estorba(tmp_path):
    assert leer_env(tmp_path / "no_existe") == {}


def test_exigir_mailto_falla_con_un_mensaje_util():
    config = Config(mailto="", ollama="http://localhost:11434", datos=Path("."))

    with pytest.raises(ErrorConfig) as capturado:
        config.exigir_mailto()

    mensaje = str(capturado.value)
    assert "TATEWARI_MAILTO" in mensaje
    assert "Unpaywall" in mensaje


def test_exigir_mailto_devuelve_el_correo():
    config = Config(
        mailto="quien@ejemplo.invalid",
        ollama="http://localhost:11434",
        datos=Path("."),
    )

    assert config.exigir_mailto() == "quien@ejemplo.invalid"


def test_asegurar_datos_crea_la_carpeta(tmp_path):
    config = cargar_config(entorno={}, base=tmp_path)

    assert not config.datos.exists()
    assert config.asegurar_datos().is_dir()


def test_el_env_de_ejemplo_trae_las_tres_variables(raiz):
    valores = leer_env(raiz / ".env.example")

    assert set(valores) == set(PREDETERMINADOS)
    assert "@" in valores["TATEWARI_MAILTO"]
    assert valores["TATEWARI_OLLAMA"] == "http://localhost:11434"

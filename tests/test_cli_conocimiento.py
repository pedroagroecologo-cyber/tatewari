"""Las órdenes `conocimiento`, `pedir` y `zea-mayz`. Sin red y sin Ollama."""

from __future__ import annotations

import pytest

from ayudas_conocimiento import EDAFOLOGIA
from tatewari.cli import SALIDA_MODELO, SALIDA_OK, main
from tatewari.cli_conocimiento import SALIDA_CONOCIMIENTO
from tatewari.modelo import ErrorOllama


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Carpeta limpia, sin .env del repositorio, con el Vault en tmp."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TATEWARI_DATOS", str(tmp_path / "revisiones"))
    vault = tmp_path / "Mi Vault"
    monkeypatch.setenv("TATEWARI_OBSIDIAN_VAULT", str(vault))
    return vault


def test_crear_vault_crea_la_estructura(capsys, entorno):
    codigo = main(["conocimiento", "crear-vault"])

    assert codigo == SALIDA_OK
    for carpeta in ("00_INBOX", "01_MATERIA", "02_CONCEPTOS", "09_LIBRO"):
        assert (entorno / carpeta).is_dir()
    assert "Open folder as vault" in capsys.readouterr().out


def test_sin_vault_configurado_lo_dice(capsys, entorno, monkeypatch):
    monkeypatch.delenv("TATEWARI_OBSIDIAN_VAULT")

    codigo = main(["conocimiento", "conceptos"])

    assert codigo == SALIDA_CONOCIMIENTO
    assert "TATEWARI_OBSIDIAN_VAULT" in capsys.readouterr().err


def test_procesar_sin_modelo_escribe_la_fuente(capsys, entorno):
    main(["conocimiento", "crear-vault"])

    codigo = main(["conocimiento", "procesar", str(EDAFOLOGIA), "--sin-modelo"])

    assert codigo == SALIDA_OK
    assert (entorno / "01_MATERIA" / EDAFOLOGIA.name).is_file()
    assert list((entorno / "01_MATERIA").glob("Fuente - *.md"))
    assert "DRAFT o REVIEW" in capsys.readouterr().out


def test_procesar_un_formato_no_admitido_da_un_error_claro(capsys, entorno, tmp_path):
    main(["conocimiento", "crear-vault"])
    hoja = tmp_path / "notas.xlsx"
    hoja.write_bytes(b"PK")

    codigo = main(["conocimiento", "procesar", str(hoja), "--sin-modelo"])

    assert codigo == SALIDA_CONOCIMIENTO
    assert "no se admite" in capsys.readouterr().err


def test_con_ollama_caido_procesar_sugiere_sin_modelo(capsys, entorno, monkeypatch):
    main(["conocimiento", "crear-vault"])

    class EnrutadorCaido:
        def describir(self):
            raise ErrorOllama("No se pudo conectar con Ollama. ¿Está abierto? Prueba: ollama serve")

    monkeypatch.setattr(
        "tatewari.cli_conocimiento.Enrutador.desde_config", lambda *a, **k: EnrutadorCaido()
    )

    codigo = main(["conocimiento", "procesar", str(EDAFOLOGIA)])

    assert codigo == SALIDA_MODELO
    assert "--sin-modelo" in capsys.readouterr().err
    assert not list((entorno / "02_CONCEPTOS").glob("*.md"))


def test_pedir_en_espanol_procesa(capsys, entorno):
    main(["conocimiento", "crear-vault"])

    codigo = main(["pedir", "procesa", "este", "documento", str(EDAFOLOGIA), "--sin-modelo"])

    assert codigo == SALIDA_OK
    assert "Entendido" in capsys.readouterr().out
    assert (entorno / "01_MATERIA" / EDAFOLOGIA.name).is_file()


def test_pedir_algo_que_no_se_entiende_dice_lo_que_si(capsys, entorno):
    codigo = main(["pedir", "haz", "la", "cena"])

    assert codigo == SALIDA_CONOCIMIENTO
    assert "procesar documento" in capsys.readouterr().err.lower()


def test_aprobar_exige_autor(capsys, entorno):
    main(["conocimiento", "crear-vault"])
    (entorno / "02_CONCEPTOS" / "Suelo.md").write_text("# Suelo\n", encoding="utf-8")

    codigo = main(["conocimiento", "estado", "Suelo", "APPROVED"])

    assert codigo == SALIDA_CONOCIMIENTO
    assert "autor" in capsys.readouterr().err.lower()


def test_habilidades_lista_las_pedidas(capsys, entorno):
    codigo = main(["conocimiento", "habilidades"])

    salida = capsys.readouterr().out
    assert codigo == SALIDA_OK
    for nombre in ("document_ingest", "document_extract", "knowledge_extract", "knowledge_link",
                   "obsidian_create_note", "obsidian_update_note", "obsidian_search",
                   "obsidian_validate", "knowledge_report", "divulgacion_cientifica"):
        assert nombre in salida


def test_zea_mayz_validar_marca_lo_no_aprobado(capsys, entorno):
    main(["conocimiento", "crear-vault"])
    borrador = entorno / "05_GUION" / "Guion.md"
    borrador.write_text("- **Afirmación:** El suelo respira. · **Base:** [[Suelo]]\n", encoding="utf-8")

    codigo = main(["zea-mayz", "validar", str(borrador)])

    assert codigo == SALIDA_CONOCIMIENTO
    assert "no existe en el Vault" in capsys.readouterr().out


def test_zea_mayz_divulgar_sin_aprobados_no_llama_al_modelo(capsys, entorno, monkeypatch):
    main(["conocimiento", "crear-vault"])

    class SinUso:
        def cliente(self, tarea):
            raise AssertionError("no debía llamarse al modelo")

    monkeypatch.setattr("tatewari.cli_conocimiento.Enrutador.desde_config", lambda *a, **k: SinUso())

    codigo = main(["zea-mayz", "divulgar", "--tema", "suelo"])

    assert codigo == SALIDA_CONOCIMIENTO
    assert "APPROVED" in capsys.readouterr().err

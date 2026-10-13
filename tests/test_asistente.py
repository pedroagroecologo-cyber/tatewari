"""Pruebas del asistente: una conversación con respuestas fijas y órdenes falsas."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from tatewari.asistente import Asistente


@dataclass
class Config:
    mailto: str = "a@b.mx"
    tiene_mailto: bool = True
    openalex_key: str = "clave"
    datos: Path = Path("revisiones")


class Protocolo:
    numero_de_ecuaciones = 24


def armar(tmp_path, respuestas, codigos=None, pendientes=(16, 8, 0), **opciones):
    carpeta = tmp_path / "protocolos"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "btc.json").write_text("{}", encoding="utf-8")
    cola = list(respuestas)
    salida: list[str] = []
    ordenes: list[list[str]] = []
    faltan = list(pendientes)

    def ejecutar(argumentos):
        ordenes.append(argumentos)
        return (codigos or {}).get(argumentos[0], 0)

    def preguntar(texto):
        salida.append(texto)
        if not cola:
            raise EOFError
        return cola.pop(0)

    asistente = Asistente(
        ejecutar=ejecutar,
        preguntar=preguntar,
        decir=salida.append,
        cargar_config=lambda: opciones.get("config", Config(datos=tmp_path / "revisiones")),
        cargar_protocolo=lambda ruta: Protocolo(),
        pendientes_de=lambda revision, protocolo, config: faltan.pop(0) if faltan else 0,
        carpeta_protocolos=carpeta,
        bovedas=opciones.get("bovedas", ()),
    )
    return asistente, salida, ordenes


def nombres(ordenes):
    return [o[0] if o[0] != "protocolo" else "validar" for o in ordenes]


def test_recorrido_completo_repite_la_cosecha_hasta_terminar(tmp_path):
    # protocolo 1, nombre, no explorar, sí cosechar, sí textos, sí PDF
    asistente, salida, ordenes = armar(tmp_path, ["1", "btc", "n", "", "", ""])
    assert asistente.recorrer() == 0
    assert nombres(ordenes) == [
        "validar", "cosechar", "cosechar", "cosechar", "cribar",
        "texto-completo", "descargar", "exportar",
    ]
    assert all("btc" in o for o in ordenes[1:])
    assert any("Cosecha completa." in linea for linea in salida)
    assert any("tatewari exportar btc" in linea for linea in salida)


def test_sin_correo_explica_y_no_sigue(tmp_path):
    config = Config(tiene_mailto=False)
    asistente, salida, ordenes = armar(tmp_path, [], config=config)
    assert asistente.recorrer() == 3
    assert ordenes == []
    assert any("TATEWARI_MAILTO" in linea for linea in salida)


def test_protocolo_invalido_pide_pegar_los_errores_al_chat(tmp_path):
    asistente, salida, ordenes = armar(tmp_path, ["1"], codigos={"protocolo": 1})
    assert asistente.recorrer() == 1
    assert nombres(ordenes) == ["validar"]
    assert any("pégaselos al chat" in linea for linea in salida)


def test_cosecha_atorada_se_detiene(tmp_path):
    asistente, salida, ordenes = armar(tmp_path, ["1", "btc", "n", ""], pendientes=(16, 16))
    assert asistente.recorrer() == 4
    assert nombres(ordenes).count("cosechar") == 2
    assert any("no avanzó" in linea for linea in salida)


def test_explorar_usa_el_tema_y_el_protocolo(tmp_path):
    asistente, _, ordenes = armar(tmp_path, ["1", "btc", "s", "bloques de tierra con cal", "q"])
    asistente.recorrer()
    explorar = next(o for o in ordenes if o[0] == "explorar")
    assert explorar[1] == "bloques de tierra con cal"
    assert explorar[2] == "--protocolo"


def test_q_o_fin_de_entrada_salen_con_calma(tmp_path):
    asistente, salida, _ = armar(tmp_path, ["1", "q"])
    assert asistente.recorrer() == 0
    assert any("Lo hecho está guardado" in linea for linea in salida)
    asistente, salida, _ = armar(tmp_path, [])  # se acaba la entrada
    assert asistente.recorrer() == 0


@pytest.mark.skipif(os.name == "nt", reason="crear enlaces en Windows pide permisos")
def test_liga_la_boveda_si_la_persona_acepta(tmp_path):
    boveda = tmp_path / "Tesis"
    boveda.mkdir()
    asistente, _, _ = armar(
        tmp_path, ["1", "btc", "n", "", "n", "n", "s"], bovedas=(boveda,)
    )
    asistente.recorrer()
    assert (boveda / "Tatewari").is_symlink()


def test_no_toca_la_boveda_sin_permiso(tmp_path):
    boveda = tmp_path / "Tesis"
    boveda.mkdir()
    asistente, salida, _ = armar(
        tmp_path, ["1", "btc", "n", "", "n", "n", ""], bovedas=(boveda,)
    )
    asistente.recorrer()
    assert not (boveda / "Tatewari").exists()
    assert any("ln -s" in linea for linea in salida)

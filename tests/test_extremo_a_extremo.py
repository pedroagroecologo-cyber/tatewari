"""El flujo completo, de principio a fin, **sin red**.

Cosechar desde el fixture, cribar, exportar. Es la prueba que dice si el programa
sirve para lo que se hizo: no comprueba una función, comprueba que alguien puede
llevar una revisión de principio a fin y acabar con una bibliografía en la mano.

Todo sale de `fixtures/demo.json` y de `protocolos/humedales.json`, y ninguna
llamada toca una API real (AGENTS.md, regla 6).
"""

from __future__ import annotations

import csv
import json
import re

import pytest

from tatewari.cli import SALIDA_OK, main
from tatewari.exportar import (
    NOMBRE_BIB,
    NOMBRE_INCLUIDOS,
    NOMBRE_POR_CONSEGUIR,
    NOMBRE_REVISION,
)


@pytest.fixture
def flujo(tmp_path, monkeypatch, ruta_protocolo_humedales, ruta_fixture_demo, capsys):
    """Lanza el flujo entero y devuelve la carpeta de la revisión.

    La salida de cada orden se descarta: lo que se comprueba son los archivos y
    su contenido, que es lo que le queda a quien usa el programa.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TATEWARI_DATOS", str(tmp_path / "revisiones"))
    monkeypatch.delenv("TATEWARI_MAILTO", raising=False)

    assert main(
        [
            "cosechar",
            "demo",
            "--protocolo",
            str(ruta_protocolo_humedales),
            "--fixture",
            str(ruta_fixture_demo),
        ]
    ) == SALIDA_OK
    assert main(["cribar", "demo"]) == SALIDA_OK
    assert main(["exportar", "demo"]) == SALIDA_OK
    capsys.readouterr()

    return tmp_path / "revisiones" / "demo"


def _decisiones(carpeta) -> list[dict]:
    with open(carpeta / "cribado.csv", encoding="utf-8", newline="") as manejador:
        return list(csv.DictReader(manejador))


def test_el_flujo_completo_genera_todos_los_archivos(flujo):
    """Ninguno de estos puede faltar al final de una revisión."""
    esperados = (
        "registros.json",
        "search_log.csv",
        "estado.json",
        "identificadores.json",
        "cribado.csv",
        "prisma.txt",
        NOMBRE_BIB,
        NOMBRE_INCLUIDOS,
        NOMBRE_REVISION,
        NOMBRE_POR_CONSEGUIR,
    )

    faltan = [nombre for nombre in esperados if not (flujo / nombre).is_file()]

    assert not faltan, f"faltan archivos: {faltan}"


def test_el_bibtex_tiene_exactamente_los_registros_incluidos(flujo):
    """Lo que pide el encargo: ni uno más, ni uno menos.

    Se comprueba contra `cribado.csv`, que es la otra salida de la misma
    decisión: si las dos no cuadran, una de las dos está mintiendo.
    """
    incluidos = [f for f in _decisiones(flujo) if f["decision"] == "incluir"]
    bib = (flujo / NOMBRE_BIB).read_text(encoding="utf-8")

    claves = re.findall(r"^@\w+\{([^,]+),", bib, re.M)
    identificadores_bib = sorted(
        re.search(r"(R\d{4})$", clave).group(1) for clave in claves
    )

    assert len(claves) == len(incluidos)
    assert identificadores_bib == sorted(f["identificador"] for f in incluidos)
    # Y ningún excluido ni dudoso se ha colado.
    for fila in _decisiones(flujo):
        if fila["decision"] != "incluir":
            assert fila["identificador"] not in identificadores_bib


def test_el_bibtex_del_fixture_trae_ocho_entradas(flujo):
    """Número fijo: si el cribado cambia, esta prueba lo dice.

    Ocho son los que incluye el **filtro determinista** solo. En este flujo no
    interviene ni el modelo local ni una persona, así que el número no depende de
    nada más que de las reglas del protocolo.
    """
    bib = (flujo / NOMBRE_BIB).read_text(encoding="utf-8")

    assert "Entradas : 8" in bib
    assert len(re.findall(r"^@\w+\{", bib, re.M)) == 8


def test_los_dudosos_van_a_revision_manual_y_no_al_bibtex(flujo):
    dudosos = [f for f in _decisiones(flujo) if f["decision"] == "dudoso"]
    revision = (flujo / NOMBRE_REVISION).read_text(encoding="utf-8")
    bib = (flujo / NOMBRE_BIB).read_text(encoding="utf-8")

    assert dudosos, "el fixture tiene que dejar algún dudoso"
    for fila in dudosos:
        assert fila["identificador"] in revision
        assert fila["identificador"] not in bib


def test_por_conseguir_solo_lleva_incluidos_sin_acceso_abierto(flujo):
    filas = _decisiones(flujo)
    por_conseguir = (flujo / NOMBRE_POR_CONSEGUIR).read_text(encoding="utf-8")
    lista = por_conseguir.split("## Lista", 1)[1]

    for fila in filas:
        esta = f"| {fila['identificador']} |" in lista
        deberia = fila["decision"] == "incluir" and fila["oa_url"] == "NR"
        assert esta == deberia, f"{fila['identificador']} mal clasificado"


def test_por_conseguir_dice_que_no_se_eluden_muros_de_pago(flujo):
    """AGENTS.md, regla 5, escrito donde lo va a leer quien tiene el problema."""
    texto = (flujo / NOMBRE_POR_CONSEGUIR).read_text(encoding="utf-8")

    assert "no elude muros de pago" in texto
    assert "a mano" in texto


def test_el_prisma_cuadra_con_el_csv(flujo):
    filas = _decisiones(flujo)
    prisma = (flujo / "prisma.txt").read_text(encoding="utf-8")

    assert "Diagrama de flujo PRISMA 2020" in prisma
    # 14 registros cosechados, uno duplicado, 13 únicos.
    assert len(filas) == 13
    assert "14" in prisma
    for decision in ("incluir", "dudoso", "excluir"):
        cuantos = sum(1 for f in filas if f["decision"] == decision)
        assert str(cuantos) in prisma


def test_todas_las_fichas_de_los_incluidos_estan_en_el_markdown(flujo):
    incluidos = [f for f in _decisiones(flujo) if f["decision"] == "incluir"]
    texto = (flujo / NOMBRE_INCLUIDOS).read_text(encoding="utf-8")

    assert f"**Artículos**: {len(incluidos)}" in texto
    for fila in incluidos:
        assert f"### {fila['identificador']}" in texto


def test_las_exportaciones_van_en_utf8_sin_bom_y_con_lf(flujo):
    for nombre in (NOMBRE_BIB, NOMBRE_INCLUIDOS, NOMBRE_REVISION, NOMBRE_POR_CONSEGUIR):
        crudo = (flujo / nombre).read_bytes()
        assert not crudo.startswith(b"\xef\xbb\xbf"), nombre
        assert b"\r\n" not in crudo, nombre
        (flujo / nombre).read_text(encoding="utf-8")


def test_los_acentos_sobreviven_el_viaje_entero(flujo):
    """De la cosecha al BibTeX sin romperse, que es el fallo clásico en Windows."""
    bib = (flujo / NOMBRE_BIB).read_text(encoding="utf-8")

    assert "Desempeño" in bib
    assert "remoción" in (flujo / NOMBRE_INCLUIDOS).read_text(encoding="utf-8")


def test_volver_a_exportar_da_exactamente_lo_mismo(flujo, capsys):
    """El mismo estado tiene que dar el mismo archivo, salvo la fecha."""
    antes = (flujo / NOMBRE_BIB).read_text(encoding="utf-8")

    main(["exportar", "demo"])
    capsys.readouterr()
    despues = (flujo / NOMBRE_BIB).read_text(encoding="utf-8")

    sin_fecha = lambda t: "\n".join(
        l for l in t.splitlines() if not l.startswith("% Generado")
    )
    assert sin_fecha(antes) == sin_fecha(despues)


def test_el_estado_no_modifica_ningun_archivo(flujo, capsys):
    """Lo que pide el encargo: «estado» es de solo lectura."""
    antes = {
        ruta.name: (ruta.read_bytes(), ruta.stat().st_mtime_ns)
        for ruta in sorted(flujo.iterdir())
        if ruta.is_file()
    }

    assert main(["estado", "demo"]) == SALIDA_OK
    capsys.readouterr()

    despues = {
        ruta.name: (ruta.read_bytes(), ruta.stat().st_mtime_ns)
        for ruta in sorted(flujo.iterdir())
        if ruta.is_file()
    }
    assert sorted(antes) == sorted(despues), "estado creó o borró un archivo"
    for nombre, (contenido, mtime) in antes.items():
        assert despues[nombre][0] == contenido, f"estado cambió {nombre}"
        assert despues[nombre][1] == mtime, f"estado tocó la fecha de {nombre}"


def test_pendientes_no_modifica_ningun_archivo(flujo, capsys):
    """Sin --registrar, «pendientes» tampoco escribe nada."""
    antes = {
        ruta.name: ruta.read_bytes() for ruta in sorted(flujo.iterdir()) if ruta.is_file()
    }

    for orden in (
        ["pendientes", "demo"],
        ["pendientes", "demo", "--modo", "incluir"],
        ["pendientes", "demo", "--modo", "auditoria"],
    ):
        assert main(orden) == SALIDA_OK
    capsys.readouterr()

    despues = {
        ruta.name: ruta.read_bytes() for ruta in sorted(flujo.iterdir()) if ruta.is_file()
    }
    assert antes == despues
    assert not (flujo / "auditoria.json").exists()


def test_con_registrar_la_auditoria_si_queda_apuntada(flujo, capsys):
    """La regla 4 de AGENTS.md pide que la auditoría quede registrada."""
    assert main(
        ["pendientes", "demo", "--modo", "auditoria", "--registrar"]
    ) == SALIDA_OK
    capsys.readouterr()

    rondas = json.loads((flujo / "auditoria.json").read_text(encoding="utf-8"))
    assert len(rondas) == 1
    assert rondas[0]["semilla"] > 0
    assert rondas[0]["muestra"]


def test_el_estado_resume_el_punto_en_que_va_la_revision(flujo, capsys):
    main(["estado", "demo"])

    salida = capsys.readouterr().out

    assert "COSECHA" in salida
    assert "Ecuaciones del protocolo : 40" in salida
    assert "Ejecutadas               : 1" in salida
    assert "Pendientes               : 39" in salida
    assert "Registros únicos         : 13" in salida
    assert "[sí] cribado.csv" in salida
    assert "[sí] incluidos.bib" in salida
    assert "Siguiente paso:" in salida


def test_estado_y_exportar_cuentan_lo_mismo(flujo, capsys):
    """Dos órdenes que se contradicen sobre lo mismo es peor que una imperfecta.

    Pasó de verdad: `estado` contaba el acceso abierto por lo que dijo Unpaywall
    y `exportar` por el `oa_url` del registro, así que una decía 0 y la otra 7.
    """
    main(["exportar", "demo"])
    salida_exportar = capsys.readouterr().out
    main(["estado", "demo"])
    salida_estado = capsys.readouterr().out

    con_abierto, por_conseguir = re.search(
        r"Incluidos : \d+ \((\d+) con acceso abierto, (\d+) por conseguir\)",
        salida_exportar,
    ).groups()

    assert f"Incluidos con URL abierta: {con_abierto} de" in salida_estado
    assert f"Por conseguir a mano     : {por_conseguir}" in salida_estado


def test_el_flujo_no_deja_ningun_dato_inventado(flujo):
    """AGENTS.md, regla 2: lo que falta va como «NR», nunca como un valor plausible."""
    filas = _decisiones(flujo)

    sin_doi = [f for f in filas if f["doi"] == "NR"]
    assert len(sin_doi) == 1
    assert sin_doi[0]["revista"] == "NR"
    assert sin_doi[0]["autores"] == "NR"

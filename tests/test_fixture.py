"""Pruebas del fixture de registros sintéticos. No tocan la red.

El fixture es el contrato de datos de la cosecha: si cambia su forma, la
deduplicación y el cribado se enteran aquí y no tres encargos más tarde.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

CAMPOS = (
    "doi",
    "titulo",
    "anio",
    "idioma",
    "revista",
    "autores",
    "resumen",
    "tipo",
    "citas",
    "oa_url",
)

PREFIJO_SINTETICO = "SINTETICO DE PRUEBA"


@pytest.fixture
def registros(ruta_fixture_demo):
    with open(ruta_fixture_demo, encoding="utf-8") as manejador:
        return json.load(manejador)


def test_el_fixture_tiene_catorce_registros(registros):
    assert isinstance(registros, list)
    assert len(registros) == 14


def test_todos_los_registros_tienen_el_contrato_completo(registros):
    for indice, registro in enumerate(registros):
        faltantes = [campo for campo in CAMPOS if campo not in registro]
        assert not faltantes, f"registro {indice}: faltan los campos {faltantes}"
        sobrantes = [campo for campo in registro if campo not in CAMPOS]
        assert not sobrantes, f"registro {indice}: campos de más {sobrantes}"


def test_todos_los_registros_estan_marcados_como_sinteticos(registros):
    """Ningún registro puede pasar por literatura real (AGENTS.md, regla 2)."""
    for registro in registros:
        assert registro["titulo"].startswith(PREFIJO_SINTETICO)


def test_ningun_doi_puede_confundirse_con_uno_real(registros):
    """El prefijo 10.0000 no está asignado a ninguna editorial."""
    for registro in registros:
        doi = registro["doi"]
        assert doi == "NR" or doi.lower().startswith("10.0000/")


def test_los_campos_ausentes_van_como_nr(registros):
    """Lo que falta se escribe "NR", nunca un valor plausible."""
    sin_doi = [r for r in registros if r["doi"] == "NR"]
    assert len(sin_doi) == 1
    registro = sin_doi[0]
    assert registro["revista"] == "NR"
    assert registro["autores"] == ["NR"]
    assert registro["citas"] == "NR"


def test_hay_un_articulo_duplicado(registros):
    """Dos entradas son el mismo artículo: mismo DOI salvo mayúsculas."""
    normalizados = Counter(
        r["doi"].strip().lower() for r in registros if r["doi"] != "NR"
    )
    repetidos = [doi for doi, veces in normalizados.items() if veces > 1]

    assert repetidos == ["10.0000/sintetico.003"]

    pareja = [r for r in registros if r["doi"].lower() == repetidos[0]]
    assert len(pareja) == 2
    # Mismo artículo, metadatos distintos: es lo que hace difícil deduplicar.
    assert pareja[0]["anio"] == pareja[1]["anio"]
    assert pareja[0]["titulo"] != pareja[1]["titulo"]
    assert pareja[0]["revista"] != pareja[1]["revista"]


def test_hay_un_registro_anterior_a_la_ventana(registros, ruta_protocolo_humedales):
    from tatewari.protocolo import cargar_protocolo

    protocolo = cargar_protocolo(ruta_protocolo_humedales)
    inicio, fin = protocolo.ventana

    fuera = [r for r in registros if not inicio <= r["anio"] <= fin]
    assert len(fuera) == 1
    assert fuera[0]["anio"] < inicio


def test_hay_un_registro_en_un_idioma_no_admitido(registros, ruta_protocolo_humedales):
    from tatewari.protocolo import cargar_protocolo

    protocolo = cargar_protocolo(ruta_protocolo_humedales)

    ajenos = [r for r in registros if r["idioma"] not in protocolo.idiomas]
    assert len(ajenos) == 1
    assert ajenos[0]["idioma"] == "pt"


def test_hay_un_registro_de_analisis_de_ciclo_de_vida(registros):
    con_acv = [
        r
        for r in registros
        if "life cycle assessment" in r["titulo"].lower()
        or "análisis de ciclo de vida" in r["titulo"].lower()
    ]
    assert len(con_acv) == 1
    # Aunque esté excluido por tema, menciona humedales: no se descarta solo.
    assert "wetland" in con_acv[0]["titulo"].lower()


def test_hay_un_registro_sin_resumen(registros):
    sin_resumen = [r for r in registros if r["resumen"] == "NR"]
    assert len(sin_resumen) == 1


def test_hay_varios_registros_que_si_cumplen(registros, ruta_protocolo_humedales):
    """Al menos la mitad del fixture debe ser material aprovechable."""
    from tatewari.protocolo import cargar_protocolo

    protocolo = cargar_protocolo(ruta_protocolo_humedales)
    inicio, fin = protocolo.ventana

    candidatos = [
        r
        for r in registros
        if inicio <= r["anio"] <= fin
        and r["idioma"] in protocolo.idiomas
        and r["tipo"] in protocolo.tipos
        and r["resumen"] != "NR"
        and "life cycle" not in r["resumen"].lower()
    ]
    assert len(candidatos) >= 7


def test_los_tipos_estan_dentro_de_lo_previsto(registros):
    assert {r["tipo"] for r in registros} == {"article", "review"}


def test_las_urls_no_apuntan_a_ningun_sitio_real(registros):
    """El TLD .invalid está reservado justo para esto (RFC 2606)."""
    for registro in registros:
        url = registro["oa_url"]
        assert url == "NR" or url.startswith("https://ejemplo.invalid/")

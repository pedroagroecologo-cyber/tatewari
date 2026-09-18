"""Pruebas de la deduplicación y de los identificadores estables.

Lo que se vigila aquí es sobre todo la estabilidad del identificador: si se
moviera entre cosechas, una decisión manual pasaría a apuntar a otro artículo sin
que nadie se enterase.
"""

from __future__ import annotations

import json

import pytest

from tatewari.dedup import (
    clave_de_registro,
    deduplicar,
    guardar_asignaciones,
    leer_asignaciones,
    normalizar_doi,
)


def registro(**campos):
    """Un registro mínimo, con lo que no se diga en `"NR"`."""
    base = {
        "doi": "NR",
        "titulo": "NR",
        "anio": 2020,
        "idioma": "es",
        "revista": "NR",
        "autores": ["NR"],
        "resumen": "NR",
        "tipo": "article",
        "citas": "NR",
        "oa_url": "NR",
    }
    base.update(campos)
    return base


# ---------------------------------------------------------------------------
# La clave
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("10.1234/ABC.def", "10.1234/abc.def"),
        ("https://doi.org/10.1234/abc", "10.1234/abc"),
        ("http://dx.doi.org/10.1234/abc", "10.1234/abc"),
        ("doi:10.1234/abc", "10.1234/abc"),
        ("  10.1234/abc  ", "10.1234/abc"),
        ("NR", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_normalizar_doi(crudo, esperado):
    assert normalizar_doi(crudo) == esperado


def test_la_clave_es_el_doi_cuando_lo_hay():
    clave = clave_de_registro(registro(doi="https://doi.org/10.1234/ABC", titulo="T"))

    assert clave == "doi:10.1234/abc"


def test_sin_doi_la_clave_es_el_titulo_reducido():
    con_acentos = clave_de_registro(
        registro(titulo="Tanque séptico — caracterización del efluente")
    )
    sin_acentos = clave_de_registro(
        registro(titulo="Tanque septico - caracterizacion del efluente")
    )

    assert con_acentos.startswith("titulo:")
    assert con_acentos == sin_acentos


def test_sin_doi_ni_titulo_el_registro_se_queda_solo_en_su_grupo():
    """No se puede afirmar que dos registros sin nada sean el mismo artículo."""
    resultado = deduplicar([registro(), registro()])

    assert len(resultado.grupos) == 2
    assert resultado.duplicados_eliminados == 0


# ---------------------------------------------------------------------------
# La fusión
# ---------------------------------------------------------------------------


def test_el_mismo_doi_en_mayusculas_es_el_mismo_articulo():
    resultado = deduplicar(
        [
            registro(doi="10.1234/abc", titulo="Primero"),
            registro(doi="10.1234/ABC", titulo="Primero, sin acentos"),
        ]
    )

    assert resultado.identificados == 2
    assert len(resultado.grupos) == 1
    assert resultado.duplicados_eliminados == 1
    assert resultado.grupos[0].copias == 2


def test_al_fusionar_se_rellenan_los_nr_con_datos_reales():
    """Rellenar un "NR" con un dato que otra fuente sí reportó no es inventar."""
    resultado = deduplicar(
        [
            registro(doi="10.1234/abc", titulo="T", revista="NR", oa_url="NR"),
            registro(
                doi="10.1234/abc",
                titulo="T",
                revista="Revista Real",
                oa_url="https://ejemplo.invalid/a.pdf",
            ),
        ]
    )

    fundido = resultado.unicos[0]
    assert fundido["revista"] == "Revista Real"
    assert fundido["oa_url"] == "https://ejemplo.invalid/a.pdf"


def test_al_fusionar_no_se_sobreescribe_un_dato_que_ya_habia():
    """Si no, el contenido cambiaría según el orden en que llegaron las ecuaciones."""
    resultado = deduplicar(
        [
            registro(doi="10.1234/abc", titulo="T", revista="La primera"),
            registro(doi="10.1234/abc", titulo="T", revista="La segunda"),
        ]
    )

    assert resultado.unicos[0]["revista"] == "La primera"


def test_las_consultas_de_origen_se_acumulan():
    """Saber que un artículo salió en tres ecuaciones es un dato de la revisión."""
    resultado = deduplicar(
        [
            dict(registro(doi="10.1234/abc", titulo="T"), consulta_origen="ecuacion 1"),
            dict(registro(doi="10.1234/abc", titulo="T"), consulta_origen="ecuacion 7"),
            dict(
                registro(doi="10.1234/abc", titulo="T"),
                consulta_origen=["ecuacion 7", "ecuacion 9"],
            ),
        ]
    )

    assert resultado.unicos[0]["consulta_origen"] == [
        "ecuacion 1",
        "ecuacion 7",
        "ecuacion 9",
    ]
    assert resultado.unicos[0]["copias"] == 3


def test_sin_consulta_de_origen_queda_nr_y_no_una_lista_vacia():
    """AGENTS.md, regla 2: lo que no se sabe se escribe "NR"."""
    resultado = deduplicar([registro(doi="10.1234/abc", titulo="T")])

    assert resultado.unicos[0]["consulta_origen"] == ["NR"]


# ---------------------------------------------------------------------------
# Identificadores estables
# ---------------------------------------------------------------------------


def test_los_identificadores_son_correlativos_desde_r0001():
    resultado = deduplicar(
        [registro(doi=f"10.1234/{n}", titulo=f"T{n}") for n in range(1, 4)]
    )

    assert [g.identificador for g in resultado.grupos] == ["R0001", "R0002", "R0003"]


def test_el_identificador_se_conserva_entre_cosechas_sucesivas():
    """La prueba importante de este archivo.

    Llega una cosecha nueva con registros **por delante** de los de antes. Si los
    identificadores se recalcularan, «R0001» pasaría a ser otro artículo y
    cualquier decisión manual sobre él se habría despegado de su artículo sin dar
    ningún error.
    """
    primera = deduplicar(
        [
            registro(doi="10.1234/uno", titulo="Uno"),
            registro(doi="10.1234/dos", titulo="Dos"),
        ]
    )
    asignaciones = primera.asignaciones
    identificadores_previos = {
        g.registro["doi"]: g.identificador for g in primera.grupos
    }

    segunda = deduplicar(
        [
            registro(doi="10.1234/nuevo", titulo="Recién llegado"),
            registro(doi="10.1234/uno", titulo="Uno"),
            registro(doi="10.1234/dos", titulo="Dos"),
        ],
        asignaciones,
    )
    identificadores_ahora = {
        g.registro["doi"]: g.identificador for g in segunda.grupos
    }

    assert identificadores_ahora["10.1234/uno"] == identificadores_previos["10.1234/uno"]
    assert identificadores_ahora["10.1234/dos"] == identificadores_previos["10.1234/dos"]
    # El nuevo sigue la numeración donde se quedó, aunque llegara primero.
    assert identificadores_ahora["10.1234/nuevo"] == "R0003"


def test_un_identificador_no_se_reutiliza_aunque_su_articulo_desaparezca():
    """Podría haber una decisión manual apuntando a él."""
    asignaciones = {"doi:10.1234/desaparecido": "R0001"}

    resultado = deduplicar([registro(doi="10.1234/nuevo", titulo="T")], asignaciones)

    assert resultado.grupos[0].identificador == "R0002"


def test_las_asignaciones_van_y_vuelven_del_disco(tmp_path):
    ruta = tmp_path / "identificadores.json"
    asignaciones = {"doi:10.1234/b": "R0002", "doi:10.1234/a": "R0001"}

    guardar_asignaciones(ruta, asignaciones)

    assert leer_asignaciones(ruta) == asignaciones
    # Guardado en orden de identificador, para que el archivo no baile.
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert list(guardado) == ["doi:10.1234/a", "doi:10.1234/b"]


def test_leer_asignaciones_de_un_archivo_que_no_existe(tmp_path):
    assert leer_asignaciones(tmp_path / "no_existe.json") == {}


def test_el_fixture_de_demostracion_da_trece_unicos(ruta_fixture_demo):
    with open(ruta_fixture_demo, encoding="utf-8") as manejador:
        registros = json.load(manejador)

    resultado = deduplicar(registros)

    assert resultado.identificados == 14
    assert resultado.duplicados_eliminados == 1
    assert len(resultado.grupos) == 13

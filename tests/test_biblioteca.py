"""Pruebas de la biblioteca acumulativa.

Lo que se vigila aquí es sobre todo tres cosas:

1. Que **la deduplicación entre revisiones no invente ni pierda** artículos: dos
   revisiones que traen el mismo DOI tienen que acabar en una sola referencia,
   y dos que traen `R0001` distintos no pueden pisarse.
2. Que **fundir no borre**: un campo con dato no se sobrescribe nunca, pase lo
   que pase con el orden de importación.
3. Que **volver a importar sea seguro**. Si reimportar duplicara, la biblioteca
   dejaría de poder crecer en sesiones sucesivas, que es su única razón de ser.

Las pruebas corren sin red y sin Ollama (AGENTS.md, regla 6): la biblioteca no
sale a ninguna parte, así que aquí basta con carpetas temporales.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from tatewari.biblioteca import (
    NOMBRE_BIBLIOTECA,
    VERSION_ESQUEMA,
    Biblioteca,
    ErrorBiblioteca,
    abrir,
    reconstruir,
)

NR = "NR"

#: Las columnas de `cribado.csv`, en el orden en que las escribe `cribado.py`.
COLUMNAS_CRIBADO = (
    "identificador",
    "decision",
    "motivo",
    "categoria",
    "decidido_por",
    "decision_filtro",
    "motivo_filtro",
    "clasificacion",
    "bloques",
    "bloques_presentes",
    "regla",
    "doi",
    "titulo",
    "anio",
    "idioma",
    "tipo",
    "revista",
    "autores",
    "consulta_origen",
    "copias",
    "oa_url",
)


def registro(**campos):
    """Un registro de cosecha mínimo, con lo que no se diga en "NR"."""
    base = {
        "doi": NR,
        "titulo": NR,
        "anio": NR,
        "idioma": NR,
        "revista": NR,
        "autores": [NR],
        "resumen": NR,
        "tipo": NR,
        "citas": NR,
        "oa_url": NR,
    }
    base.update(campos)
    return base


def fila_cribado(**campos):
    """Una fila de `cribado.csv` con todas sus columnas."""
    base = {columna: NR for columna in COLUMNAS_CRIBADO}
    base["decision"] = "incluir"
    base["decidido_por"] = "filtro"
    base["copias"] = "1"
    base.update(campos)
    return base


def escribir_revision(
    carpeta: Path,
    filas=None,
    registros=None,
    decisiones=None,
    bitacora=None,
    estado=None,
) -> Path:
    """Monta una carpeta de revisión de mentira, con solo lo que se le pida."""
    carpeta.mkdir(parents=True, exist_ok=True)

    with open(carpeta / "estado.json", "w", encoding="utf-8") as manejador:
        json.dump(
            estado or {"revision": carpeta.name, "protocolo": "protocolos/x.json"},
            manejador,
            ensure_ascii=False,
        )

    if filas is not None:
        with open(carpeta / "cribado.csv", "w", encoding="utf-8", newline="") as m:
            escritor = csv.DictWriter(m, fieldnames=COLUMNAS_CRIBADO)
            escritor.writeheader()
            escritor.writerows(filas)

    if registros is not None:
        with open(carpeta / "registros.json", "w", encoding="utf-8") as m:
            json.dump(registros, m, ensure_ascii=False)

    if decisiones is not None:
        with open(carpeta / "decisiones.json", "w", encoding="utf-8") as m:
            json.dump(decisiones, m, ensure_ascii=False)

    if bitacora is not None:
        # Con BOM, igual que la escribe `cosecha.py` para que Excel no destroce
        # los acentos (AGENTS.md, regla 8).
        columnas = ("N", "fecha", "base", "ecuacion", "url", "resultados", "observaciones")
        with open(carpeta / "search_log.csv", "w", encoding="utf-8-sig", newline="") as m:
            escritor = csv.DictWriter(m, fieldnames=columnas, extrasaction="ignore")
            escritor.writeheader()
            escritor.writerows(bitacora)

    return carpeta


@pytest.fixture
def biblioteca(tmp_path):
    """Una biblioteca vacía en una carpeta temporal."""
    with abrir(tmp_path) as instancia:
        yield instancia


# ---------------------------------------------------------------------------
# El esquema
# ---------------------------------------------------------------------------


def test_abrir_crea_el_archivo_y_las_tablas(tmp_path):
    with abrir(tmp_path) as biblio:
        tablas = {
            fila["name"]
            for fila in biblio.conexion.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert (tmp_path / NOMBRE_BIBLIOTECA).is_file()
    assert {"referencia", "autor", "revision", "equivalencia", "decision"} <= tablas
    assert {"dimension", "etiqueta", "anotacion", "hueco", "ecuacion"} <= tablas


def test_abrir_dos_veces_no_rompe_nada(tmp_path):
    """El esquema se crea con IF NOT EXISTS: reabrir tiene que ser inocuo."""
    with abrir(tmp_path) as biblio:
        biblio.alta_referencia(registro(doi="10.1/a", titulo="Uno"))
    with abrir(tmp_path) as biblio:
        assert biblio.contar()["referencia"] == 1


def test_claves_foraneas_activas(biblioteca):
    """Sin `PRAGMA foreign_keys`, las claves foráneas del esquema son adorno."""
    with pytest.raises(sqlite3.IntegrityError):
        biblioteca.conexion.execute(
            "INSERT INTO autor (referencia_id, orden, nombre) VALUES (?, ?, ?)",
            ("B99999", 0, "Fantasma, A."),
        )


def test_esquema_de_version_futura_se_rechaza(tmp_path):
    """Una base de una versión más nueva no se toca: se avisa y se para."""
    with abrir(tmp_path) as biblio:
        biblio.conexion.execute(
            "UPDATE esquema_version SET version = ?", (VERSION_ESQUEMA + 1,)
        )
    with pytest.raises(ErrorBiblioteca) as error:
        abrir(tmp_path)
    assert "Actualiza Tatewari" in str(error.value)


# ---------------------------------------------------------------------------
# Alta y deduplicación
# ---------------------------------------------------------------------------


def test_alta_devuelve_identificador_propio_de_la_biblioteca(biblioteca):
    identificador, nueva = biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno")
    )
    assert nueva is True
    assert identificador == "B00001"


def test_los_identificadores_siguen_la_numeracion(biblioteca):
    biblioteca.alta_referencia(registro(doi="10.1/a", titulo="Uno"))
    segundo, _ = biblioteca.alta_referencia(registro(doi="10.1/b", titulo="Dos"))
    assert segundo == "B00002"


def test_el_mismo_doi_no_entra_dos_veces(biblioteca):
    primero, _ = biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Un título")
    )
    segundo, nueva = biblioteca.alta_referencia(
        registro(doi="https://doi.org/10.1/A", titulo="Otro título distinto")
    )
    assert segundo == primero
    assert nueva is False
    assert biblioteca.contar()["referencia"] == 1


def test_sin_doi_se_deduplica_por_titulo(biblioteca):
    primero, _ = biblioteca.alta_referencia(registro(titulo="Humedales artificiales"))
    segundo, nueva = biblioteca.alta_referencia(
        registro(titulo="  humedales   artificiales  ")
    )
    assert segundo == primero
    assert nueva is False


def test_sin_doi_ni_titulo_cada_registro_entra_solo(biblioteca):
    """No se puede afirmar que dos registros vacíos sean el mismo artículo."""
    biblioteca.alta_referencia(registro())
    biblioteca.alta_referencia(registro())
    assert biblioteca.contar()["referencia"] == 2


def test_un_registro_que_llega_luego_con_doi_se_funde_por_titulo(biblioteca):
    """Primero sin DOI, después con él: es el mismo artículo, no dos."""
    primero, _ = biblioteca.alta_referencia(registro(titulo="Un estudio"))
    segundo, nueva = biblioteca.alta_referencia(
        registro(doi="10.1/nuevo", titulo="Un estudio")
    )
    assert segundo == primero
    assert nueva is False
    fila = biblioteca.conexion.execute(
        "SELECT doi FROM referencia WHERE id = ?", (primero,)
    ).fetchone()
    assert fila["doi"] == "10.1/nuevo"


# ---------------------------------------------------------------------------
# Fundir no borra
# ---------------------------------------------------------------------------


def test_fundir_rellena_lo_que_estaba_en_nr(biblioteca):
    biblioteca.alta_referencia(registro(doi="10.1/a", titulo="Uno", anio=2020))
    biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno", revista="Revista Real", resumen="Algo")
    )
    fila = biblioteca.conexion.execute("SELECT * FROM referencia").fetchone()
    assert fila["anio"] == "2020"
    assert fila["revista"] == "Revista Real"
    assert fila["resumen"] == "Algo"


def test_fundir_no_pisa_un_campo_que_ya_tenia_dato(biblioteca):
    biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno", revista="La primera")
    )
    biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno", revista="La segunda")
    )
    fila = biblioteca.conexion.execute("SELECT revista FROM referencia").fetchone()
    assert fila["revista"] == "La primera"


def test_los_autores_conservan_su_orden(biblioteca):
    identificador, _ = biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno", autores=["Zeta, Z.", "Alfa, A."])
    )
    encontrado = biblioteca.buscar()[0]
    assert encontrado["autores"] == ["Zeta, Z.", "Alfa, A."]


def test_una_lista_de_autores_no_sobrescribe_otra(biblioteca):
    """Una lista parcial que pisara una completa perdería datos en silencio."""
    biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno", autores=["Uno, A.", "Dos, B.", "Tres, C."])
    )
    biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno", autores=["Uno, A."])
    )
    assert len(biblioteca.buscar()[0]["autores"]) == 3


def test_los_autores_llegan_separados_por_barras_desde_el_csv(biblioteca):
    biblioteca.alta_referencia(
        {"doi": "10.1/a", "titulo": "Uno", "autores": "Uno, A.|Dos, B."}
    )
    assert biblioteca.buscar()[0]["autores"] == ["Uno, A.", "Dos, B."]


def test_lo_que_no_vino_se_guarda_como_nr(biblioteca):
    """AGENTS.md regla 2: nunca un valor plausible, siempre "NR" visible."""
    biblioteca.alta_referencia(registro(doi="10.1/a", titulo="Uno"))
    fila = biblioteca.conexion.execute("SELECT * FROM referencia").fetchone()
    for campo in ("anio", "revista", "resumen", "volumen", "paginas", "oa_estado"):
        assert fila[campo] == NR


# ---------------------------------------------------------------------------
# Importar una revisión
# ---------------------------------------------------------------------------


def test_importar_una_revision_desde_el_cribado(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[
            fila_cribado(
                identificador="R0001",
                doi="10.1/a",
                titulo="Humedal artificial",
                anio="2021",
                clasificacion="Humedal artificial solo",
                motivo="Cumple la regla",
            ),
            fila_cribado(
                identificador="R0002",
                decision="excluir",
                doi="10.1/b",
                titulo="Otra cosa",
                anio="2019",
            ),
        ],
    )
    resultado = biblioteca.importar_revision(carpeta)

    assert resultado.referencias_nuevas == 2
    assert resultado.decisiones == 2
    assert resultado.etiquetas == 1
    assert biblioteca.contar()["referencia"] == 2


def test_el_identificador_local_queda_atado_al_de_la_biblioteca(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0007", doi="10.1/a", titulo="Uno")],
    )
    biblioteca.importar_revision(carpeta)
    fila = biblioteca.conexion.execute(
        "SELECT referencia_id FROM equivalencia WHERE revision = ? AND id_local = ?",
        ("rev", "R0007"),
    ).fetchone()
    assert fila["referencia_id"] == "B00001"


def test_dos_revisiones_con_el_mismo_r0001_no_se_pisan(biblioteca, tmp_path):
    """El caso que obliga a que la biblioteca tenga numeración propia."""
    una = escribir_revision(
        tmp_path / "una",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Artículo A")],
    )
    otra = escribir_revision(
        tmp_path / "otra",
        filas=[fila_cribado(identificador="R0001", doi="10.1/b", titulo="Artículo B")],
    )
    biblioteca.importar_revision(una)
    biblioteca.importar_revision(otra)

    assert biblioteca.contar()["referencia"] == 2
    equivalencias = {
        (fila["revision"], fila["referencia_id"])
        for fila in biblioteca.conexion.execute(
            "SELECT revision, referencia_id FROM equivalencia WHERE id_local = 'R0001'"
        )
    }
    assert equivalencias == {("una", "B00001"), ("otra", "B00002")}


def test_dos_revisiones_que_comparten_doi_comparten_referencia(biblioteca, tmp_path):
    una = escribir_revision(
        tmp_path / "una",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Compartido")],
    )
    otra = escribir_revision(
        tmp_path / "otra",
        filas=[fila_cribado(identificador="R0042", doi="10.1/a", titulo="Compartido")],
    )
    biblioteca.importar_revision(una)
    segundo = biblioteca.importar_revision(otra)

    assert biblioteca.contar()["referencia"] == 1
    assert segundo.referencias_nuevas == 0
    assert segundo.referencias_vistas == 1


def test_reimportar_no_duplica(biblioteca, tmp_path):
    """Si reimportar duplicara, la biblioteca no podría crecer por sesiones."""
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
    )
    biblioteca.importar_revision(carpeta)
    segundo = biblioteca.importar_revision(carpeta)

    assert biblioteca.contar()["referencia"] == 1
    assert segundo.referencias_nuevas == 0
    assert biblioteca.contar()["revision"] == 1


def test_importar_sin_cribado_usa_la_cosecha_cruda(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        registros=[
            registro(doi="10.1/a", titulo="Uno"),
            registro(doi="10.1/a", titulo="Uno"),  # el mismo, por otra ecuación
            registro(doi="10.1/b", titulo="Dos"),
        ],
    )
    resultado = biblioteca.importar_revision(carpeta)
    assert resultado.referencias_nuevas == 2


def test_el_resumen_se_completa_desde_la_cosecha(biblioteca, tmp_path):
    """`cribado.csv` no lleva resumen; sin esto la búsqueda por texto iría ciega."""
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
        registros=[registro(doi="10.1/a", titulo="Uno", resumen="Remoción de DQO")],
    )
    biblioteca.importar_revision(carpeta)
    assert biblioteca.buscar(texto="DQO")[0]["titulo"] == "Uno"


def test_una_carpeta_que_no_existe_falla_claro(biblioteca, tmp_path):
    with pytest.raises(ErrorBiblioteca) as error:
        biblioteca.importar_revision(tmp_path / "no_existe")
    assert "No existe la carpeta" in str(error.value)


def test_una_revision_vacia_lo_avisa(biblioteca, tmp_path):
    carpeta = escribir_revision(tmp_path / "rev")
    resultado = biblioteca.importar_revision(carpeta)
    assert resultado.referencias == 0
    assert any("no se importó" in aviso for aviso in resultado.avisos)


# ---------------------------------------------------------------------------
# Las decisiones
# ---------------------------------------------------------------------------


def test_la_decision_del_filtro_se_guarda_con_origen_regla(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[
            fila_cribado(
                identificador="R0001",
                doi="10.1/a",
                titulo="Uno",
                decision="incluir",
                decidido_por="filtro",
            )
        ],
    )
    biblioteca.importar_revision(carpeta)
    fila = biblioteca.conexion.execute("SELECT * FROM decision").fetchone()
    assert fila["estado"] == "incluido"
    assert fila["origen"] == "regla"


def test_decisiones_json_manda_sobre_el_filtro(biblioteca, tmp_path):
    """AGENTS.md regla 4: el filtro propone, la persona o el modelo deciden."""
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[
            fila_cribado(
                identificador="R0001", doi="10.1/a", titulo="Uno", decision="dudoso"
            )
        ],
        decisiones={
            "R0001": {
                "decision": "incluir",
                "motivo": "Lo revisé a mano",
                "autor": "inge",
                "fecha": "2026-09-17",
            }
        },
    )
    biblioteca.importar_revision(carpeta)
    fila = biblioteca.conexion.execute("SELECT * FROM decision").fetchone()
    assert fila["estado"] == "incluido"
    assert fila["origen"] == "humano"
    assert fila["motivo"] == "Lo revisé a mano"


def test_una_decision_del_modelo_se_marca_como_del_modelo(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
        decisiones={
            "R0001": {
                "decision": "dudoso",
                "motivo": "No queda claro",
                "autor": "modelo:qwen3:4b",
                "fecha": "2026-09-17",
            }
        },
    )
    biblioteca.importar_revision(carpeta)
    fila = biblioteca.conexion.execute("SELECT * FROM decision").fetchone()
    assert fila["origen"] == "modelo"


def test_una_decision_sobre_un_registro_ausente_se_avisa(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
        decisiones={"R9999": {"decision": "incluir", "motivo": "x", "autor": "inge"}},
    )
    resultado = biblioteca.importar_revision(carpeta)
    assert any("R9999" in aviso for aviso in resultado.avisos)


# ---------------------------------------------------------------------------
# Las ecuaciones y los huecos
# ---------------------------------------------------------------------------


def test_la_bitacora_se_refleja_con_su_ecuacion_literal(biblioteca, tmp_path):
    """AGENTS.md regla 3: la ecuación se guarda tal cual se envió."""
    literal = '"humedal artificial" AND "anaerobic"'
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
        bitacora=[
            {
                "N": "1",
                "fecha": "2026-09-17T10:00:00",
                "base": "OpenAlex",
                "ecuacion": literal,
                "url": "https://api.openalex.org/works?filter=x",
                "resultados": "14",
                "observaciones": "",
            }
        ],
    )
    biblioteca.importar_revision(carpeta)
    fila = biblioteca.conexion.execute("SELECT * FROM ecuacion").fetchone()
    assert fila["literal"] == literal
    assert fila["resultados"] == 14


def test_una_ecuacion_sin_resultados_queda_como_hueco(biblioteca, tmp_path):
    """Un vacío es un hallazgo, no una omisión."""
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
        bitacora=[
            {
                "N": "1",
                "fecha": "2026-09-17T10:00:00",
                "base": "OpenAlex",
                "ecuacion": '"humedal" AND "Bolivia"',
                "url": "https://api.openalex.org/works?filter=y",
                "resultados": "0",
                "observaciones": "",
            },
            {
                "N": "2",
                "fecha": "2026-09-17T10:00:01",
                "base": "OpenAlex",
                "ecuacion": '"humedal" AND "México"',
                "url": "https://api.openalex.org/works?filter=z",
                "resultados": "31",
                "observaciones": "",
            },
        ],
    )
    resultado = biblioteca.importar_revision(carpeta)

    assert resultado.huecos == 1
    huecos = biblioteca.huecos("rev")
    assert len(huecos) == 1
    assert "Bolivia" in huecos[0]["valor"]


def test_la_bitacora_con_bom_no_pierde_la_primera_columna(biblioteca, tmp_path):
    """Se escribe en utf-8-sig; leerla sin `-sig` pegaría el BOM al nombre de N."""
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
        bitacora=[
            {
                "N": "7",
                "fecha": "2026-09-17T10:00:00",
                "base": "OpenAlex",
                "ecuacion": "algo",
                "url": "https://ejemplo.invalid",
                "resultados": "3",
                "observaciones": "",
            }
        ],
    )
    biblioteca.importar_revision(carpeta)
    fila = biblioteca.conexion.execute("SELECT numero FROM ecuacion").fetchone()
    assert fila["numero"] == 7


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def test_buscar_por_texto_mira_titulo_y_resumen(biblioteca):
    biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Humedales", resumen="Trata de remoción")
    )
    biblioteca.alta_referencia(registro(doi="10.1/b", titulo="Otra cosa"))

    assert len(biblioteca.buscar(texto="Humedales")) == 1
    assert len(biblioteca.buscar(texto="remoción")) == 1
    assert len(biblioteca.buscar(texto="inexistente")) == 0


def test_buscar_por_estado_de_una_revision(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[
            fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno"),
            fila_cribado(
                identificador="R0002", doi="10.1/b", titulo="Dos", decision="excluir"
            ),
        ],
    )
    biblioteca.importar_revision(carpeta)
    assert len(biblioteca.buscar(revision="rev", estado="incluido")) == 1
    assert len(biblioteca.buscar(revision="rev", estado="excluido")) == 1


def test_buscar_por_dimension(biblioteca, tmp_path):
    carpeta = escribir_revision(
        tmp_path / "rev",
        filas=[
            fila_cribado(
                identificador="R0001",
                doi="10.1/a",
                titulo="Uno",
                clasificacion="Sistema combinado",
            ),
            fila_cribado(
                identificador="R0002",
                doi="10.1/b",
                titulo="Dos",
                clasificacion="Humedal solo",
            ),
        ],
    )
    biblioteca.importar_revision(carpeta)
    encontrados = biblioteca.buscar(dimension="clasificacion", valor="Humedal solo")
    assert len(encontrados) == 1
    assert encontrados[0]["titulo"] == "Dos"


def test_buscar_por_anio_deja_fuera_los_nr(biblioteca):
    """El año es TEXT porque puede valer "NR"; el filtro no puede tropezar."""
    biblioteca.alta_referencia(registro(doi="10.1/a", titulo="Nuevo", anio=2024))
    biblioteca.alta_referencia(registro(doi="10.1/b", titulo="Viejo", anio=2001))
    biblioteca.alta_referencia(registro(doi="10.1/c", titulo="Sin año"))

    encontrados = biblioteca.buscar(anio_desde=2010)
    assert [f["titulo"] for f in encontrados] == ["Nuevo"]


def test_buscar_no_repite_una_referencia_con_varias_etiquetas(biblioteca, tmp_path):
    """El JOIN con etiqueta multiplicaría filas sin el DISTINCT."""
    identificador, _ = biblioteca.alta_referencia(
        registro(doi="10.1/a", titulo="Uno")
    )
    biblioteca.conexion.execute(
        "INSERT INTO revision (nombre, importada) VALUES ('rev', '2026-09-17')"
    )
    biblioteca.conexion.execute(
        "INSERT INTO dimension (revision, nombre, tipo) VALUES ('rev', 'region', 'determinista')"
    )
    for valor in ("México", "Perú"):
        biblioteca.conexion.execute(
            "INSERT INTO etiqueta (revision, referencia_id, dimension, valor, origen, fecha) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("rev", identificador, "region", valor, "termino", "2026-09-17"),
        )
    assert len(biblioteca.buscar(dimension="region")) == 1


# ---------------------------------------------------------------------------
# Reconstrucción
# ---------------------------------------------------------------------------


def test_reconstruir_rehace_la_base_desde_las_carpetas(tmp_path):
    """Lo que hace desechable a la base, y por tanto segura como fuente de verdad."""
    revisiones = tmp_path / "revisiones"
    escribir_revision(
        revisiones / "una",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
    )
    escribir_revision(
        revisiones / "otra",
        filas=[fila_cribado(identificador="R0001", doi="10.1/b", titulo="Dos")],
    )

    with abrir(tmp_path) as biblio:
        biblio.importar_revision(revisiones / "una")
        assert biblio.contar()["referencia"] == 1

    resumenes = reconstruir(tmp_path, revisiones)

    assert [r.revision for r in resumenes] == ["otra", "una"]
    with abrir(tmp_path) as biblio:
        assert biblio.contar()["referencia"] == 2
        assert biblio.contar()["revision"] == 2


def test_reconstruir_ignora_las_carpetas_que_no_son_revisiones(tmp_path):
    revisiones = tmp_path / "revisiones"
    escribir_revision(
        revisiones / "buena",
        filas=[fila_cribado(identificador="R0001", doi="10.1/a", titulo="Uno")],
    )
    (revisiones / "suelta").mkdir(parents=True)
    (revisiones / "suelta" / "notas.txt").write_text("nada", encoding="utf-8")

    resumenes = reconstruir(tmp_path, revisiones)
    assert [r.revision for r in resumenes] == ["buena"]


# ---------------------------------------------------------------------------
# Contra la revisión de ejemplo que se versiona en el repositorio
# ---------------------------------------------------------------------------


@pytest.fixture
def carpeta_demo(raiz) -> Path:
    carpeta = raiz / "revisiones" / "demo"
    if not carpeta.is_dir():
        pytest.skip("No hay revisión demo cosechada en este árbol")
    return carpeta


def test_importar_la_revision_demo(tmp_path, carpeta_demo):
    with abrir(tmp_path) as biblio:
        resultado = biblio.importar_revision(carpeta_demo)
        # El fixture trae 14 registros de los que dos son el mismo artículo.
        assert resultado.referencias_nuevas == 13
        assert biblio.contar()["referencia"] == 13


def test_los_acentos_sobreviven_a_la_base(tmp_path, carpeta_demo, raiz):
    """AGENTS.md regla 8: sin `encoding="utf-8"` explícito, Windows los rompe."""
    with open(carpeta_demo / "registros.json", encoding="utf-8") as manejador:
        esperado = json.load(manejador)[0]["titulo"]

    with abrir(tmp_path) as biblio:
        biblio.importar_revision(carpeta_demo)
        fila = biblio.conexion.execute(
            "SELECT titulo FROM referencia WHERE clave_titulo = ?",
            (__import__("tatewari.texto", fromlist=["x"]).clave_alfanumerica(esperado),),
        ).fetchone()

    assert fila["titulo"] == esperado


def test_la_revision_del_fixture_queda_marcada_como_sintetica(tmp_path, carpeta_demo):
    """El README es explícito: el fixture no debe citarse ni exportarse.

    La marca la pone la importación para que el exportador pueda negarse cuando
    llegue, en vez de descubrirlo cuando ya esté en Zotero.
    """
    with abrir(tmp_path) as biblio:
        biblio.importar_revision(carpeta_demo)
        assert biblio.revisiones()[0]["sintetica"] == 1

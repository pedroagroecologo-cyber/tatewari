"""Pruebas del cribado determinista. No tocan la red ni usan ningún modelo.

La prueba que fija el resultado sobre el fixture completo está en `test_oro.py`.
Aquí se prueban las piezas por separado: el orden de evaluación, el motor de
reglas, la clasificación y las decisiones manuales.
"""

from __future__ import annotations

import csv
import json

import pytest

from tatewari.config import Config
from tatewari.cribado import (
    CATEGORIA_IDIOMA,
    CATEGORIA_MANUAL,
    CATEGORIA_SIN_REGLA,
    CATEGORIA_TEMA,
    CATEGORIA_VENTANA,
    COLUMNAS_CRIBADO,
    Cribado,
    DecisionManual,
    ErrorCribado,
    clasificar,
    cribar,
    decidir,
    protocolo_registrado,
    regla_se_cumple,
    validar_decisiones,
)
from tatewari.protocolo import Clasificacion, Regla, validar_protocolo


@pytest.fixture
def protocolo_cribado(protocolo_minimo):
    """Protocolo pequeño y explícito, para probar el motor sin ruido.

    B1 y B2 son bloques; G1 es un grupo. Las reglas usan las tres condiciones.
    """
    datos = dict(protocolo_minimo)
    datos["bloques"] = {
        "B1": ["agua residual", "wastewater"],
        "B2": ["humedal artificial", "constructed wetland"],
    }
    datos["grupos"] = {"G1": ["ciclo de vida", "life cycle assessment"]}
    datos["exclusion"] = ["análisis de ciclo de vida"]
    datos["clasificacion"] = [
        {"etiqueta": "Agua en humedal", "todos": ["B1", "B2"]},
        {"etiqueta": "Solo agua", "todos": ["B1"]},
    ]
    datos["reglas"] = {
        "sinResumen": "dudoso",
        "incluir": [
            {
                "todos": ["B1", "B2"],
                "ninguno": ["G1"],
                "motivo": "Trata agua residual en un humedal artificial.",
            }
        ],
        "dudoso": [
            {
                "todos": ["B2"],
                "ninguno": ["B1"],
                "motivo": "Humedal sin agua residual clara.",
            }
        ],
    }
    return validar_protocolo(datos)


def registro(**campos):
    base = {
        "identificador": "R0001",
        "doi": "10.1234/abc",
        "titulo": "Un título cualquiera",
        "anio": 2020,
        "idioma": "es",
        "revista": "NR",
        "autores": ["NR"],
        "resumen": "Un resumen cualquiera.",
        "tipo": "article",
        "citas": "NR",
        "oa_url": "NR",
    }
    base.update(campos)
    return base


# ---------------------------------------------------------------------------
# El motor de reglas
# ---------------------------------------------------------------------------


def test_todos_exige_todos_los_bloques():
    regla = Regla(todos=("B1", "B2"))

    assert regla_se_cumple(regla, {"B1", "B2", "B3"}) == (True, ("B1", "B2"))
    assert regla_se_cumple(regla, {"B1"}) == (False, ())


def test_alguno_de_exige_uno_de_cada_sublista():
    regla = Regla(alguno_de=(("B1", "B2"), ("B3", "B4")))

    cumple, disparados = regla_se_cumple(regla, {"B2", "B3"})
    assert cumple
    assert set(disparados) == {"B2", "B3"}

    # De la segunda sublista no hay ninguno: no se cumple.
    assert regla_se_cumple(regla, {"B1", "B2"}) == (False, ())


def test_ninguno_tumba_la_regla():
    regla = Regla(todos=("B1",), ninguno=("G1",))

    assert regla_se_cumple(regla, {"B1"})[0] is True
    assert regla_se_cumple(regla, {"B1", "G1"}) == (False, ())


def test_los_bloques_disparados_no_se_repiten():
    """Un mismo bloque puede estar citado en "todos" y en una sublista."""
    regla = Regla(todos=("B1",), alguno_de=(("B1", "B2"),))

    cumple, disparados = regla_se_cumple(regla, {"B1", "B2"})

    assert cumple
    assert disparados == ("B1", "B2")
    assert len(disparados) == len(set(disparados))


def test_las_tres_condiciones_a_la_vez():
    regla = Regla(todos=("B1",), alguno_de=(("B2", "B3"),), ninguno=("G1",))

    assert regla_se_cumple(regla, {"B1", "B3"})[0] is True
    assert regla_se_cumple(regla, {"B1", "B3", "G1"})[0] is False
    assert regla_se_cumple(regla, {"B3"})[0] is False


# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------


def test_la_clasificacion_es_la_primera_etiqueta_que_cuadra(protocolo_cribado):
    """El orden del protocolo decide: la etiqueta más específica va primero."""
    assert clasificar(protocolo_cribado, {"B1", "B2"}) == "Agua en humedal"
    assert clasificar(protocolo_cribado, {"B1"}) == "Solo agua"


def test_sin_etiqueta_que_cuadre_la_clasificacion_es_nr(protocolo_cribado):
    assert clasificar(protocolo_cribado, {"B2"}) == "NR"
    assert clasificar(protocolo_cribado, set()) == "NR"


def test_una_etiqueta_sin_su_bloque_no_se_aplica():
    protocolo = validar_protocolo(
        {
            "titulo": "T",
            "ventana": [2016, 2026],
            "idiomas": ["es"],
            "tipos": ["article"],
            "bloques": {"B1": ["t"], "B2": ["u"]},
            "clasificacion": [{"etiqueta": "Ambos", "todos": ["B1", "B2"]}],
        }
    )

    assert clasificar(protocolo, {"B1"}) == "NR"
    assert protocolo.clasificacion == (Clasificacion("Ambos", ("B1", "B2")),)


# ---------------------------------------------------------------------------
# Orden de evaluación
# ---------------------------------------------------------------------------


def test_primero_la_ventana_temporal(protocolo_cribado):
    """Aunque el contenido encaje de sobra, el motivo verdadero es el año."""
    decision = decidir(
        registro(
            anio=1999,
            resumen="agua residual tratada en un humedal artificial",
        ),
        protocolo_cribado,
    )

    assert decision.decision == "excluir"
    assert decision.categoria == CATEGORIA_VENTANA
    assert "1999" in decision.motivo


def test_despues_el_idioma(protocolo_cribado):
    decision = decidir(
        registro(
            idioma="fr",
            resumen="agua residual tratada en un humedal artificial",
        ),
        protocolo_cribado,
    )

    assert decision.decision == "excluir"
    assert decision.categoria == CATEGORIA_IDIOMA


def test_la_ventana_manda_sobre_el_idioma(protocolo_cribado):
    """Con los dos mal, el motivo es el primero que se evalúa."""
    decision = decidir(registro(anio=1999, idioma="fr"), protocolo_cribado)

    assert decision.categoria == CATEGORIA_VENTANA


def test_un_registro_sin_resumen_es_dudoso_y_no_excluido(protocolo_cribado):
    """El error clásico: descartar a ciegas lo que no se puede leer."""
    decision = decidir(registro(resumen="NR"), protocolo_cribado)

    assert decision.decision == "dudoso"
    assert decision.categoria == ""
    assert "no es cribable en automático" in decision.motivo


def test_el_protocolo_puede_decir_otra_cosa_para_los_registros_sin_resumen(
    protocolo_minimo,
):
    """`sinResumen` es del protocolo; el valor por defecto es «dudoso»."""
    datos = dict(protocolo_minimo)
    datos["reglas"] = {"sinResumen": "excluir", "incluir": [{"todos": ["B1"]}]}
    protocolo = validar_protocolo(datos)

    decision = decidir(registro(resumen="NR"), protocolo)

    assert decision.decision == "excluir"
    assert decision.categoria == "Sin resumen"


def test_luego_la_exclusion_tematica(protocolo_cribado):
    decision = decidir(
        registro(
            resumen=(
                "Un análisis de ciclo de vida de agua residual en un humedal "
                "artificial."
            )
        ),
        protocolo_cribado,
    )

    assert decision.decision == "excluir"
    assert decision.categoria == CATEGORIA_TEMA
    # El motivo cita el término del protocolo que lo disparó.
    assert "análisis de ciclo de vida" in decision.motivo


def test_y_solo_entonces_las_reglas_de_bloques(protocolo_cribado):
    decision = decidir(
        registro(resumen="agua residual tratada en un humedal artificial"),
        protocolo_cribado,
    )

    assert decision.decision == "incluir"
    assert decision.regla == "incluir[0]"
    assert decision.bloques == ("B1", "B2")
    assert decision.motivo == "Trata agua residual en un humedal artificial."


def test_las_reglas_de_incluir_van_antes_que_las_de_dudoso(protocolo_minimo):
    """Con las dos cumplidas, gana «incluir»."""
    datos = dict(protocolo_minimo)
    datos["bloques"] = {"B1": ["agua residual"]}
    datos["reglas"] = {
        "incluir": [{"todos": ["B1"], "motivo": "Sí."}],
        "dudoso": [{"todos": ["B1"], "motivo": "Quizá."}],
    }
    protocolo = validar_protocolo(datos)

    decision = decidir(registro(resumen="agua residual"), protocolo)

    assert decision.decision == "incluir"
    assert decision.regla == "incluir[0]"


def test_lo_que_no_cumple_ninguna_regla_se_excluye_con_ese_motivo(protocolo_cribado):
    decision = decidir(
        registro(resumen="Un estudio de suelos agrícolas sin nada que ver."),
        protocolo_cribado,
    )

    assert decision.decision == "excluir"
    assert decision.categoria == CATEGORIA_SIN_REGLA
    assert "ninguna regla" in decision.motivo


def test_una_regla_de_dudoso_manda_el_registro_a_una_persona(protocolo_cribado):
    decision = decidir(
        registro(resumen="Un humedal artificial de aguas pluviales."),
        protocolo_cribado,
    )

    assert decision.decision == "dudoso"
    assert decision.regla == "dudoso[0]"
    assert decision.bloques == ("B2",)


# ---------------------------------------------------------------------------
# Datos que faltan
# ---------------------------------------------------------------------------


def test_un_ano_sin_reportar_es_dudoso_y_no_una_exclusion(protocolo_cribado):
    """Un dato que falta nunca es motivo de exclusión automática."""
    decision = decidir(registro(anio="NR"), protocolo_cribado)

    assert decision.decision == "dudoso"
    assert "año no viene reportado" in decision.motivo


def test_un_idioma_sin_reportar_es_dudoso(protocolo_cribado):
    decision = decidir(registro(idioma="NR"), protocolo_cribado)

    assert decision.decision == "dudoso"
    assert "idioma no viene reportado" in decision.motivo


def test_el_titulo_tambien_cuenta_para_detectar_bloques(protocolo_cribado):
    """Sin resumen se decide «dudoso», pero el título sigue siendo dato real."""
    decision = decidir(
        registro(titulo="Humedal artificial para agua residual", resumen="NR"),
        protocolo_cribado,
    )

    assert decision.decision == "dudoso"
    assert set(decision.bloques_presentes) == {"B1", "B2"}
    assert decision.clasificacion == "Agua en humedal"


# ---------------------------------------------------------------------------
# Auditoría de la decisión
# ---------------------------------------------------------------------------


def test_toda_decision_lleva_motivo_en_espanol(protocolo_cribado, ruta_fixture_demo):
    with open(ruta_fixture_demo, encoding="utf-8") as manejador:
        registros = json.load(manejador)

    resultado = cribar(registros, protocolo_cribado)

    for decision in resultado.decisiones:
        assert decision.motivo.strip()
        assert decision.decidido_por == "filtro"


def test_los_bloques_presentes_explican_por_que_no_se_disparo_otra_regla(
    protocolo_cribado,
):
    """`bloques` son los que dispararon; `bloques_presentes`, todos los vistos."""
    decision = decidir(
        registro(resumen="Un humedal artificial de aguas pluviales."),
        protocolo_cribado,
    )

    assert decision.bloques == ("B2",)
    assert decision.bloques_presentes == ("B2",)


# ---------------------------------------------------------------------------
# Decisiones manuales
# ---------------------------------------------------------------------------


def test_una_decision_manual_sobreescribe_al_filtro_sin_borrarlo(
    protocolo_cribado,
):
    manual = DecisionManual(
        identificador="R0001",
        decision="incluir",
        motivo="El texto completo sí reporta remoción.",
        autor="Pedro",
        fecha="2026-09-12",
    )

    resultado = cribar(
        [registro(resumen="Un estudio de suelos agrícolas.")],
        protocolo_cribado,
        decisiones_manuales={"R0001": manual},
    )
    decision = resultado.buscar("R0001")

    assert decision.decision == "incluir"
    assert decision.decidido_por == "Pedro"
    assert decision.es_manual
    # La del filtro no se borra: se conserva al lado para poder comparar.
    assert decision.decision_filtro == "excluir"
    assert "ninguna regla" in decision.motivo_filtro
    assert "El texto completo sí reporta remoción." in decision.motivo
    assert "Pedro" in decision.motivo and "2026-09-12" in decision.motivo


def test_una_exclusion_manual_se_cuenta_en_su_propia_categoria(protocolo_cribado):
    """Para que no se confunda con una exclusión automática en el PRISMA."""
    manual = DecisionManual(
        identificador="R0001",
        decision="excluir",
        motivo="Es el mismo estudio que R0004, publicado dos veces.",
        autor="Pedro",
        fecha="2026-09-12",
    )

    resultado = cribar(
        [registro(resumen="agua residual en un humedal artificial")],
        protocolo_cribado,
        decisiones_manuales={"R0001": manual},
    )

    assert resultado.motivos_de_exclusion == {CATEGORIA_MANUAL: 1}
    assert resultado.buscar("R0001").decision_filtro == "incluir"


def test_un_registro_rescatado_a_mano_deja_de_contar_como_excluido(
    protocolo_cribado,
):
    manual = DecisionManual(
        identificador="R0001",
        decision="incluir",
        motivo="Rescatado tras leer el texto completo.",
        autor="Pedro",
        fecha="2026-09-12",
    )

    resultado = cribar(
        [registro(anio=1999)],
        protocolo_cribado,
        decisiones_manuales={"R0001": manual},
    )

    assert resultado.conteos["excluir"] == 0
    assert resultado.motivos_de_exclusion == {}
    assert resultado.buscar("R0001").categoria == ""


def test_una_decision_para_un_registro_que_no_esta_avisa_y_no_se_pierde(
    protocolo_cribado,
):
    manual = DecisionManual(
        identificador="R9999",
        decision="incluir",
        motivo="De otra cosecha.",
        autor="Pedro",
        fecha="2026-09-12",
    )

    resultado = cribar(
        [registro()], protocolo_cribado, decisiones_manuales={"R9999": manual}
    )

    assert len(resultado.avisos) == 1
    assert "R9999" in resultado.avisos[0]


def test_validar_decisiones_acepta_la_forma_de_objeto():
    decisiones = validar_decisiones(
        {
            "R0007": {
                "decision": "incluir",
                "motivo": "Sí vale.",
                "autor": "Pedro",
                "fecha": "2026-09-12",
            }
        }
    )

    assert decisiones["R0007"].decision == "incluir"
    assert decisiones["R0007"].autor == "Pedro"


def test_validar_decisiones_acepta_la_forma_de_lista():
    decisiones = validar_decisiones(
        [
            {
                "identificador": "R0007",
                "decision": "dudoso",
                "motivo": "No lo veo claro.",
                "autor": "Pedro",
                "fecha": "2026-09-12",
            }
        ]
    )

    assert decisiones["R0007"].decision == "dudoso"


def test_una_decision_manual_sin_motivo_autor_o_fecha_no_vale():
    """Si no se puede auditar, no vale más que la del filtro."""
    with pytest.raises(ErrorCribado) as fallo:
        validar_decisiones({"R0007": {"decision": "incluir"}})

    assert "motivo, autor, fecha" in str(fallo.value)


def test_una_decision_manual_con_una_decision_inventada_no_vale():
    with pytest.raises(ErrorCribado) as fallo:
        validar_decisiones(
            {
                "R0007": {
                    "decision": "quizá",
                    "motivo": "m",
                    "autor": "a",
                    "fecha": "f",
                }
            }
        )

    assert "incluir, dudoso, excluir" in str(fallo.value)


def test_los_errores_de_las_decisiones_se_reunen_todos():
    """Corregir el archivo de uno en uno es un suplicio."""
    with pytest.raises(ErrorCribado) as fallo:
        validar_decisiones(
            {
                "R0001": {"decision": "incluir"},
                "R0002": {"decision": "inventada", "motivo": "m", "autor": "a", "fecha": "f"},
                "R0003": {"decision": "incluir", "motivo": "m", "autor": "a", "fecha": "f"},
            }
        )

    assert len(fallo.value.errores) == 2
    assert "R0001" in str(fallo.value)
    assert "R0002" in str(fallo.value)


def test_un_campo_de_mas_en_una_decision_se_avisa():
    with pytest.raises(ErrorCribado) as fallo:
        validar_decisiones(
            {
                "R0007": {
                    "decision": "incluir",
                    "motivo": "m",
                    "autor": "a",
                    "fecha": "f",
                    "confianza": 0.9,
                }
            }
        )

    assert "confianza" in str(fallo.value)


# ---------------------------------------------------------------------------
# Salidas en disco
# ---------------------------------------------------------------------------


@pytest.fixture
def revision_en_disco(tmp_path, ruta_fixture_demo):
    """Una revisión ya cosechada, en una carpeta temporal."""
    config = Config(
        mailto="prueba@ejemplo.invalid",
        ollama="http://localhost:11434",
        datos=tmp_path / "revisiones",
    )
    carpeta = config.datos / "demo"
    carpeta.mkdir(parents=True)
    registros = json.loads(ruta_fixture_demo.read_text(encoding="utf-8"))
    (carpeta / "registros.json").write_text(
        json.dumps(registros, ensure_ascii=False), encoding="utf-8"
    )
    return config, carpeta


def test_el_cribado_escribe_el_csv_y_el_prisma(revision_en_disco, protocolo):
    config, carpeta = revision_en_disco

    cribado = Cribado(revision="demo", protocolo=protocolo, config=config)
    resultado = cribado.ejecutar()

    assert (carpeta / "cribado.csv").is_file()
    assert (carpeta / "prisma.txt").is_file()
    assert (carpeta / "identificadores.json").is_file()
    assert "PRISMA" in (carpeta / "prisma.txt").read_text(encoding="utf-8")
    assert resultado.cribados == 13


def test_el_csv_tiene_una_fila_por_registro_unico(revision_en_disco, protocolo):
    config, carpeta = revision_en_disco
    Cribado(revision="demo", protocolo=protocolo, config=config).ejecutar()

    with open(carpeta / "cribado.csv", encoding="utf-8", newline="") as manejador:
        filas = list(csv.DictReader(manejador))

    assert len(filas) == 13
    assert list(filas[0]) == list(COLUMNAS_CRIBADO)


def test_el_csv_escapa_las_comas_y_las_comillas_de_los_titulos(
    revision_en_disco, protocolo
):
    """Un título con comas y comillas no puede partir la fila en dos."""
    config, carpeta = revision_en_disco
    titulo = 'SINTETICO DE PRUEBA — Remoción de DQO, DBO5 y SST: el "caso" rural'
    registros = json.loads((carpeta / "registros.json").read_text(encoding="utf-8"))
    registros[0]["titulo"] = titulo
    (carpeta / "registros.json").write_text(
        json.dumps(registros, ensure_ascii=False), encoding="utf-8"
    )

    Cribado(revision="demo", protocolo=protocolo, config=config).ejecutar()

    with open(carpeta / "cribado.csv", encoding="utf-8", newline="") as manejador:
        filas = list(csv.DictReader(manejador))

    assert len(filas) == 13
    assert filas[0]["titulo"] == titulo
    # Y en el archivo crudo, el título va entrecomillado y las comillas dobladas.
    crudo = (carpeta / "cribado.csv").read_text(encoding="utf-8")
    assert '""caso""' in crudo


def test_el_csv_va_en_utf8_sin_bom_y_con_saltos_lf(revision_en_disco, protocolo):
    """La excepción del BOM de AGENTS.md es solo para `search_log.csv`."""
    config, carpeta = revision_en_disco
    Cribado(revision="demo", protocolo=protocolo, config=config).ejecutar()

    datos = (carpeta / "cribado.csv").read_bytes()

    assert not datos.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in datos
    assert "Remoción".encode("utf-8") in datos or "remoción".encode("utf-8") in datos


def test_los_identificadores_se_conservan_al_volver_a_cribar(
    revision_en_disco, protocolo
):
    """Cribar dos veces no puede mover ningún identificador."""
    config, carpeta = revision_en_disco
    cribado = Cribado(revision="demo", protocolo=protocolo, config=config)

    primero = cribado.ejecutar()
    asignaciones = json.loads(
        (carpeta / "identificadores.json").read_text(encoding="utf-8")
    )
    segundo = cribado.ejecutar()

    assert [d.identificador for d in primero.decisiones] == [
        d.identificador for d in segundo.decisiones
    ]
    assert segundo.asignaciones == asignaciones


def test_el_cribado_lee_las_decisiones_manuales_del_disco(
    revision_en_disco, protocolo
):
    config, carpeta = revision_en_disco
    (carpeta / "decisiones.json").write_text(
        json.dumps(
            {
                "R0004": {
                    "decision": "incluir",
                    "motivo": "Es de 2009 pero es el estudio de referencia.",
                    "autor": "Pedro",
                    "fecha": "2026-09-12",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resultado = Cribado(
        revision="demo", protocolo=protocolo, config=config
    ).ejecutar()
    decision = resultado.buscar("R0004")

    assert decision.decision == "incluir"
    assert decision.decidido_por == "Pedro"
    assert decision.decision_filtro == "excluir"
    assert resultado.manuales == 1
    assert "Decisiones que no tomó el filtro" in resultado.diagrama()


def test_sin_registros_el_cribado_avisa_de_que_hay_que_cosechar(tmp_path, protocolo):
    config = Config(
        mailto="prueba@ejemplo.invalid",
        ollama="http://localhost:11434",
        datos=tmp_path / "revisiones",
    )

    with pytest.raises(ErrorCribado) as fallo:
        Cribado(revision="vacia", protocolo=protocolo, config=config).ejecutar()

    assert "cosechar" in str(fallo.value)


def test_unas_decisiones_rotas_en_disco_no_pasan_desapercibidas(
    revision_en_disco, protocolo
):
    config, carpeta = revision_en_disco
    (carpeta / "decisiones.json").write_text("{esto no es json", encoding="utf-8")

    with pytest.raises(ErrorCribado) as fallo:
        Cribado(revision="demo", protocolo=protocolo, config=config).ejecutar()

    assert "JSON" in str(fallo.value)


def test_el_protocolo_se_toma_del_estado_de_la_cosecha(revision_en_disco):
    config, carpeta = revision_en_disco
    (carpeta / "estado.json").write_text(
        json.dumps({"revision": "demo", "protocolo": "protocolos/humedales.json"}),
        encoding="utf-8",
    )

    assert protocolo_registrado(carpeta).name == "humedales.json"


def test_sin_estado_no_hay_protocolo_registrado(revision_en_disco):
    _, carpeta = revision_en_disco

    assert protocolo_registrado(carpeta) is None

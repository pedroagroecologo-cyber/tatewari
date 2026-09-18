"""Pruebas del cribado con el modelo local. Sin red y **sin Ollama instalado**.

Las tres que no se pueden quitar:

- el caso feliz;
- el JSON envuelto en explicación o en un bloque de código;
- la respuesta inservible, que debe quedar en «dudoso» y **jamás** en «excluir».
"""

from __future__ import annotations

import pytest

from tatewari.cribado import PREFIJO_MODELO, cribar
from tatewari.cribado_modelo import (
    LIMITE_RESUMEN,
    PALABRAS_MOTIVO,
    construir_prompt,
    cribar_dudosos,
    extraer_json,
    interpretar,
    recortar,
    recortar_palabras,
    sin_razonamiento,
)

# ---------------------------------------------------------------------------
# Interpretar la respuesta
# ---------------------------------------------------------------------------


def test_caso_feliz_un_json_limpio():
    respuesta = interpretar('{"decision": "incluir", "motivo": "Trata agua residual"}')

    assert respuesta is not None
    assert respuesta.decision == "incluir"
    assert respuesta.motivo == "Trata agua residual"


def test_un_json_envuelto_en_explicacion():
    """Un modelo de 3B explica lo que va a hacer antes de hacerlo."""
    texto = (
        "Claro, con mucho gusto. Tras leer el resumen, mi decisión es la "
        'siguiente:\n\n{"decision": "excluir", "motivo": "Es un estudio de '
        'ciclo de vida"}\n\nEspero que te sirva.'
    )

    respuesta = interpretar(texto)

    assert respuesta is not None
    assert respuesta.decision == "excluir"
    assert respuesta.motivo == "Es un estudio de ciclo de vida"


def test_un_json_dentro_de_un_bloque_de_codigo():
    texto = '```json\n{"decision": "dudoso", "motivo": "El resumen no lo dice"}\n```'

    respuesta = interpretar(texto)

    assert respuesta is not None
    assert respuesta.decision == "dudoso"


def test_una_llave_que_no_es_json_no_estorba():
    """«{el artículo}» no es JSON: se sigue buscando el siguiente candidato."""
    texto = 'Creo que {el artículo} sirve. {"decision":"incluir","motivo":"Sí"}'

    respuesta = interpretar(texto)

    assert respuesta is not None
    assert respuesta.decision == "incluir"


def test_un_json_sin_decision_no_vale_y_se_sigue_buscando():
    texto = '{"comentario":"pienso en voz alta"} {"decision":"incluir","motivo":"Sí"}'

    assert interpretar(texto).decision == "incluir"


def test_las_claves_con_acento_y_los_sinonimos_se_entienden():
    respuesta = interpretar('{"decisión": "Excluido", "razón": "No trata el tema"}')

    assert respuesta is not None
    assert respuesta.decision == "excluir"
    assert respuesta.motivo == "No trata el tema"


def test_una_llave_dentro_del_motivo_no_rompe_el_analisis():
    respuesta = interpretar('{"decision":"incluir","motivo":"usa {llaves} raras"}')

    assert respuesta is not None
    assert respuesta.motivo == "usa {llaves} raras"


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "No tengo ni idea de qué me estás pidiendo.",
        "{esto no es json}",
        '{"decision": "quizás"}',
        '{"decision": ""}',
        "{",
        '{"decision": {"anidada": "incluir"}}',
    ],
)
def test_una_respuesta_inservible_no_se_interpreta(texto):
    assert interpretar(texto) is None


def test_un_no_suelto_no_se_lee_como_excluir():
    """Excluir por un «no» suelto sería excluir a ciegas."""
    assert interpretar('{"decision": "no"}') is None
    assert interpretar('{"decision": "sí"}') is None


def test_el_razonamiento_no_se_confunde_con_la_conclusion():
    """Un modelo que piensa en voz alta prueba opciones y las descarta."""
    texto = (
        '<think>A ver, podría ser {"decision":"excluir"}… no, espera, sí trata '
        'agua residual.</think>{"decision":"incluir","motivo":"Trata agua residual"}'
    )

    assert interpretar(texto).decision == "incluir"


def test_un_razonamiento_sin_cerrar_se_lleva_el_resto():
    """Si el modelo se quedó pensando y nunca concluyó, no hay conclusión."""
    assert interpretar('<think>sigo dudando {"decision":"excluir"}') is None
    assert sin_razonamiento("<think>solo pienso").strip() == ""


def test_extraer_json_devuelve_el_diccionario():
    assert extraer_json('{"decision":"incluir"}') == {"decision": "incluir"}
    assert extraer_json("sin json") is None


# ---------------------------------------------------------------------------
# Recortes
# ---------------------------------------------------------------------------


def test_el_motivo_se_recorta_a_doce_palabras():
    largo = " ".join(f"palabra{n}" for n in range(30))

    recortado = recortar_palabras(largo)

    assert len(recortado.split()) == PALABRAS_MOTIVO
    assert recortado.endswith("…")


def test_un_motivo_corto_no_se_toca():
    assert recortar_palabras("Trata agua residual") == "Trata agua residual"


def test_un_motivo_ausente_queda_nr():
    """AGENTS.md, regla 2."""
    assert recortar_palabras(None) == "NR"
    assert recortar_palabras("   ") == "NR"
    assert interpretar('{"decision":"incluir"}').motivo == "NR"


def test_el_resumen_se_recorta_por_un_espacio():
    largo = "palabra " * 400

    recortado = recortar(largo, 100)

    assert len(recortado) <= 101
    assert recortado.endswith("…")
    assert not recortado.startswith(" ")


def test_un_resumen_ausente_se_le_dice_al_modelo_como_nr():
    assert recortar(None) == "NR"
    assert recortar("NR") == "NR"


# ---------------------------------------------------------------------------
# El prompt
# ---------------------------------------------------------------------------


def test_el_prompt_lleva_los_criterios_del_protocolo(protocolo):
    registro = {"titulo": "Un título", "anio": 2020, "resumen": "Un resumen."}

    prompt = construir_prompt(registro, protocolo)

    assert protocolo.titulo in prompt
    for regla in protocolo.reglas.incluir:
        assert regla.motivo in prompt
    assert "CRITERIOS DE INCLUSIÓN" in prompt


def test_el_prompt_lleva_los_temas_excluidos(protocolo):
    prompt = construir_prompt({"titulo": "T", "resumen": "R"}, protocolo)

    assert "TEMAS EXCLUIDOS" in prompt
    assert "life cycle assessment" in prompt


def test_el_prompt_lleva_el_titulo_y_el_resumen_recortado(protocolo):
    registro = {"titulo": "El título exacto", "anio": 2021, "resumen": "x" * 5000}

    prompt = construir_prompt(registro, protocolo)

    assert "El título exacto" in prompt
    assert "2021" in prompt
    assert len(prompt) < 5000
    assert "…" in prompt


def test_el_prompt_exige_solo_json(protocolo):
    prompt = construir_prompt({"titulo": "T", "resumen": "R"}, protocolo)

    assert "ÚNICAMENTE" in prompt
    assert '"decision"' in prompt
    assert '"motivo"' in prompt
    assert "doce palabras" in prompt


def test_el_prompt_no_le_pide_comprobar_el_ano_ni_el_idioma(protocolo):
    """Eso ya lo comprobó el filtro con datos, no con opiniones."""
    prompt = construir_prompt({"titulo": "T", "resumen": "R"}, protocolo)

    assert "ya están comprobados" in prompt
    assert "No los" in prompt


def test_sin_resumen_el_prompt_avisa_de_que_solo_hay_titulo(protocolo):
    """Si no, un modelo pequeño copia el criterio de inclusión y se lo inventa."""
    prompt = construir_prompt({"titulo": "T", "resumen": "NR"}, protocolo)

    assert "NO trae resumen" in prompt
    assert "solo con el título" in prompt


def test_el_recordatorio_solo_sale_en_el_reintento(protocolo):
    registro = {"titulo": "T", "resumen": "R"}

    assert "IMPORTANTE" not in construir_prompt(registro, protocolo)
    assert "IMPORTANTE" in construir_prompt(registro, protocolo, recordatorio=True)


# ---------------------------------------------------------------------------
# La pasada completa
# ---------------------------------------------------------------------------


@pytest.fixture
def dudosos(protocolo, ruta_fixture_demo):
    """Los dos registros que el filtro determinista deja en «dudoso»."""
    import json

    registros = json.loads(ruta_fixture_demo.read_text(encoding="utf-8"))
    return cribar(registros, protocolo).por_decision("dudoso")


def test_solo_se_preguntan_los_dudosos(dudosos, protocolo, ollama, tags_falsos):
    """En el fixture son 2 de 13. Preguntar por todo no cabe en una laptop."""
    assert len(dudosos) == 2
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=[
            '{"decision":"incluir","motivo":"Sí sirve"}',
            '{"decision":"excluir","motivo":"No sirve"}',
        ],
    )

    resultado = cribar_dudosos(dudosos, protocolo, cliente)

    assert resultado.preguntados == 2
    assert len(sesion.cuerpos) == 2


def test_la_decision_del_modelo_lleva_su_nombre(dudosos, protocolo, ollama, tags_falsos):
    """Que se sepa siempre quién decidió qué."""
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=[
            '{"decision":"incluir","motivo":"Sí sirve"}',
            '{"decision":"dudoso","motivo":"No se sabe"}',
        ],
    )

    resultado = cribar_dudosos(dudosos, protocolo, cliente, fecha="2026-09-12")

    assert resultado.modelo == "llama3.2:3b"
    for decision in resultado.decisiones.values():
        assert decision.autor == f"{PREFIJO_MODELO}llama3.2:3b"
        assert decision.fecha == "2026-09-12"
        assert decision.motivo.strip()


def test_una_respuesta_inservible_deja_el_registro_en_dudoso(
    dudosos, protocolo, ollama, tags_falsos
):
    """La regla que no se negocia: nunca se excluye por no haber entendido.

    Se responde basura cuatro veces: dos por registro, porque cada uno tiene su
    reintento.
    """
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=["no entiendo nada"] * 4,
    )

    resultado = cribar_dudosos(dudosos, protocolo, cliente)

    assert resultado.conteos["excluir"] == 0
    assert resultado.conteos["dudoso"] == 2
    assert resultado.no_interpretados == 2
    # Y no se guarda ninguna decisión: nadie decidió nada.
    assert resultado.decisiones == {}
    assert all(not paso.interpretado for paso in resultado.pasos)


def test_se_reintenta_una_vez_y_solo_una(dudosos, protocolo, ollama, tags_falsos):
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=[
            "basura",
            '{"decision":"incluir","motivo":"Al segundo intento"}',
            "basura",
            "basura",
        ],
    )

    resultado = cribar_dudosos(dudosos, protocolo, cliente)

    primero, segundo = resultado.pasos
    assert primero.decision == "incluir"
    assert primero.intentos == 2
    assert segundo.decision == "dudoso"
    assert segundo.intentos == 2
    # Dos intentos por registro, ni uno más.
    assert len(sesion.cuerpos) == 4


def test_el_reintento_le_aprieta_con_el_recordatorio(
    dudosos, protocolo, ollama, tags_falsos
):
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=["basura", '{"decision":"dudoso","motivo":"Vale"}', "x", "y"],
    )

    cribar_dudosos(dudosos[:1], protocolo, cliente)

    assert "IMPORTANTE" not in sesion.cuerpos[0]["prompt"]
    assert "IMPORTANTE" in sesion.cuerpos[1]["prompt"]


def test_el_avance_se_avisa_antes_y_despues(dudosos, protocolo, ollama, tags_falsos):
    """Sin avance, el primer registro parece que colgó el programa."""
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=['{"decision":"incluir","motivo":"Sí"}'] * 2,
    )
    empezados: list[tuple[int, int, str]] = []
    acabados: list[tuple[int, int, str]] = []

    cribar_dudosos(
        dudosos,
        protocolo,
        cliente,
        antes=lambda i, t, d: empezados.append((i, t, d.identificador)),
        despues=lambda i, t, p: acabados.append((i, t, p.decision)),
    )

    assert [(i, t) for i, t, _ in empezados] == [(1, 2), (2, 2)]
    assert [(i, t) for i, t, _ in acabados] == [(1, 2), (2, 2)]
    assert empezados[0][2] == dudosos[0].identificador


def test_el_resumen_cuenta_lo_que_paso(dudosos, protocolo, ollama, tags_falsos):
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=[
            '{"decision":"incluir","motivo":"Sí"}',
            "basura",
            "basura",
        ],
    )

    resultado = cribar_dudosos(dudosos, protocolo, cliente)
    resumen = resultado.resumen()

    assert "llama3.2:3b" in resumen
    assert "2 registros dudosos" in resumen
    assert "nunca se excluye" in resumen


def test_sin_dudosos_no_se_pregunta_nada(protocolo, ollama, tags_falsos):
    cliente, sesion = ollama(modelos=[tags_falsos("llama3.2:3b")], respuestas=[])

    resultado = cribar_dudosos([], protocolo, cliente)

    assert resultado.preguntados == 0
    assert sesion.cuerpos == []


def test_la_decision_del_modelo_se_aplica_al_cribado(
    protocolo, ruta_fixture_demo, ollama, tags_falsos
):
    """De punta a punta: el modelo decide y el CSV lo refleja con su nombre."""
    import json

    registros = json.loads(ruta_fixture_demo.read_text(encoding="utf-8"))
    primero = cribar(registros, protocolo)
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=[
            '{"decision":"incluir","motivo":"El título basta"}',
            '{"decision":"excluir","motivo":"Son aguas pluviales"}',
        ],
    )

    salida = cribar_dudosos(primero.por_decision("dudoso"), protocolo, cliente)
    segundo = cribar(registros, protocolo, decisiones_manuales=salida.decisiones)

    assert primero.conteos["dudoso"] == 2
    assert segundo.conteos["dudoso"] == 0
    assert segundo.conteos["incluir"] == primero.conteos["incluir"] + 1
    assert segundo.conteos["excluir"] == primero.conteos["excluir"] + 1
    # La exclusión del modelo se cuenta aparte de las del filtro.
    assert "Decisión del modelo local" in segundo.motivos_de_exclusion
    for identificador in salida.decisiones:
        decision = segundo.buscar(identificador)
        assert decision.decidido_por == "modelo:llama3.2:3b"
        # Y lo que decía el filtro no se ha borrado.
        assert decision.decision_filtro == "dudoso"
